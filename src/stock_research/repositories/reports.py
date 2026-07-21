from __future__ import annotations

import json
from datetime import date

from sqlalchemy import Column, Date, DateTime, Engine, MetaData, String, Table, Text, select
from sqlalchemy.dialects.sqlite import insert

from stock_research.domain.models import DailyReport


metadata = MetaData()
reports = Table(
    "reports",
    metadata,
    Column("report_date", Date, primary_key=True),
    Column("generated_at", DateTime(timezone=True), nullable=False),
    Column("run_status", String, nullable=False),
    Column("report_json", Text, nullable=False),
)


class ReportRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        metadata.create_all(engine)

    def save(self, report: DailyReport) -> DailyReport:
        values = {
            "report_date": report.report_date,
            "generated_at": report.generated_at,
            "run_status": report.run_status.value,
            "report_json": json.dumps(report.model_dump(mode="json"), ensure_ascii=False),
        }
        statement = insert(reports).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[reports.c.report_date],
            set_={key: value for key, value in values.items() if key != "report_date"},
        )
        with self.engine.begin() as connection:
            connection.execute(statement)
        return report

    def get(self, report_date: date) -> DailyReport | None:
        statement = select(reports.c.report_json).where(reports.c.report_date == report_date)
        with self.engine.connect() as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return None if payload is None else DailyReport.model_validate_json(payload)

    def latest(self) -> DailyReport | None:
        statement = select(reports.c.report_json).order_by(
            reports.c.report_date.desc(), reports.c.generated_at.desc()
        )
        with self.engine.connect() as connection:
            payload = connection.execute(statement).scalars().first()
        return None if payload is None else DailyReport.model_validate_json(payload)

    def list_dates(self) -> list[date]:
        statement = select(reports.c.report_date).order_by(reports.c.report_date.desc())
        with self.engine.connect() as connection:
            return list(connection.execute(statement).scalars())
