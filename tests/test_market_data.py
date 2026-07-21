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
