"""One computation pass producing every indicator the engines need.

Scoring, the BUY gate and the SELL engine all read from an ``IndicatorSnapshot`` rather
than recomputing indicators themselves. That guarantees a single alert, its audit record
and any later backtest all describe the same numbers.

The snapshot keeps a few *series* (RSI, MACD histogram, closes, the RS line) because the
SELL engine legitimately needs "compared with three bars ago" style conditions. Those
series are still window-truncated, so they carry no future information.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.domain.indicators import core as ind
from app.domain.types import BarWindow, MarketContext


def _f(value) -> float | None:
    if value is None:
        return None
    v = float(value)
    return v if np.isfinite(v) else None


@dataclass
class IndicatorSnapshot:
    ticker: str
    bars_available: int

    close: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0

    ema9: float | None = None
    ema20: float | None = None
    ema21: float | None = None
    ema50: float | None = None
    sma50: float | None = None
    sma100: float | None = None
    sma200: float | None = None

    sma50_slope: float | None = None
    sma200_slope: float | None = None

    rsi14: float | None = None
    rsi14_prev5: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    macd_hist_prev3: float | None = None

    atr14: float | None = None
    atr_pct: float | None = None
    prev_atr14: float | None = None
    true_range: float | None = None

    obv: float | None = None
    obv_change_20: float | None = None

    roc21: float | None = None
    roc63: float | None = None
    roc126: float | None = None
    roc5: float | None = None

    bb_width: float | None = None
    bb_width_rank: float | None = None

    vol_avg5: float | None = None
    vol_avg20: float | None = None
    vol_avg50: float | None = None
    rel_volume: float | None = None
    dollar_volume_50: float | None = None
    up_volume_ratio: float | None = None

    high_20_prior: float | None = None
    high_50_prior: float | None = None
    high_252_prior: float | None = None
    low_10: float | None = None
    low_20: float | None = None
    low_252: float | None = None
    dist_52w_high_pct: float | None = None

    realized_vol_20: float | None = None
    downside_vol_20: float | None = None
    beta_252: float | None = None
    max_drawdown_252: float | None = None
    recent_drawdown: float | None = None
    avg_gap_pct: float | None = None

    rs_21: float | None = None
    rs_63: float | None = None
    rs_126: float | None = None
    rs_sector_63: float | None = None
    rs_qqq_63: float | None = None
    rs_line_rising_10: bool = False
    rs_line_rising_21: bool = False

    higher_highs_ratio: float | None = None

    # Series retained for multi-bar SELL conditions (all window-truncated).
    close_series: np.ndarray = field(default_factory=lambda: np.array([]))
    rsi_series: np.ndarray = field(default_factory=lambda: np.array([]))
    ema20_series: np.ndarray = field(default_factory=lambda: np.array([]))
    sma50_series: np.ndarray = field(default_factory=lambda: np.array([]))
    rs_line_series: np.ndarray = field(default_factory=lambda: np.array([]))

    def as_dict(self) -> dict:
        """Scalar view for persistence and audit logs (series omitted)."""
        return {
            k: v
            for k, v in self.__dict__.items()
            if not isinstance(v, np.ndarray) and not k.endswith("_series")
        }


def _higher_highs_ratio(high: np.ndarray, low: np.ndarray, window: int = 20, count: int = 3) -> float | None:
    """Fraction of the last ``count`` 20-bar windows making both a higher high and higher low."""
    needed = window * (count + 1)
    if len(high) < needed:
        return None
    hits = 0
    for k in range(count):
        cur_hi = high[len(high) - window * (k + 1) : len(high) - window * k].max()
        cur_lo = low[len(low) - window * (k + 1) : len(low) - window * k].min()
        prev_hi = high[len(high) - window * (k + 2) : len(high) - window * (k + 1)].max()
        prev_lo = low[len(low) - window * (k + 2) : len(low) - window * (k + 1)].min()
        if cur_hi > prev_hi and cur_lo > prev_lo:
            hits += 1
    return hits / count


def compute_snapshot(window: BarWindow, context: MarketContext | None = None) -> IndicatorSnapshot:
    close = window.close
    high = window.high
    low = window.low
    open_ = window.open
    volume = window.volume
    n = len(close)

    snap = IndicatorSnapshot(ticker=window.ticker, bars_available=n)
    if n == 0:
        return snap

    snap.close = float(close[-1])
    snap.open = float(open_[-1])
    snap.high = float(high[-1])
    snap.low = float(low[-1])
    snap.volume = float(volume[-1])
    snap.close_series = close

    # --- moving averages ---------------------------------------------------------------
    ema20_series = ind.ema(close, 20)
    sma50_series = ind.sma(close, 50)
    sma200_series = ind.sma(close, 200)
    snap.ema20_series = ema20_series
    snap.sma50_series = sma50_series

    snap.ema9 = ind.last_valid(ind.ema(close, 9))
    snap.ema20 = ind.last_valid(ema20_series)
    snap.ema21 = ind.last_valid(ind.ema(close, 21))
    snap.ema50 = ind.last_valid(ind.ema(close, 50))
    snap.sma50 = ind.last_valid(sma50_series)
    snap.sma100 = ind.last_valid(ind.sma(close, 100))
    snap.sma200 = ind.last_valid(sma200_series)

    snap.sma50_slope = ind.slope_annualized(sma50_series[~np.isnan(sma50_series)], 20)
    clean200 = sma200_series[~np.isnan(sma200_series)]
    snap.sma200_slope = ind.slope_annualized(clean200, 20)

    # --- momentum ----------------------------------------------------------------------
    rsi_series = ind.rsi(close, 14)
    snap.rsi_series = rsi_series
    snap.rsi14 = ind.last_valid(rsi_series)
    if len(rsi_series) > 5:
        snap.rsi14_prev5 = _f(rsi_series[-6])

    macd_line, macd_sig, macd_hist = ind.macd(close)
    snap.macd = ind.last_valid(macd_line)
    snap.macd_signal = ind.last_valid(macd_sig)
    snap.macd_hist = ind.last_valid(macd_hist)
    if len(macd_hist) > 3:
        snap.macd_hist_prev3 = _f(macd_hist[-4])

    snap.roc5 = ind.last_valid(ind.roc(close, 5))
    snap.roc21 = ind.last_valid(ind.roc(close, 21))
    snap.roc63 = ind.last_valid(ind.roc(close, 63))
    snap.roc126 = ind.last_valid(ind.roc(close, 126))

    # --- volatility / risk ---------------------------------------------------------------
    atr_series = ind.atr(high, low, close, 14)
    snap.atr14 = ind.last_valid(atr_series)
    if len(atr_series) > 1:
        snap.prev_atr14 = _f(atr_series[-2])
    if snap.atr14 and snap.close > 0:
        snap.atr_pct = 100.0 * snap.atr14 / snap.close
    tr = ind.true_range(high, low, close)
    snap.true_range = _f(tr[-1])

    snap.realized_vol_20 = ind.last_valid(ind.realized_volatility(close, 20))
    snap.downside_vol_20 = ind.last_valid(ind.downside_volatility(close, 20))
    snap.max_drawdown_252 = ind.max_drawdown(close, 252)
    high20 = ind.rolling_max(high, 20)
    if np.isfinite(high20[-1]) and high20[-1] > 0:
        snap.recent_drawdown = float(snap.close / high20[-1] - 1.0)
    gaps = ind.overnight_gaps(open_, close)
    tail_gaps = gaps[-60:]
    tail_gaps = tail_gaps[np.isfinite(tail_gaps)]
    snap.avg_gap_pct = float(tail_gaps.mean()) if len(tail_gaps) else None

    # --- volume ---------------------------------------------------------------------------
    snap.obv = ind.last_valid(ind.obv(close, volume))
    obv_series = ind.obv(close, volume)
    if len(obv_series) > 20 and abs(obv_series[-21]) > 0:
        snap.obv_change_20 = float(obv_series[-1] / abs(obv_series[-21]) - np.sign(obv_series[-21]))

    if n >= 5:
        snap.vol_avg5 = float(volume[-5:].mean())
    if n >= 20:
        snap.vol_avg20 = float(volume[-20:].mean())
    if n >= 50:
        snap.vol_avg50 = float(volume[-50:].mean())
        snap.dollar_volume_50 = float((close[-50:] * volume[-50:]).mean())
    if snap.vol_avg50 and snap.vol_avg50 > 0:
        snap.rel_volume = snap.volume / snap.vol_avg50

    if n >= 21:
        deltas = np.diff(close[-21:])
        vols = volume[-20:]
        up = float(vols[deltas > 0].sum())
        down = float(vols[deltas < 0].sum())
        if up + down > 0:
            snap.up_volume_ratio = up / (up + down)

    # --- structure --------------------------------------------------------------------------
    # Prior highs deliberately EXCLUDE the current bar: a "breakout" must exceed the range
    # that existed before today, not a range that includes today's own high.
    if n >= 21:
        snap.high_20_prior = float(high[-21:-1].max())
    if n >= 51:
        snap.high_50_prior = float(high[-51:-1].max())
    if n >= 253:
        snap.high_252_prior = float(high[-253:-1].max())
    if n >= 10:
        snap.low_10 = float(low[-10:].min())
    if n >= 20:
        snap.low_20 = float(low[-20:].min())
    if n >= 252:
        snap.low_252 = float(low[-252:].min())
        high252 = float(high[-252:].max())
        if high252 > 0:
            snap.dist_52w_high_pct = 100.0 * (snap.close / high252 - 1.0)

    bbw_series = ind.bollinger_width(close, 20)
    if len(bbw_series) >= 2 and np.isfinite(bbw_series[-2]):
        snap.bb_width = float(bbw_series[-2])  # tightness of the base BEFORE today's bar
        snap.bb_width_rank = ind.percentile_rank(bbw_series[-127:-1], snap.bb_width)

    snap.higher_highs_ratio = _higher_highs_ratio(high, low)

    # --- relative strength ---------------------------------------------------------------
    if context and context.benchmark is not None:
        bench = context.benchmark.close
        snap.rs_21 = ind.relative_strength(close, bench, 21)
        snap.rs_63 = ind.relative_strength(close, bench, 63)
        snap.rs_126 = ind.relative_strength(close, bench, 126)
        snap.beta_252 = ind.beta(close, bench, 252)

        line = ind.rs_line(close, bench)
        snap.rs_line_series = line
        if len(line) > 21 and np.isfinite(line[-1]):
            snap.rs_line_rising_10 = bool(np.isfinite(line[-11]) and line[-1] > line[-11])
            snap.rs_line_rising_21 = bool(
                snap.rs_line_rising_10 and np.isfinite(line[-22]) and line[-11] > line[-22]
            )

        sector_window = None
        if context.sector_windows:
            sector_window = next(iter(context.sector_windows.values()))
        if sector_window is not None:
            snap.rs_sector_63 = ind.relative_strength(close, sector_window.close, 63)
        qqq = context.secondary.get("QQQ") if context.secondary else None
        if qqq is not None:
            snap.rs_qqq_63 = ind.relative_strength(close, qqq.close, 63)

    return snap
