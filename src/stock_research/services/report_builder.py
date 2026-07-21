from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pandas as pd

from stock_research.domain.enums import (
    Action,
    Confidence,
    Horizon,
    Market,
    RiskLevel,
    RunStatus,
)
from stock_research.domain.models import (
    DailyReport,
    DailyRunRequest,
    MarketStatus,
    MarketSession,
    PreviousDayPerformance,
    Recommendation,
    RecommendationInput,
    StockAnalysis,
    StockConfig,
    StockResearchInput,
)
from stock_research.services.evidence import EvidenceService
from stock_research.services.indicators import calculate_technical_snapshot
from stock_research.services.market_data import MarketDataProvider, MarketDataUnavailable
from stock_research.services.recommendations import RecommendationEngine
from stock_research.services.sessions import CompletedSessionCalendar, MarketSessionCalendar


class ReportBuilder:
    def __init__(
        self,
        evidence_service: EvidenceService | None = None,
        recommendation_engine: RecommendationEngine | None = None,
        session_calendar: CompletedSessionCalendar | None = None,
    ) -> None:
        self._evidence_service = evidence_service or EvidenceService()
        self._recommendation_engine = recommendation_engine or RecommendationEngine()
        self._session_calendar = session_calendar or MarketSessionCalendar()

    def build(
        self,
        request: DailyRunRequest,
        stocks: Sequence[StockConfig],
        market_data: MarketDataProvider,
    ) -> DailyReport:
        analyses: list[StockAnalysis] = []
        warnings: list[str] = []
        research_by_symbol = self._group_research(request.research_inputs)

        for stock in stocks:
            matching = research_by_symbol.get(stock.symbol, [])
            if len(matching) != 1:
                gap = (
                    f"{stock.symbol}: expected exactly one research input; "
                    f"received {len(matching)}."
                )
                warnings.append(gap)
                analyses.append(self._gap_analysis(stock, gap))
                continue

            research = matching[0]
            if not research.evidence:
                gap = f"{stock.symbol}: research input has zero cited sources; data gap retained."
                warnings.append(gap)
                analysis = self._build_zero_source(stock, research, market_data, gap, request)
                analyses.append(analysis)
                warnings.extend(item for item in analysis.data_gaps if item != gap)
                continue

            try:
                bars = market_data.fetch_daily_bars(stock, request.report_date)
            except MarketDataUnavailable as error:
                gap = f"{stock.symbol}: price data unavailable ({error})."
                warnings.append(gap)
                analyses.append(self._gap_analysis(stock, gap, research=research))
                continue

            evidence = self._evidence_service.validate_and_deduplicate(research.evidence)
            research = research.model_copy(update={"evidence": evidence})
            technical = calculate_technical_snapshot(bars)
            chronology_gap = self._chronology_gap(
                stock, technical.data_as_of, research.data_as_of, request
            )
            if chronology_gap is not None:
                warnings.append(chronology_gap)
                analyses.append(
                    StockAnalysis(
                        stock=stock,
                        previous_day=self._previous_day(
                            bars, f"No causal attribution: {chronology_gap}"
                        ),
                        technical=technical,
                        research=research,
                        recommendations=self._gap_recommendations(chronology_gap),
                        data_gaps=[chronology_gap],
                    )
                )
                continue
            previous_day = self._previous_day(bars, research.news_summary)
            recommendations = self._recommendation_engine.recommend(
                RecommendationInput(
                    stock=stock,
                    technical=technical,
                    evidence=evidence,
                    events=research.events,
                )
            )
            analyses.append(
                StockAnalysis(
                    stock=stock,
                    previous_day=previous_day,
                    technical=technical,
                    research=research,
                    recommendations=recommendations,
                )
            )

        status = RunStatus.SUCCESS if not warnings else RunStatus.PARTIAL
        return DailyReport(
            report_date=request.report_date,
            generated_at=request.generated_at,
            run_status=status,
            market_statuses=self._market_statuses(stocks, analyses, request),
            global_risks=self._global_risks(analyses),
            run_warnings=warnings,
            analyses=analyses,
        )

    @staticmethod
    def _group_research(
        inputs: Sequence[StockResearchInput],
    ) -> dict[str, list[StockResearchInput]]:
        grouped: dict[str, list[StockResearchInput]] = {}
        for research in inputs:
            grouped.setdefault(research.symbol, []).append(research)
        return grouped

    def _build_zero_source(
        self,
        stock: StockConfig,
        research: StockResearchInput,
        market_data: MarketDataProvider,
        gap: str,
        request: DailyRunRequest,
    ) -> StockAnalysis:
        try:
            bars = market_data.fetch_daily_bars(stock, request.report_date)
        except MarketDataUnavailable as error:
            combined_gap = f"{gap} Price data unavailable ({error})."
            return self._gap_analysis(stock, combined_gap, research=research)
        technical = calculate_technical_snapshot(bars)
        chronology_gap = self._chronology_gap(
            stock, technical.data_as_of, research.data_as_of, request
        )
        gaps = [gap]
        reason = research.news_summary
        if chronology_gap is not None:
            gaps.append(chronology_gap)
            reason = f"No causal attribution: {chronology_gap}"
        return StockAnalysis(
            stock=stock,
            previous_day=self._previous_day(bars, reason),
            technical=technical,
            research=research,
            recommendations=self._gap_recommendations(gap),
            data_gaps=gaps,
        )

    @staticmethod
    def _gap_analysis(
        stock: StockConfig,
        gap: str,
        *,
        research: StockResearchInput | None = None,
    ) -> StockAnalysis:
        return StockAnalysis(
            stock=stock,
            research=research,
            recommendations=ReportBuilder._gap_recommendations(gap),
            data_gaps=[gap],
        )

    @staticmethod
    def _gap_recommendations(gap: str) -> list[Recommendation]:
        return [
            Recommendation(
                horizon=horizon,
                action=Action.WATCH,
                confidence=Confidence.LOW,
                risk_level=RiskLevel.HIGH,
                rationale=[f"Data-gap fallback: {gap}"],
                trigger="Trigger: obtain and validate the missing local data before reassessment.",
                observation_or_target="Observation only: no price target is produced for incomplete data.",
                invalidation="Invalidation: the missing data remains unavailable or cannot be verified.",
                position_limit="≤0%",
                evidence_titles=[],
                citation_urls=[],
            )
            for horizon in (Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG)
        ]

    @staticmethod
    def _previous_day(bars: pd.DataFrame, reason: str) -> PreviousDayPerformance:
        frame = bars.copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        for column in ("close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["date", "close", "volume"]).sort_values("date")
        latest = frame.iloc[-1]
        prior = frame.iloc[-2] if len(frame) > 1 else None
        prior_close = None if prior is None else float(prior["close"])
        prior_volume = None if prior is None else float(prior["volume"])
        close = float(latest["close"])
        volume = float(latest["volume"])
        change = 0.0 if prior_close is None else close - prior_close
        return PreviousDayPerformance(
            data_as_of=latest["date"].date(),
            close=close,
            previous_close=prior_close,
            change=change,
            change_percent=ReportBuilder._percent_change(close, prior_close),
            volume=volume,
            previous_volume=prior_volume,
            volume_change_percent=ReportBuilder._percent_change(volume, prior_volume),
            reason=reason,
        )

    def _chronology_gap(
        self,
        stock: StockConfig,
        technical_date: date,
        research_date: date,
        request: DailyRunRequest,
    ) -> str | None:
        expected_date = self._expected_session(request, stock.market)
        if expected_date is None:
            return f"{stock.symbol}: completed-session status is unavailable for {request.report_date}."
        if technical_date != research_date:
            return (
                f"{stock.symbol}: date mismatch; technical date {technical_date} does not equal "
                f"research date {research_date}; expected completed session {expected_date}."
            )
        if technical_date != expected_date:
            return (
                f"{stock.symbol}: stale data; technical and research dates are {technical_date}; "
                f"expected completed session {expected_date} before report date {request.report_date}."
            )
        return None

    def _expected_session(self, request: DailyRunRequest, market: Market) -> date | None:
        metadata = self._request_session(request, market)
        if metadata is not None:
            return metadata.completed_session
        return self._session_calendar.latest_completed_session(market, request.report_date)

    @staticmethod
    def _request_session(request: DailyRunRequest, market: Market) -> MarketSession | None:
        return next((item for item in request.market_sessions if item.market is market), None)

    @staticmethod
    def _percent_change(current: float, previous: float | None) -> float | None:
        if previous is None or previous == 0:
            return None
        return (current - previous) / previous * 100

    def _market_statuses(
        self,
        stocks: Sequence[StockConfig],
        analyses: Sequence[StockAnalysis],
        request: DailyRunRequest,
    ) -> list[MarketStatus]:
        statuses: list[MarketStatus] = []
        for market in (Market.A_SHARE, Market.HONG_KONG):
            symbols = {stock.symbol for stock in stocks if stock.market is market}
            if not symbols:
                continue
            matching = [analysis for analysis in analyses if analysis.stock.symbol in symbols]
            observed = [analysis for analysis in matching if analysis.technical is not None]
            metadata = self._request_session(request, market)
            expected_date = self._expected_session(request, market)
            available = [
                analysis
                for analysis in observed
                if expected_date is not None
                and analysis.technical is not None
                and analysis.research is not None
                and analysis.technical.data_as_of == expected_date
                and analysis.research.data_as_of == expected_date
            ]
            if metadata is not None and metadata.is_closed and len(available) == len(symbols):
                state = "closed"
                message = (
                    f"Market was closed on report date {request.report_date}; prior completed session "
                    "data is current for all configured stocks."
                )
            elif len(available) == len(symbols):
                state = "available"
                message = "Completed session data is current for all configured stocks."
            elif available:
                state = "partial"
                message = "Completed session data is current for only part of this market."
            else:
                state = "unavailable"
                message = "Completed session data is unavailable or stale for configured stocks."
            dates = [analysis.technical.data_as_of for analysis in observed if analysis.technical]
            statuses.append(
                MarketStatus(
                    market=market,
                    data_as_of=max(dates) if dates else None,
                    status=state,
                    message=message,
                )
            )
        return statuses

    @staticmethod
    def _global_risks(analyses: Sequence[StockAnalysis]) -> list[str]:
        risks: list[str] = []
        for analysis in analyses:
            if analysis.research is None:
                continue
            risk = analysis.research.international_summary
            if risk not in risks:
                risks.append(risk)
        return risks
