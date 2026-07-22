# 近期股价涨跌原因分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在每只股票的日报和飞书消息中显示带证据边界的近期股价涨跌原因分析。

**Architecture:** 在 `StockResearchInput` 增加兼容旧报告的中文摘要字段；渲染层只展示该研究字段，不改变技术指标或推荐算法。自动化研究提示负责要求研究者填入近五日价格表现、已证实驱动、推断和未确认因素。

**Tech Stack:** Python 3.14、Pydantic v2、Jinja2、Typer、pytest、Ruff。

## Global Constraints

- 仅覆盖 A 股、港股和北交所；美股与国际信息仅作为背景。
- 所有系统生成文本使用简体中文，且不得生成交易指令或收益承诺。
- 原有 JSON 报告必须可读取；Webhook 只从环境变量读取，不能写入仓库。

---

### Task 1: 研究输入兼容字段

**Files:**
- Modify: `src/stock_research/domain/models.py:167-199`
- Modify: `tests/test_evidence.py:148-162`

**Interfaces:**
- Consumes: `StockResearchInput` 的既有六个研究摘要字段。
- Produces: `recent_price_move_summary: str`，旧载荷缺失时返回中文数据缺口文本。

- [ ] **Step 1: Write the failing test**

```python
def test_research_input_preserves_recent_price_move_summary() -> None:
    payload = valid_research_payload()
    payload["recent_price_move_summary"] = "近五个完整交易日上涨；已证实因素见引用，行业联动仅为推断。"

    assert StockResearchInput.model_validate(payload).recent_price_move_summary == payload[
        "recent_price_move_summary"
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_evidence.py::test_research_input_preserves_recent_price_move_summary -q`

Expected: FAIL with an attribute error because the model lacks the field.

- [ ] **Step 3: Write minimal implementation**

```python
recent_price_move_summary: str = "数据缺口：未提供近期股价涨跌的可引用原因分析。"
```

Add it to the existing nonblank-summary validator so explicitly blank new input is rejected.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_evidence.py::test_research_input_preserves_recent_price_move_summary -q`

Expected: PASS.

### Task 2: 报告与飞书结构化渲染

**Files:**
- Modify: `src/stock_research/services/report_store.py:103-116,423-465`
- Modify: `src/stock_research/web/templates/report.html:52-55`
- Modify: `tests/test_report_store.py`

**Interfaces:**
- Consumes: `analysis.research.recent_price_move_summary`。
- Produces: Markdown 和 HTML 中标题为“近期股价涨跌原因”的独立段落；飞书沿用 `notification_sections()` 的单公司 Markdown。

- [ ] **Step 1: Write the failing test**

```python
def test_report_renders_recent_price_move_analysis_in_all_channels(tmp_path: Path) -> None:
    report = make_report()
    summary = "近五个完整交易日上涨；公司公告为已证实原因，行业联动仅为推断。"
    report.analyses[0].research.recent_price_move_summary = summary

    paths = ReportStore(tmp_path).save(report)
    assert "## 近期股价涨跌原因" in paths.markdown.read_text(encoding="utf-8")
    assert summary in paths.html.read_text(encoding="utf-8")
    assert any(summary in text for _, text in ReportStore.notification_sections(report))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report_store.py -k recent_price_move -q`

Expected: FAIL because the renderer has no section yet.

- [ ] **Step 3: Write minimal implementation**

Add a Chinese display label and append a Markdown section immediately after the prior-day block. Add an HTML `<section>` at the equivalent location. Do not translate the source-owned summary text.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report_store.py -k recent_price_move -q`

Expected: PASS.

### Task 3: 日常研究提示与回归验证

**Files:**
- Modify: `docs/automation/daily-research-prompt.md:115-154`
- Modify: `tests/fixtures/daily_research_request.json`
- Modify: `tests/test_daily_run.py`

**Interfaces:**
- Consumes: 配置股票清单与公开网页研究证据。
- Produces: 每个 `StockResearchInput` 的 `recent_price_move_summary`，且说明五日窗口、事实/推断/未知边界。

- [ ] **Step 1: Write the failing test**

```python
def test_daily_research_prompt_requires_recent_price_move_reasoning() -> None:
    prompt = Path("docs/automation/daily-research-prompt.md").read_text(encoding="utf-8")
    assert "recent_price_move_summary" in prompt
    assert "最近五个完整交易日" in prompt
    assert "不得将市场联动表述为公司事实" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_daily_run.py -k recent_price_move -q`

Expected: FAIL because the research prompt does not yet request the field.

- [ ] **Step 3: Write minimal implementation**

Extend the JSON contract and research instructions with the new field and its evidence-bound writing rules. Add a concrete Chinese fixture value.

- [ ] **Step 4: Run targeted and full verification**

Run: `python -m pytest tests/test_evidence.py tests/test_report_store.py tests/test_daily_run.py -q; python -m pytest -q; python -m ruff check .; python -m ruff format --check .; git diff --check`

Expected: all tests pass and static checks produce no violations.
