from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from stock_research.cli import app, build_services, load_daily_request
from stock_research.db import create_engine_at
from stock_research.domain.enums import RunStatus
from stock_research.domain.models import StockConfig
from stock_research.repositories.runs import RunRepository
from stock_research.services.daily_run import DailyRunService
from stock_research.services.market_data import MarketDataUnavailable
from stock_research.services.report_builder import ReportBuilder
from stock_research.services.report_store import ReportStore

from test_report_builder import FakeMarketData, make_request, make_research, make_stock


PROJECT_ROOT = Path(__file__).parent.parent
TEST_DATA_DIR = Path(__file__).parent / "fixtures"
DAILY_RESEARCH_PROMPT = PROJECT_ROOT / "docs" / "automation" / "daily-research-prompt.md"
README = PROJECT_ROOT / "README.md"
ACTIVE_STOCK_COMMAND = (
    "python -c 'from stock_research.cli import build_services; import json; "
    "print(json.dumps([dict(symbol=stock.symbol, name=stock.name, market=stock.market.value) "
    "for stock in build_services().configuration.list_stocks()], ensure_ascii=False))'"
)
runner = CliRunner()


class OfflineMarketDataProvider:
    def fetch_daily_bars(self, stock, end, days: int = 260):
        raise MarketDataUnavailable(stock.symbol, "offline fixture has no market data")


def test_daily_research_prompt_requires_cited_safe_local_handoff() -> None:
    assert DAILY_RESEARCH_PROMPT.exists()

    prompt = DAILY_RESEARCH_PROMPT.read_text(encoding="utf-8")
    required_instructions = (
        "09:00 China Standard Time",
        "last completed trading session",
        "SQLite-backed persisted active stock list",
        "same app home and repository used by `DailyRunService`",
        "python -c 'from stock_research.cli import build_services; import json; print(json.dumps",
        "dict(symbol=stock.symbol, name=stock.name, market=stock.market.value)",
        "stock-research validate-input",
        "stock-research generate --input",
        "Prefer primary sources",
        "exchange/company disclosures",
        "price and volume context",
        "sector/product prices",
        "policy and regulatory developments",
        "company news",
        "US peers",
        "international transmission",
        "title, URL, source name, publication time, retrieval time, direction, credibility, category, summary",
        "title`, `occurred_at`, `direction`, `summary`, and `symbols`",
        "source links",
        "unverified",
        "conflicting",
        "Never place orders, connect to brokers, or execute trades.",
        "Never assert return certainty or write an uncited material claim.",
        "Do not use or request API keys",
        "Record data gaps rather than inventing information.",
        "trigger, observation/target, invalidation, position limit, risk, and confidence",
    )

    for instruction in required_instructions:
        assert instruction in prompt

    readme = README.read_text(encoding="utf-8")
    assert "SQLite-backed persisted active repository" in readme
    assert "YAML is only an import input" in readme
    assert ACTIVE_STOCK_COMMAND in prompt
    assert ACTIVE_STOCK_COMMAND in readme
    assert "$env:STOCK_RESEARCH_HOME/config/stocks.yaml" not in readme
    assert ".stock-research/config/stocks.yaml" not in readme


def test_readme_documents_read_only_failed_run_inspection() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "<app-home>/data/runs.sqlite3" in readme
    assert "mode=ro" in readme
    assert (
        "SELECT report_date, status, stage, error_message, started_at, finished_at "
        "FROM runs ORDER BY started_at DESC LIMIT 10"
    ) in readme
    assert "`stock-research reports` lists generated reports, not failed run attempts" in readme


def test_fixture_payload_can_be_validated_then_generated_by_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    monkeypatch.setattr("stock_research.cli.AkShareMarketDataProvider", OfflineMarketDataProvider)
    request_path = TEST_DATA_DIR / "daily_research_request.json"

    assert runner.invoke(app, ["import-config", str(TEST_DATA_DIR / "stocks.yaml")]).exit_code == 0
    assert runner.invoke(app, ["validate-input", str(request_path)]).exit_code == 0
    configured_symbols = {stock.symbol for stock in build_services().configuration.list_stocks()}
    input_symbols = {
        research.symbol for research in load_daily_request(request_path).research_inputs
    }
    assert input_symbols == configured_symbols

    result = runner.invoke(app, ["generate", "--input", str(request_path)])

    assert result.exit_code == 0
    report = ReportStore(tmp_path / "reports").load_latest()
    assert report is not None
    assert {analysis.stock.symbol for analysis in report.analyses} == configured_symbols
    assert all(analysis.research is not None for analysis in report.analyses)
    assert all(analysis.research.evidence for analysis in report.analyses if analysis.research)
    assert all(
        evidence.url
        for analysis in report.analyses
        if analysis.research
        for evidence in analysis.research.evidence
    )
    assert all(analysis.recommendations[0].invalidation for analysis in report.analyses)
    assert not any(
        "expected exactly one research input" in warning for warning in report.run_warnings
    )


class FakeStockRepository:
    def __init__(self, stocks: list[StockConfig]) -> None:
        self.stocks = stocks

    def list_all(self) -> list[StockConfig]:
        return self.stocks


def test_daily_run_marks_partial_when_one_stock_has_no_price_data(tmp_path: Path) -> None:
    stocks = [make_stock(), make_stock("HK.00700")]
    service = DailyRunService(
        stock_repository=FakeStockRepository(stocks),
        market_data_provider=FakeMarketData({"HK.00700"}),
        report_builder=ReportBuilder(),
        report_store=ReportStore(tmp_path / "reports"),
        run_repository=RunRepository(create_engine_at(tmp_path / "runs.sqlite3")),
    )

    result = service.run(make_request(make_research(), make_research("HK.00700")))

    assert result.run_status is RunStatus.PARTIAL
    assert any("HK.00700" in warning for warning in result.run_warnings)
    assert len(result.analyses) == 2
    assert (tmp_path / "reports" / "2026-07-21" / "report.json").exists()


class ExplodingBuilder:
    def build(self, request, stocks, market_data):
        raise RuntimeError("unexpected fixture failure")


def test_daily_run_persists_failed_unhandled_exception_with_stage(tmp_path: Path) -> None:
    runs = RunRepository(create_engine_at(tmp_path / "runs.sqlite3"))
    service = DailyRunService(
        stock_repository=FakeStockRepository([make_stock()]),
        market_data_provider=FakeMarketData(),
        report_builder=ExplodingBuilder(),
        report_store=ReportStore(tmp_path / "reports"),
        run_repository=runs,
    )

    with pytest.raises(RuntimeError, match="unexpected fixture failure"):
        service.run(make_request(make_research()))

    record = runs.latest()
    assert record is not None
    assert record.status is RunStatus.FAILED
    assert record.stage == "build_report"
    assert record.error_message == "unexpected fixture failure"


def test_run_repository_round_trips_success_metadata(tmp_path: Path) -> None:
    from stock_research.domain.models import RunRecord

    runs = RunRepository(create_engine_at(tmp_path / "runs.sqlite3"))
    record = RunRecord(
        report_date=date(2026, 7, 21),
        started_at=datetime(2026, 7, 21, 1, 0, tzinfo=UTC),
        finished_at=datetime(2026, 7, 21, 1, 1, tzinfo=UTC),
        status=RunStatus.SUCCESS,
        stage="complete",
        output_paths={"json": "reports/2026-07-21/report.json"},
    )

    runs.save(record)

    assert runs.latest() == record


def test_daily_run_rejects_missing_persistence_dependencies(tmp_path: Path) -> None:
    runs = RunRepository(create_engine_at(tmp_path / "runs.sqlite3"))

    with pytest.raises(ValueError, match="report_store and run_repository are required"):
        DailyRunService(
            stock_repository=FakeStockRepository([make_stock()]),
            market_data_provider=FakeMarketData(),
            report_builder=ReportBuilder(),
            report_store=None,
            run_repository=runs,
        )


def test_run_repository_orders_mixed_offsets_by_utc_instant(tmp_path: Path) -> None:
    from stock_research.domain.models import RunRecord

    runs = RunRepository(create_engine_at(tmp_path / "runs.sqlite3"))
    earlier = RunRecord(
        report_date=date(2026, 7, 21),
        started_at=datetime(2026, 7, 21, 10, 0, tzinfo=timezone(timedelta(hours=8))),
        finished_at=datetime(2026, 7, 21, 10, 1, tzinfo=timezone(timedelta(hours=8))),
        status=RunStatus.SUCCESS,
        stage="complete",
    )
    later = RunRecord(
        report_date=date(2026, 7, 21),
        started_at=datetime(2026, 7, 21, 3, 0, tzinfo=UTC),
        finished_at=datetime(2026, 7, 21, 3, 1, tzinfo=UTC),
        status=RunStatus.SUCCESS,
        stage="complete",
    )

    runs.save(earlier)
    runs.save(later)

    assert runs.latest() == later
    assert earlier.started_at.tzinfo is UTC


def test_run_record_rejects_finish_before_start() -> None:
    from stock_research.domain.models import RunRecord

    with pytest.raises(ValidationError, match="finished_at must not be earlier than started_at"):
        RunRecord(
            report_date=date(2026, 7, 21),
            started_at=datetime(2026, 7, 21, 3, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 21, 2, 59, tzinfo=UTC),
            status=RunStatus.FAILED,
            stage="build_report",
        )
