"""Provider selection and failover.

The rest of the system asks the registry for "the market data provider" and never names a
vendor. Switching vendors is an environment change, not a code change (requirement 16).

Failover is *ordered and bounded*: the primary is tried first, then each configured
fallback in turn. If all of them fail the error propagates — the scanner then records a
data-integrity refusal rather than proceeding on partial data (requirement 51).
"""

from __future__ import annotations

from datetime import datetime

from app.core.clock import utc_now
from app.core.config import Settings, get_settings
from app.core.errors import MarketDataUnavailableError, ProviderError
from app.core.logging import get_logger
from app.data.providers.base import MarketDataProvider, ProviderHealth
from app.data.providers.rest import (
    AlphaVantageProvider,
    FinnhubProvider,
    FmpProvider,
    PolygonProvider,
    TwelveDataProvider,
)
from app.data.providers.synthetic import SyntheticProvider
from app.domain.types import Bar, Fundamentals, InstrumentInfo, Quote

log = get_logger(__name__)

PROVIDER_CLASSES: dict[str, type] = {
    "synthetic": SyntheticProvider,
    "polygon": PolygonProvider,
    "finnhub": FinnhubProvider,
    "fmp": FmpProvider,
    "twelvedata": TwelveDataProvider,
    "alphavantage": AlphaVantageProvider,
}


def build_provider(name: str, settings: Settings | None = None) -> MarketDataProvider:
    settings = settings or get_settings()
    key = name.strip().lower()
    cls = PROVIDER_CLASSES.get(key)
    if cls is None:
        raise ProviderError(
            f"unknown market data provider '{name}'",
            {"supported": sorted(PROVIDER_CLASSES)},
        )
    if key == "synthetic":
        return SyntheticProvider()
    return cls(api_key=settings.provider_key(key))  # type: ignore[call-arg]


class ProviderRegistry(MarketDataProvider):
    """A ``MarketDataProvider`` that fronts a primary plus ordered fallbacks."""

    name = "registry"

    def __init__(self, primary: MarketDataProvider, fallbacks: list[MarketDataProvider] | None = None):
        self.primary = primary
        self.fallbacks = fallbacks or []
        self.last_used: str = primary.name
        self.last_error: str | None = None

    @property
    def chain(self) -> list[MarketDataProvider]:
        return [self.primary, *self.fallbacks]

    @property
    def supports_delisted(self) -> bool:  # type: ignore[override]
        return self.primary.supports_delisted

    def _try(self, method: str, *args, allow_empty: bool = False, **kwargs):
        errors: list[str] = []
        for provider in self.chain:
            try:
                result = getattr(provider, method)(*args, **kwargs)
            except ProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
                log.warning("provider_failed", extra={"provider": provider.name, "method": method,
                                                      "error": str(exc)})
                continue
            if result or allow_empty:
                self.last_used = provider.name
                self.last_error = None
                return result
            errors.append(f"{provider.name}: empty result")
        self.last_error = "; ".join(errors)
        raise MarketDataUnavailableError(
            f"all providers failed for {method}", {"errors": errors, "args": [str(a) for a in args]}
        )

    # -- interface ----------------------------------------------------------------------

    def list_universe(self) -> list[InstrumentInfo]:
        return self._try("list_universe")

    def get_bars(self, ticker, timeframe="1d", limit=400, start=None, end=None) -> list[Bar]:
        return self._try("get_bars", ticker, timeframe, limit, start, end)

    def get_quote(self, ticker: str) -> Quote | None:
        try:
            return self._try("get_quote", ticker, allow_empty=True)
        except MarketDataUnavailableError:
            # A missing quote degrades the spread check to "skipped" rather than blocking
            # the whole evaluation — bars are the load-bearing input, quotes are not.
            return None

    def get_fundamentals(self, ticker: str) -> Fundamentals | None:
        for provider in self.chain:
            try:
                result = provider.get_fundamentals(ticker)
            except ProviderError:
                continue
            if result is not None:
                return result
        return None

    def health(self) -> ProviderHealth:
        checks = self.health_all()
        primary = checks[0]
        return ProviderHealth(
            name=f"registry({self.primary.name})",
            ok=any(c.ok for c in checks),
            detail=primary.detail if primary.ok else "; ".join(f"{c.name}={c.detail}" for c in checks),
            checked_at=utc_now(),
        )

    def health_all(self) -> list[ProviderHealth]:
        out: list[ProviderHealth] = []
        for provider in self.chain:
            try:
                out.append(provider.health())
            except Exception as exc:  # noqa: BLE001 - health must never raise
                out.append(ProviderHealth(provider.name, False, str(exc), utc_now()))
        return out

    def close(self) -> None:
        for provider in self.chain:
            if hasattr(provider, "close"):
                provider.close()  # type: ignore[attr-defined]


_registry: ProviderRegistry | None = None


def get_provider(settings: Settings | None = None, force_rebuild: bool = False) -> ProviderRegistry:
    global _registry
    if _registry is not None and not force_rebuild:
        return _registry
    settings = settings or get_settings()
    primary = build_provider(settings.market_data_provider, settings)
    fallbacks: list[MarketDataProvider] = []
    for name in settings.fallback_providers:
        if name.lower() == settings.market_data_provider.lower():
            continue
        try:
            fallbacks.append(build_provider(name, settings))
        except ProviderError as exc:
            log.warning("fallback_unavailable", extra={"provider": name, "error": str(exc)})
    _registry = ProviderRegistry(primary, fallbacks)
    return _registry


def set_provider(registry: ProviderRegistry | None) -> None:
    """Test seam — inject a registry (or clear it) without touching the environment."""
    global _registry
    _registry = registry


def provider_is_synthetic(registry: ProviderRegistry | None = None) -> bool:
    reg = registry or get_provider()
    return reg.primary.name == "synthetic"


def last_bar_age_seconds(bars: list[Bar], now: datetime | None = None) -> float | None:
    if not bars:
        return None
    now = now or utc_now()
    latest = bars[-1].ts
    if latest.tzinfo is None:
        return None
    return (now - latest).total_seconds()
