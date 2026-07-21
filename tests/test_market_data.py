from datetime import date, timedelta

import pandas as pd
import pytest

from stock_research.domain.enums import Market
from stock_research.domain.models import StockConfig
from stock_research.services.market_data import AkShareMarketDataProvider, MarketDataUnavailable


class FakeAkShare:
    def stock_zh_a_hist(self, **_: str) -> pd.DataFrame:
        dates = [date(2026, 7, 20) - timedelta(days=index) for index in range(31)]
        return pd.DataFrame(
            {
                "\u65e5\u671f": dates,
                "\u5f00\u76d8": list(range(31, 0, -1)),
                "\u6700\u9ad8": list(range(32, 1, -1)),
                "\u6700\u4f4e": list(range(30, -1, -1)),
                "\u6536\u76d8": [value + 0.5 for value in range(31, 0, -1)],
                "\u6210\u4ea4\u91cf": list(range(310, 0, -10)),
            }
        )


class FakeHongKongAkShare:
    def __init__(self) -> None:
        self.hk_arguments: dict[str, str] | None = None

    def stock_zh_a_hist(self, **_: str) -> pd.DataFrame:
        raise AssertionError("A-share endpoint must not be used for a Hong Kong stock")

    def stock_hk_hist(self, **arguments: str) -> pd.DataFrame:
        self.hk_arguments = arguments
        dates = [date(2026, 7, 20) - timedelta(days=index) for index in range(31)]
        return pd.DataFrame(
            {
                "date": dates,
                "open": list(range(31, 0, -1)),
                "high": list(range(32, 1, -1)),
                "low": list(range(30, -1, -1)),
                "close": [value + 0.5 for value in range(31, 0, -1)],
                "volume": list(range(310, 0, -10)),
            }
        )


def test_a_share_symbol_maps_to_akshare_code() -> None:
    assert AkShareMarketDataProvider.to_vendor_code("SH.600000") == ("600000", "sh")


def test_hk_symbol_maps_to_akshare_code() -> None:
    assert AkShareMarketDataProvider.to_vendor_code("HK.00700") == ("00700", "hk")


def test_fetch_daily_bars_normalizes_and_sorts_rows() -> None:
    provider = AkShareMarketDataProvider(client=FakeAkShare())
    stock = StockConfig(symbol="SH.600000", name="Example", market=Market.A_SHARE)

    bars = provider.fetch_daily_bars(stock, end=date(2026, 7, 20), days=31)

    assert list(bars.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert list(bars["date"])[0] == date(2026, 6, 20)
    assert list(bars["date"])[-1] == date(2026, 7, 20)
    assert bars["close"].tolist() == [value + 0.5 for value in range(1, 32)]


def test_fetch_daily_bars_requires_at_least_thirty_completed_bars() -> None:
    provider = AkShareMarketDataProvider(client=FakeAkShare())
    stock = StockConfig(symbol="SH.600000", name="Example", market=Market.A_SHARE)

    with pytest.raises(MarketDataUnavailable, match="SH.600000"):
        provider.fetch_daily_bars(stock, end=date(2026, 7, 20), days=3)


def test_hk_fetch_dispatches_to_hk_client_and_normalizes_rows() -> None:
    client = FakeHongKongAkShare()
    provider = AkShareMarketDataProvider(client=client)
    stock = StockConfig(symbol="HK.00700", name="Example HK", market=Market.HONG_KONG)

    bars = provider.fetch_daily_bars(stock, end=date(2026, 7, 20), days=31)

    assert client.hk_arguments == {
        "symbol": "00700",
        "period": "daily",
        "start_date": "20260519",
        "end_date": "20260720",
        "adjust": "qfq",
    }
    assert list(bars.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert bars.iloc[0].to_dict() == {
        "date": date(2026, 6, 20),
        "open": 1,
        "high": 2,
        "low": 0,
        "close": 1.5,
        "volume": 10,
    }
    assert bars.iloc[-1]["date"] == date(2026, 7, 20)
