from __future__ import annotations

import json
import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError

from stock_research.db import create_engine_at
from stock_research.domain.models import DailyRunRequest
from stock_research.repositories.runs import RunRepository
from stock_research.repositories.stocks import StockRepository
from stock_research.services.configuration import ConfigurationService
from stock_research.services.daily_run import DailyRunService
from stock_research.services.market_data import AkShareMarketDataProvider
from stock_research.services.report_builder import ReportBuilder
from stock_research.services.report_store import ReportStore


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
    typer.echo(f"JSON: {paths.json}\nMarkdown: {paths.markdown}\nHTML: {paths.html}")


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


@app.command("serve")
def serve(
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
) -> None:
    """Serve the local research-report interface on loopback only."""
    import uvicorn

    uvicorn.run("stock_research.web.app:create_app", factory=True, host="127.0.0.1", port=port)
