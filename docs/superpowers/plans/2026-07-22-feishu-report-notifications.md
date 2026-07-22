# 飞书报告通知 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每次 `stock-research generate` 成功持久化报告后，将完整 Markdown 报告通过本机环境变量配置的飞书 V2 自定义机器人 Webhook 发送，并在单条请求过大时安全分段。

**Architecture:** 新建独立的 `FeishuNotificationService`，负责 Webhook 校验、以 JSON UTF-8 字节数为边界的分段和顺序 HTTP 发送；命令层在 `DailyRunService.run()` 成功后读取已落盘的 Markdown 并调用该服务。通知配置仅从 `STOCK_RESEARCH_FEISHU_WEBHOOK_URL` 读取，通知失败不影响已保存报告和原运行记录，但 `generate` 以非零状态明确失败。

**Tech Stack:** Python 3.12、httpx、Typer、pytest、Ruff。

## Global Constraints

- 仅支持 `https://open.feishu.cn/open-apis/bot/v2/hook/...` 的飞书 V2 Webhook。
- 不得将实际 Webhook 写入 Git、源码、夹具、README、自动化提示词或 CLI 输出。
- 发送 `msg_type: "text"`，并将最终 JSON 请求的 UTF-8 大小限制为 18KiB，低于官方 20KB 上限。
- 报告先保存；通知失败不得删除、改写或撤回报告和成功运行记录。
- 每次 `generate` 都触发通知，包括人工重复运行；不加自动重试。
- 超长内容必须保留每个 Unicode 字符、按顺序发送、标记报告日期和 `第 n/m 段`，连续分段至少相隔 0.2 秒。
- 测试不访问网络；通过可注入传输和休眠函数验证。
- 不改动当前未提交的北京交易所相关文件：`src/stock_research/services/market_data.py`、`src/stock_research/services/report_builder.py`、`tests/test_market_data.py`、`tests/test_report_builder.py`。

---

### Task 1: 建立可测试的飞书 V2 通知服务

**Files:**
- Create: `src/stock_research/services/feishu_notifications.py`
- Create: `tests/test_feishu_notifications.py`

**Interfaces:**
- Produces: `FeishuNotificationError(RuntimeError)`, `FeishuNotificationService`, `split_text_for_feishu(text: str, report_date: date) -> list[str]`。
- Consumes: `STOCK_RESEARCH_FEISHU_WEBHOOK_URL`、一个 `post(url, *, json, headers, timeout)` 传输可调用对象、一个 `sleep(seconds)` 可调用对象。

- [ ] **Step 1: 写失败的配置与单段发送测试**

```python
def test_from_environment_rejects_missing_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STOCK_RESEARCH_FEISHU_WEBHOOK_URL", raising=False)
    with pytest.raises(FeishuNotificationError, match="STOCK_RESEARCH_FEISHU_WEBHOOK_URL"):
        FeishuNotificationService.from_environment()


def test_send_markdown_posts_one_v2_text_payload() -> None:
    posted: list[dict[str, object]] = []
    service = FeishuNotificationService(
        "https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        post=lambda url, **kwargs: posted.append(kwargs["json"]) or FakeResponse(200, {"StatusCode": 0}),
        sleep=lambda seconds: None,
    )
    assert service.send_markdown(date(2026, 7, 22), "# 完整报告\n内容") == 1
    assert posted[0]["msg_type"] == "text"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_feishu_notifications.py::test_from_environment_rejects_missing_webhook tests/test_feishu_notifications.py::test_send_markdown_posts_one_v2_text_payload -v`

Expected: FAIL，因为通知服务尚不存在。

- [ ] **Step 3: 实现最小通知服务**

```python
class FeishuNotificationService:
    @classmethod
    def from_environment(cls) -> Self: ...

    def send_markdown(self, report_date: date, markdown: str) -> int: ...
```

校验 HTTPS 飞书 V2 URL；默认传输以 `httpx.post(..., timeout=10.0)` 调用；每个请求加入
`Content-Type: application/json; charset=utf-8`。仅 HTTP 2xx 且 JSON `StatusCode == 0` 或 `code == 0`
视为成功；其余响应抛出不含 Webhook 的 `FeishuNotificationError`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_feishu_notifications.py -v`

Expected: PASS。

- [ ] **Step 5: 提交该切片**

```bash
git add src/stock_research/services/feishu_notifications.py tests/test_feishu_notifications.py
git commit -m "feat(notifications): add Feishu webhook sender"
```

### Task 2: 以请求体 UTF-8 大小安全分段并处理错误

**Files:**
- Modify: `src/stock_research/services/feishu_notifications.py`
- Modify: `tests/test_feishu_notifications.py`

**Interfaces:**
- Produces: 对任意非空报告返回完整、排序的文本段；`send_markdown` 返回已成功发送的段数。
- Consumes: Task 1 的服务与注入传输。

- [ ] **Step 1: 写超长 Unicode、顺序和失败测试**

```python
def test_split_preserves_chinese_emoji_and_keeps_each_serialized_payload_under_limit() -> None:
    markdown = ("研究😀\n" * 8_000)
    chunks = split_text_for_feishu(markdown, date(2026, 7, 22))
    assert len(chunks) > 1
    assert all(serialized_payload_size(chunk) <= 18 * 1024 for chunk in chunks)
    assert remove_chunk_headers(chunks) == markdown


def test_send_stops_at_the_failed_chunk_without_retrying() -> None:
    service, calls = service_that_returns_success_then_failure()
    with pytest.raises(FeishuNotificationError, match="segment 2"):
        service.send_markdown(date(2026, 7, 22), "长报告...")
    assert len(calls) == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_feishu_notifications.py -v`

Expected: FAIL，因为尚未分段或未包含分段失败语义。

- [ ] **Step 3: 实现确定性分段和限速**

以预留足够位数的分段头计算有效正文预算，优先使用保留换行的完整行，长行按 Python Unicode
字符边界切割。生成最终 `第 n/m 段` 标题后重新断言每个 JSON 请求最多 18KiB。第二段及后续段
发送前调用注入的 `sleep(0.2)`；失败即停止，不重试。

- [ ] **Step 4: 运行通知服务测试确认通过**

Run: `python -m pytest tests/test_feishu_notifications.py -v`

Expected: PASS，且不发生真实 HTTP 请求。

- [ ] **Step 5: 提交该切片**

```bash
git add src/stock_research/services/feishu_notifications.py tests/test_feishu_notifications.py
git commit -m "feat(notifications): chunk Feishu report messages safely"
```

### Task 3: 将通知接入每次 generate 并记录操作说明

**Files:**
- Modify: `src/stock_research/cli.py`
- Modify: `README.md`
- Modify: `docs/automation/daily-research-prompt.md`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `generate` 在报告保存后调用私有 `_notify_generated_report(paths, report_date)`；成功时输出发送段数，失败时输出报告路径和安全错误并退出 1。
- Consumes: `FeishuNotificationService` 与 `ReportPaths.markdown`。

- [ ] **Step 1: 写 CLI 集成失败测试**

```python
def test_generate_saves_report_then_notifies_for_manual_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STOCK_RESEARCH_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "_notify_generated_report", recording_notifier)
    result = runner.invoke(app, ["generate", "--input", str(request_path)])
    assert result.exit_code == 0
    assert notified_markdown == (tmp_path / "reports" / "2026-07-22" / "report.md").read_text(encoding="utf-8")


def test_generate_keeps_saved_report_when_feishu_configuration_is_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("STOCK_RESEARCH_FEISHU_WEBHOOK_URL", raising=False)
    result = runner.invoke(app, ["generate", "--input", str(request_path)])
    assert result.exit_code == 1
    assert (tmp_path / "reports" / "2026-07-22" / "report.md").exists()
    assert "notification failed" in result.stderr
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_cli.py -k "generate and (notifies or feishu)" -v`

Expected: FAIL，因为当前命令未发送报告。

- [ ] **Step 3: 实现后持久化通知与文档**

让 `generate` 只在 `daily_run.run()` 成功返回、取得 `ReportPaths.markdown` 后调用服务。通知异常时
打印三个已生成路径及不含 URL 的错误，退出 1；通知成功后打印路径与段数。README 记录 Windows
用户环境变量设置命令、重开 Codex App 后生效、失败恢复方式；每日提示词仅说明该环境变量须由本机
预先配置，绝不包含实际 Webhook。

- [ ] **Step 4: 运行集成测试确认通过**

Run: `python -m pytest tests/test_cli.py tests/test_daily_run.py tests/test_feishu_notifications.py -v`

Expected: PASS；人工和自动化共用 `generate` 的行为可由测试确认。

- [ ] **Step 5: 提交该切片**

```bash
git add src/stock_research/cli.py README.md docs/automation/daily-research-prompt.md tests/test_cli.py
git commit -m "feat(cli): notify Feishu after report generation"
```

### Task 4: 完整验证、配置本机 Webhook 并审查

**Files:**
- Test: 全部现有测试与新增测试。

- [ ] **Step 1: 执行完整验证**

Run: `python -m pytest -v && python -m ruff check . && python -m ruff format --check . && git diff --check`

Expected: 测试、检查和格式全部通过。

- [ ] **Step 2: 配置用户级机密并验证不入库**

Run: 使用 Windows 用户级环境变量设置 `STOCK_RESEARCH_FEISHU_WEBHOOK_URL`，随后仅检查变量已存在，
不在终端打印其值；运行 `git status --short`，确认无 Webhook 或机密文件被跟踪。

Expected: 后续本地自动化进程可从用户环境读取配置，Git 无机密。

- [ ] **Step 3: 进行只读代码审查与推送前验证**

Run: 审查本功能提交的 diff、执行完整测试、Ruff、CLI help、`git diff --check` 和工作树状态。

Expected: 没有未修复的安全、可靠性或回归问题；不触及既有北京交易所未提交改动。

## Plan Self-Review

### Spec coverage

- 每次人工和自动 `generate` 通知：Task 3。
- 环境变量机密与无 Git 泄露：Tasks 1、3、4。
- 飞书 V2 文本请求和 18KiB 安全上限：Tasks 1、2。
- UTF-8 完整分段、顺序、限速和失败停止：Task 2。
- 报告先保存、失败不回滚且 CLI 以非零展示：Task 3。
- 无网络单测、全量验证和本机配置：Task 4。

### Placeholder scan

本计划没有占位步骤；每项任务给出了路径、接口、测试、命令、期望结果和提交信息。

### Type consistency

`FeishuNotificationService.send_markdown(report_date, markdown)` 由 CLI 的
`_notify_generated_report(paths, report_date)` 调用；服务只接收文本，CLI 只读取已保存的
`ReportPaths.markdown`，因此不会改变 `DailyRunService` 或报告领域模型。
