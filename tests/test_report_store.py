import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, update

from stock_research.db import create_engine_at
from stock_research.domain.enums import (
    Action,
    Confidence,
    Credibility,
    Direction,
    EvidenceCategory,
    EventScope,
    Horizon,
    Market,
    RiskLevel,
    RunStatus,
    Trend,
)
from stock_research.domain.models import (
    DailyReport,
    Evidence,
    EventSignal,
    Holding,
    MarketStatus,
    PreviousDayPerformance,
    Recommendation,
    StockConfig,
    TechnicalSnapshot,
)
from stock_research.repositories.reports import ReportRepository, reports
from stock_research.services.report_builder import ReportBuilder
from stock_research.services.report_store import ReportStore

from test_report_builder import FakeMarketData, make_request, make_research, make_stock


def make_complete_report():
    return ReportBuilder().build(make_request(make_research()), [make_stock()], FakeMarketData())


def make_legacy_report_payload() -> dict[str, object]:
    payload = make_complete_report().model_dump(mode="json")
    legacy_gap = (
        "SH.600000: price data unavailable (SH.600000: "
        "HTTPSConnectionPool(host='private.example', "
        "url='https://private.example/v1', proxy URL='http://proxy.internal:8080'))."
    )
    payload["run_status"] = "partial"
    payload["disclaimer"] = (
        "Research-only report; not personalized investment advice, a return guarantee, "
        "or an instruction to trade."
    )
    payload["run_warnings"] = [legacy_gap]
    market_status = payload["market_statuses"][0]
    market_status["status"] = "unavailable"
    market_status["message"] = (
        "Completed session data is unavailable or stale for configured stocks."
    )
    analysis = payload["analyses"][0]
    analysis["data_gaps"] = [legacy_gap]
    analysis["previous_day"]["reason"] = f"No causal attribution: {legacy_gap}"
    for recommendation in analysis["recommendations"]:
        recommendation["action"] = "watch"
        recommendation["confidence"] = "low"
        recommendation["risk_level"] = "high"
        recommendation["rationale"] = [f"Data-gap fallback: {legacy_gap}"]
        recommendation["trigger"] = (
            "Trigger: obtain and validate the missing local data before reassessment."
        )
        recommendation["observation_or_target"] = (
            "Observation only: no price target is produced for incomplete data."
        )
        recommendation["invalidation"] = (
            "Invalidation: the missing data remains unavailable or cannot be verified."
        )
        recommendation["position_limit"] = "≤0%"
        recommendation["evidence_titles"] = []
        recommendation["citation_urls"] = []
    return payload


def test_report_contains_all_required_sections_per_stock(tmp_path: Path) -> None:
    report = make_complete_report()

    paths = ReportStore(tmp_path).save(report)

    markdown = paths.markdown.read_text(encoding="utf-8")
    for heading in [
        "大盘分析与后续展望",
        "价格表现与归因",
        "基本面分析",
        "行业分析",
        "技术面分析",
        "政策分析",
        "消息面分析",
        "操作建议",
        "来源",
    ]:
        assert heading in markdown
    assert paths.json.exists() and paths.html.exists()
    assert paths.json.parent == tmp_path / "2026-07-21"
    assert not list(paths.json.parent.glob("*.tmp"))


def test_report_uses_compact_per_stock_presentation(tmp_path: Path) -> None:
    report = make_complete_report()

    paths = ReportStore(tmp_path).save(report)
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")
    stock_section = "\n".join(ReportStore._markdown_analysis(report.analyses[0]))

    assert "## 股票配置\n- 市场：" in markdown
    technical_section = stock_section.split("## 技术面分析\n", maxsplit=1)[1].split(
        "\n\n## 政策分析", maxsplit=1
    )[0]
    assert "收盘" in technical_section
    assert "- 建议依据标题：" not in markdown
    assert "- 获取时间：" not in markdown
    assert "Local cited source 0" in markdown
    assert len(stock_section.splitlines()) <= 60
    assert html.count("<dt>") < 20


def test_report_hides_empty_optional_sections_and_unconfigured_product_price(
    tmp_path: Path,
) -> None:
    report = make_complete_report()

    paths = ReportStore(tmp_path).save(report)
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")

    for content in (markdown, html):
        assert "突发事件" not in content
        assert "无已提供的可验证突发事件" not in content
        assert "产品价格：" not in content
        assert "无已记录的数据缺口" not in content
    assert "## 来源" in markdown
    assert "## 来源与数据缺口" not in markdown


def test_report_combines_price_performance_with_one_concise_previous_day_reason(
    tmp_path: Path,
) -> None:
    report = make_complete_report()
    analysis = report.analyses[0]
    previous = analysis.previous_day.model_copy(
        update={"reason": "重复的前日归因只应保留在原始 JSON。"}
    )
    research = analysis.research.model_copy(
        update={"recent_price_move_summary": "近五日走势与已证实驱动。"}
    )
    report = report.model_copy(
        update={
            "analyses": [
                analysis.model_copy(update={"previous_day": previous, "research": research})
            ]
        }
    )

    paths = ReportStore(tmp_path).save(report)
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")
    payload = json.loads(paths.json.read_text(encoding="utf-8"))

    for content in (markdown, html):
        assert "价格表现与归因" in content
        assert "近五日走势与已证实驱动。" in content
        assert "重复的前日归因只应保留在原始 JSON。" in content
        assert "前日表现与原因" not in content
        assert "近期股价涨跌原因" not in content
    assert payload["analyses"][0]["previous_day"]["reason"] == (
        "重复的前日归因只应保留在原始 JSON。"
    )


def test_report_moves_matching_cross_stock_public_evidence_to_overview(tmp_path: Path) -> None:
    first = make_stock()
    second = make_stock("SZ.000001")
    report = ReportBuilder().build(
        make_request(make_research(first.symbol), make_research(second.symbol)),
        [first, second],
        FakeMarketData(),
    )
    shared = Evidence(
        title="Shared market source",
        url="https://example.test/shared-market-source",
        source_name="Shared market newsroom",
        published_at=datetime(2026, 7, 20, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 21, tzinfo=UTC),
        category=EvidenceCategory.INTERNATIONAL,
        direction=Direction.NEUTRAL,
        credibility=Credibility.SECONDARY,
        summary="A public market source that applies to multiple configured stocks.",
        symbols=[first.symbol, second.symbol],
    )
    analyses = []
    for index, analysis in enumerate(report.analyses, start=1):
        analyses.append(
            analysis.model_copy(
                update={
                    "research": analysis.research.model_copy(
                        update={
                            "evidence": [*analysis.research.evidence, shared],
                            "international_summary": f"个股 {index} 的国际传导解释。",
                        }
                    )
                }
            )
        )
    report = report.model_copy(update={"analyses": analyses})

    paths = ReportStore(tmp_path).save(report)
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")
    sections = ReportStore.notification_sections(report)

    assert markdown.count("https://example.test/shared-market-source") == 1
    assert html.count('href="https://example.test/shared-market-source"') == 1
    assert "## 公共参考来源" in markdown
    assert "公共参考来源" in sections[0][1]
    assert all("shared-market-source" not in section for _, section in sections[1:-1])
    assert "个股 1 的国际传导解释。" in markdown
    assert "个股 2 的国际传导解释。" in markdown
    assert "个股 1 的国际传导解释。" in sections[1][1]
    assert "个股 2 的国际传导解释。" in sections[2][1]
    assert "https://example.test/SH.600000/0" in markdown
    assert "https://example.test/SZ.000001/0" in markdown


def test_report_keeps_repeated_company_evidence_in_each_stock_section(tmp_path: Path) -> None:
    first = make_stock()
    second = make_stock("SZ.000001")
    report = ReportBuilder().build(
        make_request(make_research(first.symbol), make_research(second.symbol)),
        [first, second],
        FakeMarketData(),
    )
    shared_company_source = Evidence(
        title="Shared company source",
        url="https://example.test/shared-company-source",
        source_name="Company newsroom",
        published_at=datetime(2026, 7, 20, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 21, tzinfo=UTC),
        category=EvidenceCategory.COMPANY,
        direction=Direction.NEUTRAL,
        credibility=Credibility.PRIMARY,
        summary="A company source that must remain visible for every affected stock.",
        symbols=[first.symbol, second.symbol],
    )
    report = report.model_copy(
        update={
            "analyses": [
                analysis.model_copy(
                    update={
                        "research": analysis.research.model_copy(
                            update={
                                "evidence": [
                                    *analysis.research.evidence,
                                    shared_company_source,
                                ]
                            }
                        )
                    }
                )
                for analysis in report.analyses
            ]
        }
    )

    markdown = ReportStore._render_markdown(report)

    assert "公共参考来源" not in markdown
    assert markdown.count("https://example.test/shared-company-source") == 2


def test_report_keeps_news_and_nonidentical_international_evidence_per_stock(
    tmp_path: Path,
) -> None:
    first = make_stock()
    second = make_stock("SZ.000001")
    report = ReportBuilder().build(
        make_request(make_research(first.symbol), make_research(second.symbol)),
        [first, second],
        FakeMarketData(),
    )
    shared_news = Evidence(
        title="Shared news source",
        url="https://example.test/shared-news-source",
        source_name="Newsroom",
        published_at=datetime(2026, 7, 20, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 21, tzinfo=UTC),
        category=EvidenceCategory.NEWS,
        direction=Direction.NEUTRAL,
        credibility=Credibility.SECONDARY,
        summary="A news item that remains in each stock's evidence list.",
        symbols=[first.symbol, second.symbol],
    )
    international_by_stock = [
        Evidence(
            title="International context",
            url="https://example.test/international-context",
            source_name="International newsroom",
            published_at=datetime(2026, 7, 20, tzinfo=UTC),
            retrieved_at=datetime(2026, 7, 21, tzinfo=UTC),
            category=EvidenceCategory.INTERNATIONAL,
            direction=Direction.NEUTRAL,
            credibility=Credibility.SECONDARY,
            summary=f"Stock {index} needs a distinct international transmission explanation.",
            symbols=[stock.symbol],
        )
        for index, stock in enumerate((first, second), start=1)
    ]
    report = report.model_copy(
        update={
            "analyses": [
                analysis.model_copy(
                    update={
                        "research": analysis.research.model_copy(
                            update={
                                "evidence": [
                                    *analysis.research.evidence,
                                    shared_news,
                                    international_by_stock[index],
                                ]
                            }
                        )
                    }
                )
                for index, analysis in enumerate(report.analyses)
            ]
        }
    )

    paths = ReportStore(tmp_path).save(report)
    markdown = paths.markdown.read_text(encoding="utf-8")

    assert "公共参考来源" not in markdown
    assert markdown.count("https://example.test/shared-news-source") == 2
    assert markdown.count("https://example.test/international-context") == 2


def test_report_collapses_identical_horizon_advice_and_hides_internal_fields(
    tmp_path: Path,
) -> None:
    report = make_complete_report()
    analysis = report.analyses[0]
    recommendations = [
        recommendation.model_copy(update={"holding_impact": "相对成本价的信息性收益：+20.00%。"})
        for recommendation in analysis.recommendations
    ]
    report = report.model_copy(
        update={"analyses": [analysis.model_copy(update={"recommendations": recommendations})]}
    )

    paths = ReportStore(tmp_path).save(report)
    html = paths.html.read_text(encoding="utf-8")
    payload = json.loads(paths.json.read_text(encoding="utf-8"))
    stock_section = "\n".join(ReportStore._markdown_analysis(report.analyses[0]))
    expected = ReportStore._recommendation_summary(recommendations[0])

    assert f"## 操作建议\n- 短、中、长线一致：{expected}" in stock_section
    assert "短线建议" not in stock_section
    assert "中线建议" not in stock_section
    assert "长线建议" not in stock_section
    assert f"短、中、长线一致：{expected}" in html
    for internal_value in (
        recommendations[0].trigger,
        recommendations[0].holding_impact,
        "周期复核：",
        "仓位上限：",
        "持仓影响：",
    ):
        assert internal_value not in stock_section
        assert internal_value not in html
    assert payload["analyses"][0]["recommendations"][0]["trigger"]
    assert payload["analyses"][0]["recommendations"][0]["holding_impact"] == (
        "相对成本价的信息性收益：+20.00%。"
    )


def test_report_lists_horizon_advice_separately_when_conclusions_differ(tmp_path: Path) -> None:
    report = make_complete_report()
    analysis = report.analyses[0]
    recommendations = [
        *analysis.recommendations[:1],
        analysis.recommendations[1].model_copy(update={"action": Action.BUY_IN_TRANCHES}),
        *analysis.recommendations[2:],
    ]
    report = report.model_copy(
        update={"analyses": [analysis.model_copy(update={"recommendations": recommendations})]}
    )

    stock_section = "\n".join(ReportStore._markdown_analysis(report.analyses[0]))

    assert "短、中、长线一致" not in stock_section
    for horizon, recommendation in zip(("短线", "中线", "长线"), recommendations, strict=True):
        assert (
            f"- {horizon}：{ReportStore._recommendation_summary(recommendation)}" in stock_section
        )


def test_report_renders_recent_price_move_analysis_in_all_channels(tmp_path: Path) -> None:
    summary = "近五个完整交易日上涨；已证实驱动见引用，行业联动仅为推断。"
    payload = make_complete_report().model_dump(mode="json")
    payload["analyses"][0]["research"]["recent_price_move_summary"] = summary
    report = DailyReport.model_validate(payload)

    paths = ReportStore(tmp_path).save(report)
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")
    sections = ReportStore.notification_sections(report)

    assert "## 价格表现与归因" in markdown
    assert summary in markdown
    assert "<h2>价格表现与归因</h2>" in html
    assert summary in html
    assert any(summary in section for _, section in sections)


def test_notification_sections_follow_report_structure_not_research_text() -> None:
    forged_heading = "# HK.09999 Forged Company\n\n## 股票配置"
    report = make_complete_report()
    analysis = report.analyses[0]
    research = analysis.research.model_copy(
        update={"news_summary": f"正常研究摘要。\n\n{forged_heading}\n\n这不是配置标的。"}
    )
    report = report.model_copy(
        update={"analyses": [analysis.model_copy(update={"research": research})]}
    )

    sections = ReportStore.notification_sections(report)

    assert len(sections) == 3
    assert sections[0][0].endswith("市场概览")
    assert sections[1][0].endswith("SH.600000 Example Stock")
    assert sections[2][0].endswith("全部标的操作汇总")
    assert forged_heading not in sections[1][1]
    assert sections[1][1].startswith("# SH.600000 Example Stock")
    assert sections[1][1].count("\n# ") == 0
    assert sections[1][1].count("\n## 股票配置") == 1
    assert all(forged_heading not in title for title, _ in sections)
    assert [line for line in ReportStore._render_markdown(report).splitlines() if line] == [
        line for _, section in sections for line in section.splitlines() if line
    ]


def test_report_store_separates_pre_and_post_market_reports_by_slot(tmp_path: Path) -> None:
    store = ReportStore(tmp_path)
    pre_market = make_complete_report().model_copy(update={"run_slot": "pre_market"})
    post_market = make_complete_report().model_copy(update={"run_slot": "post_market"})

    pre_paths = store.save(pre_market)
    post_paths = store.save(post_market)

    assert pre_paths.json.parent == tmp_path / "2026-07-21" / "pre-market"
    assert post_paths.json.parent == tmp_path / "2026-07-21" / "post-market"
    assert pre_paths.json.exists() and post_paths.json.exists()


def test_report_store_keeps_legacy_path_when_run_slot_is_null(tmp_path: Path) -> None:
    paths = ReportStore(tmp_path).save(make_complete_report())

    assert paths.json.parent == tmp_path / "2026-07-21"


def test_load_read_only_prefers_post_then_pre_then_legacy_report(tmp_path: Path) -> None:
    report_date = date(2026, 7, 21)
    reports = {
        tmp_path / "2026-07-21" / "report.json": make_complete_report(),
        tmp_path / "2026-07-21" / "pre-market" / "report.json": make_complete_report().model_copy(
            update={"run_slot": "pre_market"}
        ),
        tmp_path / "2026-07-21" / "post-market" / "report.json": make_complete_report().model_copy(
            update={"run_slot": "post_market"}
        ),
    }
    for path, report in reports.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    assert ReportStore.load_read_only(tmp_path, report_date).run_slot == "post_market"
    (tmp_path / "2026-07-21" / "post-market" / "report.json").unlink()
    assert ReportStore.load_read_only(tmp_path, report_date).run_slot == "pre_market"
    (tmp_path / "2026-07-21" / "pre-market" / "report.json").unlink()
    assert ReportStore.load_read_only(tmp_path, report_date).run_slot is None
    assert not (tmp_path / "reports.sqlite3").exists()


@pytest.mark.parametrize("run_slot", ["invalid", "../outside", "post-market"])
def test_report_store_rejects_invalid_run_slot(tmp_path: Path, run_slot: str) -> None:
    with pytest.raises(ValueError, match="运行时段"):
        ReportStore(tmp_path).paths_for(date(2026, 7, 21), run_slot)


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


def test_markdown_and_html_render_chinese_display_labels_and_enum_values(tmp_path: Path) -> None:
    report = make_complete_report()
    analysis = report.analyses[0]
    recommendations = [
        analysis.recommendations[0].model_copy(update={"action": Action.WATCH}),
        *analysis.recommendations[1:],
    ]
    report = report.model_copy(
        update={"analyses": [analysis.model_copy(update={"recommendations": recommendations})]}
    )

    paths = ReportStore(tmp_path).save(report)
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")
    payload = json.loads(paths.json.read_text(encoding="utf-8"))

    assert "运行状态：成功" in markdown
    assert "# SH.600000 Example Stock" in markdown
    assert "## 股票配置\n- 市场：A股" in markdown
    assert "短、中、长线一致：观望（低风险 / 中等置信度）" in markdown
    assert "run_status" not in markdown
    assert "action" not in markdown
    assert "<dt>运行状态</dt><dd>成功</dd>" in html
    assert "<h1>SH.600000 Example Stock</h1>" in html
    assert "<p>市场：A股；行业：Banking</p>" in html
    assert "短、中、长线一致：观望（低风险 / 中等置信度）" in html
    assert "run_status" not in html
    assert "action" not in html
    assert payload["run_status"] == "success"
    assert payload["analyses"][0]["recommendations"][0]["action"] == "watch"


def test_compact_human_reports_omit_raw_volume_details_without_changing_json_numbers(
    tmp_path: Path,
) -> None:
    paths = ReportStore(tmp_path).save(make_complete_report())

    payload = json.loads(paths.json.read_text(encoding="utf-8"))
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")

    assert "成交量：1,790 股" not in markdown
    assert "前一日成交量：1,780 股" not in markdown
    assert "成交量变化：+0.56%" not in markdown
    assert "<dt>成交量</dt><dd>1,790 股</dd>" not in html
    previous_day = payload["analyses"][0]["previous_day"]
    assert previous_day["volume"] == 1790.0
    assert previous_day["previous_volume"] == 1780.0
    assert abs(previous_day["volume_change_percent"] - 0.5617977528) < 1e-10


def test_reports_end_with_per_stock_recommendation_summary(tmp_path: Path) -> None:
    first = make_stock()
    second = make_stock("SZ.000001")
    report = ReportBuilder().build(
        make_request(make_research(first.symbol), make_research(second.symbol)),
        [first, second],
        FakeMarketData(),
    )

    paths = ReportStore(tmp_path).save(report)
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")

    assert markdown.rstrip().endswith(
        "- SZ.000001 Example Stock：短、中、长线一致：观望（低风险 / 中等置信度）"
    )
    assert "## 全部标的操作汇总" in markdown
    assert "| 股票 | 短线建议 | 中线建议 | 长线建议 |" not in markdown
    assert '<section class="recommendation-summary"' in html
    assert "全部标的操作汇总" in html
    assert "SH.600000 Example Stock" in html
    assert "SZ.000001 Example Stock" in html
    assert "观望（低风险 / 中等置信度）" in html


def test_display_mapping_covers_all_rendered_fields_enums_and_nullable_values() -> None:
    displayed_models = (
        StockConfig,
        Holding,
        MarketStatus,
        PreviousDayPerformance,
        TechnicalSnapshot,
        EventSignal,
        Recommendation,
    )
    enum_values = (
        *Market,
        *Trend,
        *Horizon,
        *Action,
        *RiskLevel,
        *Confidence,
        *RunStatus,
        *Direction,
        *EventScope,
        *EvidenceCategory,
        *Credibility,
    )

    for model in displayed_models:
        for field_name in model.model_fields:
            assert ReportStore._display_field(field_name) != field_name
    enum_field_names = {
        Market: "market",
        Trend: "trend",
        Horizon: "horizon",
        Action: "action",
        RiskLevel: "risk_level",
        Confidence: "confidence",
        RunStatus: "run_status",
        Direction: "direction",
        EventScope: "scope",
        EvidenceCategory: "category",
        Credibility: "credibility",
    }
    for enum_value in enum_values:
        assert ReportStore._display_value(
            enum_value.value, enum_field_names[type(enum_value)]
        ) != str(enum_value.value)
    assert ReportStore._display_value(None) == "无"
    assert ReportStore._display_value(True) == "是"
    assert ReportStore._display_value(False) == "否"


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


def test_report_repository_reads_legacy_data_gap_fallback_rationale(tmp_path: Path) -> None:
    repository = ReportRepository(create_engine_at(tmp_path / "metadata.sqlite3"))
    report = ReportBuilder().build(
        make_request(make_research()),
        [make_stock()],
        FakeMarketData(unavailable={"SH.600000"}),
    )
    repository.save(report)

    payload = report.model_dump(mode="json")
    gap = payload["analyses"][0]["data_gaps"][0]
    for recommendation in payload["analyses"][0]["recommendations"]:
        recommendation["rationale"] = [f"Data-gap fallback: {gap}"]
    with repository.engine.begin() as connection:
        connection.execute(
            update(reports)
            .where(reports.c.report_date == report.report_date)
            .values(report_json=json.dumps(payload, ensure_ascii=False))
        )

    restored = repository.latest()

    assert restored is not None
    assert restored.analyses[0].recommendations[0].rationale == [f"Data-gap fallback: {gap}"]


def test_legacy_data_gap_fallback_rationale_renders_in_chinese(tmp_path: Path) -> None:
    repository = ReportRepository(create_engine_at(tmp_path / "metadata.sqlite3"))
    report = ReportBuilder().build(
        make_request(make_research()),
        [make_stock()],
        FakeMarketData(unavailable={"SH.600000"}),
    )
    repository.save(report)

    payload = report.model_dump(mode="json")
    gap = payload["analyses"][0]["data_gaps"][0]
    for recommendation in payload["analyses"][0]["recommendations"]:
        recommendation["rationale"] = [f"Data-gap fallback: {gap}"]
    with repository.engine.begin() as connection:
        connection.execute(
            update(reports)
            .where(reports.c.report_date == report.report_date)
            .values(report_json=json.dumps(payload, ensure_ascii=False))
        )

    restored = repository.latest()
    assert restored is not None
    paths = ReportStore(tmp_path / "rendered", repository=repository).save(restored)
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")

    assert f"数据缺口：{gap}" in markdown
    assert gap in html
    assert "Data-gap fallback:" not in markdown
    assert "Data-gap fallback:" not in html


def test_real_legacy_report_renders_safe_chinese_without_mutating_saved_json(
    tmp_path: Path,
) -> None:
    repository = ReportRepository(create_engine_at(tmp_path / "metadata.sqlite3"))
    payload = make_legacy_report_payload()
    legacy_report = DailyReport.model_validate(payload)
    repository.save(legacy_report)
    with repository.engine.connect() as connection:
        stored_before = connection.scalar(select(reports.c.report_json))

    restored = repository.latest()
    assert restored is not None
    paths = ReportStore(tmp_path / "rendered").save(restored)
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")
    rendered_payload = json.loads(paths.json.read_text(encoding="utf-8"))
    with repository.engine.connect() as connection:
        stored_after = connection.scalar(select(reports.c.report_json))

    safe_gap = "SH.600000：未能取得完整的日行情数据，已暂缓技术分析。"
    for content in (markdown, html):
        assert "本报告仅供研究参考，不构成个性化投资建议、收益保证或交易指令。" in content
        assert "已配置股票的已完成交易日数据不可用或已过期。" in content
        assert safe_gap in content
        assert "触发条件：补齐并核验缺失的本地数据后再评估。" not in content
        assert "仅观察：数据不完整时不提供价格目标。" not in content
        assert "失效条件：缺失数据仍不可获得或无法核验。" not in content
        assert "前日表现不作归因" not in content
        assert "Local cited source 0" in content
        assert "https://example.test/SH.600000/0" in content
        for forbidden in (
            "Research-only report",
            "Completed session data",
            "Data-gap fallback:",
            "Trigger: obtain",
            "Observation only:",
            "Invalidation:",
            "No causal attribution:",
            "HTTPSConnectionPool",
            "private.example",
            "proxy.internal",
            "proxy URL",
        ):
            assert forbidden not in content

    assert stored_after == stored_before
    assert rendered_payload["disclaimer"] == payload["disclaimer"]
    assert rendered_payload["run_warnings"] == payload["run_warnings"]
    rendered_analysis = rendered_payload["analyses"][0]
    assert rendered_analysis["data_gaps"] == payload["analyses"][0]["data_gaps"]
    assert (
        rendered_analysis["previous_day"]["reason"]
        == payload["analyses"][0]["previous_day"]["reason"]
    )
    assert rendered_analysis["recommendations"] == payload["analyses"][0]["recommendations"]


def test_legacy_system_text_collision_does_not_translate_source_owned_fields(
    tmp_path: Path,
) -> None:
    legacy_title = (
        "Research-only report; not personalized investment advice, a return guarantee, "
        "or an instruction to trade."
    )
    payload = make_legacy_report_payload()
    analysis = payload["analyses"][0]
    research = analysis["research"]
    research["evidence"][0]["title"] = legacy_title
    research["evidence"][0]["source_name"] = legacy_title
    research["evidence"][0]["summary"] = legacy_title
    research["events"] = [
        {
            "title": "Legacy source-owned title collision",
            "occurred_at": "2026-07-20T12:00:00Z",
            "direction": "neutral",
            "summary": legacy_title,
            "symbols": ["SH.600000"],
            "scope": "local",
            "is_confirmed": True,
            "citation_title": legacy_title,
            "citation_url": "https://example.test/SH.600000/event",
        }
    ]
    for recommendation in analysis["recommendations"]:
        recommendation["evidence_titles"] = [legacy_title]
        recommendation["citation_urls"] = ["https://example.test/SH.600000/recommendation"]

    paths = ReportStore(tmp_path).save(DailyReport.model_validate(payload))
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")

    assert legacy_title in markdown
    assert legacy_title in html
    assert f"- 建议依据标题：{legacy_title}" not in markdown
    assert "免责声明：本报告仅供研究参考，不构成个性化投资建议、收益保证或交易指令。" in markdown
    assert (
        '<div class="notice research-notice"><strong>仅供研究使用</strong><span>'
        "本报告仅供研究参考，不构成个性化投资建议、收益保证或交易指令。</span>" in html
    )


def test_source_owned_fields_preserve_enum_like_strings(tmp_path: Path) -> None:
    payload = make_legacy_report_payload()
    analysis = payload["analyses"][0]
    research = analysis["research"]
    research["evidence"][0]["title"] = "news"
    research["evidence"][0]["source_name"] = "company"
    research["events"] = [
        {
            "title": "news",
            "occurred_at": "2026-07-20T12:00:00Z",
            "direction": "neutral",
            "summary": "A sufficiently detailed source-owned event summary.",
            "symbols": ["SH.600000"],
            "scope": "local",
            "is_confirmed": True,
            "citation_title": "watch",
            "citation_url": "https://example.test/SH.600000/event",
        }
    ]
    analysis["recommendations"][0]["evidence_titles"] = ["low"]
    analysis["recommendations"][0]["citation_urls"] = [
        "https://example.test/SH.600000/recommendation"
    ]

    paths = ReportStore(tmp_path).save(DailyReport.model_validate(payload))
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")

    for content in (markdown, html):
        assert "news" in content
        assert "company" in content
        assert "watch" in content
        assert "建议依据标题：low" not in content


def test_contextual_medium_labels_render_in_markdown_and_html(tmp_path: Path) -> None:
    report = make_complete_report()
    analysis = report.analyses[0]
    recommendations = [
        recommendation.model_copy(
            update={"risk_level": RiskLevel.MEDIUM, "confidence": Confidence.MEDIUM}
        )
        if recommendation.horizon is Horizon.MEDIUM
        else recommendation
        for recommendation in analysis.recommendations
    ]
    report = report.model_copy(
        update={"analyses": [analysis.model_copy(update={"recommendations": recommendations})]}
    )

    paths = ReportStore(tmp_path).save(report)
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")
    payload = json.loads(paths.json.read_text(encoding="utf-8"))

    assert "中线：观望（中等风险 / 中等置信度）" in markdown
    assert "中线：观望（中等风险 / 中等置信度）" in html
    assert ReportStore._display_value(Horizon.MEDIUM.value, "horizon") == "中线"
    assert ReportStore._display_value(RiskLevel.MEDIUM.value, "risk_level") == "中等"
    assert ReportStore._display_value(Confidence.MEDIUM.value, "confidence") == "中等"
    rendered_recommendation = next(
        item for item in payload["analyses"][0]["recommendations"] if item["horizon"] == "medium"
    )
    assert rendered_recommendation["horizon"] == "medium"
    assert rendered_recommendation["risk_level"] == "medium"
    assert rendered_recommendation["confidence"] == "medium"


def test_all_formats_render_equivalent_dates_holding_and_citations(tmp_path: Path) -> None:
    stock = make_stock().model_copy(
        update={
            "holding": Holding(
                quantity=Decimal("100"),
                cost_basis=Decimal("10"),
                cash_available=Decimal("2500"),
                risk_profile="balanced",
            )
        }
    )
    event = EventSignal(
        title="Confirmed adverse disclosure event",
        occurred_at=datetime(2026, 7, 20, tzinfo=UTC),
        direction=Direction.NEGATIVE,
        summary="A confirmed fixture event with enough detail for multi-format parity testing.",
        symbols=[stock.symbol],
        scope="local",
        is_confirmed=True,
        citation_title="Confirmed exchange event notice",
        citation_url="https://example.test/confirmed-event",
    )
    research = make_research().model_copy(update={"events": [event]})
    report = ReportBuilder().build(make_request(research), [stock], FakeMarketData())

    paths = ReportStore(tmp_path).save(report)

    rendered = [
        paths.json.read_text(encoding="utf-8"),
        paths.markdown.read_text(encoding="utf-8"),
        paths.html.read_text(encoding="utf-8"),
    ]
    expected_facts = [
        "2026-07-21",
        "2026-07-20",
        "Confirmed exchange event notice",
        "https://example.test/confirmed-event",
    ]
    for content in rendered:
        assert all(fact in content for fact in expected_facts)
    assert "相对成本价的信息性收益：+79.00%。" in rendered[0]
    assert 'href="https://example.test/confirmed-event"' in rendered[2]
    assert "持仓：100 股，成本 10" in rendered[1]
    assert "持仓：100 股，成本 10" in rendered[2]
    assert "风险偏好：均衡型" not in rendered[1]
    assert "风险偏好：均衡型" not in rendered[2]
    assert json.loads(rendered[0])["analyses"][0]["stock"]["holding"]["risk_profile"] == "balanced"

    for content in rendered[1:]:
        assert event.title in content
        assert event.citation_title in content
        assert "现金可用" not in content
        assert "相对成本价的信息性收益：+79.00%。" not in content
