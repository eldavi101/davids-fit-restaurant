"""Fidelity-tradable stock universe (requirement 15).

"Reasonably tradable through Fidelity" is expressed as a set of configurable filters, not
as a hard-coded list — and crucially, **every exclusion records its reason**. A ticker that
drops out of the universe can always be asked why, which matters when a name the user
expects to see is missing.

Fidelity is never contacted or scraped. Eligibility is derived from exchange, security
type and liquidity data supplied by the configured market-data provider.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import StrategyConfig, UniverseConfig
from app.domain.types import InstrumentInfo


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    ticker: str
    eligible: bool
    reason: str | None

    def as_dict(self) -> dict:
        return {"ticker": self.ticker, "eligible": self.eligible, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class LiquidityFacts:
    """Liquidity inputs come from bars, so they are supplied separately from the profile."""

    price: float | None = None
    market_cap: float | None = None
    avg_volume_50d: float | None = None
    avg_dollar_volume_50d: float | None = None


def check_eligibility(
    info: InstrumentInfo,
    facts: LiquidityFacts,
    cfg: UniverseConfig,
) -> EligibilityResult:
    """Apply every universe rule in a fixed order and return the first failure."""
    t = info.ticker

    # --- security class -----------------------------------------------------------------
    if info.is_otc and not cfg.include_otc:
        return EligibilityResult(t, False, "OTC securities excluded")
    if info.is_leveraged_etf and not cfg.include_leveraged_etf:
        return EligibilityResult(t, False, "leveraged ETFs excluded")
    if info.is_inverse_etf and not cfg.include_inverse_etf:
        return EligibilityResult(t, False, "inverse ETFs excluded")
    if info.is_etf and not cfg.include_etf:
        return EligibilityResult(t, False, "ETFs excluded by configuration")
    if info.is_adr and not cfg.include_adr:
        return EligibilityResult(t, False, "ADRs excluded by configuration")
    if not info.is_etf and not info.is_adr and not cfg.include_common:
        return EligibilityResult(t, False, "common stocks excluded by configuration")

    # --- exchange -------------------------------------------------------------------------
    if cfg.allowed_exchanges:
        if info.exchange is None:
            return EligibilityResult(t, False, "exchange unknown")
        if info.exchange not in cfg.allowed_exchanges:
            return EligibilityResult(
                t, False, f"exchange {info.exchange} not in {', '.join(cfg.allowed_exchanges)}"
            )

    # --- price ------------------------------------------------------------------------------
    if facts.price is None:
        return EligibilityResult(t, False, "no price available")
    if facts.price < cfg.min_price:
        # The min-price rule is also what keeps penny stocks out; `include_penny` only
        # loosens it when explicitly enabled.
        if not cfg.include_penny:
            return EligibilityResult(
                t, False, f"price ${facts.price:.2f} below minimum ${cfg.min_price:.2f}"
            )
    if cfg.max_price is not None and facts.price > cfg.max_price:
        return EligibilityResult(
            t, False, f"price ${facts.price:.2f} above maximum ${cfg.max_price:.2f}"
        )

    # --- size and liquidity --------------------------------------------------------------------
    # ETFs legitimately have no market cap; the rule applies to operating companies.
    if not info.is_etf:
        if facts.market_cap is None:
            return EligibilityResult(t, False, "market cap unknown")
        if facts.market_cap < cfg.min_market_cap:
            return EligibilityResult(
                t, False,
                f"market cap ${facts.market_cap/1e6:.0f}M below minimum ${cfg.min_market_cap/1e6:.0f}M",
            )

    if facts.avg_dollar_volume_50d is None:
        return EligibilityResult(t, False, "average dollar volume unknown")
    if facts.avg_dollar_volume_50d < cfg.min_avg_dollar_volume:
        return EligibilityResult(
            t, False,
            f"average dollar volume ${facts.avg_dollar_volume_50d/1e6:.1f}M below "
            f"${cfg.min_avg_dollar_volume/1e6:.0f}M",
        )

    if facts.avg_volume_50d is None:
        return EligibilityResult(t, False, "average share volume unknown")
    if facts.avg_volume_50d < cfg.min_avg_volume:
        return EligibilityResult(
            t, False,
            f"average volume {facts.avg_volume_50d:,.0f} below {cfg.min_avg_volume:,.0f} shares",
        )

    return EligibilityResult(t, True, None)


def filter_universe(
    instruments: list[tuple[InstrumentInfo, LiquidityFacts]],
    cfg: StrategyConfig,
) -> tuple[list[InstrumentInfo], list[EligibilityResult]]:
    """Returns (eligible instruments, full result ledger including exclusions)."""
    results: list[EligibilityResult] = []
    eligible: list[InstrumentInfo] = []
    for info, facts in instruments:
        result = check_eligibility(info, facts, cfg.universe)
        results.append(result)
        if result.eligible:
            eligible.append(info)
    return eligible, results


#: Symbols the regime engine always needs, regardless of tradability filters.
BENCHMARK_SYMBOLS: tuple[str, ...] = (
    "SPY", "QQQ", "IWM",
    "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
)

SECTOR_TO_ETF: dict[str, str] = {
    "Technology": "XLK",
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Financial Services": "XLF",
    "Health Care": "XLV",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Consumer Discretionary": "XLY",
    "Consumer Cyclical": "XLY",
    "Consumer Staples": "XLP",
    "Consumer Defensive": "XLP",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def sector_etf_for(sector: str | None) -> str:
    """Sector ETF used as the relative-strength comparator; SPY when unknown."""
    if not sector:
        return "SPY"
    return SECTOR_TO_ETF.get(sector, "SPY")
