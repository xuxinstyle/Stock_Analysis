from __future__ import annotations

from math import log, sqrt

import pandas as pd

from stock_research.domain.enums import Trend
from stock_research.domain.models import TechnicalSnapshot


_REQUIRED_COLUMNS = ("date", "open", "high", "low", "close", "volume")


def calculate_technical_snapshot(bars: pd.DataFrame) -> TechnicalSnapshot:
    missing = set(_REQUIRED_COLUMNS).difference(bars.columns)
    if missing:
        raise ValueError(f"bars are missing required columns: {', '.join(sorted(missing))}")

    frame = bars.loc[:, _REQUIRED_COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in _REQUIRED_COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = (
        frame.dropna()
        .sort_values("date")
        .drop_duplicates(subset="date", keep="last")
        .reset_index(drop=True)
    )
    if frame.empty:
        raise ValueError("bars contain no complete daily records")

    close = frame["close"]
    sma_5 = close.rolling(5).mean()
    sma_20 = close.rolling(20).mean()
    sma_60 = close.rolling(60).mean()
    rsi_14 = _rsi(close)
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    bollinger_middle = sma_20
    bollinger_deviation = close.rolling(20).std(ddof=0)
    volume_mean = frame["volume"].rolling(20).mean()
    log_returns = (close / close.shift(1)).apply(lambda value: None if value <= 0 else log(value))
    realized_volatility = log_returns.rolling(20).std(ddof=0) * sqrt(252)

    latest = frame.index[-1]
    latest_sma_20 = _optional(sma_20.loc[latest])
    latest_sma_60 = _optional(sma_60.loc[latest])
    latest_close = float(close.loc[latest])
    return TechnicalSnapshot(
        data_as_of=frame.loc[latest, "date"].date(),
        latest_close=latest_close,
        sma_5=_optional(sma_5.loc[latest]),
        sma_20=latest_sma_20,
        sma_60=latest_sma_60,
        rsi_14=_optional(rsi_14.loc[latest]),
        macd=float(macd.loc[latest]),
        macd_signal=float(macd_signal.loc[latest]),
        macd_histogram=float((macd - macd_signal).loc[latest]),
        bollinger_lower=_optional((bollinger_middle - 2 * bollinger_deviation).loc[latest]),
        bollinger_middle=latest_sma_20,
        bollinger_upper=_optional((bollinger_middle + 2 * bollinger_deviation).loc[latest]),
        volume_ratio_20=_ratio(frame.loc[latest, "volume"], volume_mean.loc[latest]),
        support_20=_optional(frame["low"].rolling(20).min().loc[latest]),
        resistance_20=_optional(frame["high"].rolling(20).max().loc[latest]),
        realized_volatility_20=_optional(realized_volatility.loc[latest]),
        trend=_trend(latest_close, latest_sma_20, latest_sma_60),
    )


def _rsi(close: pd.Series) -> pd.Series:
    change = close.diff()
    gains = change.clip(lower=0).rolling(14).mean()
    losses = -change.clip(upper=0).rolling(14).mean()
    relative_strength = gains / losses
    rsi = 100 - (100 / (1 + relative_strength))
    return rsi.mask(losses == 0, 100).mask(gains == 0, 0)


def _optional(value: object) -> float | None:
    return None if pd.isna(value) else float(value)


def _ratio(numerator: float, denominator: object) -> float | None:
    if pd.isna(denominator) or denominator == 0:
        return None
    return float(numerator / denominator)


def _trend(close: float, sma_20: float | None, sma_60: float | None) -> Trend:
    if sma_20 is None:
        return Trend.NEUTRAL
    if close > sma_20 and (sma_60 is None or sma_20 > sma_60):
        return Trend.UP
    if close < sma_20 and (sma_60 is None or sma_20 < sma_60):
        return Trend.DOWN
    return Trend.NEUTRAL
