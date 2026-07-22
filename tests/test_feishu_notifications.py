from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from stock_research.services.feishu_notifications import (
    FeishuNotificationError,
    FeishuNotificationService,
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
