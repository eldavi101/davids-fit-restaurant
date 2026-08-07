"""Technical indicators.

Every function takes a 1-D numpy array (oldest first) and returns an array of the same
length, with ``np.nan`` in positions where there is not yet enough history. Nothing is
back-filled and nothing is padded with a plausible-looking value: an indicator that
cannot be computed says so, and the callers treat NaN as "insufficient history" rather
than as a number.

All smoothing follows the conventional definitions (Wilder for RSI/ATR, seeded EMA for
MACD) so results match standard charting packages.
"""

from __future__ import annotations

import numpy as np


def _empty_like(x: np.ndarray) -> np.ndarray:
    return np.full(len(x), np.nan, dtype=float)


def sma(values: np.ndarray, period: int) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    out = _empty_like(values)
    if period <= 0 or len(values) < period:
        return out
    cumsum = np.cumsum(np.insert(values, 0, 0.0))
    out[period - 1 :] = (cumsum[period:] - cumsum[:-period]) / period
    return out


def ema(values: np.ndarray, period: int) -> np.ndarray:
    """EMA seeded with the SMA of the first ``period`` values."""
    values = np.asarray(values, dtype=float)
    out = _empty_like(values)
    if period <= 0 or len(values) < period:
        return out
    alpha = 2.0 / (period + 1.0)
    prev = float(values[:period].mean())
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def wilder_smooth(values: np.ndarray, period: int, seed_index: int) -> np.ndarray:
    """Wilder's smoothing seeded with the simple mean ending at ``seed_index``."""
    out = _empty_like(values)
    if len(values) <= seed_index or period <= 0:
        return out
    seed_slice = values[seed_index - period + 1 : seed_index + 1]
    if len(seed_slice) < period or np.isnan(seed_slice).any():
        return out
    prev = float(seed_slice.mean())
    out[seed_index] = prev
    for i in range(seed_index + 1, len(values)):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def rsi(values: np.ndarray, period: int = 14) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    out = _empty_like(values)
    if len(values) <= period:
        return out
    delta = np.diff(values, prepend=values[0])
    delta[0] = 0.0
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)

    avg_gain = wilder_smooth(gains, period, period)
    avg_loss = wilder_smooth(losses, period, period)

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_loss > 0, avg_gain / avg_loss, np.inf)
        out = 100.0 - 100.0 / (1.0 + rs)
    out[np.isnan(avg_gain) | np.isnan(avg_loss)] = np.nan
    # Zero losses over the window ⇒ RSI 100 by definition.
    out[(avg_loss == 0) & ~np.isnan(avg_gain)] = 100.0
    return out


def macd(
    values: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = np.asarray(values, dtype=float)
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)
    line = fast_ema - slow_ema

    valid = ~np.isnan(line)
    sig = _empty_like(values)
    if valid.any():
        first = int(np.argmax(valid))
        tail = line[first:]
        tail_signal = ema(tail, signal)
        sig[first:] = tail_signal
    hist = line - sig
    return line, sig, hist


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    out = np.empty(len(close), dtype=float)
    out[0] = high[0] - low[0]
    if len(close) > 1:
        prev_close = close[:-1]
        out[1:] = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close)),
        )
    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    tr = true_range(high, low, close)
    if len(tr) <= period:
        return _empty_like(tr)
    return wilder_smooth(tr, period, period)


def obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    out = np.zeros(len(close), dtype=float)
    if len(close) < 2:
        return out
    direction = np.sign(np.diff(close))
    out[1:] = np.cumsum(direction * volume[1:])
    return out


def roc(values: np.ndarray, period: int) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    out = _empty_like(values)
    if len(values) <= period:
        return out
    base = values[:-period]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[period:] = np.where(base > 0, 100.0 * (values[period:] / base - 1.0), np.nan)
    return out


def rolling_max(values: np.ndarray, period: int) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    out = _empty_like(values)
    if len(values) < period or period <= 0:
        return out
    for i in range(period - 1, len(values)):
        out[i] = values[i - period + 1 : i + 1].max()
    return out


def rolling_min(values: np.ndarray, period: int) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    out = _empty_like(values)
    if len(values) < period or period <= 0:
        return out
    for i in range(period - 1, len(values)):
        out[i] = values[i - period + 1 : i + 1].min()
    return out


def bollinger_width(values: np.ndarray, period: int = 20, num_std: float = 2.0) -> np.ndarray:
    """(upper - lower) / middle — a unitless measure of how tight the range is."""
    values = np.asarray(values, dtype=float)
    out = _empty_like(values)
    if len(values) < period:
        return out
    middle = sma(values, period)
    for i in range(period - 1, len(values)):
        std = values[i - period + 1 : i + 1].std(ddof=0)
        if middle[i] and middle[i] > 0:
            out[i] = (2.0 * num_std * std) / middle[i]
    return out


def log_returns(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    out = _empty_like(values)
    if len(values) < 2:
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = values[1:] / values[:-1]
        out[1:] = np.where(ratio > 0, np.log(ratio), np.nan)
    return out


def simple_returns(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    out = _empty_like(values)
    if len(values) < 2:
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        out[1:] = np.where(values[:-1] > 0, values[1:] / values[:-1] - 1.0, np.nan)
    return out


def realized_volatility(values: np.ndarray, period: int = 20, annualize: bool = True) -> np.ndarray:
    """Annualised standard deviation of daily log returns."""
    rets = log_returns(values)
    out = _empty_like(values)
    factor = np.sqrt(252.0) if annualize else 1.0
    for i in range(period, len(values)):
        window = rets[i - period + 1 : i + 1]
        window = window[~np.isnan(window)]
        if len(window) >= max(2, period // 2):
            out[i] = float(window.std(ddof=1)) * factor
    return out


def downside_volatility(values: np.ndarray, period: int = 20, annualize: bool = True) -> np.ndarray:
    rets = log_returns(values)
    out = _empty_like(values)
    factor = np.sqrt(252.0) if annualize else 1.0
    for i in range(period, len(values)):
        window = rets[i - period + 1 : i + 1]
        window = window[~np.isnan(window)]
        negative = window[window < 0]
        if len(window) >= max(2, period // 2):
            # Downside deviation about zero; an all-up window legitimately scores 0.
            out[i] = float(np.sqrt((negative**2).sum() / len(window))) * factor if len(negative) else 0.0
    return out


def beta(values: np.ndarray, benchmark: np.ndarray, period: int = 252) -> float | None:
    """Beta of the final ``period`` overlapping returns against a benchmark."""
    n = min(len(values), len(benchmark))
    if n < period + 1:
        period = n - 1
    if period < 30:
        return None
    r_stock = simple_returns(np.asarray(values, dtype=float)[-(period + 1) :])[1:]
    r_bench = simple_returns(np.asarray(benchmark, dtype=float)[-(period + 1) :])[1:]
    mask = ~np.isnan(r_stock) & ~np.isnan(r_bench)
    if mask.sum() < 30:
        return None
    var = float(np.var(r_bench[mask], ddof=1))
    if var <= 0:
        return None
    cov = float(np.cov(r_stock[mask], r_bench[mask], ddof=1)[0, 1])
    return cov / var


def max_drawdown(values: np.ndarray, period: int | None = None) -> float:
    """Largest peak-to-trough decline as a negative fraction (e.g. -0.32)."""
    values = np.asarray(values, dtype=float)
    if period is not None:
        values = values[-period:]
    if len(values) < 2:
        return 0.0
    running_peak = np.maximum.accumulate(values)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(running_peak > 0, values / running_peak - 1.0, 0.0)
    return float(np.nanmin(dd))


def slope_annualized(values: np.ndarray, lookback: int) -> float | None:
    """Per-bar compound growth rate of a series over ``lookback`` bars."""
    values = np.asarray(values, dtype=float)
    if len(values) <= lookback:
        return None
    start, end = values[-1 - lookback], values[-1]
    if not np.isfinite(start) or not np.isfinite(end) or start <= 0:
        return None
    return float((end / start) ** (1.0 / lookback) - 1.0)


def overnight_gaps(open_: np.ndarray, close: np.ndarray) -> np.ndarray:
    """Absolute overnight gap as a percentage of the previous close."""
    open_ = np.asarray(open_, dtype=float)
    close = np.asarray(close, dtype=float)
    out = _empty_like(close)
    if len(close) < 2:
        return out
    with np.errstate(divide="ignore", invalid="ignore"):
        out[1:] = np.where(
            close[:-1] > 0, np.abs(100.0 * (open_[1:] / close[:-1] - 1.0)), np.nan
        )
    return out


def relative_strength(values: np.ndarray, benchmark: np.ndarray, period: int) -> float | None:
    """Percentage out/under-performance of the stock versus a benchmark over ``period``.

        RS_n = 100 · ( (C_t / C_{t-n}) / (B_t / B_{t-n}) - 1 )
    """
    values = np.asarray(values, dtype=float)
    benchmark = np.asarray(benchmark, dtype=float)
    if len(values) <= period or len(benchmark) <= period:
        return None
    c0, c1 = values[-1 - period], values[-1]
    b0, b1 = benchmark[-1 - period], benchmark[-1]
    if not all(np.isfinite(v) for v in (c0, c1, b0, b1)) or c0 <= 0 or b0 <= 0:
        return None
    bench_ratio = b1 / b0
    if bench_ratio <= 0:
        return None
    return float(100.0 * ((c1 / c0) / bench_ratio - 1.0))


def rs_line(values: np.ndarray, benchmark: np.ndarray) -> np.ndarray:
    """The stock/benchmark ratio series, aligned on the most recent bars."""
    values = np.asarray(values, dtype=float)
    benchmark = np.asarray(benchmark, dtype=float)
    n = min(len(values), len(benchmark))
    if n == 0:
        return np.array([], dtype=float)
    v, b = values[-n:], benchmark[-n:]
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b > 0, v / b, np.nan)


def percentile_rank(values: np.ndarray, value: float) -> float:
    """Fraction of ``values`` at or below ``value`` — used for BBW tightness ranking."""
    clean = values[~np.isnan(values)]
    if len(clean) == 0 or not np.isfinite(value):
        return 0.5
    return float((clean <= value).sum() / len(clean))


def last_valid(values: np.ndarray) -> float | None:
    """Most recent finite value, or None."""
    if values is None or len(values) == 0:
        return None
    finite = np.isfinite(values)
    if not finite.any():
        return None
    return float(values[np.max(np.flatnonzero(finite))])
