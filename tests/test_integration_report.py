import json
from pathlib import Path

from stock_research.domain.enums import RunStatus
from stock_research.services.report_builder import ReportBuilder
from stock_research.services.report_store import ReportStore

from test_report_builder import FakeMarketData, make_request, make_research, make_stock


def make_partial_report():
    report = ReportBuilder().build(make_request(make_research()), [make_stock()], FakeMarketData())
    analysis = report.analyses[0].model_copy(
        update={"data_gaps": ["Fixture price input was unavailable for one session."]}
    )
    return report.model_copy(
        update={
            "run_status": RunStatus.PARTIAL,
            "run_warnings": ["Fixture source coverage is incomplete."],
            "analyses": [analysis],
        }
    )


def test_all_report_formats_reference_the_same_stock_and_warning(tmp_path: Path) -> None:
    paths = ReportStore(tmp_path).save(make_partial_report())
    payload = json.loads(paths.json.read_text(encoding="utf-8"))
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")

    assert payload["analyses"][0]["stock"]["symbol"] == "SH.600000"
    assert "SH.600000" in markdown and "SH.600000" in html
    assert payload["run_warnings"][0] in markdown and payload["run_warnings"][0] in html
