"""Provider-neutral domain types.

``BarWindow`` is the look-ahead barrier described in BACKTESTING_SPEC.md §2.1. Every
indicator and every engine takes a window rather than a raw array, and the window
physically cannot return data after its cursor. This is why the live scanner and the
backtester can share one implementation without risking future leakage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass(frozen=True, slots=True)
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    raw_close: float | None = None
    split_factor: float = 1.0
    dividend: float = 0.0


@dataclass(frozen=True, slots=True)
class Quote:
    ticker: str
    last: float
    bid: float | None = None
    ask: float | None = None
    ts: datetime | None = None

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask <= 0:
            return None
        return max(0.0, self.ask - self.bid)

    @property
    def spread_bps(self) -> float | None:
        spread = self.spread
        if spread is None:
            return None
        mid = (self.bid + self.ask) / 2.0  # type: ignore[operator]
        if mid <= 0:
            return None
        return 10_000.0 * spread / mid


@dataclass(frozen=True, slots=True)
class InstrumentInfo:
    ticker: str
    company_name: str | None = None
    exchange: str | None = None
    security_type: str = "COMMON"
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    is_etf: bool = False
    is_adr: bool = False
    is_leveraged_etf: bool = False
    is_inverse_etf: bool = False
    is_otc: bool = False


@dataclass(frozen=True, slots=True)
class Fundamentals:
    """Every field optional — providers differ wildly in coverage.

    ``coverage`` (computed) drives the sparse-data guard in the fundamental score:
    a stock with almost no fundamental data gets a flat neutral 50 rather than a
    score assembled from defaults pretending to be information.
    """

    ticker: str
    eps: float | None = None
    revenue: float | None = None
    revenue_growth_yoy: float | None = None
    earnings_growth_yoy: float | None = None
    eps_surprise_pct: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    free_cash_flow: float | None = None
    total_cash: float | None = None
    total_debt: float | None = None
    debt_to_equity: float | None = None
    roe: float | None = None
    pe: float | None = None
    forward_pe: float | None = None
    peg: float | None = None
    institutional_ownership: float | None = None
    short_interest_pct: float | None = None
    next_earnings_date: datetime | None = None

    SCORED_FIELDS: tuple[str, ...] = (
        "revenue_growth_yoy", "earnings_growth_yoy", "eps_surprise_pct",
        "operating_margin", "free_cash_flow", "debt_to_equity", "roe", "peg",
    )

    @property
    def coverage(self) -> float:
        present = sum(1 for f in self.SCORED_FIELDS if getattr(self, f) is not None)
        return present / len(self.SCORED_FIELDS)


class BarSeries:
    """Columnar OHLCV storage backed by numpy arrays, oldest bar first."""

    __slots__ = ("ticker", "ts", "open", "high", "low", "close", "volume")

    def __init__(
        self,
        ticker: str,
        ts: np.ndarray,
        open_: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
    ):
        lengths = {len(ts), len(open_), len(high), len(low), len(close), len(volume)}
        if len(lengths) != 1:
            raise ValueError(f"ragged bar series for {ticker}: {lengths}")
        self.ticker = ticker
        self.ts = ts
        self.open = np.asarray(open_, dtype=float)
        self.high = np.asarray(high, dtype=float)
        self.low = np.asarray(low, dtype=float)
        self.close = np.asarray(close, dtype=float)
        self.volume = np.asarray(volume, dtype=float)

    def __len__(self) -> int:
        return len(self.close)

    @classmethod
    def from_bars(cls, ticker: str, bars: list[Bar]) -> BarSeries:
        ordered = sorted(bars, key=lambda b: b.ts)
        return cls(
            ticker,
            np.array([b.ts for b in ordered], dtype=object),
            np.array([b.open for b in ordered], dtype=float),
            np.array([b.high for b in ordered], dtype=float),
            np.array([b.low for b in ordered], dtype=float),
            np.array([b.close for b in ordered], dtype=float),
            np.array([b.volume for b in ordered], dtype=float),
        )

    def window(self, t: int = -1) -> BarWindow:
        """A window whose cursor sits on bar ``t`` (negative indexes from the end)."""
        if t < 0:
            t = len(self) + t
        return BarWindow(self, t)

    def bar(self, t: int) -> Bar:
        return Bar(
            ts=self.ts[t],
            open=float(self.open[t]),
            high=float(self.high[t]),
            low=float(self.low[t]),
            close=float(self.close[t]),
            volume=float(self.volume[t]),
        )


class BarWindow:
    """A read-only view of a ``BarSeries`` up to and including bar ``t``.

    There is no method on this class that can return data after ``t``. Anything wanting
    a later bar must be handed a different window, which is a deliberate friction: it
    makes look-ahead a visible, reviewable act rather than an accidental slice.
    """

    __slots__ = ("_series", "_t")

    def __init__(self, series: BarSeries, t: int):
        if not 0 <= t < len(series):
            raise IndexError(f"cursor {t} outside series of length {len(series)}")
        self._series = series
        self._t = t

    # -- identity ----------------------------------------------------------------------
    @property
    def ticker(self) -> str:
        return self._series.ticker

    @property
    def t(self) -> int:
        return self._t

    def __len__(self) -> int:
        """Number of bars visible — never the length of the underlying series."""
        return self._t + 1

    # -- columns (always truncated at the cursor) --------------------------------------
    @property
    def open(self) -> np.ndarray:
        return self._series.open[: self._t + 1]

    @property
    def high(self) -> np.ndarray:
        return self._series.high[: self._t + 1]

    @property
    def low(self) -> np.ndarray:
        return self._series.low[: self._t + 1]

    @property
    def close(self) -> np.ndarray:
        return self._series.close[: self._t + 1]

    @property
    def volume(self) -> np.ndarray:
        return self._series.volume[: self._t + 1]

    @property
    def ts(self) -> np.ndarray:
        return self._series.ts[: self._t + 1]

    # -- convenience -------------------------------------------------------------------
    @property
    def last_close(self) -> float:
        return float(self._series.close[self._t])

    @property
    def last_ts(self) -> datetime:
        return self._series.ts[self._t]

    def current_bar(self) -> Bar:
        return self._series.bar(self._t)

    def shifted(self, back: int) -> BarWindow:
        """A window ``back`` bars earlier — used for 'as of the previous close' logic."""
        return BarWindow(self._series, self._t - back)

    def truncated_copy(self) -> BarSeries:
        """A standalone series containing only the visible bars.

        Used by the no-lookahead test: indicators computed on this copy must equal
        indicators computed on the window, proving nothing peeked past the cursor.
        """
        return BarSeries(
            self._series.ticker,
            self.ts.copy(),
            self.open.copy(),
            self.high.copy(),
            self.low.copy(),
            self.close.copy(),
            self.volume.copy(),
        )


@dataclass
class MarketContext:
    """Everything a per-stock evaluation needs about the wider market.

    Passing this explicitly (instead of letting scorers fetch benchmarks themselves)
    keeps the domain layer pure and makes backtests trivially reproducible.
    """

    benchmark: BarWindow | None = None
    sector_windows: dict[str, BarWindow] = field(default_factory=dict)
    secondary: dict[str, BarWindow] = field(default_factory=dict)
    volatility_level: float | None = None
    as_of: datetime | None = None
