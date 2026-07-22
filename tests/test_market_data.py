from datetime import date, datetime, timedelta
import pandas as pd
import pytest
from opentdx.const import ADJUST, MARKET, PERIOD
from requests.exceptions import ProxyError

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

    def stock_zh_a_hist_tx(self, **_: str) -> pd.DataFrame:
        return self.stock_zh_a_hist()


class FakeTencentAkShare:
    def __init__(self) -> None:
        self.tencent_arguments: dict[str, str] | None = None
        self.eastmoney_called = False

    def stock_zh_a_hist(self, **_: str) -> pd.DataFrame:
        self.eastmoney_called = True
        raise AssertionError("Eastmoney A-share history endpoint must not be used")

    def stock_zh_a_hist_tx(self, **arguments: str) -> pd.DataFrame:
        self.tencent_arguments = arguments
        dates = [date(2026, 7, 21) - timedelta(days=index) for index in range(31)]
        return pd.DataFrame(
            {
                "date": dates,
                "open": list(range(31, 0, -1)),
                "high": list(range(32, 1, -1)),
                "low": list(range(30, -1, -1)),
                "close": [value + 0.5 for value in range(31, 0, -1)],
                "amount": list(range(31_000, 0, -1_000)),
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


class UnavailableAkShare:
    def stock_zh_a_hist_tx(self, **_: str) -> pd.DataFrame:
        raise ProxyError("public market-data endpoint disconnected")


class FakeOpenTdxClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, object, object, int]] = []

    def __enter__(self) -> "FakeOpenTdxClient":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None

    def stock_kline(
        self, market: object, code: str, period: object, *, adjust: object, count: int
    ) -> list[dict[str, object]]:
        self.calls.append((market, code, period, adjust, count))
        dates = [date(2026, 6, 21) + timedelta(days=index) for index in range(32)]
        return [
            {
                "datetime": datetime.combine(value, datetime.min.time()),
                "open": index + 1,
                "high": index + 2,
                "low": index,
                "close": index + 1.5,
                "vol": (index + 1) * 1_000,
            }
            for index, value in enumerate(dates)
        ]


class UnavailableOpenTdxClient:
    def __enter__(self) -> "UnavailableOpenTdxClient":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None

    def stock_kline(self, *_: object, **__: object) -> list[dict[str, object]]:
        raise Exception("public daily-bar request failed")


class FakeDefaultQuotationClient:
    def __init__(self, connect_result: object, login_result: object = True) -> None:
        self.connect_result = connect_result
        self.login_result = login_result
        self.connected = False
        self.login_called = False
        self.disconnected = False

    def connect(self) -> object:
        if isinstance(self.connect_result, BaseException):
            raise self.connect_result
        if self.connect_result is not None:
            self.connected = True
        return self.connect_result

    def login(self) -> object:
        self.login_called = True
        return self.login_result

    def disconnect(self) -> None:
        self.disconnected = True
        self.connected = False


class FakeDefaultTdxClient:
    quotation_client: FakeDefaultQuotationClient
    rows: list[dict[str, object]]

    def q_client(self) -> FakeDefaultQuotationClient:
        return self.quotation_client

    def stock_kline(self, *_: object, **__: object) -> list[dict[str, object]]:
        return self.rows


def install_default_tdx_client(
    monkeypatch: pytest.MonkeyPatch,
    quotation_client: FakeDefaultQuotationClient,
    rows: list[dict[str, object]] | None = None,
) -> None:
    FakeDefaultTdxClient.quotation_client = quotation_client
    FakeDefaultTdxClient.rows = (
        rows
        if rows is not None
        else FakeOpenTdxClient().stock_kline(
            MARKET.BJ, "920808", PERIOD.DAILY, adjust=ADJUST.QFQ, count=62
        )
    )
    monkeypatch.setattr("opentdx.tdxClient.TdxClient", FakeDefaultTdxClient)


class MalformedTencentAkShare:
    def stock_zh_a_hist_tx(self, **_: str) -> list[object]:
        return []


def test_a_share_symbol_maps_to_akshare_code() -> None:
    assert AkShareMarketDataProvider.to_vendor_code("SH.600000") == ("600000", "sh")


def test_hk_symbol_maps_to_akshare_code() -> None:
    assert AkShareMarketDataProvider.to_vendor_code("HK.00700") == ("00700", "hk")


def test_beijing_symbol_maps_to_akshare_code() -> None:
    assert AkShareMarketDataProvider.to_vendor_code("BJ.920808") == ("920808", "bj")


def test_fetch_daily_bars_normalizes_and_sorts_rows() -> None:
    provider = AkShareMarketDataProvider(client=FakeAkShare())
    stock = StockConfig(symbol="SH.600000", name="Example", market=Market.A_SHARE)

    bars = provider.fetch_daily_bars(stock, end=date(2026, 7, 20), days=31)

    assert list(bars.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert list(bars["date"])[0] == date(2026, 6, 20)
    assert list(bars["date"])[-1] == date(2026, 7, 20)
    assert bars["close"].tolist() == [value + 0.5 for value in range(1, 32)]


def test_beijing_daily_adapter_requests_qfq_daily_bars() -> None:
    client = FakeOpenTdxClient()
    provider = AkShareMarketDataProvider(beijing_client_factory=lambda: client)
    stock = StockConfig(symbol="BJ.920808", name="Example BSE", market=Market.BEIJING)
    provider.fetch_daily_bars(stock, end=date(2026, 7, 21), days=31)
    assert client.calls == [(MARKET.BJ, "920808", PERIOD.DAILY, ADJUST.QFQ, 62)]


def test_a_share_fetch_uses_tencent_history_not_eastmoney() -> None:
    client = FakeTencentAkShare()
    provider = AkShareMarketDataProvider(client=client)
    stock = StockConfig(symbol="SZ.002594", name="Example", market=Market.A_SHARE)

    provider.fetch_daily_bars(stock, end=date(2026, 7, 21), days=31)

    assert client.tencent_arguments is not None
    assert client.tencent_arguments["symbol"] == "sz002594"
    assert client.tencent_arguments["adjust"] == "qfq"
    assert client.eastmoney_called is False


def test_beijing_daily_adapter_normalizes_opentdx_volume() -> None:
    provider = AkShareMarketDataProvider(beijing_client_factory=FakeOpenTdxClient)
    stock = StockConfig(symbol="BJ.920808", name="Example BSE", market=Market.BEIJING)

    bars = provider.fetch_daily_bars(stock, end=date(2026, 7, 21), days=31)

    assert list(bars.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert bars.iloc[-1]["date"] == date(2026, 7, 21)
    assert bars.iloc[-1]["volume"] == 31_000


def test_beijing_daily_bar_request_failure_becomes_data_gap() -> None:
    provider = AkShareMarketDataProvider(beijing_client_factory=UnavailableOpenTdxClient)
    stock = StockConfig(symbol="BJ.920808", name="Example BSE", market=Market.BEIJING)

    with pytest.raises(MarketDataUnavailable, match="public daily-bar request failed"):
        provider.fetch_daily_bars(stock, end=date(2026, 7, 21), days=31)


def test_beijing_default_factory_maps_missing_connection_to_data_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quotation_client = FakeDefaultQuotationClient(connect_result=None)
    install_default_tdx_client(monkeypatch, quotation_client)
    provider = AkShareMarketDataProvider()
    stock = StockConfig(symbol="BJ.920808", name="Example BSE", market=Market.BEIJING)

    with pytest.raises(MarketDataUnavailable, match="could not connect"):
        provider.fetch_daily_bars(stock, end=date(2026, 7, 21), days=31)

    assert quotation_client.login_called is False


def test_beijing_default_factory_maps_no_server_to_data_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quotation_client = FakeDefaultQuotationClient(Exception("no available server"))
    install_default_tdx_client(monkeypatch, quotation_client)
    provider = AkShareMarketDataProvider()
    stock = StockConfig(symbol="BJ.920808", name="Example BSE", market=Market.BEIJING)

    with pytest.raises(MarketDataUnavailable, match="no available server"):
        provider.fetch_daily_bars(stock, end=date(2026, 7, 21), days=31)


def test_beijing_default_factory_maps_failed_login_and_disconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quotation_client = FakeDefaultQuotationClient(connect_result=object(), login_result=False)
    install_default_tdx_client(monkeypatch, quotation_client)
    provider = AkShareMarketDataProvider()
    stock = StockConfig(symbol="BJ.920808", name="Example BSE", market=Market.BEIJING)

    with pytest.raises(MarketDataUnavailable, match="login failed"):
        provider.fetch_daily_bars(stock, end=date(2026, 7, 21), days=31)

    assert quotation_client.disconnected is True


def test_beijing_default_factory_disconnects_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quotation_client = FakeDefaultQuotationClient(connect_result=object())
    install_default_tdx_client(monkeypatch, quotation_client)
    provider = AkShareMarketDataProvider()
    stock = StockConfig(symbol="BJ.920808", name="Example BSE", market=Market.BEIJING)

    provider.fetch_daily_bars(stock, end=date(2026, 7, 21), days=31)

    assert quotation_client.disconnected is True


def test_malformed_vendor_response_becomes_data_gap() -> None:
    provider = AkShareMarketDataProvider(client=MalformedTencentAkShare())
    stock = StockConfig(symbol="SZ.002594", name="Example", market=Market.A_SHARE)

    with pytest.raises(MarketDataUnavailable, match="malformed daily-bar response"):
        provider.fetch_daily_bars(stock, end=date(2026, 7, 21), days=31)


def test_fetch_daily_bars_requires_at_least_thirty_completed_bars() -> None:
    provider = AkShareMarketDataProvider(client=FakeAkShare())
    stock = StockConfig(symbol="SH.600000", name="Example", market=Market.A_SHARE)

    with pytest.raises(MarketDataUnavailable, match="SH.600000"):
        provider.fetch_daily_bars(stock, end=date(2026, 7, 20), days=3)


def test_fetch_daily_bars_wraps_vendor_connection_failure_as_data_gap() -> None:
    provider = AkShareMarketDataProvider(client=UnavailableAkShare())
    stock = StockConfig(symbol="SH.600000", name="Example", market=Market.A_SHARE)

    with pytest.raises(MarketDataUnavailable, match="public market-data endpoint disconnected"):
        provider.fetch_daily_bars(stock, end=date(2026, 7, 20), days=31)


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
    assert bars.iloc[-1].to_dict() == {
        "date": date(2026, 7, 20),
        "open": 31,
        "high": 32,
        "low": 30,
        "close": 31.5,
        "volume": 310,
    }
