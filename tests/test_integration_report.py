import json
from datetime import UTC, date, datetime
from pathlib import Path

from stock_research.domain.enums import RunStatus
from stock_research.services.report_builder import ReportBuilder
from stock_research.services.report_store import ReportStore

from test_report_builder import FakeMarketData, make_request, make_research, make_stock


def _between(content: str, start: str, end: str) -> str:
    start_index = content.find(start)
    assert start_index >= 0, f"missing start marker: {start}"
    end_index = content.find(end, start_index + len(start))
    assert end_index >= 0, f"missing end marker: {end}"
    return content[start_index:end_index]


def make_partial_report():
    report = ReportBuilder().build(make_request(make_research()), [make_stock()], FakeMarketData())
    original_analysis = report.analyses[0]
    assert original_analysis.research is not None
    assert original_analysis.previous_day is not None
    assert original_analysis.technical is not None
    analysis = original_analysis.model_copy(
        update={
            "research": original_analysis.research.model_copy(
                update={"data_as_of": date(2026, 8, 6)}
            ),
            "previous_day": original_analysis.previous_day.model_copy(
                update={"data_as_of": date(2026, 8, 5)}
            ),
            "technical": original_analysis.technical.model_copy(
                update={"data_as_of": date(2026, 8, 4)}
            ),
            "data_gaps": ["Fixture price input was unavailable for one session."],
        }
    )
    market_status = report.market_statuses[0].model_copy(update={"data_as_of": date(2026, 8, 7)})
    return report.model_copy(
        update={
            "report_date": date(2026, 8, 10),
            "generated_at": datetime(2026, 8, 11, 1, 2, 3, tzinfo=UTC),
            "run_status": RunStatus.PARTIAL,
            "market_statuses": [market_status],
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
    assert market_status.data_as_of is not None
    date_contract = {
        "report": report.report_date.isoformat(),
        "generated": report.generated_at.date().isoformat(),
        "market": market_status.data_as_of.isoformat(),
        "research": analysis.research.data_as_of.isoformat(),
        "previous_day": analysis.previous_day.data_as_of.isoformat(),
        "technical": analysis.technical.data_as_of.isoformat(),
    }
    assert len(set(date_contract.values())) == len(date_contract)

    expected_payload = report.model_dump(mode="json")
    assert payload["report_date"] == expected_payload["report_date"]
    assert payload["generated_at"] == expected_payload["generated_at"]
    assert payload["market_statuses"][0]["data_as_of"] == date_contract["market"]
    assert payload["market_statuses"][0]["market"] == market_status.market.value
    assert payload["market_statuses"][0]["status"] == market_status.status
    assert analysis_payload["research"]["data_as_of"] == date_contract["research"]
    assert analysis_payload["previous_day"]["data_as_of"] == date_contract["previous_day"]
    assert analysis_payload["technical"]["data_as_of"] == date_contract["technical"]

    assert f"# 每日股票研究报告 — {date_contract['report']}" in markdown
    assert f"- 生成时间：{report.generated_at.isoformat()}" in markdown
    assert f"- A股：可用；数据截至：{date_contract['market']}；" in markdown
    assert f"- 研究数据截至：{date_contract['research']}" in markdown
    previous_markdown = _between(markdown, "## 价格表现与归因", "## 基本面分析")
    assert f"数据截至 {date_contract['previous_day']}；收盘" in previous_markdown
    technical_markdown = _between(markdown, "## 技术面分析", "## 政策分析")
    assert f"数据截至 {date_contract['technical']}；收盘" in technical_markdown

    assert f"<dt>报告日期</dt><dd>{date_contract['report']}</dd>" in html
    assert f"<dt>生成时间</dt><dd>{report.generated_at.isoformat()}</dd>" in html
    market_html = _between(html, "<section><h2>市场状态</h2>", "<section><h2>全局风险</h2>")
    assert f"<strong>A股</strong> · 可用 · {date_contract['market']} ·" in market_html
    research_html = _between(html, "<section><h2>消息面分析</h2>", "<section><h2>操作建议</h2>")
    assert f"<strong>研究数据截至：</strong>{date_contract['research']}" in research_html
    previous_html = _between(
        html,
        "<section><h2>价格表现与归因</h2>",
        "<section><h2>基本面分析</h2>",
    )
    assert f"数据截至 {date_contract['previous_day']}；收盘" in previous_html
    technical_html = _between(html, "<section><h2>技术面分析</h2>", "<section><h2>政策分析</h2>")
    assert f"数据截至 {date_contract['technical']}；收盘" in technical_html

    json_facts = (
        analysis.stock.symbol,
        analysis.stock.name,
        market_status.market.value,
        market_status.status,
        report.run_warnings[0],
        analysis.data_gaps[0],
        report.disclaimer,
        analysis.research.evidence[0].title,
        source_url,
    )
    assert all(fact in json_report for fact in json_facts)

    rendered_facts = (
        analysis.stock.symbol,
        analysis.stock.name,
        "A股",
        "可用",
        report.run_warnings[0],
        analysis.data_gaps[0],
        report.disclaimer,
        analysis.research.evidence[0].title,
        source_url,
    )
    for content in (markdown, html):
        assert all(fact in content for fact in rendered_facts)

    section_contracts = (
        ("previous_day", "价格表现与归因"),
        ("fundamental_summary", "基本面分析"),
        ("industry_summary", "行业分析"),
        ("technical", "技术面分析"),
        ("policy_summary", "政策分析"),
        ("news_summary", "消息面分析"),
        ("recommendations", "操作建议"),
        ("evidence", "来源与数据缺口"),
    )
    for json_key, heading in section_contracts:
        assert json_key in json_report
        assert heading in markdown
        assert heading in html

    assert {item["horizon"] for item in analysis_payload["recommendations"]} == {
        "short",
        "medium",
        "long",
    }
