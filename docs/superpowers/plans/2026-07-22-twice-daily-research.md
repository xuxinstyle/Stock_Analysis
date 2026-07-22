# Twice-Daily Stock Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在工作日 09:00 与 23:00 分别生成并保留盘前、盘后股票研究报告，盘后使用当日已完成行情。

**Architecture:** 在请求和报告中加入可选运行槽位；槽位决定完成会话可否等于报告日及文件存档目录。现有报告构建、飞书通知和日期级 SQLite 最新报告接口保持复用。

**Tech Stack:** Python 3.14、Pydantic、Typer、SQLite、Codex App cron automation、pytest。

## Global Constraints

- 仅研究 A 股、北交所和港股；国际信息仅为传导背景。
- 不下单、不接券商、不读写交易凭据或模型 API 密钥。
- 所有人类可读系统文案使用简体中文；来源标题和 URL 保留原文。
- `run_slot=null` 必须保持历史 JSON、手动运行和既有存档路径兼容。

---

### Task 1: 定义盘后完成会话与双报告存档

**Files:**
- Modify: `src/stock_research/domain/models.py`
- Modify: `src/stock_research/services/report_builder.py`
- Modify: `src/stock_research/services/report_store.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_report_store.py`

- [ ] **Step 1: 写失败测试**

```python
def test_post_market_request_accepts_same_day_completed_session():
    request = DailyRunRequest.model_validate({
        "report_date": "2026-07-22", "run_slot": "post_market",
        "generated_at": "2026-07-22T23:00:00+08:00", "research_inputs": [],
        "market_sessions": [{"market": "a_share", "completed_session": "2026-07-22", "is_closed": False}],
    })
    assert request.market_sessions[0].completed_session == request.report_date
```

- [ ] **Step 2: 验证该测试因现有严格日期规则失败**

Run: `python -m pytest -q tests/test_cli.py -k post_market`

- [ ] **Step 3: 实现最小模型与存档改动**

```python
run_slot: Literal["pre_market", "post_market"] | None = None

if session.completed_session > self.report_date:
    raise ValueError("market session cannot follow report_date")
if self.run_slot != "post_market" and session.completed_session == self.report_date:
    raise ValueError("market session must precede report_date outside post_market")
if session.is_closed and session.completed_session == self.report_date:
    raise ValueError("closed market session must precede report_date")
```

Use `report.run_slot` to store automatic reports under `pre-market` or `post-market`, preserving the legacy path for `None`.

- [ ] **Step 4: 验证目标测试和相关存档测试通过**

Run: `python -m pytest -q tests/test_cli.py tests/test_report_store.py`

### Task 2: 明确两次自动化的研究口径

**Files:**
- Modify: `docs/automation/daily-research-prompt.md`
- Modify: `README.md`
- Test: `tests/test_daily_run.py`

- [ ] **Step 1: 写失败测试**

```python
assert "23:00 China Standard Time" in prompt
assert "post_market" in prompt
assert "当天收盘、涨跌、成交量" in prompt
```

- [ ] **Step 2: 验证提示词测试失败**

Run: `python -m pytest -q tests/test_daily_run.py::test_daily_research_prompt_requires_cited_safe_local_handoff`

- [ ] **Step 3: 以同一提示词增加模式分支**

盘前任务传入 `pre_market`，盘后任务传入 `post_market`。盘后规则必须确认当日市场已闭市、填写当天完成会话和数据日期、覆盖当日价格/量能/技术面与盘中盘后事件；无法确认时保留缺口并使用最后可验证会话。

- [ ] **Step 4: 验证每日工作流测试通过**

Run: `python -m pytest -q tests/test_daily_run.py`

### Task 3: 更新 Codex App 本地定时任务并验收

**Files:**
- Update: Codex App automation `automation-2`
- Create: Codex App post-market local cron automation

- [ ] **Step 1: 将既有任务更新为盘前模式**

保留工作日 09:00、中国时区、本地项目、失败才提醒；任务提示词显式传入 `pre_market`。

- [ ] **Step 2: 新建盘后任务**

创建工作日 23:00、中国时区、本地项目、失败才提醒的任务；任务提示词显式传入 `post_market`。

- [ ] **Step 3: 读取两个任务配置并核验**

确认两个自动化均为 ACTIVE、本地 `E:\\Stock_Analysis` 项目，时间分别为 09:00 和 23:00，且提示词模式正确。

### Task 4: 全量验证与提交

**Files:**
- Modify: 本计划涉及的源代码、测试与文档

- [ ] **Step 1: 运行完整验证**

Run: `python -m pytest -q; python -m ruff check .; python -m ruff format --check .; git diff --check`

- [ ] **Step 2: 提交并推送授权的 main**

```powershell
git add src tests docs README.md
git commit -m "feat(automation): add post-market research run"
git push origin main
```
