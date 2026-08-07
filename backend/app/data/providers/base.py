"""The ``MarketDataProvider`` contract.

Requirement 16: the system must never be permanently welded to one vendor. Every adapter
implements this interface, the registry picks one by configuration and can fail over to
others, and nothing above ``app/data`` knows which vendor produced a bar.

Fidelity is never scraped. The universe comes from licensed market-data providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.domain.types import Bar, Fundamentals, InstrumentInfo, Quote


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    name: str
    ok: bool
    detail: str
    checked_at: datetime


class MarketDataProvider(ABC):
    """Adapters must be safe to call concurrently and must never raise for a merely
    missing symbol — they return ``None``/empty and let the caller decide."""

    name: str = "base"
    #: Whether this provider can supply history for delisted symbols. Drives the
    #: survivorship-bias warning attached to backtest runs.
    supports_delisted: bool = False

    @abstractmethod
    def list_universe(self) -> list[InstrumentInfo]:
        """All symbols the provider can offer, before any eligibility filtering."""

    @abstractmethod
    def get_bars(
        self,
        ticker: str,
        timeframe: str = "1d",
        limit: int = 400,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        """Split/dividend-adjusted bars, oldest first. Empty list when unavailable."""

    @abstractmethod
    def get_quote(self, ticker: str) -> Quote | None:
        """Latest quote, or None when the provider has no quote endpoint/entitlement."""

    def get_fundamentals(self, ticker: str) -> Fundamentals | None:
        """Optional — providers without fundamentals return None and the fundamental
        component score falls back to a flagged neutral 50."""
        return None

    def get_instrument(self, ticker: str) -> InstrumentInfo | None:
        for info in self.list_universe():
            if info.ticker == ticker:
                return info
        return None

    @abstractmethod
    def health(self) -> ProviderHealth:
        """Cheap liveness probe surfaced on ``GET /system/status``."""
