import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_serializer, model_validator

from stock_research.domain.enums import (
    Action,
    Confidence,
    Credibility,
    Direction,
    EvidenceCategory,
    Horizon,
    Market,
    RiskLevel,
    Trend,
)


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
    holding: Holding | None = None

    @model_validator(mode="after")
    def validate_symbol(self) -> Self:
        patterns = {
            Market.A_SHARE: r"^(SH|SZ)\.\d{6}$",
            Market.HONG_KONG: r"^HK\.\d{5}$",
        }
        if not re.fullmatch(patterns[self.market], self.symbol):
            raise ValueError("symbol must use SH.600000, SZ.000001, or HK.00700 format")
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
    events: list[EventSignal]
    evidence: list[Evidence]

    @field_validator("symbol")
    @classmethod
    def validate_subject_symbol(cls, value: str) -> str:
        if not re.fullmatch(r"(?:(?:SH|SZ)\.\d{6}|HK\.\d{5})", value):
            raise ValueError("symbol must use SH.600000, SZ.000001, or HK.00700 format")
        return value

    @field_validator(
        "fundamental_summary",
        "industry_summary",
        "policy_summary",
        "news_summary",
        "international_summary",
        "product_price_summary",
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
        return self
