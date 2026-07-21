from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from pydantic import ValidationError

from stock_research.domain.enums import (
    Action,
    Credibility,
    Direction,
    EvidenceCategory,
    Market,
    RunStatus,
)
from stock_research.domain.models import (
    DailyRunRequest,
    Evidence,
    Recommendation,
    StockAnalysis,
    StockConfig,
    StockResearchInput,
)
from stock_research.services.market_data import MarketDataUnavailable
from stock_research.services.report_builder import ReportBuilder


def make_stock(symbol: str = "SH.600000") -> StockConfig:
    return StockConfig(
        symbol=symbol,
        name="Example Stock",
        market=Market.A_SHARE if symbol.startswith(("SH", "SZ")) else Market.HONG_KONG,
        industry="Banking",
    )


def make_research(symbol: str = "SH.600000", *, evidence_count: int = 2) -> StockResearchInput:
    evidence = [
        Evidence(
            title=f"Local cited source {index}",
            url=f"https://example.test/{symbol}/{index}",
            source_name=f"Local source {index}",
            published_at=datetime(2026, 7, 20, tzinfo=UTC),
            retrieved_at=datetime(2026, 7, 21, tzinfo=UTC),
            category=EvidenceCategory.COMPANY,
            direction=Direction.NEUTRAL,
            credibility=Credibility.PRIMARY,
            summary="A sufficiently detailed local evidence summary for deterministic testing.",
            symbols=[symbol],
        )
        for index in range(evidence_count)
    ]
    return StockResearchInput(
        symbol=symbol,
        data_as_of=date(2026, 7, 20),
        fundamental_summary="Fundamental research supplied by the local research envelope.",
        industry_summary="Industry research supplied by the local research envelope.",
        policy_summary="Policy research supplied by the local research envelope.",
        news_summary="News research supplied by the local research envelope.",
        international_summary="International risk research supplied by the local envelope.",
        product_price_summary="Product price research supplied by the local envelope.",
        events=[],
        evidence=evidence,
    )


def make_request(*research: StockResearchInput) -> DailyRunRequest:
    return DailyRunRequest(
        report_date=date(2026, 7, 21),
        generated_at=datetime(2026, 7, 21, 1, 0, tzinfo=UTC),
        research_inputs=list(research),
    )


def make_bars(end: date = date(2026, 7, 20)) -> pd.DataFrame:
    rows = []
    start = end - timedelta(days=79)
    for index in range(80):
        close = 10.0 + index * 0.1
        rows.append(
            {
                "date": start + pd.Timedelta(days=index),
                "open": close - 0.05,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": 1_000 + index * 10,
            }
        )
    return pd.DataFrame(rows)


class FakeMarketData:
    def __init__(
        self,
        unavailable: set[str] | None = None,
        *,
        bars_end: date = date(2026, 7, 20),
        bars_ends: dict[str, date] | None = None,
    ) -> None:
        self.unavailable = unavailable or set()
        self.bars_end = bars_end
        self.bars_ends = bars_ends or {}

    def fetch_daily_bars(self, stock: StockConfig, end: date, days: int = 260) -> pd.DataFrame:
        if stock.symbol in self.unavailable:
            raise MarketDataUnavailable(stock.symbol, "fixture market outage")
        return make_bars(self.bars_ends.get(stock.symbol, self.bars_end))


class FixtureSessionCalendar:
    def __init__(self, completed_sessions: dict[tuple[Market, date], date | None]) -> None:
        self.completed_sessions = completed_sessions

    def latest_completed_session(self, market: Market, report_date: date) -> date | None:
        return self.completed_sessions[(market, report_date)]


def test_builder_creates_complete_analysis_and_preserves_citations() -> None:
    stock = make_stock()
    research = make_research()
    duplicate = research.evidence[0].model_copy(
        update={"title": "Lower priority duplicate", "credibility": Credibility.SECONDARY}
    )
    request = make_request(
        research.model_copy(update={"evidence": [*research.evidence, duplicate]})
    )

    report = ReportBuilder().build(request, [stock], FakeMarketData())

    assert report.run_status is RunStatus.SUCCESS
    assert len(report.analyses) == 1
    analysis = report.analyses[0]
    assert analysis.previous_day is not None and analysis.previous_day.change > 0
    assert analysis.technical is not None
    assert len(analysis.research.evidence) == 2
    assert len(analysis.recommendations) == 3
    assert all(item.citation_urls for item in analysis.recommendations)


def test_zero_source_research_is_a_labelled_partial_without_fabricated_citations() -> None:
    stock = make_stock()

    report = ReportBuilder().build(
        make_request(make_research(evidence_count=0)), [stock], FakeMarketData()
    )

    assert report.run_status is RunStatus.PARTIAL
    assert report.analyses[0].research is not None
    assert report.analyses[0].data_gaps
    assert "zero cited sources" in report.analyses[0].data_gaps[0]
    assert all(item.action is Action.WATCH for item in report.analyses[0].recommendations)
    assert all(not item.citation_urls for item in report.analyses[0].recommendations)
    assert all(not item.evidence_titles for item in report.analyses[0].recommendations)


def test_market_failure_keeps_stock_in_partial_report() -> None:
    available = make_stock()
    unavailable = make_stock("HK.00700")

    report = ReportBuilder().build(
        make_request(make_research(), make_research("HK.00700")),
        [available, unavailable],
        FakeMarketData({"HK.00700"}),
    )

    assert report.run_status is RunStatus.PARTIAL
    assert len(report.analyses) == 2
    failed = report.analyses[1]
    assert failed.stock.symbol == "HK.00700"
    assert failed.previous_day is None and failed.technical is None
    assert failed.data_gaps and "fixture market outage" in failed.data_gaps[0]
    assert all(item.action is Action.WATCH for item in failed.recommendations)
    assert any("HK.00700" in warning for warning in report.run_warnings)


def test_missing_research_input_keeps_stock_as_data_gap() -> None:
    stock = make_stock()

    report = ReportBuilder().build(make_request(), [stock], FakeMarketData())

    assert report.run_status is RunStatus.PARTIAL
    assert report.analyses[0].research is None
    assert "exactly one research input" in report.analyses[0].data_gaps[0]
    assert all(item.action is Action.WATCH for item in report.analyses[0].recommendations)


def test_zero_source_and_market_failure_labels_both_data_gaps() -> None:
    stock = make_stock()

    report = ReportBuilder().build(
        make_request(make_research(evidence_count=0)),
        [stock],
        FakeMarketData({stock.symbol}),
    )

    gaps = " ".join(report.analyses[0].data_gaps)
    assert "zero cited sources" in gaps
    assert "fixture market outage" in gaps
    assert any("fixture market outage" in warning for warning in report.run_warnings)


def test_stale_research_date_uses_partial_uncited_watch_without_news_attribution() -> None:
    stock = make_stock()
    stale = make_research().model_copy(update={"data_as_of": date(2026, 6, 18)})

    report = ReportBuilder().build(make_request(stale), [stock], FakeMarketData())

    analysis = report.analyses[0]
    assert report.run_status is RunStatus.PARTIAL
    assert any("date mismatch" in gap for gap in analysis.data_gaps)
    assert analysis.previous_day is not None
    assert stale.news_summary not in analysis.previous_day.reason
    assert all(item.action is Action.WATCH for item in analysis.recommendations)
    assert all(not item.citation_urls for item in analysis.recommendations)


def test_stock_analysis_rejects_duplicate_recommendation_horizons() -> None:
    report = ReportBuilder().build(make_request(make_research()), [make_stock()], FakeMarketData())
    analysis = report.analyses[0]
    duplicate = [
        analysis.recommendations[0],
        analysis.recommendations[0],
        analysis.recommendations[2],
    ]

    with pytest.raises(ValidationError, match="exactly one recommendation"):
        StockAnalysis.model_validate({**analysis.model_dump(), "recommendations": duplicate})


def test_complete_stock_analysis_rejects_uncited_recommendation() -> None:
    report = ReportBuilder().build(make_request(make_research()), [make_stock()], FakeMarketData())
    analysis = report.analyses[0]
    uncited: Recommendation = analysis.recommendations[0].model_copy(
        update={"evidence_titles": [], "citation_urls": []}
    )

    with pytest.raises(ValidationError, match="valid analyses require cited recommendations"):
        StockAnalysis.model_validate(
            {
                **analysis.model_dump(),
                "recommendations": [uncited, *analysis.recommendations[1:]],
            }
        )


def test_jointly_stale_technical_and_research_dates_are_partial() -> None:
    stock = make_stock()
    jointly_stale = make_research().model_copy(update={"data_as_of": date(2026, 7, 17)})

    report = ReportBuilder().build(
        make_request(jointly_stale),
        [stock],
        FakeMarketData(bars_end=date(2026, 7, 17)),
    )

    assert report.run_status is RunStatus.PARTIAL
    assert "expected completed session 2026-07-20" in report.analyses[0].data_gaps[0]
    assert all(item.action is Action.WATCH for item in report.analyses[0].recommendations)


def test_monday_report_uses_friday_as_expected_session() -> None:
    stock = make_stock()
    friday_research = make_research().model_copy(update={"data_as_of": date(2026, 7, 17)})
    monday_request = make_request(friday_research).model_copy(
        update={"report_date": date(2026, 7, 20)}
    )

    report = ReportBuilder().build(
        monday_request,
        [stock],
        FakeMarketData(bars_end=date(2026, 7, 17)),
    )

    assert report.run_status is RunStatus.SUCCESS


def test_market_status_uses_market_specific_completed_sessions_and_keeps_stale_date() -> None:
    a_share = make_stock()
    hong_kong = make_stock("HK.00700")
    request = make_request(
        make_research().model_copy(update={"data_as_of": date(2026, 7, 17)}),
        make_research("HK.00700").model_copy(update={"data_as_of": date(2026, 7, 17)}),
    )
    calendar = FixtureSessionCalendar(
        {
            (Market.A_SHARE, request.report_date): date(2026, 7, 17),
            (Market.HONG_KONG, request.report_date): date(2026, 7, 20),
        }
    )

    report = ReportBuilder(session_calendar=calendar).build(
        request,
        [a_share, hong_kong],
        FakeMarketData(
            bars_ends={
                a_share.symbol: date(2026, 7, 17),
                hong_kong.symbol: date(2026, 7, 17),
            }
        ),
    )

    statuses = {status.market: status for status in report.market_statuses}
    assert report.run_status is RunStatus.PARTIAL
    assert statuses[Market.A_SHARE].status == "available"
    assert statuses[Market.A_SHARE].data_as_of == date(2026, 7, 17)
    assert statuses[Market.HONG_KONG].status == "unavailable"
    assert statuses[Market.HONG_KONG].data_as_of == date(2026, 7, 17)
    assert "expected completed session 2026-07-20" in report.analyses[1].data_gaps[0]


@pytest.mark.parametrize(
    ("updates", "expected_message"),
    [
        ({"action": Action.BUY_IN_TRANCHES}, "uncited data-gap recommendations"),
        ({"confidence": "medium"}, "uncited data-gap recommendations"),
        ({"risk_level": "medium"}, "uncited data-gap recommendations"),
        ({"rationale": ["Generic fallback without a labelled gap."]}, "explicit data-gap"),
    ],
)
def test_uncited_data_gap_recommendation_must_be_conservative_fallback(
    updates: dict[str, object], expected_message: str
) -> None:
    stale = make_research().model_copy(update={"data_as_of": date(2026, 7, 17)})
    analysis = (
        ReportBuilder()
        .build(make_request(stale), [make_stock()], FakeMarketData(bars_end=date(2026, 7, 17)))
        .analyses[0]
    )
    invalid = analysis.recommendations[0].model_copy(update=updates)

    with pytest.raises(ValidationError, match=expected_message):
        StockAnalysis.model_validate(
            {
                **analysis.model_dump(),
                "recommendations": [invalid, *analysis.recommendations[1:]],
            }
        )


def test_recommendation_citation_titles_and_urls_must_be_paired() -> None:
    analysis = (
        ReportBuilder()
        .build(make_request(make_research()), [make_stock()], FakeMarketData())
        .analyses[0]
    )
    mismatched = analysis.recommendations[0].model_copy(update={"evidence_titles": ["One"]})

    with pytest.raises(ValidationError, match="paired citation titles and URLs"):
        StockAnalysis.model_validate(
            {
                **analysis.model_dump(),
                "recommendations": [mismatched, *analysis.recommendations[1:]],
            }
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"evidence_titles": ["", "Local cited source 1"]},
        {"citation_urls": ["", "https://example.test/SH.600000/1"]},
    ],
)
def test_recommendation_citation_pairs_reject_blank_values(
    updates: dict[str, list[str]],
) -> None:
    analysis = (
        ReportBuilder()
        .build(make_request(make_research()), [make_stock()], FakeMarketData())
        .analyses[0]
    )
    blank = analysis.recommendations[0].model_copy(update=updates)

    with pytest.raises(ValidationError, match="nonempty citation titles and URLs"):
        StockAnalysis.model_validate(
            {
                **analysis.model_dump(),
                "recommendations": [blank, *analysis.recommendations[1:]],
            }
        )


@pytest.mark.parametrize("blank_gap", ["", "   ", "\t"])
def test_stock_analysis_rejects_blank_data_gap(blank_gap: str) -> None:
    stale = make_research().model_copy(update={"data_as_of": date(2026, 7, 17)})
    analysis = (
        ReportBuilder()
        .build(make_request(stale), [make_stock()], FakeMarketData(bars_end=date(2026, 7, 17)))
        .analyses[0]
    )

    with pytest.raises(ValidationError, match="data gaps must not be blank"):
        StockAnalysis.model_validate({**analysis.model_dump(), "data_gaps": [blank_gap]})


def test_uncited_fallback_rationale_must_match_an_actual_data_gap() -> None:
    stale = make_research().model_copy(update={"data_as_of": date(2026, 7, 17)})
    analysis = (
        ReportBuilder()
        .build(make_request(stale), [make_stock()], FakeMarketData(bars_end=date(2026, 7, 17)))
        .analyses[0]
    )
    invented = analysis.recommendations[0].model_copy(
        update={"rationale": ["Data-gap fallback: invented but unlisted gap"]}
    )

    with pytest.raises(ValidationError, match="match an actual listed data gap"):
        StockAnalysis.model_validate(
            {
                **analysis.model_dump(),
                "recommendations": [invented, *analysis.recommendations[1:]],
            }
        )
