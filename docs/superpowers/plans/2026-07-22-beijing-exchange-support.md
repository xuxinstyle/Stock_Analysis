# Beijing Stock Exchange Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-class Beijing Stock Exchange support so `BJ.920808` can be configured, researched, and reported safely with the existing A-share/Hong Kong workflow.

**Architecture:** Add `Market.BEIJING` as the explicit market discriminator, then extend all symbol-validation boundaries and market-status enumeration. Reuse the existing mainland AkShare historical-bars endpoint with the stripped BSE code while preserving the current normalization and data-gap behavior.

**Tech Stack:** Python 3.12+, Pydantic, SQLAlchemy/SQLite, FastAPI/Jinja, Typer, pandas, pytest, Ruff.

## Global Constraints

- BSE symbols use current `BJ.9xxxxx` notation; reject legacy `BJ.872808`.
- `beijing` is a separate market-session/status value, even when its calendar date matches mainland A shares.
- Never add orders, brokers, credentials, market-data API keys, or uncited research claims.
- Preserve existing A-share/Hong Kong behavior and partial-report data-gap semantics.
- Persist the user's six explicitly supplied holdings only after code verification; store exact Decimal-compatible costs and no inferred cash/risk profile.

---

### Task 1: Establish failing BSE contract tests

**Files:**
- Modify: `tests/test_configuration.py`
- Modify: `tests/test_market_data.py`
- Modify: `tests/test_report_builder.py`
- Modify: `tests/test_web.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Market`, `StockConfig`, `StockResearchInput`, `Evidence`, `AkShareMarketDataProvider`, `ReportBuilder`, and Web `StockForm`.
- Produces: regression coverage requiring `Market.BEIJING`, `BJ.920808`, BSE daily-bar dispatch, BSE request/session validation, BSE report status, and Web persistence.

- [ ] **Step 1: Add failing model and configuration tests**

```python
def test_beijing_symbol_requires_current_exchange_prefix() -> None:
    stock = StockConfig(symbol="BJ.920808", name="曙光数创", market=Market.BEIJING)
    assert stock.symbol == "BJ.920808"

    with pytest.raises(ValidationError):
        StockConfig(symbol="BJ.872808", name="曙光数创", market=Market.BEIJING)
```

- [ ] **Step 2: Add failing request/evidence and market-data tests**

```python
assert AkShareMarketDataProvider.to_vendor_code("BJ.920808") == ("920808", "bj")
stock = StockConfig(symbol="BJ.920808", name="曙光数创", market=Market.BEIJING)
bars = AkShareMarketDataProvider(client=FakeAkShare()).fetch_daily_bars(stock, end=date(2026, 7, 20), days=31)
assert not bars.empty
```

Add a `StockResearchInput` and `Evidence` case using `BJ.920808`, and a `DailyRunRequest` with `{"market": "beijing", "completed_session": "2026-07-20", "is_closed": False}`.

- [ ] **Step 3: Add failing report and Web tests**

```python
beijing = make_stock("BJ.920808")
report = ReportBuilder().build(make_request(make_research("BJ.920808")), [beijing], FakeMarketData())
assert report.market_statuses[0].market is Market.BEIJING

response = client.post("/stocks/new", data={"symbol": "BJ.920808", "name": "曙光数创", "market": "beijing"})
assert response.status_code == 303
```

- [ ] **Step 4: Run focused tests and verify expected RED failures**

Run: `python -m pytest tests/test_configuration.py tests/test_market_data.py tests/test_report_builder.py tests/test_web.py tests/test_cli.py -v`

Expected: failures specifically because `Market.BEIJING` and `BJ.` validation/dispatch support do not exist yet.

### Task 2: Implement BSE as a first-class market

**Files:**
- Modify: `src/stock_research/domain/enums.py`
- Modify: `src/stock_research/domain/models.py`
- Modify: `src/stock_research/services/market_data.py`
- Modify: `src/stock_research/services/report_builder.py`

**Interfaces:**
- Consumes: the failing BSE contract tests from Task 1.
- Produces: `Market.BEIJING == "beijing"`; validated BSE stock/research/evidence symbols; BSE historical bars; BSE market status.

- [ ] **Step 1: Add the enum and central symbol patterns**

```python
class Market(StrEnum):
    A_SHARE = "a_share"
    BEIJING = "beijing"
    HONG_KONG = "hong_kong"

patterns = {
    Market.A_SHARE: r"^(SH|SZ)\.\d{6}$",
    Market.BEIJING: r"^BJ\.9\d{5}$",
    Market.HONG_KONG: r"^HK\.\d{5}$",
}
```

Use the same accepted-subject expression in `StockResearchInput` so research and evidence reject non-current BSE forms.

- [ ] **Step 2: Add BSE vendor mapping and dispatch**

```python
return code, {"SH": "sh", "SZ": "sz", "BJ": "bj", "HK": "hk"}[exchange]

if stock.market in (Market.A_SHARE, Market.BEIJING):
    return client.stock_zh_a_hist(**arguments)
```

- [ ] **Step 3: Emit a separate BSE market status**

```python
for market in (Market.A_SHARE, Market.BEIJING, Market.HONG_KONG):
    # retain the existing status calculation unchanged
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_configuration.py tests/test_market_data.py tests/test_report_builder.py tests/test_web.py tests/test_cli.py -v`

Expected: all focused tests pass, including the new BSE cases.

### Task 3: Update user-facing contracts and documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/automation/daily-research-prompt.md`

**Interfaces:**
- Consumes: `Market.BEIJING`, `BJ.9xxxxx`, and distinct BSE session behavior from Task 2.
- Produces: accurate CLI/Web/automation instructions for BSE configuration and research.

- [ ] **Step 1: Add BSE configuration notation to the README**

Document that configured subjects include mainland A shares, BSE, and Hong Kong; list `BJ.920808` as the current BSE example and state that a `beijing` market session is separate.

- [ ] **Step 2: Extend the automation prompt contract**

Replace the A/HK-only scope with A-share/BSE/HK scope. Add `BJ.` to active-symbol coverage, `beijing` to `market_sessions`, and `BJ.920808` to the request examples while retaining all research-only and cited-source boundaries.

- [ ] **Step 3: Verify documentation references**

Run: `rg -n 'BJ\.920808|beijing|BSE|北京证券交易所' README.md docs/automation/daily-research-prompt.md`

Expected: each new user-facing contract contains the current BSE notation and session label.

### Task 4: Verify and persist the requested active holdings

**Files:**
- Create: `.stock-research/input/active-stocks-2026-07-22.yaml` (temporary import source)
- Create: `.stock-research/data/stock_research.sqlite3` (application-managed SQLite state)

**Interfaces:**
- Consumes: validated configuration service and the user's six confirmed holdings.
- Produces: atomically replaced active SQLite list with six A-share/BSE subjects and explicit holdings.

- [ ] **Step 1: Run full code-quality verification**

Run:

```powershell
python -m pytest -v
python -m ruff check .
python -m ruff format --check .
git diff --check
```

Expected: all tests and quality checks pass with no diff whitespace errors.

- [ ] **Step 2: Create the exact import document**

```yaml
stocks:
  - {symbol: SZ.002594, name: 比亚迪, market: a_share, industry: 新能源汽车, holding: {quantity: "500", cost_basis: "95.786"}}
  - {symbol: BJ.920808, name: 曙光数创, market: beijing, industry: 数据中心液冷, holding: {quantity: "2000", cost_basis: "72.726"}}
  - {symbol: SH.688268, name: 华特气体, market: a_share, industry: 电子特种气体, holding: {quantity: "561", cost_basis: "146.485"}}
  - {symbol: SZ.002851, name: 麦格米特, market: a_share, industry: 电力电子, holding: {quantity: "500", cost_basis: "146.917"}}
  - {symbol: SH.600862, name: 中航高科, market: a_share, industry: 航空新材料, holding: {quantity: "1300", cost_basis: "18.614"}}
  - {symbol: SH.688114, name: 华大智造, market: a_share, industry: 基因测序设备, holding: {quantity: "1547", cost_basis: "51.47"}}
```

- [ ] **Step 3: Import atomically through the application CLI**

Run: `python -m stock_research.cli import-config .\.stock-research\input\active-stocks-2026-07-22.yaml`

Expected: `imported 6 stock configuration(s)`.

- [ ] **Step 4: Verify the persisted active context is exact and read-only**

Run: `python -c 'from stock_research.cli import active_stock_context; import json; print(json.dumps(active_stock_context(), ensure_ascii=False))'`

Expected: exactly six symbols, names, markets, industries, holding quantities, and cost bases matching Step 2; no inferred cash or risk profile.
