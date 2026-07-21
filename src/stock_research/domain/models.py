import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from stock_research.domain.enums import Credibility, Direction, EvidenceCategory, Market


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


class EventSignal(BaseModel):
    title: str = Field(min_length=4, max_length=240)
    occurred_at: datetime
    direction: Direction
    summary: str = Field(min_length=20, max_length=1500)
    symbols: list[str] = Field(min_length=1)


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
