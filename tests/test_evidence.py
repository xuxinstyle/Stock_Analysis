import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from stock_research.domain.enums import Credibility, Direction, EvidenceCategory
from stock_research.domain.models import Evidence, StockResearchInput
from stock_research.services.evidence import EvidenceService


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "daily_research_request.json"


def evidence(
    title: str,
    url: str,
    credibility: Credibility,
    *,
    published_at: datetime | None = None,
    retrieved_at: datetime | None = None,
) -> Evidence:
    return Evidence(
        title=title,
        url=url,
        source_name="Example Newsroom",
        published_at=published_at,
        retrieved_at=retrieved_at or datetime(2026, 7, 21, 1, tzinfo=UTC),
        category=EvidenceCategory.NEWS,
        direction=Direction.NEUTRAL,
        credibility=credibility,
        summary="This is a sufficiently detailed fixture evidence summary.",
        symbols=["SH.600000"],
    )


def valid_research_payload(*, symbol: str = "SH.600000") -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["research_inputs"][0] | {
        "symbol": symbol
    }


def test_deduplicate_keeps_the_more_credible_source() -> None:
    result = EvidenceService().validate_and_deduplicate(
        [
            evidence("Market rumor", "https://news.example/item#coverage", Credibility.LOW),
            evidence("Exchange filing", "https://news.example/item", Credibility.PRIMARY),
        ]
    )

    assert len(result) == 1
    assert result[0].credibility is Credibility.PRIMARY


def test_deduplicate_ties_keep_later_publication_then_retrieval() -> None:
    service = EvidenceService()
    result = service.validate_and_deduplicate(
        [
            evidence(
                "Earlier record",
                "https://news.example/item",
                Credibility.SECONDARY,
                published_at=datetime(2026, 7, 20, tzinfo=UTC),
                retrieved_at=datetime(2026, 7, 21, 1, tzinfo=UTC),
            ),
            evidence(
                "Later publication",
                "https://news.example/item#updated",
                Credibility.SECONDARY,
                published_at=datetime(2026, 7, 21, tzinfo=UTC),
                retrieved_at=datetime(2026, 7, 21, 0, tzinfo=UTC),
            ),
            evidence(
                "Later retrieval",
                "https://news.example/item",
                Credibility.SECONDARY,
                published_at=datetime(2026, 7, 21, tzinfo=UTC),
                retrieved_at=datetime(2026, 7, 21, 2, tzinfo=UTC),
            ),
        ]
    )

    assert [item.title for item in result] == ["Later retrieval"]


def test_research_input_rejects_evidence_for_another_stock() -> None:
    payload = valid_research_payload(symbol="SH.600000")
    payload["evidence"][0]["symbols"] = ["HK.00700"]  # type: ignore[index]

    with pytest.raises(ValidationError, match="must include research symbol"):
        StockResearchInput.model_validate(payload)


def test_research_input_rejects_event_for_another_stock() -> None:
    payload = valid_research_payload(symbol="SH.600000")
    payload["events"][0]["symbols"] = ["HK.00700"]  # type: ignore[index]

    with pytest.raises(ValidationError, match="event symbols must include research symbol"):
        StockResearchInput.model_validate(payload)


def test_research_input_rejects_confirmed_negative_event_without_scope() -> None:
    payload = valid_research_payload(symbol="SH.600000")
    event = payload["events"][0]  # type: ignore[index]
    event.update(  # type: ignore[union-attr]
        {
            "direction": "negative",
            "is_confirmed": True,
            "citation_title": "Confirmed local disclosure",
            "citation_url": "https://example.test/local-disclosure",
        }
    )
    event.pop("scope", None)  # type: ignore[union-attr]

    with pytest.raises(ValidationError, match="scope"):
        StockResearchInput.model_validate(payload)


def test_research_input_rejects_us_subject_symbol() -> None:
    payload = valid_research_payload(symbol="US.AAPL")
    payload["evidence"] = [
        {**item, "symbols": ["US.AAPL"]}
        for item in payload["evidence"]  # type: ignore[misc]
    ]

    with pytest.raises(ValidationError, match=r"symbol must use SH\.600000"):
        StockResearchInput.model_validate(payload)


def test_research_input_accepts_current_beijing_subject_symbol() -> None:
    payload = valid_research_payload(symbol="BJ.920808")
    payload["evidence"] = [
        {**item, "symbols": ["BJ.920808"]}
        for item in payload["evidence"]  # type: ignore[misc]
    ]
    payload["events"] = [
        {**item, "symbols": ["BJ.920808"]}
        for item in payload["events"]  # type: ignore[misc]
    ]

    assert StockResearchInput.model_validate(payload).symbol == "BJ.920808"


@pytest.mark.parametrize(
    "summary_name",
    [
        "fundamental_summary",
        "industry_summary",
        "policy_summary",
        "news_summary",
        "international_summary",
        "product_price_summary",
        "recent_price_move_summary",
    ],
)
def test_research_input_requires_each_summary(summary_name: str) -> None:
    payload = valid_research_payload()
    payload[summary_name] = "   "

    with pytest.raises(ValidationError):
        StockResearchInput.model_validate(payload)


def test_research_input_preserves_events_as_a_list() -> None:
    research_input = StockResearchInput.model_validate(valid_research_payload())

    assert isinstance(research_input.events, list)
    assert research_input.events[0].title == "Example disclosure event"


def test_research_input_preserves_recent_price_move_summary() -> None:
    payload = valid_research_payload()
    summary = "近五个完整交易日上涨；已证实驱动见引用，行业联动仅为推断。"
    payload["recent_price_move_summary"] = summary

    assert StockResearchInput.model_validate(payload).recent_price_move_summary == summary
