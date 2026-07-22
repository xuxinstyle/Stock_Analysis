from __future__ import annotations

import json
import os
from dataclasses import dataclass
from importlib.resources import files
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError

from stock_research.db import create_engine_at, create_read_only_engine_at
from stock_research.domain.models import DailyRunRequest
from stock_research.repositories.runs import RunRepository
from stock_research.repositories.stocks import StockRepository
from stock_research.services.configuration import ConfigurationService
from stock_research.services.daily_run import DailyRunService
from stock_research.services.feishu_notifications import (
    FeishuNotificationError,
    FeishuNotificationService,
)
from stock_research.services.market_data import AkShareMarketDataProvider
from stock_research.services.report_builder import ReportBuilder
from stock_research.services.report_store import ReportPaths, ReportStore


app = typer.Typer(no_args_is_help=True, add_completion=False)


@dataclass(frozen=True)
class Services:
    configuration: ConfigurationService
    daily_run: DailyRunService
    report_store: ReportStore


def app_home() -> Path:
    configured = os.environ.get("STOCK_RESEARCH_HOME")
    root = Path(configured) if configured else Path.cwd() / ".stock-research"
    return root.expanduser().resolve()


def build_services(home: Path | None = None) -> Services:
    root = (home or app_home()).resolve()
    data_directory = root / "data"
    stock_repository = StockRepository(create_engine_at(data_directory / "stock_research.sqlite3"))
    report_store = ReportStore(root / "reports")
    return Services(
        configuration=ConfigurationService(stock_repository),
        daily_run=DailyRunService(
            stock_repository=stock_repository,
            market_data_provider=AkShareMarketDataProvider(),
            report_builder=ReportBuilder(),
            report_store=report_store,
            run_repository=RunRepository(create_engine_at(data_directory / "runs.sqlite3")),
        ),
        report_store=report_store,
    )


def active_stock_context(home: Path | None = None) -> list[dict[str, object]]:
    root = (home or app_home()).resolve()
    database = root / "data" / "stock_research.sqlite3"
    try:
        engine = create_read_only_engine_at(database)
    except FileNotFoundError as error:
        raise RuntimeError("no persisted configuration database is available") from error
    repository = StockRepository(engine, initialize=False)
    try:
        stocks = repository.list_all()
    finally:
        engine.dispose()

    context: list[dict[str, object]] = []
    for stock in stocks:
        holding = stock.holding
        context.append(
            {
                "symbol": stock.symbol,
                "name": stock.name,
                "market": stock.market.value,
                "industry": stock.industry,
                "holding": (
                    None
                    if holding is None
                    else {"configured": True, "risk_profile": holding.risk_profile}
                ),
            }
        )
    return context


def _configuration_path(home: Path | None = None) -> Path:
    return (home or app_home()) / "config" / "stocks.yaml"


def _example_configuration_text() -> str:
    return (
        files("stock_research")
        .joinpath("resources/stocks.example.yaml")
        .read_text(encoding="utf-8")
    )


def load_daily_request(input_path: Path) -> DailyRunRequest:
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        return DailyRunRequest.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as error:
        raise typer.BadParameter(f"invalid daily research request: {error}") from error


def _notify_generated_report(paths: ReportPaths, report_date: date) -> int:
    markdown = paths.markdown.read_text(encoding="utf-8")
    return FeishuNotificationService.from_environment().send_markdown(report_date, markdown)


@app.command("init")
def init(
    output_path: Annotated[Path | None, typer.Argument()] = None,
) -> None:
    """Create an editable stock configuration without overwriting an existing one."""
    destination = output_path or _configuration_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as output:
            output.write(_example_configuration_text())
    except FileExistsError:
        typer.echo(f"configuration already exists: {destination}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"created configuration: {destination}")


@app.command("import-config")
def import_config(
    input_path: Annotated[Path, typer.Argument(exists=True, readable=True)],
) -> None:
    """Validate and atomically replace the configured stock set from YAML."""
    try:
        stocks = build_services().configuration.replace_from_yaml(input_path)
    except (OSError, ValidationError, ValueError, yaml.YAMLError) as error:
        typer.echo(f"configuration import failed: {error}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"imported {len(stocks)} stock configuration(s)")


@app.command("validate-input")
def validate_input(
    input_path: Annotated[Path, typer.Argument(exists=True, readable=True)],
) -> None:
    """Validate a DailyRunRequest JSON document without running a report."""
    request = load_daily_request(input_path)
    typer.echo(
        f"\u6bcf\u65e5\u7814\u7a76\u8bf7\u6c42\u6709\u6548: {request.report_date.isoformat()}"
    )


@app.command("generate")
def generate(
    input_path: Annotated[Path, typer.Option("--input", exists=True, readable=True)],
) -> None:
    """Generate and persist a research-only report from a validated request."""
    try:
        request = load_daily_request(input_path)
        services = build_services()
        report = services.daily_run.run(request)
        paths = services.report_store.paths_for(report.report_date)
    except (OSError, ValidationError, ValueError, RuntimeError) as error:
        typer.echo(f"report generation failed: {error}", err=True)
        raise typer.Exit(code=1)
    try:
        segments = _notify_generated_report(paths, report.report_date)
    except (OSError, FeishuNotificationError) as error:
        typer.echo(
            "report generated, but Feishu notification failed: "
            f"{error}\nJSON: {paths.json}\nMarkdown: {paths.markdown}\nHTML: {paths.html}",
            err=True,
        )
        raise typer.Exit(code=1)
    typer.echo(
        f"JSON: {paths.json}\nMarkdown: {paths.markdown}\nHTML: {paths.html}\n"
        f"Feishu: {segments} segment(s) sent"
    )


@app.command("reports")
def reports() -> None:
    """List persisted report dates and their recorded run statuses."""
    store = build_services().report_store
    dates = store.repository.list_dates()
    if not dates:
        typer.echo("no reports found")
        return
    for report_date in dates:
        report = store.load(report_date)
        if report is not None:
            typer.echo(f"{report_date.isoformat()}: {report.run_status.value}")


@app.command("report")
def report(
    report_date: Annotated[str, typer.Argument()],
) -> None:
    """Display one saved report without fetching data or generating output."""
    try:
        selected_date = date.fromisoformat(report_date)
    except ValueError:
        typer.echo("report date must use YYYY-MM-DD", err=True)
        raise typer.Exit(code=2) from None
    saved_report = ReportStore.load_read_only(app_home() / "reports", selected_date)
    if saved_report is None:
        typer.echo(f"report not found for {selected_date.isoformat()}")
        raise typer.Exit(code=1)
    typer.echo(saved_report.model_dump_json(indent=2))


@app.command("serve")
def serve(
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
) -> None:
    """Serve the local research-report interface on loopback only."""
    import uvicorn

    uvicorn.run("stock_research.web.app:create_app", factory=True, host="127.0.0.1", port=port)
