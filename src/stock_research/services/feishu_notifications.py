from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from datetime import date
from typing import Protocol, Self
from urllib.parse import urlparse

import httpx


WEBHOOK_ENVIRONMENT_VARIABLE = "STOCK_RESEARCH_FEISHU_WEBHOOK_URL"
MAX_REQUEST_BYTES = 18 * 1024
_HEADERS = {"Content-Type": "application/json; charset=utf-8"}


class FeishuNotificationError(RuntimeError):
    """A configured Feishu report notification could not be completed."""


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Mapping[str, object]: ...


class HttpPost(Protocol):
    def __call__(
        self,
        url: str,
        *,
        json: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse: ...


def _default_post(
    url: str,
    *,
    json: Mapping[str, object],
    headers: Mapping[str, str],
    timeout: float,
) -> httpx.Response:
    return httpx.post(url, json=json, headers=headers, timeout=timeout)


def _message_text(report_date: date, segment_number: int, segment_count: int, markdown: str) -> str:
    return f"股票研究报告 {report_date.isoformat()}（第 {segment_number}/{segment_count} 段）\n{markdown}"


def _payload(text: str) -> dict[str, object]:
    return {"msg_type": "text", "content": {"text": text}}


def _payload_size(text: str) -> int:
    return len(
        json.dumps(_payload(text), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def split_text_for_feishu(text: str, report_date: date) -> list[str]:
    """Return the initial one-segment representation; long-message splitting follows in Task 2."""
    if not text:
        raise FeishuNotificationError("saved Markdown report is empty")
    message = _message_text(report_date, 1, 1, text)
    if _payload_size(message) > MAX_REQUEST_BYTES:
        raise FeishuNotificationError("saved Markdown report exceeds the Feishu message size limit")
    return [message]


class FeishuNotificationService:
    def __init__(
        self,
        webhook_url: str,
        *,
        post: HttpPost = _default_post,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._validate_webhook_url(webhook_url)
        self._webhook_url = webhook_url
        self._post = post
        self._sleep = sleep

    @classmethod
    def from_environment(cls) -> Self:
        webhook_url = os.environ.get(WEBHOOK_ENVIRONMENT_VARIABLE)
        if not webhook_url:
            raise FeishuNotificationError(
                f"{WEBHOOK_ENVIRONMENT_VARIABLE} must be configured before sending Feishu reports"
            )
        return cls(webhook_url)

    def send_markdown(self, report_date: date, markdown: str) -> int:
        messages = split_text_for_feishu(markdown, report_date)
        for segment_number, message in enumerate(messages, start=1):
            if segment_number > 1:
                self._sleep(0.2)
            try:
                response = self._post(
                    self._webhook_url,
                    json=_payload(message),
                    headers=_HEADERS,
                    timeout=10.0,
                )
            except httpx.HTTPError as error:
                raise FeishuNotificationError(
                    f"Feishu notification failed for segment {segment_number}"
                ) from error
            self._require_success(response, segment_number)
        return len(messages)

    @staticmethod
    def _validate_webhook_url(webhook_url: str) -> None:
        parsed = urlparse(webhook_url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "open.feishu.cn"
            or not parsed.path.startswith("/open-apis/bot/v2/hook/")
            or parsed.path == "/open-apis/bot/v2/hook/"
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise FeishuNotificationError("Feishu webhook must be an HTTPS V2 custom-bot URL")

    @staticmethod
    def _require_success(response: HttpResponse, segment_number: int) -> None:
        if not 200 <= response.status_code < 300:
            raise FeishuNotificationError(
                f"Feishu notification failed for segment {segment_number}: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as error:
            raise FeishuNotificationError(
                f"Feishu notification failed for segment {segment_number}: invalid response"
            ) from error
        status_code = payload.get("StatusCode", payload.get("code"))
        if status_code != 0:
            raise FeishuNotificationError(
                f"Feishu notification failed for segment {segment_number}: service rejected request"
            )
