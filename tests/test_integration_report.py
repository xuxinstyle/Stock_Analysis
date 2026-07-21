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


def test_all_report_formats_preserve_complete_partial_report_contract(tmp_path: Path) -> None:
    report = make_partial_report()
    paths = ReportStore(tmp_path).save(report)
    json_report = paths.json.read_text(encoding="utf-8")
    payload = json.loads(json_report)
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")

    analysis = report.analyses[0]
    analysis_payload = payload["analyses"][0]
    assert analysis.research is not None
    assert analysis.previous_day is not None
    assert analysis.technical is not None
    source_url = str(analysis.research.evidence[0].url)
    market_status = report.market_statuses[0]
    shared_facts = (
        analysis.stock.symbol,
        analysis.stock.name,
        report.report_date.isoformat(),
        report.generated_at.date().isoformat(),
        market_status.market.value,
        market_status.status,
        report.run_warnings[0],
        analysis.data_gaps[0],
        report.disclaimer,
        analysis.research.data_as_of.isoformat(),
        analysis.previous_day.data_as_of.isoformat(),
        analysis.technical.data_as_of.isoformat(),
        source_url,
    )
    for content in (json_report, markdown, html):
        assert all(fact in content for fact in shared_facts)

    section_contracts = (
        ("previous_day", "前日表现与原因"),
        ("fundamental_summary", "基本面分析"),
        ("industry_summary", "行业分析"),
        ("technical", "技术面分析"),
        ("policy_summary", "政策分析"),
        ("news_summary", "消息面分析"),
        ("events", "突发事件"),
        ("evidence", "来源与数据缺口"),
    )
    for json_key, heading in section_contracts:
        assert json_key in json_report
        assert heading in markdown
        assert heading in html

    for horizon, heading in (
        ("short", "短线建议"),
        ("medium", "中线建议"),
        ("long", "长线建议"),
    ):
        assert any(item["horizon"] == horizon for item in analysis_payload["recommendations"])
        assert heading in markdown
        assert heading in html
