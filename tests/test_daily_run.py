from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from stock_research.db import create_engine_at
from stock_research.domain.enums import RunStatus
from stock_research.domain.models import StockConfig
from stock_research.repositories.runs import RunRepository
from stock_research.services.daily_run import DailyRunService
from stock_research.services.report_builder import ReportBuilder
from stock_research.services.report_store import ReportStore

from test_report_builder import FakeMarketData, make_request, make_research, make_stock


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
