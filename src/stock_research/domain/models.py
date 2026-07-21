import re
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from stock_research.domain.enums import Market


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
