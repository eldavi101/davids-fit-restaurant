"""Market data orchestration: ingest, cache, and assemble the evaluation context.

Sits between the provider adapters and the domain engines. Responsibilities:

* fetch and persist adjusted bars idempotently;
* build ``BarSeries``/``BarWindow`` objects for scoring;
* assemble the benchmark and sector windows the relative-strength and regime engines need;
* answer freshness questions, which is what gates new BUY signals under requirement 51.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import Settings, StrategyConfig, get_settings
from app.core.errors import InsufficientHistoryError, MarketDataUnavailableError
from app.core.logging import get_logger
from app.data.providers.registry import ProviderRegistry, get_provider
from app.data.universe import BENCHMARK_SYMBOLS, sector_etf_for
from app.db.models import Instrument, MarketPrice
from app.domain.types import Bar, BarSeries, BarWindow, MarketContext

log = get_logger(__name__)


@dataclass
class DataHealth:
    fresh: bool
    last_bar_age_minutes: float | None
    issues: list[str] = field(default_factory=list)


class MarketDataService:
    def __init__(
        self,
        provider: ProviderRegistry | None = None,
        settings: Settings | None = None,
    ):
        self.provider = provider or get_provider()
        self.settings = settings or get_settings()
        self._series_cache: dict[str, BarSeries] = {}

    # -- ingest --------------------------------------------------------------------------

    def fetch_bars(self, ticker: str, limit: int = 600, timeframe: str = "1d") -> list[Bar]:
        return self.provider.get_bars(ticker, timeframe=timeframe, limit=limit)

    def persist_bars(
        self, session: Session, instrument: Instrument, bars: list[Bar], timeframe: str = "1d"
    ) -> int:
        """Idempotent upsert keyed on (instrument, timeframe, ts)."""
        if not bars:
            return 0
        existing = {
            row[0]
            for row in session.execute(
                select(MarketPrice.ts_utc)
                .where(MarketPrice.instrument_id == instrument.id)
                .where(MarketPrice.timeframe == timeframe)
                .where(MarketPrice.ts_utc >= bars[0].ts)
            ).all()
        }
        added = 0
        for bar in bars:
            if bar.ts in existing:
                continue
            session.add(
                MarketPrice(
                    instrument_id=instrument.id,
                    ts_utc=bar.ts,
                    timeframe=timeframe,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    raw_close=bar.raw_close,
                    split_factor=bar.split_factor,
                    dividend=bar.dividend,
                    data_provider=self.provider.last_used,
                )
            )
            added += 1
        return added

    def load_series(
        self,
        ticker: str,
        limit: int = 600,
        use_cache: bool = True,
        timeframe: str = "1d",
    ) -> BarSeries:
        """Provider bars as a ``BarSeries``. Cached per service instance per scan."""
        if use_cache and ticker in self._series_cache:
            return self._series_cache[ticker]
        bars = self.fetch_bars(ticker, limit=limit, timeframe=timeframe)
        if not bars:
            raise MarketDataUnavailableError(f"no bars returned for {ticker}", {"ticker": ticker})
        series = BarSeries.from_bars(ticker, bars)
        self._series_cache[ticker] = series
        return series

    def load_series_from_db(
        self, session: Session, instrument: Instrument, limit: int = 600, timeframe: str = "1d"
    ) -> BarSeries | None:
        rows = list(
            session.execute(
                select(MarketPrice)
                .where(MarketPrice.instrument_id == instrument.id)
                .where(MarketPrice.timeframe == timeframe)
                .order_by(MarketPrice.ts_utc.desc())
                .limit(limit)
            ).scalars()
        )
        if not rows:
            return None
        rows.reverse()
        return BarSeries.from_bars(
            instrument.ticker,
            [
                Bar(ts=r.ts_utc, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume)
                for r in rows
            ],
        )

    # -- context -------------------------------------------------------------------------

    def load_benchmarks(self, limit: int = 600) -> dict[str, BarSeries]:
        """SPY/QQQ/IWM and the sector ETFs. A missing sector ETF degrades that comparison
        to SPY rather than failing the whole scan."""
        out: dict[str, BarSeries] = {}
        for symbol in BENCHMARK_SYMBOLS:
            try:
                out[symbol] = self.load_series(symbol, limit=limit)
            except MarketDataUnavailableError:
                log.warning("benchmark_unavailable", extra={"symbol": symbol})
        return out

    def build_context(
        self,
        benchmarks: dict[str, BarSeries],
        sector: str | None,
        cursor_ts: datetime | None = None,
        volatility_level: float | None = None,
    ) -> MarketContext:
        """Assemble the ``MarketContext`` for one stock evaluation.

        When ``cursor_ts`` is supplied (backtesting) each benchmark window is cut at the
        last bar at or before that timestamp, so the benchmark cannot leak future data
        into a historical evaluation either.
        """

        def window_for(symbol: str) -> BarWindow | None:
            series = benchmarks.get(symbol)
            if series is None or len(series) == 0:
                return None
            if cursor_ts is None:
                return series.window(-1)
            idx = _index_at_or_before(series, cursor_ts)
            return None if idx is None else series.window(idx)

        spy = window_for("SPY")
        sector_symbol = sector_etf_for(sector)
        sector_window = window_for(sector_symbol) or spy

        return MarketContext(
            benchmark=spy,
            sector_windows={sector_symbol: sector_window} if sector_window else {},
            secondary={
                symbol: w
                for symbol in ("QQQ", "IWM")
                if (w := window_for(symbol)) is not None
            },
            volatility_level=volatility_level,
            as_of=cursor_ts or utc_now(),
        )

    # -- freshness ------------------------------------------------------------------------

    def assess_freshness(self, series: BarSeries, cfg: StrategyConfig, now: datetime | None = None) -> DataHealth:
        """Freshness and completeness. Anything here that fails blocks a NEW BUY signal."""
        issues: list[str] = []
        now = now or utc_now()

        if len(series) == 0:
            return DataHealth(False, None, ["no bars"])

        last_ts = series.ts[-1]
        age_minutes: float | None = None
        if isinstance(last_ts, datetime) and last_ts.tzinfo is not None:
            age_minutes = (now - last_ts).total_seconds() / 60.0
            # Daily bars are naturally hours old; the budget is applied against the last
            # session, not against wall-clock, so a weekend does not look like an outage.
            max_age = max(self.settings.max_bar_age_minutes, _session_gap_minutes(now, last_ts))
            if age_minutes > max_age:
                issues.append(f"last bar {age_minutes/60:.1f}h old (budget {max_age/60:.1f}h)")

        if len(series) < cfg.min_bars_required:
            issues.append(f"only {len(series)} bars (need {cfg.min_bars_required})")

        return DataHealth(fresh=not issues, last_bar_age_minutes=age_minutes, issues=issues)

    def require_history(self, series: BarSeries, cfg: StrategyConfig) -> None:
        if len(series) < cfg.min_bars_required:
            raise InsufficientHistoryError(
                f"{series.ticker}: {len(series)} bars available, {cfg.min_bars_required} required",
                {"ticker": series.ticker, "bars": len(series)},
            )


def _index_at_or_before(series: BarSeries, ts: datetime) -> int | None:
    """Last bar index at or before ``ts`` — the backtest's benchmark alignment."""
    for i in range(len(series) - 1, -1, -1):
        bar_ts = series.ts[i]
        if isinstance(bar_ts, datetime) and bar_ts <= ts:
            return i
    return None


def _session_gap_minutes(now: datetime, last_ts: datetime) -> float:
    """Tolerance for weekends and holidays so a closed market is not read as stale data."""
    from app.core.clock import is_trading_day

    gap_days, cursor = 0, now.date()
    while cursor > last_ts.date() and gap_days < 10:
        if not is_trading_day(cursor):
            gap_days += 1
        cursor -= timedelta(days=1)
    # One trading day of tolerance plus a full day per intervening non-trading day.
    return (1 + gap_days) * 24 * 60
