from decimal import Decimal, ROUND_HALF_UP
from math import isfinite

from stock_research.domain.enums import (
    Action,
    Confidence,
    Credibility,
    Direction,
    EvidenceCategory,
    Horizon,
    RiskLevel,
    Trend,
)
from stock_research.domain.models import Evidence, EventSignal, Recommendation, RecommendationInput


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
        decision_evidence = self._decision_grade_evidence(analysis_input.evidence)
        safety_reason = self._safety_reason(
            technical.latest_close, technical.realized_volatility_20, decision_evidence
        )
        if safety_reason is not None:
            return self._watch_decision(
                analysis_input, safety_reason, decision_evidence or analysis_input.evidence
            ), Confidence.LOW

        negative_event = self._confirmed_negative_event(analysis_input)
        if negative_event is not None:
            return self._event_downside_decision(analysis_input, negative_event), Confidence.HIGH

        support = technical.support_20
        if support is not None and technical.latest_close < support:
            return self._support_downside_decision(analysis_input, decision_evidence), Confidence.MEDIUM

        positive_evidence = self._positive_support(decision_evidence)
        if self._is_confirmed_bullish(technical.trend, technical.rsi_14, decision_evidence, positive_evidence):
            return self._bullish_decision(analysis_input, positive_evidence), Confidence.HIGH

        return self._neutral_watch_decision(analysis_input, decision_evidence), Confidence.MEDIUM

    @staticmethod
    def _decision_grade_evidence(evidence: list[Evidence]) -> list[Evidence]:
        return [
            item
            for item in evidence
            if item.credibility is not Credibility.LOW
            and item.category is not EvidenceCategory.INTERNATIONAL
        ]

    @staticmethod
    def _safety_reason(
        latest_close: float, volatility: float | None, decision_evidence: list[Evidence]
    ) -> str | None:
        if not isfinite(latest_close) or latest_close <= 0:
            return "completed price data is unavailable"
        if volatility is not None and (not isfinite(volatility) or volatility >= _HIGH_VOLATILITY):
            return "20-day realized volatility is high or unavailable"
        if len(decision_evidence) < 2:
            return "fewer than two non-low-credibility local sources are available"
        directions = {item.direction for item in decision_evidence if item.direction is not Direction.NEUTRAL}
        if Direction.POSITIVE in directions and Direction.NEGATIVE in directions:
            return "non-low-credibility local sources have conflicting directions"
        return None

    @staticmethod
    def _confirmed_negative_event(analysis_input: RecommendationInput) -> EventSignal | None:
        return next(
            (
                event
                for event in analysis_input.events
                if event.direction is Direction.NEGATIVE
                and event.is_confirmed
                and event.citation_title is not None
                and event.citation_url is not None
                and analysis_input.stock.symbol in event.symbols
            ),
            None,
        )

    @staticmethod
    def _positive_support(evidence: list[Evidence]) -> list[Evidence]:
        return [item for item in evidence if item.direction is Direction.POSITIVE]

    @staticmethod
    def _is_confirmed_bullish(
        trend: Trend,
        rsi_14: float | None,
        decision_evidence: list[Evidence],
        positive_evidence: list[Evidence],
    ) -> bool:
        if trend is not Trend.UP or rsi_14 is None or rsi_14 >= 70:
            return False

        negative_count = sum(
            item.direction is Direction.NEGATIVE for item in decision_evidence
        )
        has_primary = any(item.credibility is Credibility.PRIMARY for item in positive_evidence)
        secondary_sources = {
            item.source_name
            for item in positive_evidence
            if item.credibility is Credibility.SECONDARY
        }
        return len(positive_evidence) > negative_count and (
            has_primary or len(secondary_sources) >= 2
        )

    def _watch_decision(
        self, analysis_input: RecommendationInput, reason: str, evidence: list[Evidence]
    ) -> dict[str, object]:
        condition = self._named_condition(evidence)
        return {
            "action": Action.WATCH,
            "confidence": Confidence.LOW,
            "risk_level": RiskLevel.HIGH,
            "rationale": [f"Safety downgrade: {reason}.", f"Monitor {condition}."],
            "trigger": f"Trigger: verify {condition} before reconsidering the research-only view.",
            "observation_or_target": self._observation(analysis_input, evidence),
            "invalidation": f"Invalidation: {condition} remains unverified or materially changes.",
            **self._citation_fields(evidence),
        }

    def _event_downside_decision(
        self, analysis_input: RecommendationInput, event: EventSignal
    ) -> dict[str, object]:
        action = Action.REDUCE if analysis_input.stock.holding is not None else Action.AVOID
        condition = f"the cited event '{event.citation_title}'"
        return {
            "action": action,
            "confidence": Confidence.HIGH,
            "risk_level": RiskLevel.HIGH,
            "rationale": [
                f"Downside condition detected: {condition} confirms '{event.title}'.",
                self._observation(analysis_input, []),
            ],
            "trigger": f"Trigger: {condition} confirms '{event.title}'.",
            "observation_or_target": self._observation(analysis_input, []),
            "invalidation": f"Invalidation: {condition} is superseded by a cited corrective disclosure.",
            "evidence_titles": [event.citation_title],
            "citation_urls": [event.citation_url],
        }

    def _support_downside_decision(
        self, analysis_input: RecommendationInput, evidence: list[Evidence]
    ) -> dict[str, object]:
        support = analysis_input.technical.support_20
        action = Action.REDUCE if analysis_input.stock.holding is not None else Action.AVOID
        condition = self._named_condition(evidence)
        return {
            "action": action,
            "confidence": Confidence.MEDIUM,
            "risk_level": RiskLevel.HIGH,
            "rationale": [
                f"Downside condition detected: a close below named 20-day support {support:.2f}.",
                f"The decisive local source is {condition}.",
            ],
            "trigger": f"Trigger: a close below named 20-day support {support:.2f}, with {condition} monitored.",
            "observation_or_target": self._observation(analysis_input, evidence),
            "invalidation": (
                f"Invalidation: a completed close back above named 20-day support {support:.2f} "
                f"and {condition} remains valid."
            ),
            **self._citation_fields(evidence),
        }

    def _bullish_decision(
        self, analysis_input: RecommendationInput, evidence: list[Evidence]
    ) -> dict[str, object]:
        technical = analysis_input.technical
        support_text = self._support_text(analysis_input, evidence)
        resistance_text = self._resistance_text(analysis_input, evidence)
        condition = self._named_condition(evidence)
        return {
            "action": Action.BUY_IN_TRANCHES,
            "confidence": Confidence.HIGH,
            "risk_level": self._risk_level(technical.realized_volatility_20),
            "rationale": [
                f"Upward trend and RSI below 70 are supported by {condition}.",
                f"Use {support_text} and {resistance_text} as conditional reference points.",
            ],
            "trigger": f"Trigger: hold above {support_text} while {condition} remains valid.",
            "observation_or_target": f"Observation: reassess only if price tests {resistance_text}.",
            "invalidation": f"Invalidation: a completed close below {support_text} or a cited negative event.",
            **self._citation_fields(evidence),
        }

    def _neutral_watch_decision(
        self, analysis_input: RecommendationInput, evidence: list[Evidence]
    ) -> dict[str, object]:
        condition = self._named_condition(evidence)
        return {
            "action": Action.WATCH,
            "confidence": Confidence.MEDIUM,
            "risk_level": self._risk_level(analysis_input.technical.realized_volatility_20),
            "rationale": [
                "Available research does not meet every confirmed bullish rule.",
                f"Monitor {condition}.",
            ],
            "trigger": f"Trigger: confirm {condition} with trend and RSI evidence.",
            "observation_or_target": self._observation(analysis_input, evidence),
            "invalidation": (
                f"Invalidation: a completed close below {self._support_text(analysis_input, evidence)} "
                "or a cited negative event."
            ),
            **self._citation_fields(evidence),
        }

    @staticmethod
    def _risk_level(volatility: float | None) -> RiskLevel:
        if volatility is None or not isfinite(volatility):
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

    def _support_text(self, analysis_input: RecommendationInput, evidence: list[Evidence]) -> str:
        support = analysis_input.technical.support_20
        return (
            f"named 20-day support {support:.2f}"
            if support is not None
            else self._named_condition(evidence)
        )

    def _resistance_text(self, analysis_input: RecommendationInput, evidence: list[Evidence]) -> str:
        resistance = analysis_input.technical.resistance_20
        return (
            f"named 20-day resistance {resistance:.2f}"
            if resistance is not None
            else self._named_condition(evidence)
        )

    def _observation(self, analysis_input: RecommendationInput, evidence: list[Evidence]) -> str:
        resistance = analysis_input.technical.resistance_20
        if resistance is not None:
            return f"Observation: monitor named 20-day resistance {resistance:.2f}; this is not a price prediction."
        return f"Observation: monitor {self._named_condition(evidence)}; this is not a price prediction."

    @staticmethod
    def _citation_fields(evidence: list[Evidence]) -> dict[str, object]:
        return {
            "evidence_titles": [item.title for item in evidence],
            "citation_urls": [item.url for item in evidence],
        }

    @staticmethod
    def _named_condition(evidence: list[Evidence]) -> str:
        if evidence:
            return f"the cited evidence '{evidence[0].title}'"
        return "the documented local data condition"
