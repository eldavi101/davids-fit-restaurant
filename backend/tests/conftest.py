"""Shared fixtures.

Price series here are *constructed*, not random: each builder produces a specific,
inspectable market shape (steady uptrend, breakout, breakdown, gap-down) so a test that
fails points at the rule that broke rather than at luck in a random walk.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.core.clock import is_trading_day
from app.core.config import StrategyConfig
from app.domain.types import Bar, BarSeries, MarketContext


def trading_dates(count: int, end: datetime | None = None) -> list[datetime]:
    """``count`` trading-day timestamps ending at ``end`` (default: recent), oldest first."""
    end = end or datetime.now(UTC).replace(hour=20, minute=0, second=0, microsecond=0)
    out: list[datetime] = []
    cursor = end
    while len(out) < count:
        if is_trading_day(cursor.date()):
            out.append(cursor)
        cursor -= timedelta(days=1)
    out.reverse()
    return out


def build_series(
    ticker: str,
    closes: np.ndarray | list[float],
    volumes: np.ndarray | list[float] | None = None,
    intraday_range: float = 0.012,
    end: datetime | None = None,
) -> BarSeries:
    """Wrap a close-price path in a plausible OHLCV series."""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    volumes = (
        np.asarray(volumes, dtype=float) if volumes is not None else np.full(n, 3_000_000.0)
    )
    dates = trading_dates(n, end)

    highs = closes * (1.0 + intraday_range)
    lows = closes * (1.0 - intraday_range)
    opens = np.empty(n)
    opens[0] = closes[0]
    opens[1:] = closes[:-1]
    opens = np.clip(opens, lows, highs)

    return BarSeries.from_bars(
        ticker,
        [
            Bar(
                ts=dates[i],
                open=float(opens[i]),
                high=float(max(highs[i], opens[i], closes[i])),
                low=float(min(lows[i], opens[i], closes[i])),
                close=float(closes[i]),
                volume=float(volumes[i]),
            )
            for i in range(n)
        ],
    )


def uptrend_closes(n: int = 400, start: float = 100.0, daily: float = 0.0022, wobble: float = 0.018) -> np.ndarray:
    """A rising path with realistic pullbacks — deterministic, no randomness.

    Two oscillations of different periods so the series has genuine down days. A perfectly
    monotone ramp would peg RSI near 100, which the momentum score correctly punishes and
    which no real stock looks like.
    """
    t = np.arange(n)
    trend = start * np.exp(daily * t)
    oscillation = wobble * np.sin(t / 9.0) + 0.6 * wobble * np.sin(t / 3.5)
    return trend * (1.0 + oscillation)


def breakout_series(ticker: str = "TESTCO", n: int = 400) -> BarSeries:
    """Steady uptrend, a tight base, then a decisive breakout on heavy volume.

    Shaped to satisfy every BUY rule at once, so gate tests can toggle one input at a time.
    Note the closing sequence must clear the prior bars' *highs*, not just their closes —
    the breakout engine compares against ``max(high)`` excluding the current bar.
    """
    intraday = 0.008
    closes = uptrend_closes(n - 30, wobble=0.003)
    base_level = closes[-1]
    # 25-bar consolidation just under the highs, then a five-bar advance out of the base.
    base = base_level * (1.0 + 0.010 * np.sin(np.arange(25) / 3.0))
    breakout = base_level * np.array([1.018, 1.031, 1.045, 1.059, 1.076])
    path = np.concatenate([closes, base, breakout])

    volumes = np.full(len(path), 4_000_000.0)
    volumes[-5:] = [9_000_000.0, 10_500_000.0, 9_500_000.0, 11_000_000.0, 12_000_000.0]
    return build_series(ticker, path, volumes, intraday_range=intraday)


def benchmark_series(ticker: str = "SPY", n: int = 400, daily: float = 0.0006) -> BarSeries:
    """A benchmark that rises more slowly than the stock, so relative strength is positive."""
    return build_series(ticker, uptrend_closes(n, start=400.0, daily=daily, wobble=0.002),
                        np.full(n, 80_000_000.0))


def bear_series(ticker: str = "SPY", n: int = 400) -> BarSeries:
    """A sustained decline: below a falling SMA200 and deep in drawdown."""
    t = np.arange(n)
    rise = 400.0 * np.exp(0.0012 * np.minimum(t, n // 2))
    peak = rise[n // 2]
    fall = peak * np.exp(-0.0016 * np.maximum(0, t - n // 2))
    closes = np.where(t <= n // 2, rise, fall)
    return build_series(ticker, closes, np.full(n, 80_000_000.0))


@pytest.fixture
def cfg() -> StrategyConfig:
    return StrategyConfig()


@pytest.fixture
def stock() -> BarSeries:
    return breakout_series()


@pytest.fixture
def spy() -> BarSeries:
    return benchmark_series()


@pytest.fixture
def sector() -> BarSeries:
    return benchmark_series("XLK", daily=0.0008)


@pytest.fixture
def context(spy: BarSeries, sector: BarSeries) -> MarketContext:
    return MarketContext(
        benchmark=spy.window(-1),
        sector_windows={"XLK": sector.window(-1)},
        secondary={"QQQ": sector.window(-1)},
    )


@pytest.fixture
def bull_benchmarks(spy: BarSeries) -> dict[str, BarSeries]:
    """SPY plus all eleven sector ETFs in a broad advance — a STRONG_BULL/BULL market."""
    out = {"SPY": spy, "QQQ": benchmark_series("QQQ", daily=0.0009),
           "IWM": benchmark_series("IWM", daily=0.0005)}
    for etf in ("XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"):
        out[etf] = benchmark_series(etf, daily=0.0008)
    return out


@pytest.fixture
def db_session():
    """A fresh in-memory database per test."""
    from app.db.session import get_session_factory, init_db, reset_engine

    reset_engine("sqlite:///:memory:")
    init_db()
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
        reset_engine()
