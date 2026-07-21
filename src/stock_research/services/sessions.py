from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import date, timedelta
from typing import Protocol

from stock_research.domain.enums import Market


class CompletedSessionCalendar(Protocol):
    def latest_completed_session(self, market: Market, report_date: date) -> date | None: ...


class MarketSessionCalendar:
    """Deterministic market-session calendar with per-market closure overrides."""

    def __init__(self, closures: Mapping[Market, Collection[date]] | None = None) -> None:
        self._closures = {
            market: frozenset(closed_dates) for market, closed_dates in (closures or {}).items()
        }

    def latest_completed_session(self, market: Market, report_date: date) -> date:
        candidate = report_date - timedelta(days=1)
        closures = self._closures.get(market, frozenset())
        while candidate.weekday() >= 5 or candidate in closures:
            candidate -= timedelta(days=1)
        return candidate
