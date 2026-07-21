from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from stock_research.domain.enums import RunStatus
from stock_research.domain.models import DailyReport, DailyRunRequest, RunRecord, StockConfig
from stock_research.repositories.runs import RunRepository
from stock_research.services.market_data import MarketDataProvider
from stock_research.services.report_builder import ReportBuilder
from stock_research.services.report_store import ReportStore


class StockRepositoryProtocol(Protocol):
    def list_all(self) -> list[StockConfig]: ...


class DailyRunService:
    def __init__(
        self,
        stock_repository: StockRepositoryProtocol,
        market_data_provider: MarketDataProvider,
        report_builder: ReportBuilder,
        report_store: ReportStore,
        run_repository: RunRepository,
    ) -> None:
        if report_store is None or run_repository is None:
            raise ValueError("report_store and run_repository are required")
        self._stock_repository = stock_repository
        self._market_data_provider = market_data_provider
        self._report_builder = report_builder
        self._report_store = report_store
        self._run_repository = run_repository

    def run(self, request: DailyRunRequest) -> DailyReport:
        started_at = datetime.now(UTC)
        stage = "load_stocks"
        try:
            stocks = self._stock_repository.list_all()
            stage = "build_report"
            report = self._report_builder.build(
                request=request,
                stocks=stocks,
                market_data=self._market_data_provider,
            )
            stage = "save_report"
            paths = self._report_store.save(report)
            stage = "complete"
            self._save_run(
                RunRecord(
                    report_date=request.report_date,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    status=report.run_status,
                    stage=stage,
                    output_paths=paths.as_dict(),
                )
            )
            return report
        except Exception as error:
            self._save_run(
                RunRecord(
                    report_date=request.report_date,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    status=RunStatus.FAILED,
                    stage=stage,
                    error_message=str(error),
                )
            )
            raise

    def _save_run(self, record: RunRecord) -> None:
        self._run_repository.save(record)
