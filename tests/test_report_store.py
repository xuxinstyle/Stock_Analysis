import json
from pathlib import Path

from stock_research.db import create_engine_at
from stock_research.repositories.reports import ReportRepository
from stock_research.services.report_builder import ReportBuilder
from stock_research.services.report_store import ReportStore

from test_report_builder import FakeMarketData, make_request, make_research, make_stock


def make_complete_report():
    return ReportBuilder().build(make_request(make_research()), [make_stock()], FakeMarketData())


def test_report_contains_all_required_sections_per_stock(tmp_path: Path) -> None:
    report = make_complete_report()

    paths = ReportStore(tmp_path).save(report)

    markdown = paths.markdown.read_text(encoding="utf-8")
    for heading in [
        "前日表现与原因",
        "基本面分析",
        "行业分析",
        "技术面分析",
        "政策分析",
        "消息面分析",
        "突发事件",
        "短线建议",
        "中线建议",
        "长线建议",
        "来源与数据缺口",
    ]:
        assert heading in markdown
    assert paths.json.exists() and paths.html.exists()
    assert paths.json.parent == tmp_path / "2026-07-21"
    assert not list(paths.json.parent.glob("*.tmp"))


def test_formats_retain_unicode_symbol_warning_and_citation(tmp_path: Path) -> None:
    report = make_complete_report().model_copy(
        update={"run_warnings": ["本地数据警告：请检查来源"]}
    )

    paths = ReportStore(tmp_path).save(report)

    payload = json.loads(paths.json.read_text(encoding="utf-8"))
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")
    assert payload["run_warnings"] == ["本地数据警告：请检查来源"]
    assert "本地数据警告：请检查来源" in markdown and "本地数据警告：请检查来源" in html
    assert "SH.600000" in markdown and "SH.600000" in html
    assert "https://example.test/SH.600000/0" in markdown
    assert 'href="https://example.test/SH.600000/0"' in html


def test_report_repository_reads_latest_and_dates_from_sqlite(tmp_path: Path) -> None:
    repository = ReportRepository(create_engine_at(tmp_path / "metadata.sqlite3"))
    report = make_complete_report()

    repository.save(report)

    latest = repository.latest()
    assert latest is not None
    assert latest.report_date == report.report_date
    assert latest.run_status == report.run_status
    assert latest.analyses[0].recommendations[0].citation_urls
    assert repository.list_dates() == [report.report_date]
