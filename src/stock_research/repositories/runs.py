from __future__ import annotations

import json
from datetime import date

from sqlalchemy import Column, Date, Engine, MetaData, String, Table, Text, select
from sqlalchemy.dialects.sqlite import insert

from stock_research.domain.models import RunRecord


metadata = MetaData()
runs = Table(
    "runs",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("report_date", Date, nullable=False, index=True),
    Column("started_at", String, nullable=False),
    Column("finished_at", String, nullable=False),
    Column("status", String, nullable=False),
    Column("stage", String, nullable=False),
    Column("error_message", Text, nullable=True),
    Column("output_paths", Text, nullable=False),
    Column("report_version", String, nullable=False),
)


class RunRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        metadata.create_all(engine)

    def save(self, record: RunRecord) -> RunRecord:
        values = {
            "run_id": record.run_id,
            "report_date": record.report_date,
            "started_at": record.started_at.isoformat(),
            "finished_at": record.finished_at.isoformat(),
            "status": record.status.value,
            "stage": record.stage,
            "error_message": record.error_message,
            "output_paths": json.dumps(record.output_paths, ensure_ascii=False),
            "report_version": record.report_version,
        }
        statement = insert(runs).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[runs.c.run_id],
            set_={key: value for key, value in values.items() if key != "run_id"},
        )
        with self.engine.begin() as connection:
            connection.execute(statement)
        return record

    def latest(self) -> RunRecord | None:
        statement = select(runs).order_by(runs.c.started_at.desc(), runs.c.run_id.desc())
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return None if row is None else self._deserialize(dict(row))

    def list_for_date(self, report_date: date) -> list[RunRecord]:
        statement = (
            select(runs).where(runs.c.report_date == report_date).order_by(runs.c.started_at.desc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._deserialize(dict(row)) for row in rows]

    @staticmethod
    def _deserialize(row: dict[str, object]) -> RunRecord:
        row["output_paths"] = json.loads(str(row["output_paths"]))
        return RunRecord.model_validate(row)
