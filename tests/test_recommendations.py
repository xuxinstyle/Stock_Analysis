from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Callable

import pandas as pd
import pytest
from pydantic import ValidationError

from stock_research.domain.enums import (
    Action,
    Confidence,
    Credibility,
    Direction,
    EvidenceCategory,
    Horizon,
    Market,
    Trend,
)
from stock_research.domain.models import (
    Evidence,
    EventSignal,
    Holding,
    RecommendationInput,
    StockConfig,
    TechnicalSnapshot,
)
from stock_research.services.recommendations import RecommendationEngine
from stock_research.services.indicators import calculate_technical_snapshot


def confirmed_bullish_input(*, holding: Holding | None = None) -> RecommendationInput:
    return RecommendationInput(
        stock=StockConfig(
            symbol="SH.600000",
            name="Example A Share",
            market=Market.A_SHARE,
            holding=holding,
        ),
        technical=TechnicalSnapshot(
            data_as_of=date(2026, 7, 20),
            latest_close=12.0,
            rsi_14=55.0,
            support_20=11.2,
            resistance_20=12.8,
            realized_volatility_20=0.24,
            trend=Trend.UP,
        ),
        evidence=[
            evidence(
                "Exchange filing supports earnings outlook", Direction.POSITIVE, Credibility.PRIMARY
            ),
            evidence("Industry demand improves", Direction.POSITIVE, Credibility.SECONDARY),
        ],
        events=[],
    )


def conflicting_input() -> RecommendationInput:
    payload = confirmed_bullish_input()
    return payload.model_copy(
        update={
            "evidence": [
                evidence("Positive filing", Direction.POSITIVE, Credibility.PRIMARY),
                evidence("Negative supply event", Direction.NEGATIVE, Credibility.SECONDARY),
            ]
        }
    )


def held_position() -> Holding:
    return Holding(quantity=Decimal("100"), cost_basis=Decimal("10"))


def safety_downgrade_input() -> RecommendationInput:
    confirmed = confirmed_bullish_input(holding=held_position())
    return confirmed.model_copy(
        update={"technical": confirmed.technical.model_copy(update={"realized_volatility_20": 0.5})}
    )


def confirmed_local_negative_event_input() -> RecommendationInput:
    confirmed = confirmed_bullish_input(holding=held_position())
    return confirmed.model_copy(
        update={
            "events": [
                EventSignal(
                    title="Confirmed adverse regulatory action",
                    occurred_at=datetime(2026, 7, 20, tzinfo=UTC),
                    direction=Direction.NEGATIVE,
                    summary="A confirmed event materially weakens the near-term operating outlook.",
                    symbols=["SH.600000"],
                    scope="local",
                    is_confirmed=True,
                    citation_title="Regulator enforcement notice",
                    citation_url="https://example.com/regulator-enforcement-notice",
                )
            ]
        }
    )


def broken_support_input() -> RecommendationInput:
    confirmed = confirmed_bullish_input(holding=held_position())
    return confirmed.model_copy(
        update={
            "technical": confirmed.technical.model_copy(
                update={"latest_close": 11.0, "trend": Trend.DOWN}
            )
        }
    )


def neutral_watch_input() -> RecommendationInput:
    confirmed = confirmed_bullish_input()
    return confirmed.model_copy(
        update={"technical": confirmed.technical.model_copy(update={"trend": Trend.NEUTRAL})}
    )


def evidence(
    title: str,
    direction: Direction,
    credibility: Credibility,
    *,
    category: EvidenceCategory = EvidenceCategory.NEWS,
) -> Evidence:
    return Evidence(
        title=title,
        url=f"https://example.com/{title.lower().replace(' ', '-')}",
        source_name=title,
        published_at=datetime(2026, 7, 20, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 21, tzinfo=UTC),
        category=category,
        direction=direction,
        credibility=credibility,
        summary="This fixture supplies a sufficiently detailed, cited research statement.",
        symbols=["SH.600000"],
    )


def test_positive_confirmed_input_returns_three_horizon_recommendations() -> None:
    recommendations = RecommendationEngine().recommend(confirmed_bullish_input())

    assert [item.horizon for item in recommendations] == [
        Horizon.SHORT,
        Horizon.MEDIUM,
        Horizon.LONG,
    ]
    assert all(
        item.action in {Action.WATCH, Action.BUY_IN_TRANCHES, Action.HOLD}
        for item in recommendations
    )
    assert all(
        item.trigger and item.invalidation and item.rationale and item.position_limit
        for item in recommendations
    )


def test_generated_recommendations_use_chinese_system_copy() -> None:
    recommendation = RecommendationEngine().recommend(confirmed_bullish_input())[0]

    assert recommendation.trigger.startswith("触发条件：")
    assert recommendation.observation_or_target.startswith("观察结论：")
    assert recommendation.invalidation.startswith("失效条件：")


def assert_chinese_system_narratives(
    analysis_input: RecommendationInput,
    rationale_anchor: str,
    expected_action: Action,
    *,
    has_holding: bool,
) -> None:
    recommendations = RecommendationEngine().recommend(analysis_input)
    horizon_names = {
        Horizon.SHORT: "短期",
        Horizon.MEDIUM: "中期",
        Horizon.LONG: "长期",
    }

    assert all(item.action is expected_action for item in recommendations)
    for recommendation in recommendations:
        assert any(rationale_anchor in item for item in recommendation.rationale)
        assert recommendation.rationale[-1].startswith(
            f"{horizon_names[recommendation.horizon]}：关注"
        )
        assert "触发条件：" in recommendation.trigger
        assert "周期复核：" in recommendation.trigger
        assert "观察结论：" in recommendation.observation_or_target
        assert "周期关注：" in recommendation.observation_or_target
        assert "失效条件：" in recommendation.invalidation
        assert "周期重新评估：" in recommendation.invalidation
        if has_holding:
            assert recommendation.holding_impact is not None
            assert recommendation.holding_impact.startswith("相对成本价的")
        else:
            assert recommendation.holding_impact is None


@pytest.mark.parametrize(
    ("analysis_input_factory", "rationale_anchor", "expected_action", "has_holding"),
    [
        (safety_downgrade_input, "安全降级：", Action.WATCH, True),
        (confirmed_local_negative_event_input, "检测到下行条件：", Action.REDUCE, True),
        (broken_support_input, "检测到下行条件：", Action.REDUCE, True),
        (
            lambda: confirmed_bullish_input(holding=held_position()),
            "上升趋势且 RSI 低于 70",
            Action.BUY_IN_TRANCHES,
            True,
        ),
        (neutral_watch_input, "现有研究未满足所有已确认的看涨规则。", Action.WATCH, False),
    ],
    ids=["safety_downgrade", "local_negative_event", "broken_support", "bullish", "neutral_watch"],
)
def test_all_decision_paths_keep_chinese_system_narratives(
    analysis_input_factory: Callable[[], RecommendationInput],
    rationale_anchor: str,
    expected_action: Action,
    has_holding: bool,
) -> None:
    assert_chinese_system_narratives(
        analysis_input_factory(), rationale_anchor, expected_action, has_holding=has_holding
    )


def test_low_credibility_or_conflicting_evidence_cannot_return_buy() -> None:
    recommendations = RecommendationEngine().recommend(conflicting_input())

    assert all(item.action in {Action.WATCH, Action.AVOID} for item in recommendations)
    assert all(item.confidence is Confidence.LOW for item in recommendations)
    assert all(item.position_limit == "\u22645%" for item in recommendations)


def test_no_holding_does_not_create_personal_profit_or_loss() -> None:
    recommendations = RecommendationEngine().recommend(confirmed_bullish_input(holding=None))

    assert all(item.holding_impact is None for item in recommendations)


def test_holding_return_is_informational_and_uses_latest_close() -> None:
    recommendations = RecommendationEngine().recommend(
        confirmed_bullish_input(holding=Holding(quantity=Decimal("100"), cost_basis=Decimal("10")))
    )

    assert all(
        item.holding_impact == "相对成本价的信息性收益：+20.00%。" for item in recommendations
    )


def test_normal_confidence_uses_horizon_specific_position_limits() -> None:
    recommendations = RecommendationEngine().recommend(confirmed_bullish_input())

    assert [item.position_limit for item in recommendations] == ["≤10%", "≤15%", "≤20%"]


def test_horizons_have_distinct_research_review_semantics() -> None:
    recommendations = RecommendationEngine().recommend(confirmed_bullish_input())

    assert len({item.trigger for item in recommendations}) == 3
    assert len({item.observation_or_target for item in recommendations}) == 3
    assert len({item.invalidation for item in recommendations}) == 3


@pytest.mark.parametrize(
    ("risk_profile", "expected_limits"),
    [
        ("conservative", ["≤5%", "≤10%", "≤15%"]),
        ("balanced", ["≤10%", "≤15%", "≤20%"]),
        ("aggressive", ["≤15%", "≤20%", "≤25%"]),
    ],
)
def test_holding_risk_profile_adjusts_research_position_limits(
    risk_profile: str, expected_limits: list[str]
) -> None:
    recommendations = RecommendationEngine().recommend(
        confirmed_bullish_input(
            holding=Holding(
                quantity=Decimal("100"),
                cost_basis=Decimal("10"),
                risk_profile=risk_profile,  # type: ignore[arg-type]
            )
        )
    )

    assert [item.position_limit for item in recommendations] == expected_limits


def test_high_volatility_cannot_return_buy() -> None:
    analysis_input = confirmed_bullish_input().model_copy(
        update={
            "technical": confirmed_bullish_input().technical.model_copy(
                update={"realized_volatility_20": 0.5}
            )
        }
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert all(item.action is Action.WATCH for item in recommendations)
    assert all(item.confidence is Confidence.LOW for item in recommendations)


def test_fewer_than_two_credible_sources_cannot_return_buy() -> None:
    analysis_input = confirmed_bullish_input().model_copy(
        update={"evidence": [evidence("Only one filing", Direction.POSITIVE, Credibility.PRIMARY)]}
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert all(item.action is Action.WATCH for item in recommendations)
    assert all(item.confidence is Confidence.LOW for item in recommendations)
    assert all(item.position_limit == "≤5%" for item in recommendations)


def test_unavailable_price_data_cannot_return_buy() -> None:
    analysis_input = confirmed_bullish_input().model_copy(
        update={
            "technical": confirmed_bullish_input().technical.model_copy(
                update={"latest_close": 0.0}
            )
        }
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert all(item.action is Action.WATCH for item in recommendations)
    assert all(item.confidence is Confidence.LOW for item in recommendations)


@pytest.mark.parametrize("latest_close", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_price_data_cannot_return_buy(latest_close: float) -> None:
    analysis_input = confirmed_bullish_input().model_copy(
        update={
            "technical": confirmed_bullish_input().technical.model_copy(
                update={"latest_close": latest_close}
            )
        }
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert all(item.action is Action.WATCH for item in recommendations)
    assert all(item.confidence is Confidence.LOW for item in recommendations)


@pytest.mark.parametrize("latest_close", [float("nan"), float("inf"), float("-inf"), 0.0])
def test_invalid_price_data_does_not_calculate_holding_impact(latest_close: float) -> None:
    analysis_input = confirmed_bullish_input(
        holding=Holding(quantity=Decimal("100"), cost_basis=Decimal("10"))
    ).model_copy(
        update={
            "technical": confirmed_bullish_input().technical.model_copy(
                update={"latest_close": latest_close}
            )
        }
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert all(item.action is Action.WATCH for item in recommendations)
    assert all(item.confidence is Confidence.LOW for item in recommendations)
    assert all(item.holding_impact is None for item in recommendations)


def test_positive_international_only_evidence_cannot_return_buy() -> None:
    analysis_input = confirmed_bullish_input().model_copy(
        update={
            "evidence": [
                evidence(
                    "US peer demand increases",
                    Direction.POSITIVE,
                    Credibility.PRIMARY,
                    category=EvidenceCategory.INTERNATIONAL,
                ),
                evidence(
                    "Overseas supply improves",
                    Direction.POSITIVE,
                    Credibility.SECONDARY,
                    category=EvidenceCategory.INTERNATIONAL,
                ),
            ]
        }
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert all(item.action is Action.WATCH for item in recommendations)
    assert all(item.confidence is Confidence.LOW for item in recommendations)


def test_single_international_context_is_valid_nonbuying_and_citable() -> None:
    analysis_input = confirmed_bullish_input().model_copy(
        update={
            "evidence": [
                evidence(
                    "US peer demand increases",
                    Direction.POSITIVE,
                    Credibility.PRIMARY,
                    category=EvidenceCategory.INTERNATIONAL,
                )
            ]
        }
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert all(item.action is Action.WATCH for item in recommendations)
    assert all(item.evidence_titles == ["US peer demand increases"] for item in recommendations)
    assert all(
        str(item.citation_urls[0]) == "https://example.com/us-peer-demand-increases"
        for item in recommendations
    )


def test_unconfirmed_negative_event_does_not_directly_action_recommendation() -> None:
    analysis_input = confirmed_bullish_input().model_copy(
        update={
            "events": [
                EventSignal(
                    title="Unconfirmed adverse regulatory action",
                    occurred_at=datetime(2026, 7, 20, tzinfo=UTC),
                    direction=Direction.NEGATIVE,
                    summary="An unconfirmed report could weaken the near-term operating outlook.",
                    symbols=["SH.600000"],
                    scope="local",
                )
            ]
        }
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert all(item.action is Action.BUY_IN_TRANCHES for item in recommendations)


def test_foreign_confirmed_negative_event_does_not_directly_action_recommendation() -> None:
    analysis_input = confirmed_bullish_input().model_copy(
        update={
            "events": [
                EventSignal(
                    title="Foreign confirmed adverse regulatory action",
                    occurred_at=datetime(2026, 7, 20, tzinfo=UTC),
                    direction=Direction.NEGATIVE,
                    summary="A confirmed foreign event must remain reportable but not action this stock.",
                    symbols=["HK.00700"],
                    scope="international",
                    is_confirmed=True,
                    citation_title="Hong Kong regulator notice",
                    citation_url="https://example.com/hk-regulator-notice",
                )
            ]
        }
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert all(item.action is Action.BUY_IN_TRANCHES for item in recommendations)


def test_confirmed_international_event_is_context_only_for_trade_decision() -> None:
    analysis_input = confirmed_bullish_input().model_copy(
        update={
            "events": [
                EventSignal(
                    title="Overseas peer faces a regulatory investigation",
                    occurred_at=datetime(2026, 7, 20, tzinfo=UTC),
                    direction=Direction.NEGATIVE,
                    summary="The event is relevant sector context but not a local decision signal.",
                    symbols=["SH.600000"],
                    scope="international",
                    is_confirmed=True,
                    citation_title="Overseas regulator release",
                    citation_url="https://example.com/overseas-regulator",
                )
            ]
        }
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert all(item.action is Action.BUY_IN_TRANCHES for item in recommendations)


def test_confirmed_event_requires_a_title_and_url_citation() -> None:
    with pytest.raises(ValidationError, match="must include a citation title and URL"):
        EventSignal(
            title="Confirmed event without a citation",
            occurred_at=datetime(2026, 7, 20, tzinfo=UTC),
            direction=Direction.NEGATIVE,
            summary="A confirmed event needs explicit source attribution before recommendation use.",
            symbols=["SH.600000"],
            scope="local",
            is_confirmed=True,
        )


def test_completed_close_below_prior_bar_support_reaches_downside_decision() -> None:
    prior_closes = [10.0] * 20
    closes = [*prior_closes, 9.0]
    bars = pd.DataFrame(
        {
            "date": pd.date_range("2026-06-01", periods=len(closes), freq="D"),
            "open": closes,
            "high": [close + 0.5 for close in closes],
            "low": [close - 0.5 for close in closes],
            "close": closes,
            "volume": [1_000.0] * len(closes),
        }
    )
    analysis_input = confirmed_bullish_input().model_copy(
        update={"technical": calculate_technical_snapshot(bars)}
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert analysis_input.technical.support_20 == pytest.approx(9.5)
    assert {item.action for item in recommendations} == {Action.AVOID}


def test_confirmed_negative_event_recommends_reduce_or_avoid() -> None:
    analysis_input = confirmed_bullish_input().model_copy(
        update={
            "events": [
                EventSignal(
                    title="Confirmed adverse regulatory action",
                    occurred_at=datetime(2026, 7, 20, tzinfo=UTC),
                    direction=Direction.NEGATIVE,
                    summary="A confirmed event materially weakens the near-term operating outlook.",
                    symbols=["SH.600000"],
                    scope="local",
                    is_confirmed=True,
                    citation_title="Regulator enforcement notice",
                    citation_url="https://example.com/regulator-enforcement-notice",
                )
            ]
        }
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert all(item.action in {Action.REDUCE, Action.AVOID} for item in recommendations)
    assert all("Confirmed adverse regulatory action" in item.trigger for item in recommendations)
    assert all(item.evidence_titles == ["Regulator enforcement notice"] for item in recommendations)
    assert all(
        str(item.citation_urls[0]) == "https://example.com/regulator-enforcement-notice"
        for item in recommendations
    )


def test_recommendations_include_decisive_evidence_titles_and_urls() -> None:
    recommendations = RecommendationEngine().recommend(confirmed_bullish_input())

    assert all(
        "Exchange filing supports earnings outlook" in item.evidence_titles
        for item in recommendations
    )
    assert all(
        str(item.citation_urls[0])
        == "https://example.com/exchange-filing-supports-earnings-outlook"
        for item in recommendations
    )
    assert all(
        "Exchange filing supports earnings outlook" in item.trigger for item in recommendations
    )


def test_break_below_named_support_recommends_reduce_or_avoid() -> None:
    analysis_input = confirmed_bullish_input().model_copy(
        update={
            "technical": confirmed_bullish_input().technical.model_copy(
                update={"latest_close": 11.0, "trend": Trend.DOWN}
            )
        }
    )

    recommendations = RecommendationEngine().recommend(analysis_input)

    assert all(item.action in {Action.REDUCE, Action.AVOID} for item in recommendations)
    assert all("支撑位 11.20" in item.trigger for item in recommendations)


def test_recommendation_input_rejects_evidence_for_another_market_subject() -> None:
    confirmed = confirmed_bullish_input()
    foreign_evidence = evidence(
        "Hong Kong evidence", Direction.POSITIVE, Credibility.PRIMARY
    ).model_copy(update={"symbols": ["HK.00700"]})

    with pytest.raises(ValidationError, match="must include recommendation stock symbol"):
        RecommendationInput(
            stock=confirmed.stock,
            technical=confirmed.technical,
            evidence=[foreign_evidence],
            events=[],
        )


def test_recommendation_input_requires_at_least_one_evidence_citation() -> None:
    confirmed = confirmed_bullish_input()

    with pytest.raises(ValidationError, match="at least 1 item"):
        RecommendationInput(
            stock=confirmed.stock,
            technical=confirmed.technical,
            evidence=[],
            events=[],
        )
