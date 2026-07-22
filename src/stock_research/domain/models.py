import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_serializer, model_validator

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


DATA_GAP_RATIONALE_PREFIX = "数据缺口："
LEGACY_DATA_GAP_RATIONALE_PREFIX = "Data-gap fallback: "


class Holding(BaseModel):
    quantity: Decimal = Field(gt=0)
    cost_basis: Decimal = Field(gt=0)
    cash_available: Decimal | None = Field(default=None, ge=0)
    risk_profile: Literal["conservative", "balanced", "aggressive"] | None = None


class StockConfig(BaseModel):
    symbol: str
    name: str = Field(min_length=1, max_length=80)
    market: Market
    industry: str | None = None
    product_price_focus: list[str] = Field(default_factory=list, max_length=12)
    holding: Holding | None = None

    @field_validator("product_price_focus")
    @classmethod
    def normalize_product_price_focus(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            name = item.strip()
            if not name:
                raise ValueError("product price focus items must not be blank")
            if len(name) > 80:
                raise ValueError("product price focus items must not exceed 80 characters")
            if name not in normalized:
                normalized.append(name)
        return normalized

    @model_validator(mode="after")
    def validate_symbol(self) -> Self:
        patterns = {
            Market.A_SHARE: r"^(SH|SZ)\.\d{6}$",
            Market.BEIJING: r"^BJ\.9\d{5}$",
            Market.HONG_KONG: r"^HK\.\d{5}$",
        }
        if not re.fullmatch(patterns[self.market], self.symbol):
            raise ValueError("symbol must use SH.600000, SZ.000001, BJ.920808, or HK.00700 format")
        return self


class DailyBar(BaseModel):
    date: date
    open: float = Field(ge=0)
    high: float = Field(ge=0)
    low: float = Field(ge=0)
    close: float = Field(ge=0)
    volume: float = Field(ge=0)


class TechnicalSnapshot(BaseModel):
    data_as_of: date
    latest_close: float
    sma_5: float | None = None
    sma_20: float | None = None
    sma_60: float | None = None
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    bollinger_lower: float | None = None
    bollinger_middle: float | None = None
    bollinger_upper: float | None = None
    volume_ratio_20: float | None = None
    support_20: float | None = None
    resistance_20: float | None = None
    realized_volatility_20: float | None = None
    trend: Trend

    @model_serializer(mode="wrap")
    def serialize_with_rounded_metrics(self, handler: object) -> dict[str, object]:
        data = handler(self)
        return {
            key: round(value, 4) if isinstance(value, float) else value
            for key, value in data.items()
        }


class EventSignal(BaseModel):
    title: str = Field(min_length=4, max_length=240)
    occurred_at: datetime
    direction: Direction
    summary: str = Field(min_length=20, max_length=1500)
    symbols: list[str] = Field(min_length=1)
    scope: EventScope
    is_confirmed: bool = False
    citation_title: str | None = Field(default=None, min_length=4, max_length=240)
    citation_url: HttpUrl | None = None

    @model_validator(mode="after")
    def require_citation_for_confirmed_event(self) -> Self:
        if self.is_confirmed and (self.citation_title is None or self.citation_url is None):
            raise ValueError("confirmed events must include a citation title and URL")
        return self


class Evidence(BaseModel):
    title: str = Field(min_length=4, max_length=240)
    url: HttpUrl
    source_name: str = Field(min_length=2, max_length=120)
    published_at: datetime | None = None
    retrieved_at: datetime
    category: EvidenceCategory
    direction: Direction
    credibility: Credibility
    summary: str = Field(min_length=20, max_length=1500)
    symbols: list[str] = Field(min_length=1)


class RecommendationInput(BaseModel):
    stock: StockConfig
    technical: TechnicalSnapshot
    evidence: list[Evidence] = Field(min_length=1)
    events: list[EventSignal]

    @model_validator(mode="after")
    def validate_evidence_symbols(self) -> Self:
        if any(self.stock.symbol not in item.symbols for item in self.evidence):
            raise ValueError("evidence symbols must include recommendation stock symbol")
        if any(self.stock.symbol not in event.symbols for event in self.events):
            raise ValueError("event symbols must include recommendation stock symbol")
        return self


class Recommendation(BaseModel):
    horizon: Horizon
    action: Action
    confidence: Confidence
    risk_level: RiskLevel
    rationale: list[str] = Field(min_length=1)
    trigger: str = Field(min_length=1)
    observation_or_target: str = Field(min_length=1)
    invalidation: str = Field(min_length=1)
    position_limit: str = Field(min_length=1)
    holding_impact: str | None = None
    evidence_titles: list[str]
    citation_urls: list[HttpUrl]


class StockResearchInput(BaseModel):
    symbol: str
    data_as_of: date
    fundamental_summary: str
    industry_summary: str
    policy_summary: str
    news_summary: str
    international_summary: str
    product_price_summary: str
    recent_price_move_summary: str = "数据缺口：未提供近期股价涨跌的可引用原因分析。"
    events: list[EventSignal]
    evidence: list[Evidence]

    @field_validator("symbol")
    @classmethod
    def validate_subject_symbol(cls, value: str) -> str:
        if not re.fullmatch(r"(?:(?:SH|SZ)\.\d{6}|BJ\.9\d{5}|HK\.\d{5})", value):
            raise ValueError("symbol must use SH.600000, SZ.000001, BJ.920808, or HK.00700 format")
        return value

    @field_validator(
        "fundamental_summary",
        "industry_summary",
        "policy_summary",
        "news_summary",
        "international_summary",
        "product_price_summary",
        "recent_price_move_summary",
    )
    @classmethod
    def require_non_blank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value

    @model_validator(mode="after")
    def validate_evidence_symbols(self) -> Self:
        if any(self.symbol not in item.symbols for item in self.evidence):
            raise ValueError("evidence symbols must include research symbol")
        if any(self.symbol not in event.symbols for event in self.events):
            raise ValueError("event symbols must include research symbol")
        return self


class MarketSession(BaseModel):
    market: Market
    completed_session: date
    is_closed: bool


class MarketOutlook(BaseModel):
    """Evidence-bound broad-market analysis for the report's next-session outlook."""

    data_as_of: date | None = None
    current_analysis: str = "数据缺口：未提供可验证的当日大盘分析。"
    upside_conditions: list[str] = Field(
        default_factory=lambda: ["数据缺口：未提供可验证的上行情景与触发条件。"],
        min_length=1,
    )
    downside_conditions: list[str] = Field(
        default_factory=lambda: ["数据缺口：未提供可验证的下行情景与触发条件。"],
        min_length=1,
    )
    watch_items: list[str] = Field(
        default_factory=lambda: ["数据缺口：未提供可验证的后续观察指标。"],
        min_length=1,
    )

    @field_validator("current_analysis")
    @classmethod
    def require_nonblank_current_analysis(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("market outlook current_analysis must not be blank")
        return value

    @field_validator("upside_conditions", "downside_conditions", "watch_items")
    @classmethod
    def require_nonblank_market_outlook_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("market outlook entries must not be blank")
        return value


class DailyRunRequest(BaseModel):
    report_date: date
    run_slot: Literal["pre_market", "post_market"] | None = None
    generated_at: datetime
    research_inputs: list[StockResearchInput]
    market_sessions: list[MarketSession] = Field(default_factory=list)
    market_outlook: MarketOutlook = Field(default_factory=MarketOutlook)

    @model_validator(mode="after")
    def validate_market_sessions(self) -> Self:
        markets = [session.market for session in self.market_sessions]
        if len(markets) != len(set(markets)):
            raise ValueError("market session metadata must contain each market at most once")
        for session in self.market_sessions:
            if session.completed_session > self.report_date or (
                self.run_slot != "post_market" and session.completed_session == self.report_date
            ):
                raise ValueError("market session completed_session must precede report_date")
            if session.is_closed and session.completed_session == self.report_date:
                raise ValueError("休市市场交易日必须早于报告日期")
        return self


class PreviousDayPerformance(BaseModel):
    data_as_of: date
    close: float = Field(ge=0)
    previous_close: float | None = Field(default=None, ge=0)
    change: float
    change_percent: float | None = None
    volume: float = Field(ge=0)
    previous_volume: float | None = Field(default=None, ge=0)
    volume_change_percent: float | None = None
    reason: str = Field(min_length=1)


class MarketStatus(BaseModel):
    market: Market
    data_as_of: date | None = None
    status: Literal["available", "closed", "partial", "unavailable"]
    message: str = Field(min_length=1)


class StockAnalysis(BaseModel):
    stock: StockConfig
    previous_day: PreviousDayPerformance | None = None
    technical: TechnicalSnapshot | None = None
    research: StockResearchInput | None = None
    recommendations: list[Recommendation] = Field(min_length=3, max_length=3)
    data_gaps: list[str] = Field(default_factory=list)

    @field_validator("data_gaps")
    @classmethod
    def require_nonblank_data_gaps(cls, value: list[str]) -> list[str]:
        if any(not gap.strip() for gap in value):
            raise ValueError("data gaps must not be blank")
        return value

    @model_validator(mode="after")
    def validate_recommendations(self) -> Self:
        counts = {
            horizon: sum(item.horizon is horizon for item in self.recommendations)
            for horizon in Horizon
        }
        if any(count != 1 for count in counts.values()):
            raise ValueError("stock analysis requires exactly one recommendation per horizon")
        for recommendation in self.recommendations:
            titles = recommendation.evidence_titles
            urls = recommendation.citation_urls
            if len(titles) != len(urls):
                raise ValueError("recommendations require paired citation titles and URLs")
            if titles and (
                any(not title.strip() for title in titles)
                or any(not str(url).strip() for url in urls)
            ):
                raise ValueError("recommendations require nonempty citation titles and URLs")
            if titles:
                continue
            if not self.data_gaps:
                raise ValueError("valid analyses require cited recommendations")
            if not (
                recommendation.action is Action.WATCH
                and recommendation.confidence is Confidence.LOW
                and recommendation.risk_level is RiskLevel.HIGH
            ):
                raise ValueError(
                    "uncited data-gap recommendations must be WATCH with LOW confidence and HIGH risk"
                )
            canonical_rationales = {
                f"{prefix}{gap}"
                for prefix in (DATA_GAP_RATIONALE_PREFIX, LEGACY_DATA_GAP_RATIONALE_PREFIX)
                for gap in self.data_gaps
            }
            if not any(reason in canonical_rationales for reason in recommendation.rationale):
                raise ValueError(
                    "uncited fallbacks require explicit data-gap rationale that must match "
                    "an actual listed data gap"
                )
        return self


class DailyReport(BaseModel):
    report_date: date
    run_slot: Literal["pre_market", "post_market"] | None = None
    generated_at: datetime
    run_status: RunStatus
    market_statuses: list[MarketStatus] = Field(default_factory=list)
    market_outlook: MarketOutlook = Field(default_factory=MarketOutlook)
    global_risks: list[str] = Field(default_factory=list)
    run_warnings: list[str] = Field(default_factory=list)
    analyses: list[StockAnalysis]
    disclaimer: str = "本报告仅供研究参考，不构成个性化投资建议、收益保证或交易指令。"


class RunRecord(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    report_date: date
    started_at: datetime
    finished_at: datetime
    status: RunStatus
    stage: str = Field(min_length=1)
    error_message: str | None = None
    output_paths: dict[str, str] = Field(default_factory=dict)
    report_version: str = "1"

    @field_validator("started_at", "finished_at")
    @classmethod
    def normalize_run_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("run timestamps must include a UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_run_chronology(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not be earlier than started_at")
        return self
