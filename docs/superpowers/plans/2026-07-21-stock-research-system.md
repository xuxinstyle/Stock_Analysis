# 股票研究与每日建议系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个可配置 A 股/港股、由每日 Codex 自动化研究并通过网页与命令行交付带来源和条件化建议报告的 Python 系统。

**Architecture:** Python 应用将确定性部分分为配置/存储、行情与指标、证据与建议、报告渲染四层；Typer 和 FastAPI 只调用同一服务层。每日 Codex 自动化负责检索和写入受 Pydantic 校验的研究输入 JSON，应用将其与行情和规则合成为版本化的 JSON、Markdown 与 HTML 报告。

**Tech Stack:** Python 3.12、FastAPI、Typer、Pydantic v2、SQLAlchemy 2、SQLite、Jinja2、Pandas、NumPy、PyYAML、HTTPX、AkShare、pytest、Ruff。

## Global Constraints

- 标的仅为 A 股与港股；美股、国际宏观、地缘政治、汇率、利率、大宗商品仅作为外部传导信息。
- 每日研究在中国时间 09:00 执行，使用上一可得交易日行情和截至生成时间的隔夜资料；休市或缺数必须显示实际数据日期。
- 所有建议都是研究观点：不连接券商、不自动下单、不保证收益、不构成个性化投资建议。
- 每个建议必须包含依据、条件、失效/止损条件、风险等级、置信度和可追溯来源；未验证或冲突信息不能变成确定性结论。
- 持仓为可选输入；未配置时不得假定用户成本、资金或风险承受能力。
- 首版无需用户提供或购买模型 API，且不在没有 Codex App 依赖的服务器上部署。
- 网页、CLI 和自动化必须读写同一份结构化报告；输出必须包括 JSON、Markdown 和 HTML。
- 所有实现先写失败测试；每项任务通过目标测试后单独提交 Conventional Commit。

---

## Target File Structure

```text
pyproject.toml
README.md
.gitignore
config/stocks.example.yaml
docs/automation/daily-research-prompt.md
data/.gitkeep
reports/.gitkeep
src/stock_research/
  __init__.py
  cli.py
  settings.py
  db.py
  domain/
    __init__.py
    models.py
    enums.py
  repositories/
    __init__.py
    stocks.py
    reports.py
    runs.py
  services/
    __init__.py
    configuration.py
    evidence.py
    market_data.py
    indicators.py
    recommendations.py
    report_builder.py
    report_store.py
    daily_run.py
  web/
    __init__.py
    app.py
    templates/
      base.html
      dashboard.html
      report.html
      stocks.html
      stock_form.html
    static/app.css
tests/
  conftest.py
  fixtures/daily_research_request.json
  test_configuration.py
  test_evidence.py
  test_indicators.py
  test_market_data.py
  test_recommendations.py
  test_report_builder.py
  test_report_store.py
  test_daily_run.py
  test_cli.py
  test_web.py
```

## Data Contracts

All cross-layer data is defined in `src/stock_research/domain/models.py` and must retain these names:

```python
class StockConfig(BaseModel):
    symbol: str                # `SH.600000`, `SZ.000001`, or `HK.00700`
    name: str
    market: Market
    industry: str | None = None
    holding: Holding | None = None

class Evidence(BaseModel):
    title: str
    url: HttpUrl
    source_name: str
    published_at: datetime | None
    retrieved_at: datetime
    category: EvidenceCategory
    direction: Direction
    credibility: Credibility
    summary: str
    symbols: list[str]

class StockResearchInput(BaseModel):
    symbol: str
    data_as_of: date
    fundamental_summary: str
    industry_summary: str
    policy_summary: str
    news_summary: str
    international_summary: str
    product_price_summary: str
    events: list[EventSignal]
    evidence: list[Evidence]

class DailyRunRequest(BaseModel):
    report_date: date
    generated_at: datetime
    research_inputs: list[StockResearchInput]

class StockAnalysis(BaseModel):
    stock: StockConfig
    previous_day: PreviousDayPerformance
    technical: TechnicalSnapshot
    research: StockResearchInput
    recommendations: list[Recommendation]

class DailyReport(BaseModel):
    report_date: date
    generated_at: datetime
    market_statuses: list[MarketStatus]
    global_risks: list[str]
    run_warnings: list[str]
    analyses: list[StockAnalysis]
```

`Recommendation` is generated only by `RecommendationEngine.recommend(analysis_input: RecommendationInput) -> list[Recommendation]`; renderers must not invent advice. `DailyRunService.run(request: DailyRunRequest) -> DailyReport` is the sole application entry point for one report generation.

## Task 1: Bootstrap the installable project and test harness

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `src/stock_research/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_project_bootstrap.py`

**Interfaces:**
- Produces: an editable package named `stock-research`, `pytest` and `ruff` commands, and a `TEST_DATA_DIR` fixture.
- Consumes: no project code.

- [ ] **Step 1: Write the failing packaging test**

```python
# tests/test_project_bootstrap.py
from stock_research import __version__


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_project_bootstrap.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'stock_research'`.

- [ ] **Step 3: Create the minimal package and tool configuration**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "stock-research"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "akshare>=1.16",
  "fastapi>=0.115,<1.0",
  "httpx>=0.28,<1.0",
  "jinja2>=3.1,<4.0",
  "numpy>=2.0,<3.0",
  "pandas>=2.2,<3.0",
  "pydantic>=2.10,<3.0",
  "pyyaml>=6.0,<7.0",
  "sqlalchemy>=2.0,<3.0",
  "typer>=0.15,<1.0",
  "uvicorn>=0.32,<1.0",
]

[project.scripts]
stock-research = "stock_research.cli:app"

[project.optional-dependencies]
dev = ["pytest>=8.3", "ruff>=0.8"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

```python
# src/stock_research/__init__.py
__version__ = "0.1.0"
```

```gitignore
# .gitignore
__pycache__/
.pytest_cache/
.ruff_cache/
.venv/
*.py[cod]
*.sqlite3
data/*.json
reports/*
!data/.gitkeep
!reports/.gitkeep
```

`README.md` must document Python 3.12, `python -m venv .venv`, editable installation, `pytest`, `ruff check .`, and the fact that no trading or broker integration exists. In `tests/conftest.py`, define `TEST_DATA_DIR = Path(__file__).parent / "fixtures"`.

- [ ] **Step 4: Install and run quality checks**

Run: `python -m pip install -e '.[dev]'` after adding a `dev` optional dependency group containing `pytest>=8.3` and `ruff>=0.8`; then run `python -m pytest tests/test_project_bootstrap.py -v` and `python -m ruff check .`.

Expected: test PASS and Ruff reports `All checks passed!`.

- [ ] **Step 5: Commit the bootstrap**

```bash
git add pyproject.toml .gitignore README.md src/stock_research/__init__.py tests
git commit -m "build: bootstrap stock research package"
```

## Task 2: Define domain types, configuration validation, and SQLite stock persistence

**Files:**
- Create: `src/stock_research/domain/__init__.py`
- Create: `src/stock_research/domain/enums.py`
- Create: `src/stock_research/domain/models.py`
- Create: `src/stock_research/settings.py`
- Create: `src/stock_research/db.py`
- Create: `src/stock_research/repositories/__init__.py`
- Create: `src/stock_research/repositories/stocks.py`
- Create: `src/stock_research/services/configuration.py`
- Create: `config/stocks.example.yaml`
- Create: `tests/test_configuration.py`

**Interfaces:**
- Produces: `Market`, `Horizon`, `Action`, `RiskLevel`, `StockConfig`, `Holding`, `Settings`, `StockRepository`, and `ConfigurationService.import_yaml()`.
- Consumes: `sqlalchemy.Engine` from `db.create_engine_at(path)`.

- [ ] **Step 1: Write failing validation and persistence tests**

```python
def test_a_share_symbol_requires_exchange_prefix() -> None:
    with pytest.raises(ValidationError, match="SH\\.600000"):
        StockConfig(symbol="600000", name="浦发银行", market=Market.A_SHARE)


def test_yaml_import_persists_optional_holding(tmp_path: Path) -> None:
    service = ConfigurationService(StockRepository(create_engine_at(tmp_path / "app.sqlite3")))
    service.import_yaml(TEST_DATA_DIR / "stocks.yaml")
    saved = service.list_stocks()
    assert saved[0].symbol == "SH.600000"
    assert saved[0].holding is not None
    assert saved[0].holding.cost_basis == Decimal("10.50")
```

- [ ] **Step 2: Run tests to prove the contract is absent**

Run: `python -m pytest tests/test_configuration.py -v`

Expected: FAIL with import errors for `StockConfig` and `ConfigurationService`.

- [ ] **Step 3: Implement exact configuration contracts**

```python
class Market(StrEnum):
    A_SHARE = "a_share"
    HONG_KONG = "hong_kong"


class Holding(BaseModel):
    quantity: Decimal = Field(gt=0)
    cost_basis: Decimal = Field(gt=0)
    cash_available: Decimal | None = Field(default=None, ge=0)
    risk_profile: Literal["conservative", "balanced", "aggressive"] | None = None


class StockConfig(BaseModel):
    symbol: str
    name: str = Field(min_length=1, max_length=80)
    market: Market
    industry: str | None = None
    holding: Holding | None = None

    @model_validator(mode="after")
    def validate_symbol(self) -> Self:
        patterns = {
            Market.A_SHARE: r"^(SH|SZ)\\.\\d{6}$",
            Market.HONG_KONG: r"^HK\\.\\d{5}$",
        }
        if not re.fullmatch(patterns[self.market], self.symbol):
            raise ValueError("symbol must use SH.600000, SZ.000001, or HK.00700 format")
        return self
```

Create one `stocks` SQLAlchemy table with `symbol` primary key and JSON text for `holding`; `StockRepository.upsert(stock: StockConfig) -> StockConfig` must use the symbol as its conflict key. `ConfigurationService.import_yaml(path: Path) -> list[StockConfig]` must load only a top-level `stocks` list and validate every row before any write. Ship `config/stocks.example.yaml` with one SH, one SZ, and one HK item, including exactly one optional holding.

- [ ] **Step 4: Run focused tests and static checks**

Run: `python -m pytest tests/test_configuration.py -v && python -m ruff check src tests`

Expected: all configuration tests PASS and Ruff passes.

- [ ] **Step 5: Commit the configuration slice**

```bash
git add config src/stock_research/domain src/stock_research/settings.py src/stock_research/db.py src/stock_research/repositories/stocks.py src/stock_research/services/configuration.py tests/test_configuration.py tests/fixtures/stocks.yaml
git commit -m "feat(config): add validated stock and holding configuration"
```

## Task 3: Model evidence and validate Codex research input

**Files:**
- Modify: `src/stock_research/domain/enums.py`
- Modify: `src/stock_research/domain/models.py`
- Create: `src/stock_research/services/evidence.py`
- Create: `tests/test_evidence.py`
- Create: `tests/fixtures/daily_research_request.json`

**Interfaces:**
- Produces: `Evidence`, `EventSignal`, `StockResearchInput`, `EvidenceService.validate_and_deduplicate()`.
- Consumes: `StockConfig.symbol` and standard Pydantic URL/date validation.

- [ ] **Step 1: Write failing evidence tests**

```python
def test_deduplicate_keeps_the_more_credible_source() -> None:
    result = EvidenceService().validate_and_deduplicate([
        evidence("Market rumor", "https://news.example/item", Credibility.LOW),
        evidence("Exchange filing", "https://news.example/item", Credibility.PRIMARY),
    ])
    assert len(result) == 1
    assert result[0].credibility is Credibility.PRIMARY


def test_research_input_rejects_evidence_for_another_stock() -> None:
    payload = valid_research_payload(symbol="SH.600000")
    payload["evidence"][0]["symbols"] = ["HK.00700"]
    with pytest.raises(ValidationError, match="must include research symbol"):
        StockResearchInput.model_validate(payload)
```

- [ ] **Step 2: Run them before implementation**

Run: `python -m pytest tests/test_evidence.py -v`

Expected: FAIL because evidence types and service do not exist.

- [ ] **Step 3: Implement the evidence contract**

```python
class EvidenceCategory(StrEnum):
    COMPANY = "company"
    INDUSTRY = "industry"
    POLICY = "policy"
    NEWS = "news"
    INTERNATIONAL = "international"
    PRODUCT_PRICE = "product_price"


class Credibility(IntEnum):
    LOW = 1
    SECONDARY = 2
    PRIMARY = 3


class Evidence(BaseModel):
    title: str = Field(min_length=4, max_length=240)
    url: HttpUrl
    source_name: str = Field(min_length=2, max_length=120)
    published_at: datetime | None = None
    retrieved_at: datetime
    category: EvidenceCategory
    direction: Direction
    credibility: Credibility
    summary: str = Field(min_length=20, max_length=1500)
    symbols: list[str] = Field(min_length=1)
```

`EvidenceService.validate_and_deduplicate(evidence: list[Evidence]) -> list[Evidence]` must key by normalized URL without fragment and retain the higher `Credibility`; tied records retain the later `published_at`, then later `retrieved_at`. `StockResearchInput` must require each of six named summaries to be non-empty, keep `events` as a list, and validate that each evidence item contains its own `symbol`.

The JSON fixture must contain a company disclosure, an industry source, a domestic policy source, an international source, and at least one product-price observation. Use public-looking URLs but no real financial claims inside test fixtures.

- [ ] **Step 4: Run the evidence tests**

Run: `python -m pytest tests/test_evidence.py -v`

Expected: PASS, including deduplication, source validation, and required-summary tests.

- [ ] **Step 5: Commit the research input boundary**

```bash
git add src/stock_research/domain src/stock_research/services/evidence.py tests/test_evidence.py tests/fixtures/daily_research_request.json
git commit -m "feat(evidence): validate cited Codex research inputs"
```

## Task 4: Fetch daily bars and calculate transparent technical indicators

**Files:**
- Create: `src/stock_research/services/market_data.py`
- Create: `src/stock_research/services/indicators.py`
- Modify: `src/stock_research/domain/models.py`
- Create: `tests/test_market_data.py`
- Create: `tests/test_indicators.py`

**Interfaces:**
- Produces: `DailyBar`, `MarketDataProvider`, `AkShareMarketDataProvider`, `TechnicalSnapshot`, `calculate_technical_snapshot()`.
- Consumes: normalized symbols from `StockConfig`; returns ascending-date OHLCV data frames with `date`, `open`, `high`, `low`, `close`, `volume` columns.

- [ ] **Step 1: Write failing indicator and mapping tests**

```python
def test_technical_snapshot_uses_most_recent_completed_bar() -> None:
    bars = make_bars(closes=[10 + index * 0.2 for index in range(40)])
    snapshot = calculate_technical_snapshot(bars)
    assert snapshot.data_as_of == date(2026, 7, 20)
    assert snapshot.sma_20 == pytest.approx(13.9)
    assert snapshot.trend is Trend.UP


def test_a_share_symbol_maps_to_akshare_code() -> None:
    assert AkShareMarketDataProvider.to_vendor_code("SH.600000") == ("600000", "sh")


def test_hk_symbol_maps_to_akshare_code() -> None:
    assert AkShareMarketDataProvider.to_vendor_code("HK.00700") == ("00700", "hk")
```

- [ ] **Step 2: Execute the tests and confirm failure**

Run: `python -m pytest tests/test_market_data.py tests/test_indicators.py -v`

Expected: FAIL with missing provider and indicator functions.

- [ ] **Step 3: Implement provider normalization and deterministic calculations**

```python
class MarketDataProvider(Protocol):
    def fetch_daily_bars(self, stock: StockConfig, end: date, days: int = 260) -> pd.DataFrame:
        raise NotImplementedError


class AkShareMarketDataProvider:
    @staticmethod
    def to_vendor_code(symbol: str) -> tuple[str, str]:
        exchange, code = symbol.split(".", maxsplit=1)
        return code, {"SH": "sh", "SZ": "sz", "HK": "hk"}[exchange]
```

`fetch_daily_bars` must dispatch by `stock.market`, convert date and numeric columns, sort ascending, discard rows with absent OHLCV fields, and raise `MarketDataUnavailable(symbol, message)` if fewer than 30 completed bars remain. Isolate all `akshare` calls in this class so tests use a fake provider instead of the network.

Implement indicators with Pandas only: SMA(5/20/60), RSI(14), MACD(12,26,9), Bollinger(20,2), 20-day volume ratio, 20-day support/resistance, 20-day realized volatility, and an explicit `Trend` determined by latest close versus SMA(20) and SMA(20) versus SMA(60). Round only when serializing `TechnicalSnapshot`, not while calculating.

- [ ] **Step 4: Run indicator and provider tests**

Run: `python -m pytest tests/test_market_data.py tests/test_indicators.py -v && python -m ruff check src tests`

Expected: PASS without any network request in the test suite.

- [ ] **Step 5: Commit market and technical analysis**

```bash
git add src/stock_research/services/market_data.py src/stock_research/services/indicators.py src/stock_research/domain/models.py tests/test_market_data.py tests/test_indicators.py
git commit -m "feat(analysis): add market data adapter and technical indicators"
```

## Task 5: Implement constrained short-, medium-, and long-horizon recommendations

**Files:**
- Create: `src/stock_research/services/recommendations.py`
- Modify: `src/stock_research/domain/enums.py`
- Modify: `src/stock_research/domain/models.py`
- Create: `tests/test_recommendations.py`

**Interfaces:**
- Produces: `Action`, `Horizon`, `RiskLevel`, `RecommendationInput`, `Recommendation`, `RecommendationEngine.recommend()`.
- Consumes: a technical snapshot, evidence list, event list, stock configuration, and optional holding.

- [ ] **Step 1: Write tests for positive signals and mandatory safety downgrades**

```python
def test_positive_confirmed_input_returns_three_horizon_recommendations() -> None:
    recommendations = RecommendationEngine().recommend(confirmed_bullish_input())
    assert [item.horizon for item in recommendations] == [Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG]
    assert all(item.action in {Action.WATCH, Action.BUY_IN_TRANCHES, Action.HOLD} for item in recommendations)
    assert all(item.trigger and item.invalidation and item.rationale for item in recommendations)


def test_low_credibility_or_conflicting_evidence_cannot_return_buy() -> None:
    recommendations = RecommendationEngine().recommend(conflicting_input())
    assert all(item.action in {Action.WATCH, Action.AVOID} for item in recommendations)
    assert all(item.confidence is Confidence.LOW for item in recommendations)


def test_no_holding_does_not_create_personal_profit_or_loss() -> None:
    recommendations = RecommendationEngine().recommend(confirmed_bullish_input(holding=None))
    assert all(item.holding_impact is None for item in recommendations)
```

- [ ] **Step 2: Run to verify the recommendation engine is missing**

Run: `python -m pytest tests/test_recommendations.py -v`

Expected: FAIL with import errors for `RecommendationEngine`.

- [ ] **Step 3: Implement transparent rule branches**

```python
class Action(StrEnum):
    WATCH = "watch"
    BUY_IN_TRANCHES = "buy_in_tranches"
    HOLD = "hold"
    REDUCE = "reduce"
    AVOID = "avoid"


class Recommendation(BaseModel):
    horizon: Horizon
    action: Action
    confidence: Confidence
    risk_level: RiskLevel
    rationale: list[str] = Field(min_length=1)
    trigger: str
    observation_or_target: str
    invalidation: str
    position_limit: str
    holding_impact: str | None = None
```

`RecommendationEngine.recommend` must always generate horizons in `SHORT`, `MEDIUM`, `LONG` order. It must return `WATCH`/low confidence when fewer than two non-low-credibility sources exist, sources have conflicting directions, price data is unavailable, or volatility is high. It may return `BUY_IN_TRANCHES` only when trend is UP, RSI is below 70, the evidence direction is net positive, and a primary or two independent secondary sources support it. It may return `REDUCE` or `AVOID` for a confirmed negative event or break below support. Each branch must emit a trigger and invalidation derived from named support/resistance or a named evidence/event condition; it cannot emit an unconditional price prediction.

For optional holdings, calculate return as `(latest_close - cost_basis) / cost_basis`, present it as an informational string, and never calculate it when holding is absent. Enforce action-specific position caps as descriptive strings: `≤10%` short, `≤15%` medium, `≤20%` long; cap them at `≤5%` when confidence is low.

- [ ] **Step 4: Run all recommendation tests**

Run: `python -m pytest tests/test_recommendations.py -v`

Expected: PASS, including all low-confidence safeguards.

- [ ] **Step 5: Commit rule-based recommendations**

```bash
git add src/stock_research/services/recommendations.py src/stock_research/domain tests/test_recommendations.py
git commit -m "feat(recommendations): add constrained multi-horizon advice"
```

## Task 6: Build and persist a complete multi-format daily report

**Files:**
- Create: `src/stock_research/repositories/reports.py`
- Create: `src/stock_research/repositories/runs.py`
- Create: `src/stock_research/services/report_builder.py`
- Create: `src/stock_research/services/report_store.py`
- Create: `src/stock_research/services/daily_run.py`
- Modify: `src/stock_research/domain/models.py`
- Create: `src/stock_research/web/templates/report.html`
- Create: `tests/test_report_builder.py`
- Create: `tests/test_report_store.py`
- Create: `tests/test_daily_run.py`

**Interfaces:**
- Produces: `DailyReport`, `RunRecord`, `ReportBuilder.build()`, `ReportStore.save()`, `DailyRunService.run()`.
- Consumes: repositories, `MarketDataProvider`, `EvidenceService`, `RecommendationEngine`, a list of `StockResearchInput`, and active stocks.

- [ ] **Step 1: Write failure-first tests for completeness and atomic report outputs**

```python
def test_report_contains_all_required_sections_per_stock(tmp_path: Path) -> None:
    report = make_complete_report()
    paths = ReportStore(tmp_path).save(report)
    markdown = paths.markdown.read_text(encoding="utf-8")
    for heading in ["前日表现与原因", "基本面分析", "行业分析", "技术面分析", "政策分析", "消息面分析", "突发事件", "短线建议", "中线建议", "长线建议", "来源与数据缺口"]:
        assert heading in markdown
    assert paths.json.exists() and paths.html.exists()


def test_daily_run_marks_partial_when_one_stock_has_no_price_data() -> None:
    result = service_with_one_market_failure().run(daily_request())
    assert result.run_status is RunStatus.PARTIAL
    assert "HK.00700" in result.run_warnings[0]
    assert len(result.analyses) == 2
```

- [ ] **Step 2: Run report tests before code exists**

Run: `python -m pytest tests/test_report_builder.py tests/test_report_store.py tests/test_daily_run.py -v`

Expected: FAIL with missing report services.

- [ ] **Step 3: Implement report orchestration and storage**

```python
class DailyRunService:
    def run(self, request: DailyRunRequest) -> DailyReport:
        return self._report_builder.build(
            request=request,
            stocks=self._stock_repository.list(),
            market_data=self._market_data_provider,
        )
```

For each configured stock, `DailyRunService` must locate exactly one matching research input, retrieve bars, compute `PreviousDayPerformance` and `TechnicalSnapshot`, deduplicate evidence, call `RecommendationEngine`, and add a `StockAnalysis`. If any stock has a missing input or `MarketDataUnavailable`, keep it in `analyses` with a data-gap warning and three `WATCH` recommendations; do not discard another stock's analysis. Set `RunStatus.SUCCESS` only when all stocks have prices and valid research; otherwise use `PARTIAL`; unexpected unhandled exceptions are persisted as `FAILED` with the stage and message.

`ReportStore.save(report)` must write under `reports/YYYY-MM-DD/` using a temporary sibling then rename each final file. Serialize JSON with UTF-8 and `ensure_ascii=False`; Markdown must have the exact section headings used in the test; HTML must be rendered by Jinja2 from `report.html`, not duplicated string templates. Save report metadata and run records in SQLite so `ReportRepository.latest() -> DailyReport | None` and `list_dates() -> list[date]` do not scan the filesystem.

- [ ] **Step 4: Run report tests and whole suite**

Run: `python -m pytest -v && python -m ruff check .`

Expected: all tests PASS; one market failure yields a partial, explicitly labelled report.

- [ ] **Step 5: Commit reporting and run tracking**

```bash
git add src/stock_research/repositories src/stock_research/services src/stock_research/web/templates/report.html tests/test_report_builder.py tests/test_report_store.py tests/test_daily_run.py
git commit -m "feat(reports): generate and persist daily research reports"
```

## Task 7: Expose the workflow through a safe Typer command-line interface

**Files:**
- Create: `src/stock_research/cli.py`
- Create: `tests/test_cli.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `stock-research init`, `import-config`, `validate-input`, `generate`, `reports`, `serve` commands.
- Consumes: configuration, report, and daily run services; commands return non-zero on invalid configuration/input or failed runs.

- [ ] **Step 1: Write CLI behaviour tests**

```python
def test_validate_input_prints_the_research_date(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate-input", str(TEST_DATA_DIR / "daily_research_request.json")])
    assert result.exit_code == 0
    assert "每日研究请求有效" in result.stdout


def test_generate_writes_three_formats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    result = runner.invoke(app, ["generate", "--input", str(TEST_DATA_DIR / "daily_research_request.json")])
    assert result.exit_code == 0
    assert "Markdown" in result.stdout and "HTML" in result.stdout and "JSON" in result.stdout
```

- [ ] **Step 2: Run CLI tests before implementation**

Run: `python -m pytest tests/test_cli.py -v`

Expected: FAIL because `stock_research.cli:app` is not importable.

- [ ] **Step 3: Implement commands with explicit paths and exit statuses**

```python
app = typer.Typer(no_args_is_help=True, add_completion=False)

@app.command("validate-input")
def validate_input(input_path: Annotated[Path, typer.Argument(exists=True)]) -> None:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    DailyRunRequest.model_validate(payload)
    typer.echo("每日研究请求有效")

@app.command("generate")
def generate(input_path: Annotated[Path, typer.Option("--input", exists=True)]) -> None:
    report = build_services().daily_run.run(load_daily_request(input_path))
    paths = build_services().report_store.save(report)
    typer.echo(f"JSON: {paths.json}\\nMarkdown: {paths.markdown}\\nHTML: {paths.html}")
```

`init` copies the example YAML only when the destination does not exist. `import-config` validates then replaces the stock set atomically. `reports` prints report dates and the status recorded for each date. `serve` calls `uvicorn.run("stock_research.web.app:create_app", factory=True, host="127.0.0.1", port=port)`. Do not provide `buy`, `sell`, broker, order, credential, or trading commands.

- [ ] **Step 4: Run CLI tests and exercise help output**

Run: `python -m pytest tests/test_cli.py -v && stock-research --help`

Expected: all tests PASS; help lists only the six stated research/configuration commands.

- [ ] **Step 5: Commit CLI surface**

```bash
git add src/stock_research/cli.py tests/test_cli.py README.md
git commit -m "feat(cli): add report generation and management commands"
```

## Task 8: Build the FastAPI dashboard and configuration screens

**Files:**
- Create: `src/stock_research/web/__init__.py`
- Create: `src/stock_research/web/app.py`
- Create: `src/stock_research/web/templates/base.html`
- Create: `src/stock_research/web/templates/dashboard.html`
- Create: `src/stock_research/web/templates/stocks.html`
- Create: `src/stock_research/web/templates/stock_form.html`
- Create: `src/stock_research/web/static/app.css`
- Create: `tests/test_web.py`

**Interfaces:**
- Produces: `create_app() -> FastAPI`; routes `GET /`, `GET /reports/{report_date}`, `GET|POST /stocks`, `GET|POST /stocks/new`, `GET|POST /stocks/{symbol}/edit`, and `POST /stocks/{symbol}/delete`.
- Consumes: `StockRepository`, `ReportRepository`, and Pydantic form conversion; no business-rule duplication in routes/templates.

- [ ] **Step 1: Write HTTP tests for dashboard, source links, and form validation**

```python
def test_dashboard_shows_latest_report_summary(client: TestClient) -> None:
    seed_report(client.app.state.services, make_complete_report())
    response = client.get("/")
    assert response.status_code == 200
    assert "每日股票研究" in response.text
    assert "SH.600000" in response.text


def test_report_page_renders_cited_source_as_link(client: TestClient) -> None:
    seed_report(client.app.state.services, make_complete_report())
    response = client.get("/reports/2026-07-21")
    assert 'href="https://example.com/primary"' in response.text


def test_invalid_stock_form_returns_422_without_persisting(client: TestClient) -> None:
    response = client.post("/stocks/new", data={"symbol": "600000", "name": "测试", "market": "a_share"})
    assert response.status_code == 422
    assert client.app.state.services.stocks.list() == []
```

- [ ] **Step 2: Run web tests before routes exist**

Run: `python -m pytest tests/test_web.py -v`

Expected: FAIL with `ModuleNotFoundError: stock_research.web`.

- [ ] **Step 3: Implement the web application with server-rendered templates**

```python
def create_app(services: ServiceContainer | None = None) -> FastAPI:
    app = FastAPI(title="Stock Research")
    app.state.services = services or build_services()
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    templates = Jinja2Templates(directory=template_dir)
    app.include_router(create_dashboard_router(app.state.services, templates))
    app.include_router(create_report_router(app.state.services, templates))
    app.include_router(create_stock_router(app.state.services, templates))
    return app
```

The dashboard must show report date, generated time, market status, global risks, run warnings and a row per stock containing previous-day move, trend, short-horizon action, confidence, and a report-detail link. `report.html` must render all mandatory report sections, an obvious research-only disclaimer, warnings, and source URL anchors. Stock screens must support create/edit/delete with optional holding fields; a delete request must require the stock's exact symbol in the path and redirect to `/stocks`. Form validation converts blank holding fields to `None`, and all validation errors return status 422 with a field-level Chinese error message.

- [ ] **Step 4: Run web tests and start an application smoke test**

Run: `python -m pytest tests/test_web.py -v && python -m ruff check .`

Expected: PASS and `create_app()` imports without side effects such as a network fetch or database write outside the configured app home.

- [ ] **Step 5: Commit the dashboard**

```bash
git add src/stock_research/web tests/test_web.py
git commit -m "feat(web): add research dashboard and stock configuration"
```

## Task 9: Add the Codex daily research handoff and local automation

**Files:**
- Create: `docs/automation/daily-research-prompt.md`
- Modify: `README.md`
- Modify: `tests/test_daily_run.py`

**Interfaces:**
- Produces: a documented, schema-constrained prompt for the Codex App automation; it writes one `DailyRunRequest` JSON file and invokes the existing CLI.
- Consumes: `config/stocks.example.yaml`, persisted stock configuration, `StockResearchInput` schema, and `stock-research generate --input`.

- [ ] **Step 1: Extend the end-to-end test around a Codex-shaped payload**

```python
def test_fixture_payload_can_be_validated_then_generated_by_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    result = runner.invoke(app, ["generate", "--input", str(TEST_DATA_DIR / "daily_research_request.json")])
    assert result.exit_code == 0
    report = ReportStore(tmp_path / "reports").load_latest()
    assert report.analyses[0].research.evidence[0].url
    assert report.analyses[0].recommendations[0].invalidation
```

- [ ] **Step 2: Run the end-to-end test before documentation integration**

Run: `python -m pytest tests/test_daily_run.py::test_fixture_payload_can_be_validated_then_generated_by_cli -v`

Expected: FAIL until Task 6/7 contracts are wired to the final fixture shape.

- [ ] **Step 3: Write the daily task prompt and configure the app automation**

`docs/automation/daily-research-prompt.md` must tell Codex to: read the active configured A-share/HK stocks; identify each market's last completed session; use web search for exchange/company disclosures, price/volume context, sector/product prices, policy, company news, US peers and international transmission; prefer primary sources; save title/URL/source/time/direction/credibility/summary for every claim; label unverified or conflicting claims; fill all six research summaries and events; validate input through `stock-research validate-input`; run `stock-research generate --input`; inspect the generated report for sections and source links; and record data gaps rather than inventing information.

The prompt must explicitly prohibit placing orders, connecting brokers, asserting return certainty, or writing uncited material claims. It must require short/medium/long recommendations to include trigger, observation/target, invalidation, position limit, risk and confidence.

Create a Codex App local project automation through the automation tool, with a human-readable name such as `每日开盘前股票研究`, target project `E:\\Stock_Analysis`, China time zone, daily 09:00 scheduling, and a failed-runs-only notification policy. Do not encode an operating-system Task Scheduler script or an API key. Confirm the automation points to the document prompt and executes in the local project environment.

- [ ] **Step 4: Verify the documented flow locally without a live search run**

Run: `stock-research validate-input tests/fixtures/daily_research_request.json; stock-research generate --input tests/fixtures/daily_research_request.json; python -m pytest tests/test_daily_run.py -v`

Expected: validation succeeds, report paths print, and all daily-run tests PASS. The automation should be created but need not be manually triggered during this verification.

- [ ] **Step 5: Commit the automation handoff**

```bash
git add docs/automation/daily-research-prompt.md README.md tests/test_daily_run.py
git commit -m "docs(automation): add daily Codex research workflow"
```

## Task 10: Final integration validation and operational documentation

**Files:**
- Modify: `README.md`
- Create: `tests/test_integration_report.py`

**Interfaces:**
- Produces: a repeatable full-suite validation target and operational instructions for first configuration, manual generation, dashboard viewing, daily report interpretation, and failure recovery.
- Consumes: all public CLI commands, web factory, fixtures, report store, and automation prompt.

- [ ] **Step 1: Write a regression test for report parity across JSON, Markdown, and HTML**

```python
def test_all_report_formats_reference_the_same_stock_and_warning(tmp_path: Path) -> None:
    paths = ReportStore(tmp_path).save(make_partial_report())
    payload = json.loads(paths.json.read_text(encoding="utf-8"))
    markdown = paths.markdown.read_text(encoding="utf-8")
    html = paths.html.read_text(encoding="utf-8")
    assert payload["analyses"][0]["stock"]["symbol"] == "SH.600000"
    assert "SH.600000" in markdown and "SH.600000" in html
    assert payload["run_warnings"][0] in markdown and payload["run_warnings"][0] in html
```

- [ ] **Step 2: Run the new regression test before parity fixes**

Run: `python -m pytest tests/test_integration_report.py -v`

Expected: FAIL if any renderer omits a required report warning or stock identity.

- [ ] **Step 3: Close parity gaps and document operating rules**

Ensure JSON, Markdown, and HTML all show stock symbol/name, report/generated/data-as-of date, market state, run warnings, data gaps, disclaimer, all required analysis sections, all three horizons, and source links. In `README.md`, add exact setup/usage examples:

```bash
stock-research init config/stocks.yaml
stock-research import-config config/stocks.yaml
stock-research validate-input data/inbox/2026-07-21.json
stock-research generate --input data/inbox/2026-07-21.json
stock-research reports
stock-research serve --port 8000
```

Document that `PARTIAL` means some valid output exists but at least one stock/source/price input was unavailable; tell users to read the report's data-gap and source section before acting. State that configuration and history are local, no broker credentials are stored, and the Codex automation requires the Codex App to be available.

- [ ] **Step 4: Run the full verification suite**

Run: `python -m pytest -v && python -m ruff check . && stock-research --help`

Expected: all tests PASS, Ruff passes, and help contains no trading commands.

- [ ] **Step 5: Commit final integration quality work**

```bash
git add README.md src tests
git commit -m "test: verify complete daily research workflow"
```

## Plan Self-Review

### Spec coverage

- A 股/港股 configuration and optional holdings: Task 2 and Task 8.
- 09:00 pre-open, previous session, holiday/data gaps: Task 6 and Task 9.
- Web search research with company, industry, policy, product, US, and international sources: Task 3 and Task 9.
- Basic, industry, technical, policy, news, prior-day and sudden-change reporting: Tasks 3, 4, 5, and 6.
- Short, medium, and long conditional suggestions: Task 5.
- JSON/Markdown/HTML, CLI and dashboard: Tasks 6, 7, 8, and 10.
- Citations, credibility, conflicts, risk and no trading: Tasks 3, 5, 6, and 9.
- Exceptions, run state, tests and user-facing warnings: Tasks 6 and 10.
- Codex direct daily analysis without user model API: Task 9.

### Placeholder scan

The plan has no deferred requirements: every created file, public interface, behaviour, command, test, expected result, and commit message is specified in its task.

### Type consistency

All external research enters as `DailyRunRequest.research_inputs` containing `StockResearchInput` items; `DailyRunService.run(DailyRunRequest)` creates `DailyReport`; `RecommendationEngine.recommend(RecommendationInput)` exclusively creates `Recommendation`; `ReportStore.save(DailyReport)` creates all output formats. CLI and web depend on these interfaces rather than reimplementing analysis rules.
