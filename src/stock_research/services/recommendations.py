from decimal import Decimal, ROUND_HALF_UP

from stock_research.domain.enums import (
    Action,
    Confidence,
    Credibility,
    Direction,
    Horizon,
    RiskLevel,
    Trend,
)
from stock_research.domain.models import Evidence, Recommendation, RecommendationInput


_HIGH_VOLATILITY = 0.5
_HORIZONS = (Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG)
_POSITION_LIMITS = {
    Horizon.SHORT: "≤10%",
    Horizon.MEDIUM: "≤15%",
    Horizon.LONG: "≤20%",
}


class RecommendationEngine:
    def recommend(self, analysis_input: RecommendationInput) -> list[Recommendation]:
        decision = self._decision(analysis_input)
        holding_impact = self._holding_impact(analysis_input)
        return [
            Recommendation(
                horizon=horizon,
                position_limit=self._position_limit(horizon, decision[1]),
                holding_impact=holding_impact,
                **decision[0],
            )
            for horizon in _HORIZONS
        ]

    def _decision(self, analysis_input: RecommendationInput) -> tuple[dict[str, object], Confidence]:
        technical = analysis_input.technical
        credible_evidence = [
            item for item in analysis_input.evidence if item.credibility is not Credibility.LOW
        ]
        safety_reason = self._safety_reason(technical.latest_close, technical.realized_volatility_20, credible_evidence)
        if safety_reason is not None:
            return self._watch_decision(analysis_input, safety_reason), Confidence.LOW

        negative_event = next(
            (event for event in analysis_input.events if event.direction is Direction.NEGATIVE), None
        )
        if negative_event is not None:
            return self._downside_decision(
                analysis_input,
                f"the negative event '{negative_event.title}'",
                f"the negative event '{negative_event.title}' is superseded by a cited corrective disclosure",
            ), Confidence.HIGH

        support = technical.support_20
        if support is not None and technical.latest_close < support:
            return self._downside_decision(
                analysis_input,
                f"a close below named 20-day support {support:.2f}",
                f"a completed close back above named 20-day support {support:.2f}",
            ), Confidence.MEDIUM

        if self._is_confirmed_bullish(analysis_input, credible_evidence):
            return self._bullish_decision(analysis_input), Confidence.HIGH

        return self._neutral_watch_decision(analysis_input), Confidence.MEDIUM

    @staticmethod
    def _safety_reason(
        latest_close: float, volatility: float | None, credible_evidence: list[Evidence]
    ) -> str | None:
        if latest_close <= 0:
            return "completed price data is unavailable"
        if volatility is not None and volatility >= _HIGH_VOLATILITY:
            return "20-day realized volatility is high"
        if len(credible_evidence) < 2:
            return "fewer than two non-low-credibility sources are available"
        directions = {item.direction for item in credible_evidence if item.direction is not Direction.NEUTRAL}
        if Direction.POSITIVE in directions and Direction.NEGATIVE in directions:
            return "non-low-credibility sources have conflicting directions"
        return None

    @staticmethod
    def _is_confirmed_bullish(
        analysis_input: RecommendationInput, credible_evidence: list[Evidence]
    ) -> bool:
        technical = analysis_input.technical
        if technical.trend is not Trend.UP or technical.rsi_14 is None or technical.rsi_14 >= 70:
            return False

        positive = [item for item in credible_evidence if item.direction is Direction.POSITIVE]
        negative = [item for item in credible_evidence if item.direction is Direction.NEGATIVE]
        has_primary = any(item.credibility is Credibility.PRIMARY for item in positive)
        secondary_sources = {
            item.source_name for item in positive if item.credibility is Credibility.SECONDARY
        }
        return len(positive) > len(negative) and (has_primary or len(secondary_sources) >= 2)

    def _watch_decision(self, analysis_input: RecommendationInput, reason: str) -> dict[str, object]:
        condition = self._named_condition(analysis_input)
        return {
            "action": Action.WATCH,
            "confidence": Confidence.LOW,
            "risk_level": RiskLevel.HIGH,
            "rationale": [f"Safety downgrade: {reason}.", f"Monitor {condition}."],
            "trigger": f"Trigger: verify {condition} before reconsidering the research-only view.",
            "observation_or_target": self._observation(analysis_input),
            "invalidation": f"Invalidation: {condition} remains unverified or materially changes.",
        }

    def _downside_decision(
        self, analysis_input: RecommendationInput, trigger_condition: str, invalidation_condition: str
    ) -> dict[str, object]:
        action = Action.REDUCE if analysis_input.stock.holding is not None else Action.AVOID
        return {
            "action": action,
            "confidence": Confidence.MEDIUM,
            "risk_level": RiskLevel.HIGH,
            "rationale": [f"Downside condition detected: {trigger_condition}.", self._observation(analysis_input)],
            "trigger": f"Trigger: {trigger_condition}.",
            "observation_or_target": self._observation(analysis_input),
            "invalidation": f"Invalidation: {invalidation_condition}.",
        }

    def _bullish_decision(self, analysis_input: RecommendationInput) -> dict[str, object]:
        technical = analysis_input.technical
        support = technical.support_20
        resistance = technical.resistance_20
        support_text = f"named 20-day support {support:.2f}" if support is not None else "the named evidence condition"
        resistance_text = (
            f"named 20-day resistance {resistance:.2f}"
            if resistance is not None
            else "the next cited evidence update"
        )
        return {
            "action": Action.BUY_IN_TRANCHES,
            "confidence": Confidence.HIGH,
            "risk_level": self._risk_level(technical.realized_volatility_20),
            "rationale": [
                "Upward trend and RSI below 70 are supported by credible net-positive evidence.",
                f"Use {support_text} and {resistance_text} as conditional reference points.",
            ],
            "trigger": f"Trigger: hold above {support_text} while the cited positive evidence remains valid.",
            "observation_or_target": f"Observation: reassess only if price tests {resistance_text}.",
            "invalidation": f"Invalidation: a completed close below {support_text} or a cited negative event.",
        }

    def _neutral_watch_decision(self, analysis_input: RecommendationInput) -> dict[str, object]:
        return {
            "action": Action.WATCH,
            "confidence": Confidence.MEDIUM,
            "risk_level": self._risk_level(analysis_input.technical.realized_volatility_20),
            "rationale": [
                "Available research does not meet every confirmed bullish rule.",
                self._observation(analysis_input),
            ],
            "trigger": f"Trigger: confirm {self._named_condition(analysis_input)} with trend and RSI evidence.",
            "observation_or_target": self._observation(analysis_input),
            "invalidation": (
                f"Invalidation: a completed close below {self._support_text(analysis_input)} "
                "or a cited negative event."
            ),
        }

    @staticmethod
    def _risk_level(volatility: float | None) -> RiskLevel:
        if volatility is None:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW if volatility < 0.2 else RiskLevel.MEDIUM

    @staticmethod
    def _position_limit(horizon: Horizon, confidence: Confidence) -> str:
        return "≤5%" if confidence is Confidence.LOW else _POSITION_LIMITS[horizon]

    @staticmethod
    def _holding_impact(analysis_input: RecommendationInput) -> str | None:
        holding = analysis_input.stock.holding
        if holding is None:
            return None
        latest_close = Decimal(str(analysis_input.technical.latest_close))
        percentage = ((latest_close - holding.cost_basis) / holding.cost_basis * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return f"Informational return versus cost basis: {percentage:+.2f}%."

    @staticmethod
    def _support_text(analysis_input: RecommendationInput) -> str:
        support = analysis_input.technical.support_20
        return f"named 20-day support {support:.2f}" if support is not None else "the named evidence condition"

    def _observation(self, analysis_input: RecommendationInput) -> str:
        resistance = analysis_input.technical.resistance_20
        if resistance is not None:
            return f"Observation: monitor named 20-day resistance {resistance:.2f}; this is not a price prediction."
        return f"Observation: monitor {self._named_condition(analysis_input)}; this is not a price prediction."

    @staticmethod
    def _named_condition(analysis_input: RecommendationInput) -> str:
        if analysis_input.evidence:
            return f"the cited evidence '{analysis_input.evidence[0].title}'"
        if analysis_input.events:
            return f"the recorded event '{analysis_input.events[0].title}'"
        return "a completed price record and named support/resistance levels"
