from decimal import Decimal, ROUND_HALF_UP
from math import isfinite

from stock_research.domain.enums import (
    Action,
    Confidence,
    Credibility,
    Direction,
    EvidenceCategory,
    EventScope,
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
_RISK_PROFILE_LIMITS = {
    "conservative": {
        Horizon.SHORT: "≤5%",
        Horizon.MEDIUM: "≤10%",
        Horizon.LONG: "≤15%",
    },
    "balanced": _POSITION_LIMITS,
    "aggressive": {
        Horizon.SHORT: "≤15%",
        Horizon.MEDIUM: "≤20%",
        Horizon.LONG: "≤25%",
    },
}
_HORIZON_GUIDANCE = {
    Horizon.SHORT: {
        "review": "未来一至五个已完成交易日",
        "focus": "近期已完成交易日的确认信号",
    },
    Horizon.MEDIUM: {
        "review": "未来数个已完成交易周",
        "focus": "按计划更新的证据与已完成交易日趋势",
    },
    Horizon.LONG: {
        "review": "未来跨多个季度的研究周期",
        "focus": "随时间验证的基本面、行业和政策证据",
    },
}


class RecommendationEngine:
    def recommend(self, analysis_input: RecommendationInput) -> list[Recommendation]:
        decision = self._decision(analysis_input)
        latest_close = analysis_input.technical.latest_close
        holding_impact = (
            self._holding_impact(analysis_input)
            if isfinite(latest_close) and latest_close > 0
            else None
        )
        return [
            Recommendation(
                horizon=horizon,
                position_limit=self._position_limit(
                    horizon, decision[1], self._risk_profile(analysis_input)
                ),
                holding_impact=holding_impact,
                **self._for_horizon(decision[0], horizon),
            )
            for horizon in _HORIZONS
        ]

    def _decision(
        self, analysis_input: RecommendationInput
    ) -> tuple[dict[str, object], Confidence]:
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
            return self._support_downside_decision(
                analysis_input, decision_evidence
            ), Confidence.MEDIUM

        positive_evidence = self._positive_support(decision_evidence)
        if self._is_confirmed_bullish(
            technical.trend, technical.rsi_14, decision_evidence, positive_evidence
        ):
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
            return "已完成交易日的价格数据不可用"
        if volatility is not None and (not isfinite(volatility) or volatility >= _HIGH_VOLATILITY):
            return "20 日已实现波动率偏高或不可用"
        if len(decision_evidence) < 2:
            return "可用的非低可信度本地来源少于两项"
        directions = {
            item.direction for item in decision_evidence if item.direction is not Direction.NEUTRAL
        }
        if Direction.POSITIVE in directions and Direction.NEGATIVE in directions:
            return "非低可信度本地来源的方向相互冲突"
        return None

    @staticmethod
    def _confirmed_negative_event(analysis_input: RecommendationInput) -> EventSignal | None:
        return next(
            (
                event
                for event in analysis_input.events
                if event.direction is Direction.NEGATIVE
                and event.is_confirmed
                and event.scope is EventScope.LOCAL
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

        negative_count = sum(item.direction is Direction.NEGATIVE for item in decision_evidence)
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
            "rationale": [f"安全降级：{reason}。", f"请持续关注{condition}。"],
            "trigger": f"触发条件：在重新评估仅供研究参考的观点前，先核实{condition}。",
            "observation_or_target": self._observation(analysis_input, evidence),
            "invalidation": f"失效条件：{condition}仍未获核实或发生重大变化。",
            **self._citation_fields(evidence),
        }

    def _event_downside_decision(
        self, analysis_input: RecommendationInput, event: EventSignal
    ) -> dict[str, object]:
        action = Action.REDUCE if analysis_input.stock.holding is not None else Action.AVOID
        condition = f"引用事件“{event.citation_title}”"
        return {
            "action": action,
            "confidence": Confidence.HIGH,
            "risk_level": RiskLevel.HIGH,
            "rationale": [
                f"检测到下行条件：{condition}确认了“{event.title}”。",
                self._observation(analysis_input, []),
            ],
            "trigger": f"触发条件：{condition}确认了“{event.title}”。",
            "observation_or_target": self._observation(analysis_input, []),
            "invalidation": f"失效条件：{condition}被有引用的更正披露取代。",
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
                f"检测到下行条件：收盘价跌破命名的 20 日支撑位 {support:.2f}。",
                f"决定性本地来源为{condition}。",
            ],
            "trigger": f"触发条件：收盘价跌破命名的 20 日支撑位 {support:.2f}，同时持续关注{condition}。",
            "observation_or_target": self._observation(analysis_input, evidence),
            "invalidation": (
                f"失效条件：已完成交易日的收盘价重新站上命名的 20 日支撑位 {support:.2f}，"
                f"且{condition}仍然有效。"
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
                f"上升趋势且 RSI 低于 70，得到{condition}支持。",
                f"将{support_text}和{resistance_text}作为条件性参考点。",
            ],
            "trigger": f"触发条件：价格维持在{support_text}上方，且{condition}仍然有效。",
            "observation_or_target": f"观察结论：仅在价格测试{resistance_text}时重新评估。",
            "invalidation": f"失效条件：已完成交易日的收盘价跌破{support_text}，或出现有引用的负面事件。",
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
                "现有研究未满足所有已确认的看涨规则。",
                f"请持续关注{condition}。",
            ],
            "trigger": f"触发条件：以趋势和 RSI 证据确认{condition}。",
            "observation_or_target": self._observation(analysis_input, evidence),
            "invalidation": (
                f"失效条件：已完成交易日的收盘价跌破{self._support_text(analysis_input, evidence)}，"
                "或出现有引用的负面事件。"
            ),
            **self._citation_fields(evidence),
        }

    @staticmethod
    def _risk_level(volatility: float | None) -> RiskLevel:
        if volatility is None or not isfinite(volatility):
            return RiskLevel.MEDIUM
        return RiskLevel.LOW if volatility < 0.2 else RiskLevel.MEDIUM

    @staticmethod
    def _position_limit(horizon: Horizon, confidence: Confidence, risk_profile: str) -> str:
        if confidence is Confidence.LOW:
            return "≤5%"
        return _RISK_PROFILE_LIMITS[risk_profile][horizon]

    @staticmethod
    def _risk_profile(analysis_input: RecommendationInput) -> str:
        holding = analysis_input.stock.holding
        if holding is None or holding.risk_profile is None:
            return "balanced"
        return holding.risk_profile

    @staticmethod
    def _for_horizon(decision: dict[str, object], horizon: Horizon) -> dict[str, object]:
        guidance = _HORIZON_GUIDANCE[horizon]
        return {
            **decision,
            "rationale": [
                *decision["rationale"],
                f"{RecommendationEngine._horizon_name(horizon)}：关注{guidance['focus']}。",
            ],
            "trigger": f"{decision['trigger']} 周期复核：{guidance['review']}。",
            "observation_or_target": (
                f"{decision['observation_or_target']} 周期关注：{guidance['focus']}。"
            ),
            "invalidation": (f"{decision['invalidation']} 周期重新评估：{guidance['review']}。"),
        }

    @staticmethod
    def _holding_impact(analysis_input: RecommendationInput) -> str | None:
        holding = analysis_input.stock.holding
        if holding is None:
            return None
        latest_close = Decimal(str(analysis_input.technical.latest_close))
        percentage = ((latest_close - holding.cost_basis) / holding.cost_basis * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return f"相对成本价的信息性收益：{percentage:+.2f}%。"

    def _support_text(self, analysis_input: RecommendationInput, evidence: list[Evidence]) -> str:
        support = analysis_input.technical.support_20
        return (
            f"命名的 20 日支撑位 {support:.2f}"
            if support is not None
            else self._named_condition(evidence)
        )

    def _resistance_text(
        self, analysis_input: RecommendationInput, evidence: list[Evidence]
    ) -> str:
        resistance = analysis_input.technical.resistance_20
        return (
            f"命名的 20 日阻力位 {resistance:.2f}"
            if resistance is not None
            else self._named_condition(evidence)
        )

    def _observation(self, analysis_input: RecommendationInput, evidence: list[Evidence]) -> str:
        resistance = analysis_input.technical.resistance_20
        if resistance is not None:
            return f"观察结论：关注命名的 20 日阻力位 {resistance:.2f}；这不是价格预测。"
        return f"观察结论：关注{self._named_condition(evidence)}；这不是价格预测。"

    @staticmethod
    def _citation_fields(evidence: list[Evidence]) -> dict[str, object]:
        return {
            "evidence_titles": [item.title for item in evidence],
            "citation_urls": [item.url for item in evidence],
        }

    @staticmethod
    def _named_condition(evidence: list[Evidence]) -> str:
        if evidence:
            return f"引用证据“{evidence[0].title}”"
        return "已记录的本地数据条件"

    @staticmethod
    def _horizon_name(horizon: Horizon) -> str:
        return {
            Horizon.SHORT: "短期",
            Horizon.MEDIUM: "中期",
            Horizon.LONG: "长期",
        }[horizon]
