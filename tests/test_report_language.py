from datetime import UTC, date, datetime

import pandas as pd

from stock_research.domain.enums import Credibility, Direction, EvidenceCategory, Market
from stock_research.domain.models import DailyRunRequest, Evidence, StockConfig, StockResearchInput
from stock_research.services.market_data import MarketDataUnavailable
from stock_research.services.report_builder import ReportBuilder


def make_stock() -> StockConfig:
    return StockConfig(
        symbol="SH.600000",
        name="Example Stock",
        market=Market.A_SHARE,
        industry="Banking",
    )


def make_research() -> StockResearchInput:
    symbol = "SH.600000"
    evidence = Evidence(
        title="Local cited source",
        url="https://example.test/source",
        source_name="Local source",
        published_at=datetime(2026, 7, 20, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 21, tzinfo=UTC),
        category=EvidenceCategory.COMPANY,
        direction=Direction.NEUTRAL,
        credibility=Credibility.PRIMARY,
        summary="A sufficiently detailed local evidence summary for deterministic testing.",
        symbols=[symbol],
    )
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
        evidence=[evidence],
    )


def make_request(research: StockResearchInput) -> DailyRunRequest:
    return DailyRunRequest(
        report_date=date(2026, 7, 21),
        generated_at=datetime(2026, 7, 21, 1, 0, tzinfo=UTC),
        research_inputs=[research],
    )


class FakeMarketData:
    def __init__(self, unavailable: set[str]) -> None:
        self.unavailable = unavailable

    def fetch_daily_bars(self, stock: StockConfig, end: date, days: int = 260) -> pd.DataFrame:
        if stock.symbol in self.unavailable:
            raise MarketDataUnavailable(stock.symbol, "fixture market outage")
        raise AssertionError("Test fixture must request unavailable market data")


def test_market_data_gap_uses_chinese_safe_fallback_copy() -> None:
    report = ReportBuilder().build(
        make_request(make_research()),
        [make_stock()],
        FakeMarketData(unavailable={"SH.600000"}),
    )

    recommendation = report.analyses[0].recommendations[0]
    gap = report.analyses[0].data_gaps[0]
    assert recommendation.rationale == [f"数据缺口：{gap}"]
    assert recommendation.trigger.startswith("触发条件：")
    assert "fixture market outage" not in report.analyses[0].data_gaps[0]
