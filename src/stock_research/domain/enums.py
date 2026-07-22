from enum import IntEnum, StrEnum


class Market(StrEnum):
    A_SHARE = "a_share"
    BEIJING = "beijing"
    HONG_KONG = "hong_kong"


class Trend(StrEnum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


class Horizon(StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class Action(StrEnum):
    WATCH = "watch"
    BUY_IN_TRANCHES = "buy_in_tranches"
    HOLD = "hold"
    REDUCE = "reduce"
    AVOID = "avoid"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RunStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class Direction(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class EventScope(StrEnum):
    LOCAL = "local"
    INTERNATIONAL = "international"


class EvidenceCategory(StrEnum):
    COMPANY = "company"
    INDUSTRY = "industry"
    POLICY = "policy"
    NEWS = "news"
    INTERNATIONAL = "international"
    PRODUCT_PRICE = "product_price"


class Credibility(IntEnum):
    LOW = 1
    SECONDARY = 2
    PRIMARY = 3
