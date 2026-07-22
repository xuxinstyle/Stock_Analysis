# Market Data Provider Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Eastmoney daily bars with Tencent for Shanghai/Shenzhen and a data-only OpenTDX adapter for Beijing, while retaining safe partial-report behavior.

**Architecture:** `AkShareMarketDataProvider` remains the application boundary. It dispatches Shanghai/Shenzhen to AkShare Tencent history, Beijing to an injected OpenTDX client using `MARKET.BJ`, and leaves Hong Kong unchanged. All outputs flow through the existing normalizer and failures become `MarketDataUnavailable`.

**Tech Stack:** Python 3.14, pandas, AkShare, OpenTDX `>=0.2.4,<0.3`, pytest, Ruff.

## Global Constraints

- No Eastmoney `push2his` call for A-share or Beijing historical daily bars.
- No API key, credential, broker account, order, or trading operation.
- OpenTDX use is limited to public `TdxClient.stock_kline` data retrieval.
- Require 30 bars ending no later than the declared completed session.
- User-facing report gaps must not contain a URL, hostname, or raw network exception.
- Do not stage pre-existing unrelated worktree changes.

### Task 1: Add and prove the Beijing data-source contract

**Files:** `pyproject.toml`, `tests/test_market_data.py`

- [ ] Write this failing test:

```python
def test_beijing_daily_adapter_requests_qfq_daily_bars() -> None:
    client = FakeOpenTdxClient()
    provider = AkShareMarketDataProvider(beijing_client_factory=lambda: client)
    stock = StockConfig(symbol="BJ.920808", name="Example BSE", market=Market.BEIJING)
    provider.fetch_daily_bars(stock, end=date(2026, 7, 21), days=31)
    assert client.calls == [(MARKET.BJ, "920808", PERIOD.DAILY, ADJUST.QFQ, 62)]
```

- [ ] Verify RED: `python -m pytest tests/test_market_data.py -k beijing_daily_adapter_requests_qfq_daily_bars -q`

  Expected: failure because there is no Beijing OpenTDX adapter.

- [ ] Add `"opentdx>=0.2.4,<0.3",` to `pyproject.toml` and install the project dependency.

- [ ] Run the only permitted live-source probe:

```python
from opentdx.const import ADJUST, MARKET, PERIOD
from opentdx.tdxClient import TdxClient
with TdxClient() as client:
    rows = client.stock_kline(MARKET.BJ, "920808", PERIOD.DAILY, adjust=ADJUST.QFQ, count=260)
completed_rows = [row for row in rows if row["datetime"].date().isoformat() <= "2026-07-21"]
assert len(completed_rows) >= 30
assert completed_rows[-1]["datetime"].date().isoformat() == "2026-07-21"
```

  The source may include a same-day intraday bar.  It is acceptable only after filtering by the
  declared completed-session date, as the production normalizer does.  If the filtered assertion
  fails, stop the source switch and preserve a partial report; do not substitute another unverified
  source.

### Task 2: Implement source dispatch and normalization

**Files:** `src/stock_research/services/market_data.py`, `tests/test_market_data.py`

- [ ] Write these failing tests:

```python
def test_a_share_fetch_uses_tencent_history_not_eastmoney() -> None:
    client = FakeTencentAkShare()
    provider = AkShareMarketDataProvider(client=client)
    stock = StockConfig(symbol="SZ.002594", name="Example", market=Market.A_SHARE)
    provider.fetch_daily_bars(stock, end=date(2026, 7, 21), days=31)
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
```

- [ ] Verify RED: `python -m pytest tests/test_market_data.py -k "tencent_history_not_eastmoney or normalizes_opentdx_volume" -q`

- [ ] Implement only this dispatch behavior:

```python
if stock.market is Market.A_SHARE:
    return client.stock_zh_a_hist_tx(symbol=f"{exchange}{code}", start_date=start_yyyymmdd, end_date=end_yyyymmdd, adjust="qfq")
if stock.market is Market.BEIJING:
    with self._beijing_client_factory() as client:
        return pd.DataFrame(client.stock_kline(MARKET.BJ, code, PERIOD.DAILY, adjust=ADJUST.QFQ, count=days * 2))
```

  Map Tencent `amount` and OpenTDX `vol` to normalized `volume`; wrap source import, connection, parsing, and insufficient-history errors as `MarketDataUnavailable`.

- [ ] Verify GREEN: `python -m pytest tests/test_market_data.py -q`

### Task 3: Make public gaps concise

**Files:** `src/stock_research/services/report_builder.py`, `tests/test_report_builder.py`, `README.md`, `docs/automation/daily-research-prompt.md`

- [ ] Write this failing test:

```python
def test_market_failure_uses_concise_public_data_gap() -> None:
    stock = make_stock()
    report = ReportBuilder().build(make_request(make_research()), [stock], FakeMarketData({stock.symbol}, message="HTTPSConnectionPool(host='private.example')"))
    assert "price data unavailable" in report.analyses[0].data_gaps[0]
    assert "private.example" not in report.analyses[0].data_gaps[0]
```

- [ ] Verify RED: `python -m pytest tests/test_report_builder.py -k concise_public_data_gap -q`

- [ ] Replace interpolation of `str(error)` in the public report branch with source-neutral text. Retain the existing three-horizon `watch` / low-confidence / high-risk fallback.

- [ ] Document Tencent/OpenTDX provenance, no-key/no-trade constraints, and the concise-gap behavior.

- [ ] Verify GREEN: `python -m pytest tests/test_report_builder.py tests/test_daily_run.py -q`

### Task 4: Validate the active portfolio and independently audit the result

**Files:** `.stock-research/input/daily-research-request-2026-07-22.json`, `.stock-research/reports/2026-07-22/report.*`, `C:\Users\KSG\.codex\automations\automation-2\memory.md`

- [ ] Probe all six configured subjects through the production provider; every final bar must be `2026-07-21` and every result must have at least 30 bars.

- [ ] Run:

```powershell
python -c "from stock_research.cli import app; app()" validate-input .stock-research\input\daily-research-request-2026-07-22.json
python -c "from stock_research.cli import app; app()" generate --input .stock-research\input\daily-research-request-2026-07-22.json
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
git diff --check
```

- [ ] Dispatch a subagent to review the final diff for no Eastmoney A/BJ daily endpoint, no key/account/trade access, BSE session correctness, and no raw diagnostics in rendered report prose.

- [ ] Commit only the provider replacement files after the independent review passes.
