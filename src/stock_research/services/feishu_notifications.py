from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping
from datetime import date
from typing import Protocol, Self
from urllib.parse import urlparse

import httpx


WEBHOOK_ENVIRONMENT_VARIABLE = "STOCK_RESEARCH_FEISHU_WEBHOOK_URL"
MAX_REQUEST_BYTES = 18 * 1024
_HEADERS = {"Content-Type": "application/json; charset=utf-8"}
_DEFAULT_REPORT_TITLE = "股票研究报告"
_SECTION_DISCLAIMER = "仅供研究参考，不构成个性化投资建议、收益保证或交易指令。"
_COMPANY_HEADING = re.compile(r"^# (?P<label>(?:SH|SZ|BJ|HK)\.\S+ .+)$", re.MULTILINE)
_AGGREGATE_SUMMARY_HEADING = re.compile(r"^## 全部标的操作汇总$", re.MULTILINE)


class FeishuNotificationError(RuntimeError):
    """A configured Feishu report notification could not be completed."""


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> object: ...


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


def _message_text(
    report_date: date,
    segment_number: int,
    segment_count: int,
    markdown: str,
    report_title: str,
) -> str:
    return (
        f"{report_title} {report_date.isoformat()}（第 {segment_number}/{segment_count} 段）\n"
        f"{markdown}"
    )


def _payload(text: str) -> dict[str, object]:
    return {"msg_type": "text", "content": {"text": text}}


def _payload_size(text: str) -> int:
    return len(
        json.dumps(_payload(text), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def split_text_for_feishu(
    text: str, report_date: date, *, report_title: str = _DEFAULT_REPORT_TITLE
) -> list[str]:
    if not text.strip():
        raise FeishuNotificationError("saved Markdown report is empty")
    reserved_header = _message_text(report_date, 99_999, 99_999, "", report_title)
    bodies = _split_body(
        text, lambda body: _payload_size(reserved_header + body) <= MAX_REQUEST_BYTES
    )
    if len(bodies) > 99_999:
        raise FeishuNotificationError(
            "saved Markdown report requires too many Feishu message segments"
        )
    messages = [
        _message_text(report_date, segment_number, len(bodies), body, report_title)
        for segment_number, body in enumerate(bodies, start=1)
    ]
    if any(_payload_size(message) > MAX_REQUEST_BYTES for message in messages):
        raise FeishuNotificationError(
            "saved Markdown report could not be split within the Feishu limit"
        )
    return messages


def split_report_sections(markdown: str) -> list[tuple[str, str]]:
    company_headings = list(_COMPANY_HEADING.finditer(markdown))
    aggregate_heading = _AGGREGATE_SUMMARY_HEADING.search(markdown)
    if not company_headings:
        raise FeishuNotificationError("saved Markdown report does not contain company sections")
    if aggregate_heading is None:
        raise FeishuNotificationError("saved Markdown report does not contain aggregate summary")

    aggregate_start = aggregate_heading.start()
    if company_headings[-1].start() >= aggregate_start:
        raise FeishuNotificationError("saved Markdown report has invalid company section order")

    sections: list[tuple[str, str]] = []
    for index, heading in enumerate(company_headings):
        next_start = (
            company_headings[index + 1].start()
            if index + 1 < len(company_headings)
            else aggregate_start
        )
        sections.append(
            (
                f"{_DEFAULT_REPORT_TITLE} — {heading.group('label')}",
                _section_text(markdown[heading.start() : next_start]),
            )
        )
    sections.append(
        (
            f"{_DEFAULT_REPORT_TITLE} — 全部标的操作汇总",
            _section_text(markdown[aggregate_start:]),
        )
    )
    return sections


def _section_text(markdown: str) -> str:
    return f"{_SECTION_DISCLAIMER}\n\n{markdown.strip()}\n"


def _split_body(text: str, fits_payload: Callable[[str], bool]) -> list[str]:
    bodies: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if not fits_payload(line):
            if current:
                bodies.append(current)
                current = ""
            bodies.extend(_split_long_line(line, fits_payload))
        elif current and not fits_payload(current + line):
            bodies.append(current)
            current = line
        else:
            current += line
    if current:
        bodies.append(current)
    return bodies


def _split_long_line(line: str, fits_payload: Callable[[str], bool]) -> list[str]:
    parts: list[str] = []
    current = ""
    for character in line:
        if current and not fits_payload(current + character):
            parts.append(current)
            current = character
        else:
            current += character
    if current:
        parts.append(current)
    return parts


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
        return self._send_messages(messages)

    def send_report_sections(self, report_date: date, markdown: str) -> int:
        sent_segments = 0
        for report_title, section_markdown in split_report_sections(markdown):
            sent_segments += self._send_messages(
                split_text_for_feishu(
                    section_markdown,
                    report_date,
                    report_title=report_title,
                )
            )
        return sent_segments

    def _send_messages(self, messages: list[str]) -> int:
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
        path_parts = parsed.path.split("/")
        if (
            parsed.scheme != "https"
            or parsed.netloc != "open.feishu.cn"
            or path_parts[:5] != ["", "open-apis", "bot", "v2", "hook"]
            or len(path_parts) != 6
            or not path_parts[-1]
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
        if not isinstance(payload, Mapping):
            raise FeishuNotificationError(
                f"Feishu notification failed for segment {segment_number}: invalid response"
            )
        status_code = payload.get("StatusCode", payload.get("code"))
        if status_code != 0:
            raise FeishuNotificationError(
                f"Feishu notification failed for segment {segment_number}: service rejected request"
            )
