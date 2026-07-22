# 飞书报告通知设计

## 目标

每次成功执行 `stock-research generate --input <request.json>` 并持久化日报后，将该日报的完整
Markdown 内容发送到指定飞书自定义机器人 Webhook。超出飞书单条请求安全大小的内容按 UTF-8 边界
拆成多条并按顺序发送。

## 范围与约束

- 通知由 `generate` 命令触发，因此每日 Codex 自动化和任何人工 `generate` 都会发送；相同报告
  被重复生成时会重复通知。
- 报告 JSON、Markdown、HTML 必须先完成现有原子保存和运行记录持久化；通知绝不替代或回滚报告。
- Webhook URL 是机密，只从本机环境变量 `STOCK_RESEARCH_FEISHU_WEBHOOK_URL` 获取。不得写入
  Git、源码、测试夹具、README、自动化提示词或命令输出。
- 仅支持飞书 V2 自定义机器人 Webhook，使用 `POST`、`Content-Type: application/json; charset=utf-8`
  和 `msg_type: "text"`。飞书文档规定 V2 自定义机器人请求体不得超过 20KB；实现将每条序列化
  JSON 请求限制在 18KiB，保留安全余量。
- 报告仍是研究用途，不发送订单、券商指令、密钥或个性化投资承诺。
- 现有未提交的北京交易所相关改动不属于本功能，实施不得修改或覆盖它们。

## 架构

新增一个独立的通知服务，职责限定为：验证 Webhook 配置、将文本分段、构建飞书 V2 文本请求、
顺序发送并验证响应。该服务通过一个可注入 HTTP 传输协议工作，测试无需真实网络。

`generate` 在 `DailyRunService.run()` 已成功返回且 `ReportStore` 已保存 Markdown 后读取
`ReportPaths.markdown`，调用通知服务。命令层保留对通知失败的可见处理，避免改变已经保存的
`DailyReport`、三种报告文件或其成功运行记录。

```text
validated request
      |
DailyRunService.run -> report.json / report.md / report.html + run record
      |
read complete report.md
      |
FeishuNotificationService
      |-- no webhook -> configuration error
      |-- chunk UTF-8 text to <= 18KiB JSON payloads
      '-- POST chunks in order -> verify Feishu success response
```

## 内容与分段

每个通知使用飞书 V2 文本消息：

```json
{
  "msg_type": "text",
  "content": {"text": "..."}
}
```

分段器以最终序列化 JSON 的 UTF-8 字节数为准，而不是 Python 字符数。先以完整行作为切点；若一行
本身太长，再按 Unicode 字符边界分割。每段都包含稳定的报告日期及 `第 n/m 段` 前缀，且必须满足
18KiB 上限。中文、Emoji、URL 和 Markdown 链接不得因字节截断而损坏。空 Markdown 视为错误，
不得发送空通知。

按顺序串行发送。所有分段完成后才视为通知成功；任一 HTTP 异常、非 2xx 状态或飞书业务错误码都
使通知失败。实现遵守自定义机器人每秒最多 5 条的限制：在连续发送时至少间隔 0.2 秒；单条消息
不等待。

## 失败语义

- 未设置或格式不合法的 Webhook：`generate` 在报告保存后以清晰配置错误退出非零。
- 第 k 段发送失败：此前已发出的分段不撤回，报告保持可用，命令退出非零并显示第 k 段错误。
- 本功能不自动重试，避免重复推送完整研究内容；用户可显式重新运行 `generate`。
- 飞书通知失败不修改已保存报告及其原始成功运行记录。自动化会看到命令失败并按既有失败通知策略
  提醒用户。

## 配置与运行方式

用户在本机设置 `STOCK_RESEARCH_FEISHU_WEBHOOK_URL` 后运行现有命令：

```powershell
stock-research generate --input .\.stock-research\input\daily-research-request-YYYY-MM-DD.json
```

无需在每日 Codex 提示词中内嵌 Webhook 或增加另一个发送命令；自动化沿用现有 `generate` 步骤即可。
README 仅记录环境变量名称、设置方法和通知失败的恢复方式，不包含真实 URL。

## 测试与验收

- 缺少 Webhook 时，报告仍保存，`generate` 非零退出且不发网络请求。
- 成功单段：传输层收到精确飞书 V2 文本请求，并验证成功业务响应。
- 超长中文/Emoji 内容：产生多段、按序发送、每段 JSON UTF-8 大小不超过 18KiB，拼接内容完整。
- HTTP 失败、非成功业务码和中间分段失败：不继续后续发送，错误指出失败分段，报告仍存在。
- `generate` 集成测试验证报告持久化先于通知、人工运行会通知、且真实网络完全由假传输替代。
- 全量 pytest、Ruff 检查、Ruff 格式检查和 `git diff --check` 通过。

## 规格自检

- 未包含占位符或未决接口；通知格式、上限、触发范围、失败语义和测试边界均已确定。
- 机密只通过环境变量读取，符合本地自动化与不提交密钥的约束。
- 文件持久化与通知的先后关系明确，通知失败不会造成研究报告丢失或错误回滚。
