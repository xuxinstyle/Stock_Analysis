from enum import StrEnum


class Market(StrEnum):
    A_SHARE = "a_share"
    HONG_KONG = "hong_kong"


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
