from datetime import date, timedelta

import pandas as pd
import pytest

from stock_research.domain.enums import Trend
from stock_research.services.indicators import calculate_technical_snapshot


def make_bars(closes: list[float]) -> pd.DataFrame:
    start = date(2026, 6, 11)
    return pd.DataFrame(
        {
            "date": [start + timedelta(days=index) for index in range(len(closes))],
            "open": closes,
            "high": [close + 0.5 for close in closes],
            "low": [close - 0.5 for close in closes],
            "close": closes,
            "volume": [1_000 + index * 10 for index in range(len(closes))],
        }
    )


def test_technical_snapshot_uses_most_recent_completed_bar() -> None:
    bars = make_bars(closes=[10 + index * 0.2 for index in range(40)])

    snapshot = calculate_technical_snapshot(bars)

    assert snapshot.data_as_of == date(2026, 7, 20)
    assert snapshot.sma_20 == pytest.approx(15.9)
    assert snapshot.trend is Trend.UP


def test_technical_snapshot_exposes_unrounded_calculations() -> None:
    bars = make_bars(closes=[10 + index * 0.13 for index in range(65)])

    snapshot = calculate_technical_snapshot(bars)

    expected_sma_20 = sum(bars["close"].tail(20)) / 20
    assert snapshot.sma_20 == pytest.approx(expected_sma_20)
    assert snapshot.sma_20 != round(expected_sma_20, 2)
