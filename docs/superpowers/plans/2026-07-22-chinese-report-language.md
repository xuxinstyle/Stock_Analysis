# Chinese Report Language Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every generated system narrative in the daily stock report Chinese, while retaining stable JSON schema identifiers, stock codes, URLs, and source titles.

**Architecture:** Keep machine-facing Pydantic field names and enum values unchanged. Translate text at the source of generated recommendations and report data gaps, redact provider exception details from report-facing gaps, localize Markdown/HTML labels, and require the daily research handoff to produce Chinese summaries.

**Tech Stack:** Python 3.12, Pydantic, Jinja2, pytest, Ruff.

## Global Constraints

- Preserve the research-only, no-order safety contract.
- A data gap remains a `WATCH` view with low confidence and high risk; it must not produce a price target.
- Do not include raw provider exception text, proxy details, or endpoint URLs in a human-facing report.
- Do not alter user-owned in-progress market-data changes.

---

### Task 1: Localize conservative data-gap recommendations

**Files:**
- Modify: `src/stock_research/services/report_builder.py`
- Modify: `src/stock_research/domain/models.py`
- Create: `tests/test_report_language.py`

- [ ] **Step 1: Write a failing report-builder regression test**

```python
def test_market_data_gap_uses_chinese_safe_fallback_copy() -> None:
    report = ReportBuilder().build(
        make_request(make_research()),
        [make_stock()],
        FakeMarketData(unavailable={"SH.600000"}),
    )
    recommendation = report.analyses[0].recommendations[0]
    assert recommendation.rationale[0].startswith("数据缺口：SH.600000：")
    assert recommendation.trigger.startswith("触发条件：")
    assert "fixture market outage" not in report.analyses[0].data_gaps[0]
```

- [ ] **Step 2: Run the test and verify it fails because the current fallback is English and exposes the provider message**

Run: `python -m pytest tests/test_report_language.py::test_market_data_gap_uses_chinese_safe_fallback_copy -v`

- [ ] **Step 3: Implement the minimal Chinese gap copy**

Use a shared Chinese data-gap rationale prefix in the report builder and the `StockAnalysis` fallback validator. Replace raw `MarketDataUnavailable` interpolation with a Chinese statement that says the completed daily quote could not be obtained and technical analysis is withheld.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `python -m pytest tests/test_report_language.py::test_market_data_gap_uses_chinese_safe_fallback_copy -v`

### Task 2: Localize ordinary short-, medium-, and long-horizon recommendations

**Files:**
- Modify: `src/stock_research/services/recommendations.py`
- Modify: `tests/test_recommendations.py`
- Modify: `tests/test_report_language.py`

- [ ] **Step 1: Write a failing test for Chinese recommendation copy**

```python
def test_generated_recommendations_use_chinese_system_copy() -> None:
    recommendation = RecommendationEngine().recommend(confirmed_bullish_input())[0]
    assert recommendation.trigger.startswith("触发条件：")
    assert recommendation.observation_or_target.startswith("观察结论：")
    assert recommendation.invalidation.startswith("失效条件：")
```

- [ ] **Step 2: Run the test and verify it fails because the generated fields use English labels**

Run: `python -m pytest tests/test_recommendations.py::test_generated_recommendations_use_chinese_system_copy -v`

- [ ] **Step 3: Translate every RecommendationEngine-generated rationale, trigger, observation, invalidation, holding impact, and horizon guidance**

Keep cited titles as source metadata and retain all existing actions, confidence levels, risk levels, citations, and position limits.

- [ ] **Step 4: Run focused recommendation tests**

Run: `python -m pytest tests/test_recommendations.py tests/test_report_language.py -v`

### Task 3: Localize report rendering and research-handoff prose

**Files:**
- Modify: `src/stock_research/domain/models.py`
- Modify: `src/stock_research/services/report_builder.py`
- Modify: `src/stock_research/services/report_store.py`
- Modify: `src/stock_research/web/templates/report.html`
- Modify: `docs/automation/daily-research-prompt.md`
- Modify: `tests/test_report_builder.py`
- Modify: `tests/test_report_store.py`

- [ ] **Step 1: Write a failing renderer test for Chinese display labels and values**

```python
def test_markdown_renders_chinese_display_labels_and_enum_values(tmp_path: Path) -> None:
    markdown = ReportStore(tmp_path).save(make_complete_report()).markdown.read_text(encoding="utf-8")
    assert "运行状态：成功" in markdown
    assert "股票代码：SH.600000" in markdown
    assert "动作：观察" in markdown
```

- [ ] **Step 2: Run the test and verify it fails with raw field names and enum values**

Run: `python -m pytest tests/test_report_store.py::test_markdown_renders_chinese_display_labels_and_enum_values -v`

- [ ] **Step 3: Add display mappings for report fields and enum values, and provide them to the HTML template**

Translate static Markdown and HTML labels without changing serialized JSON. Translate the report default disclaimer and every `ReportBuilder`-generated gap, chronology, market-status, and previous-day-attribution sentence. Add an explicit daily automation instruction that summaries, event descriptions, and data-gap explanations must be Simplified Chinese; original foreign source titles may remain as citation metadata.

- [ ] **Step 4: Run renderer and documentation checks**

Run: `python -m pytest tests/test_report_store.py tests/test_daily_run.py -v`

### Task 4: Verify the end-to-end language contract

**Files:**
- Test: `tests/test_report_language.py`

- [ ] **Step 1: Run the full suite and static checks**

Run: `python -m pytest -v`
Expected: all tests pass.

Run: `python -m ruff check .`
Expected: no lint errors.

Run: `python -m ruff format --check .`
Expected: all files already formatted.

- [ ] **Step 2: Scan generated source literals for the former English fallback phrases**

Run: `rg -n "Trigger: obtain|Observation only:|Invalidation: the missing|Data-gap fallback:" src`
Expected: no matches.

### Task 5: Close historical rendering, dashboard, prompt, and provider-boundary gaps

**Files:**
- Modify: `src/stock_research/services/report_store.py`
- Modify: `src/stock_research/web/templates/report.html`
- Modify: `src/stock_research/web/templates/dashboard.html`
- Modify: `src/stock_research/services/market_data.py`
- Modify: `docs/automation/daily-research-prompt.md`
- Modify: `tests/test_report_store.py`
- Modify: `tests/test_web.py`
- Modify: `tests/test_market_data.py`
- Modify: `tests/test_report_builder.py`
- Modify: `tests/test_daily_run.py`

- [ ] **Step 1: Write failing historical-rendering, dashboard, prompt, and provider-boundary tests**

Construct a pre-localization report payload with the original English disclaimer, status message,
`Data-gap fallback:` rationale, three original fallback fields, and a provider error containing a
hostname, URL, and proxy text. Assert that re-rendered Markdown and HTML contain Chinese safe
display text but that the saved JSON still contains the legacy payload. Assert that the dashboard
uses display mappings for status, market, trend, action, and confidence. Assert that prompt prose
uses `未核实` and `存在冲突`, not literal English reporting labels. Assert that a vendor-raised
`ValueError` becomes `MarketDataUnavailable` and reaches the partial-report fallback.

- [ ] **Step 2: Run the tests and verify each fails on the corresponding current gap**

Run: `python -m pytest tests/test_report_store.py tests/test_web.py tests/test_market_data.py tests/test_daily_run.py -v`

- [ ] **Step 3: Add the smallest display-only legacy sanitizer and bounded provider exception wrapper**

Translate only recognized legacy system strings at rendering time. Replace recognized old
price-data gaps with the same concise Chinese source-neutral gap used for new reports, including
when the old gap is nested in a legacy fallback rationale, warning, or previous-day attribution.
Do not mutate loaded models or saved JSON and do not translate source titles. Route dashboard
machine values through the existing display helpers. Catch expected vendor parsing exceptions
(`KeyError`, `TypeError`, `ValueError`, `IndexError`) at the raw-fetch boundary without catching
programmer errors or changing `days <= 0` validation.

- [ ] **Step 4: Verify the complete safety and language contract**

Run: `python -m pytest -v`
Run: `python -m ruff check .`
Run: `python -m ruff format --check .`
Run: `git diff --check`
