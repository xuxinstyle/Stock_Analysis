from datetime import UTC, date, datetime

import pandas as pd

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


def make_bars() -> pd.DataFrame:
    rows = []
    for index in range(80):
        close = 10.0 + index * 0.1
        rows.append(
            {
                "date": date(2026, 4, 1) + pd.Timedelta(days=index),
                "open": close - 0.05,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": 1_000 + index * 10,
            }
        )
    return pd.DataFrame(rows)


class FakeMarketData:
    def __init__(self, unavailable: set[str] | None = None) -> None:
        self.unavailable = unavailable or set()

    def fetch_daily_bars(self, stock: StockConfig, end: date, days: int = 260) -> pd.DataFrame:
        if stock.symbol in self.unavailable:
            raise MarketDataUnavailable(stock.symbol, "fixture market outage")
        return make_bars()


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
