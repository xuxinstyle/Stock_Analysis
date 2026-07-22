from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from stock_research.services.feishu_notifications import (
    MAX_REQUEST_BYTES,
    FeishuNotificationError,
    FeishuNotificationService,
    split_text_for_feishu,
)


@dataclass(frozen=True)
class FakeResponse:
    status_code: int
    payload: object

    def json(self) -> object:
        return self.payload


def test_from_environment_rejects_missing_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STOCK_RESEARCH_FEISHU_WEBHOOK_URL", raising=False)

    with pytest.raises(FeishuNotificationError, match="STOCK_RESEARCH_FEISHU_WEBHOOK_URL"):
        FeishuNotificationService.from_environment()


def test_send_markdown_posts_one_v2_text_payload() -> None:
    posted: list[dict[str, object]] = []

    def post(url: str, **kwargs: object) -> FakeResponse:
        assert url == "https://open.feishu.cn/open-apis/bot/v2/hook/test-token"
        assert kwargs["headers"] == {"Content-Type": "application/json; charset=utf-8"}
        assert kwargs["timeout"] == 10.0
        posted.append(kwargs["json"])
        return FakeResponse(200, {"StatusCode": 0})

    service = FeishuNotificationService(
        "https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        post=post,
        sleep=lambda seconds: None,
    )

    assert service.send_markdown(date(2026, 7, 22), "# 完整报告\n内容") == 1
    assert posted == [
        {
            "msg_type": "text",
            "content": {"text": "股票研究报告 2026-07-22（第 1/1 段）\n# 完整报告\n内容"},
        }
    ]


def test_send_report_sections_posts_one_message_per_company_and_one_aggregate_summary() -> None:
    posted: list[dict[str, object]] = []

    def post(url: str, **kwargs: object) -> FakeResponse:
        posted.append(kwargs["json"])
        return FakeResponse(200, {"StatusCode": 0})

    service = FeishuNotificationService(
        "https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        post=post,
        sleep=lambda seconds: None,
    )
    markdown = """# 每日股票研究报告 — 2026-07-22

## 市场状态
不发送到单家公司消息。

# SZ.002594 比亚迪
比亚迪公司分析。

# SH.688268 华特气体
华特气体公司分析。

## 全部标的操作汇总
比亚迪和华特气体的汇总不发送到单家公司消息。
"""

    assert service.send_report_sections(date(2026, 7, 22), markdown) == 3

    texts = [payload["content"]["text"] for payload in posted]
    assert len(texts) == 3
    assert "比亚迪公司分析。" in texts[0]
    assert "华特气体公司分析。" not in texts[0]
    assert "华特气体公司分析。" in texts[1]
    assert "比亚迪公司分析。" not in texts[1]
    assert all("全部标的操作汇总" not in text for text in texts[:2])
    assert "全部标的操作汇总" in texts[2]
    assert "比亚迪和华特气体的汇总" in texts[2]
    assert all("不构成个性化投资建议" in text for text in texts)


def test_rejects_non_feishu_or_non_v2_webhook_urls() -> None:
    with pytest.raises(FeishuNotificationError, match="HTTPS V2"):
        FeishuNotificationService("https://example.com/open-apis/bot/v2/hook/token")
    with pytest.raises(FeishuNotificationError, match="HTTPS V2"):
        FeishuNotificationService("https://open.feishu.cn/open-apis/bot/hook/token")


def test_rejects_webhook_paths_that_do_not_contain_exactly_one_token() -> None:
    for webhook_url in (
        "https://open.feishu.cn/open-apis/bot/v2/hook/token/extra",
        "https://open.feishu.cn/open-apis/bot/v2/hook//",
    ):
        with pytest.raises(FeishuNotificationError, match="HTTPS V2"):
            FeishuNotificationService(webhook_url)


def test_send_rejects_a_feishu_business_error() -> None:
    service = FeishuNotificationService(
        "https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        post=lambda url, **kwargs: FakeResponse(200, {"StatusCode": 11232}),
        sleep=lambda seconds: None,
    )

    with pytest.raises(FeishuNotificationError, match="service rejected request"):
        service.send_markdown(date(2026, 7, 22), "# 完整报告")


def test_send_rejects_a_non_object_json_response() -> None:
    service = FeishuNotificationService(
        "https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        post=lambda url, **kwargs: FakeResponse(200, []),
        sleep=lambda seconds: None,
    )

    with pytest.raises(FeishuNotificationError, match="invalid response"):
        service.send_markdown(date(2026, 7, 22), "# 完整报告")


def test_split_preserves_chinese_emoji_and_keeps_each_payload_under_limit() -> None:
    markdown = "研究😀\n" * 8_000

    chunks = split_text_for_feishu(markdown, date(2026, 7, 22))

    assert len(chunks) > 1
    assert all(len(_serialized_payload(chunk)) <= MAX_REQUEST_BYTES for chunk in chunks)
    assert "".join(chunk.split("\n", maxsplit=1)[1] for chunk in chunks) == markdown
    assert all(
        chunk.startswith(f"股票研究报告 2026-07-22（第 {number}/{len(chunks)} 段）\n")
        for number, chunk in enumerate(chunks, start=1)
    )


def test_send_stops_at_the_failed_chunk_without_retrying() -> None:
    calls: list[dict[str, object]] = []
    sleeps: list[float] = []

    def post(url: str, **kwargs: object) -> FakeResponse:
        calls.append(kwargs["json"])
        if len(calls) == 2:
            return FakeResponse(500, {})
        return FakeResponse(200, {"StatusCode": 0})

    service = FeishuNotificationService(
        "https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        post=post,
        sleep=sleeps.append,
    )

    with pytest.raises(FeishuNotificationError, match="segment 2"):
        service.send_markdown(date(2026, 7, 22), "研究😀\n" * 8_000)

    assert len(calls) == 2
    assert sleeps == [0.2]


def _serialized_payload(text: str) -> bytes:
    import json

    return json.dumps(
        {"msg_type": "text", "content": {"text": text}},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
