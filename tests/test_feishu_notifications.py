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
    payload: dict[str, object]

    def json(self) -> dict[str, object]:
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


def test_rejects_non_feishu_or_non_v2_webhook_urls() -> None:
    with pytest.raises(FeishuNotificationError, match="HTTPS V2"):
        FeishuNotificationService("https://example.com/open-apis/bot/v2/hook/token")
    with pytest.raises(FeishuNotificationError, match="HTTPS V2"):
        FeishuNotificationService("https://open.feishu.cn/open-apis/bot/hook/token")


def test_send_rejects_a_feishu_business_error() -> None:
    service = FeishuNotificationService(
        "https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        post=lambda url, **kwargs: FakeResponse(200, {"StatusCode": 11232}),
        sleep=lambda seconds: None,
    )

    with pytest.raises(FeishuNotificationError, match="service rejected request"):
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
