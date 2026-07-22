from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
from typing import Callable, ContextManager, Iterator, Protocol

import pandas as pd
from requests.exceptions import RequestException

from stock_research.domain.enums import Market
from stock_research.domain.models import StockConfig


class MarketDataUnavailable(RuntimeError):
    def __init__(self, symbol: str, message: str) -> None:
        self.symbol = symbol
        super().__init__(f"{symbol}: {message}")


class _BeijingConnectionUnavailable(RuntimeError):
    """A public OpenTDX standard-quotation setup failure."""


class _BeijingDailyBarUnavailable(RuntimeError):
    """A public OpenTDX daily-bar request failure."""


class _MalformedMarketDataResponse(RuntimeError):
    """A vendor response that cannot be represented as daily-bar data."""


class MarketDataProvider(Protocol):
    def fetch_daily_bars(self, stock: StockConfig, end: date, days: int = 260) -> pd.DataFrame: ...


class AkShareMarketDataProvider:
    _COLUMNS = {
        "date": ("date", "datetime", "\u65e5\u671f"),
        "open": ("open", "\u5f00\u76d8"),
        "high": ("high", "\u6700\u9ad8"),
        "low": ("low", "\u6700\u4f4e"),
        "close": ("close", "\u6536\u76d8"),
        "volume": ("volume", "vol", "amount", "\u6210\u4ea4\u91cf"),
    }

    def __init__(
        self,
        client: object | None = None,
        beijing_client_factory: Callable[[], ContextManager[object]] | None = None,
    ) -> None:
        self._client = client
        self._beijing_client_factory = beijing_client_factory or self._open_beijing_client

    @staticmethod
    def to_vendor_code(symbol: str) -> tuple[str, str]:
        exchange, code = symbol.split(".", maxsplit=1)
        return code, {"SH": "sh", "SZ": "sz", "BJ": "bj", "HK": "hk"}[exchange]

    def fetch_daily_bars(self, stock: StockConfig, end: date, days: int = 260) -> pd.DataFrame:
        if days <= 0:
            raise ValueError("days must be positive")

        try:
            raw = self._fetch_raw(stock, end=end, days=days)
        except (
            ImportError,
            _BeijingConnectionUnavailable,
            _BeijingDailyBarUnavailable,
            _MalformedMarketDataResponse,
            OSError,
            RequestException,
        ) as error:
            raise MarketDataUnavailable(stock.symbol, str(error)) from error
        if not isinstance(raw, pd.DataFrame):
            raise MarketDataUnavailable(stock.symbol, "malformed daily-bar response")
        try:
            bars = self._normalise(raw, end=end).tail(days).reset_index(drop=True)
        except (KeyError, TypeError, ValueError) as error:
            raise MarketDataUnavailable(stock.symbol, "malformed daily-bar response") from error
        if len(bars) < 30:
            raise MarketDataUnavailable(
                stock.symbol, "fewer than 30 completed daily bars are available"
            )
        return bars

    def _fetch_raw(self, stock: StockConfig, end: date, days: int) -> pd.DataFrame:
        code, exchange = self.to_vendor_code(stock.symbol)
        start = end - timedelta(days=days * 2)
        arguments = {
            "symbol": code,
            "period": "daily",
            "start_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
            "adjust": "qfq",
        }
        if stock.market is Market.A_SHARE:
            client = self._get_client()
            return client.stock_zh_a_hist_tx(
                symbol=f"{exchange}{code}",
                start_date=arguments["start_date"],
                end_date=arguments["end_date"],
                adjust="qfq",
            )
        if stock.market is Market.BEIJING:
            from opentdx.const import ADJUST, MARKET, PERIOD

            with self._beijing_client_factory() as beijing_client:
                try:
                    rows = beijing_client.stock_kline(
                        MARKET.BJ, code, PERIOD.DAILY, adjust=ADJUST.QFQ, count=days * 2
                    )
                except Exception as error:
                    raise _BeijingDailyBarUnavailable(
                        "OpenTDX public daily-bar request failed"
                    ) from error
            try:
                return pd.DataFrame(rows)
            except (TypeError, ValueError) as error:
                raise _MalformedMarketDataResponse("malformed daily-bar response") from error
        if stock.market is Market.HONG_KONG:
            client = self._get_client()
            return client.stock_hk_hist(**arguments)
        raise MarketDataUnavailable(stock.symbol, "unsupported market")

    def _get_client(self) -> object:
        if self._client is None:
            import akshare

            self._client = akshare
        return self._client

    @staticmethod
    @contextmanager
    def _open_beijing_client() -> Iterator[object]:
        """Open only OpenTDX's public standard quotation feed for BSE daily bars."""
        from opentdx.tdxClient import TdxClient

        quotation_client = None
        try:
            try:
                client = TdxClient()
                quotation_client = client.q_client()
                if quotation_client.connect() is None:
                    raise _BeijingConnectionUnavailable(
                        "could not connect to OpenTDX public quotation feed"
                    )
                if not quotation_client.login():
                    raise _BeijingConnectionUnavailable("OpenTDX public quotation login failed")
            except _BeijingConnectionUnavailable:
                raise
            except Exception as error:
                raise _BeijingConnectionUnavailable(
                    f"OpenTDX public quotation connection failed: {error}"
                ) from error
            yield client
        finally:
            if quotation_client is not None and quotation_client.connected:
                quotation_client.disconnect()

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
