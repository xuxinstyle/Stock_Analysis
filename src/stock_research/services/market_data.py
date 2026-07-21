from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol

import pandas as pd

from stock_research.domain.enums import Market
from stock_research.domain.models import StockConfig


class MarketDataUnavailable(RuntimeError):
    def __init__(self, symbol: str, message: str) -> None:
        self.symbol = symbol
        super().__init__(f"{symbol}: {message}")


class MarketDataProvider(Protocol):
    def fetch_daily_bars(
        self, stock: StockConfig, end: date, days: int = 260
    ) -> pd.DataFrame: ...


class AkShareMarketDataProvider:
    _COLUMNS = {
        "date": ("date", "\u65e5\u671f"),
        "open": ("open", "\u5f00\u76d8"),
        "high": ("high", "\u6700\u9ad8"),
        "low": ("low", "\u6700\u4f4e"),
        "close": ("close", "\u6536\u76d8"),
        "volume": ("volume", "\u6210\u4ea4\u91cf"),
    }

    def __init__(self, client: object | None = None) -> None:
        self._client = client

    @staticmethod
    def to_vendor_code(symbol: str) -> tuple[str, str]:
        exchange, code = symbol.split(".", maxsplit=1)
        return code, {"SH": "sh", "SZ": "sz", "HK": "hk"}[exchange]

    def fetch_daily_bars(
        self, stock: StockConfig, end: date, days: int = 260
    ) -> pd.DataFrame:
        if days <= 0:
            raise ValueError("days must be positive")

        raw = self._fetch_raw(stock, end=end, days=days)
        bars = self._normalise(raw, end=end).tail(days).reset_index(drop=True)
        if len(bars) < 30:
            raise MarketDataUnavailable(stock.symbol, "fewer than 30 completed daily bars are available")
        return bars

    def _fetch_raw(self, stock: StockConfig, end: date, days: int) -> pd.DataFrame:
        code, _ = self.to_vendor_code(stock.symbol)
        start = end - timedelta(days=days * 2)
        client = self._get_client()
        arguments = {
            "symbol": code,
            "period": "daily",
            "start_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
            "adjust": "qfq",
        }
        if stock.market is Market.A_SHARE:
            return client.stock_zh_a_hist(**arguments)
        if stock.market is Market.HONG_KONG:
            return client.stock_hk_hist(**arguments)
        raise MarketDataUnavailable(stock.symbol, "unsupported market")

    def _get_client(self) -> object:
        if self._client is None:
            import akshare

            self._client = akshare
        return self._client

    @classmethod
    def _normalise(cls, raw: pd.DataFrame, end: date) -> pd.DataFrame:
        columns: dict[str, str] = {}
        for target, aliases in cls._COLUMNS.items():
            source = next((name for name in aliases if name in raw.columns), None)
            if source is None:
                return pd.DataFrame(columns=cls._COLUMNS)
            columns[source] = target

        bars = raw.loc[:, list(columns)].rename(columns=columns).copy()
        bars["date"] = pd.to_datetime(bars["date"], errors="coerce").dt.date
        for column in ("open", "high", "low", "close", "volume"):
            bars[column] = pd.to_numeric(bars[column], errors="coerce")
        bars = bars.dropna(subset=["date", "open", "high", "low", "close", "volume"])
        bars = bars.loc[bars["date"] <= end]
        return bars.sort_values("date").drop_duplicates(subset="date", keep="last")
