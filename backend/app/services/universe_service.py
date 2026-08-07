"""Universe refresh: pull the provider's symbol list, apply eligibility, persist.

Instruments are **never deleted**. A symbol that disappears from the provider's list is
marked ``delisted`` with a timestamp, which is what lets the backtester reconstruct the
universe as it was on a past date instead of as it is today (survivorship bias,
BACKTESTING_SPEC §2.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import Settings, StrategyConfig, get_settings, get_strategy
from app.core.errors import MarketDataUnavailableError
from app.core.logging import get_logger, payload
from app.data.providers.registry import ProviderRegistry, get_provider
from app.data.universe import BENCHMARK_SYMBOLS, LiquidityFacts, check_eligibility
from app.db.models import Instrument
from app.services.market_data import MarketDataService

log = get_logger(__name__)


@dataclass
class UniverseRefreshResult:
    total_symbols: int = 0
    created: int = 0
    updated: int = 0
    eligible: int = 0
    delisted: int = 0
    exclusion_reasons: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total_symbols": self.total_symbols,
            "created": self.created,
            "updated": self.updated,
            "eligible": self.eligible,
            "delisted": self.delisted,
            "exclusion_reasons": self.exclusion_reasons,
            "errors": self.errors[:20],
        }


class UniverseService:
    def __init__(
        self,
        provider: ProviderRegistry | None = None,
        cfg: StrategyConfig | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.cfg = cfg or get_strategy()
        self.provider = provider or get_provider()
        self.market_data = MarketDataService(self.provider, self.settings)

    def refresh(
        self,
        session: Session,
        max_symbols: int | None = None,
        compute_liquidity: bool = True,
    ) -> UniverseRefreshResult:
        result = UniverseRefreshResult()
        infos = self.provider.list_universe()
        if max_symbols:
            infos = infos[:max_symbols]
        result.total_symbols = len(infos)
        seen: set[str] = set()

        for info in infos:
            ticker = info.ticker.upper()
            seen.add(ticker)
            instrument = session.execute(
                select(Instrument).where(Instrument.ticker == ticker)
            ).scalar_one_or_none()

            facts = LiquidityFacts(market_cap=info.market_cap)
            if compute_liquidity:
                facts = self._liquidity(ticker, info.market_cap, result)

            eligibility = check_eligibility(info, facts, self.cfg.universe)
            # Benchmarks and sector ETFs must always be present for the regime engine, so
            # they are stored regardless of the tradability rules; they simply are not
            # marked eligible unless they genuinely pass.
            is_benchmark = ticker in BENCHMARK_SYMBOLS

            if instrument is None:
                instrument = Instrument(ticker=ticker, first_seen_utc=utc_now())
                session.add(instrument)
                result.created += 1
            else:
                result.updated += 1

            instrument.company_name = info.company_name
            instrument.exchange = info.exchange
            instrument.security_type = info.security_type
            instrument.sector = info.sector
            instrument.industry = info.industry
            instrument.is_etf = info.is_etf
            instrument.is_adr = info.is_adr
            instrument.is_leveraged_etf = info.is_leveraged_etf
            instrument.is_inverse_etf = info.is_inverse_etf
            instrument.is_otc = info.is_otc
            instrument.market_cap = facts.market_cap
            instrument.avg_volume_50d = facts.avg_volume_50d
            instrument.avg_dollar_volume_50d = facts.avg_dollar_volume_50d
            instrument.last_price = facts.price
            instrument.eligible = eligibility.eligible
            instrument.ineligible_reason = eligibility.reason
            instrument.delisted = False
            instrument.delisted_at_utc = None
            instrument.last_seen_utc = utc_now()
            instrument.data_provider = self.provider.last_used
            instrument.updated_at_utc = utc_now()

            if eligibility.eligible:
                result.eligible += 1
            elif not is_benchmark:
                key = (eligibility.reason or "unknown").split("(")[0].strip()
                result.exclusion_reasons[key] = result.exclusion_reasons.get(key, 0) + 1

        # Mark anything the provider no longer lists as delisted — never delete it.
        for instrument in session.execute(
            select(Instrument).where(Instrument.delisted.is_(False))
        ).scalars():
            if instrument.ticker not in seen:
                instrument.delisted = True
                instrument.delisted_at_utc = utc_now()
                instrument.eligible = False
                instrument.ineligible_reason = "no longer listed by the data provider"
                result.delisted += 1

        session.flush()
        log.info("universe_refreshed", extra=payload(result.as_dict()))
        return result

    def _liquidity(self, ticker: str, market_cap: float | None, result: UniverseRefreshResult) -> LiquidityFacts:
        try:
            series = self.market_data.load_series(ticker, limit=60)
        except MarketDataUnavailableError as exc:
            result.errors.append(f"{ticker}: {exc}")
            return LiquidityFacts(market_cap=market_cap)

        if len(series) == 0:
            return LiquidityFacts(market_cap=market_cap)

        tail = min(50, len(series))
        closes = series.close[-tail:]
        volumes = series.volume[-tail:]
        return LiquidityFacts(
            price=float(closes[-1]),
            market_cap=market_cap,
            avg_volume_50d=float(volumes.mean()),
            avg_dollar_volume_50d=float((closes * volumes).mean()),
        )


def eligible_instruments(session: Session) -> list[Instrument]:
    return list(
        session.execute(
            select(Instrument)
            .where(Instrument.eligible.is_(True))
            .where(Instrument.delisted.is_(False))
            .order_by(Instrument.ticker)
        ).scalars()
    )
