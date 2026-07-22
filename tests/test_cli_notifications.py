from datetime import date

from stock_research import cli
from stock_research.services.report_store import ReportStore

from test_report_store import make_complete_report


def test_cli_builds_feishu_sections_from_saved_report_structure(tmp_path, monkeypatch) -> None:
    paths = ReportStore(tmp_path).save(make_complete_report())
    received: list[tuple[date, list[tuple[str, str]]]] = []

    class FakeFeishuService:
        def send_report_sections(self, report_date: date, sections: list[tuple[str, str]]) -> int:
            received.append((report_date, sections))
            return len(sections)

    monkeypatch.setattr(
        cli.FeishuNotificationService,
        "from_environment",
        classmethod(lambda cls: FakeFeishuService()),
    )

    assert cli._notify_generated_report(paths, date(2026, 7, 21)) == 3
    assert received[0][0] == date(2026, 7, 21)
    assert [title for title, _ in received[0][1]] == [
        "每日股票研究报告 — 市场概览",
        "每日股票研究报告 — SH.600000 Example Stock",
        "每日股票研究报告 — 全部标的操作汇总",
    ]
