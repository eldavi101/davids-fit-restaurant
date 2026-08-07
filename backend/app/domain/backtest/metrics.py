"""Performance metrics (BACKTESTING_SPEC.md §5) — shared by backtests and live analytics.

Two rules run through every function here:

* a metric that cannot be computed honestly returns ``None`` rather than a number
  (an infinite profit factor, a Sharpe from 12 observations);
* the observation count travels with the metric, so a caller can never present a
  statistic without knowing how much evidence sits behind it.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

TRADING_DAYS = 252
MIN_RETURN_OBSERVATIONS = 60
LOW_SAMPLE_TRADES = 30


@dataclass
class TradeRecord:
    ticker: str
    entry_ts: object
    exit_ts: object | None
    entry_price: float
    exit_price: float | None
    shares: float
    return_pct: float
    r_multiple: float
    exit_reason: str
    holding_days: int
    max_gain_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    opportunity_score: float | None = None
    market_regime: str | None = None
    slippage_cost: float = 0.0
    spread_cost: float = 0.0
    commission: float = 0.0
    fold: int | None = None
    sample: str | None = None

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.shares


@dataclass
class PerformanceMetrics:
    trades: int = 0
    winners: int = 0
    losers: int = 0
    win_rate: float | None = None
    avg_return_pct: float | None = None
    median_return_pct: float | None = None
    avg_winner_pct: float | None = None
    avg_loser_pct: float | None = None
    best_trade_pct: float | None = None
    worst_trade_pct: float | None = None
    profit_factor: float | None = None
    expectancy_r: float | None = None
    max_drawdown_pct: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    total_return_pct: float | None = None
    cagr: float | None = None
    avg_holding_days: float | None = None
    target_hit_rate: float | None = None
    stop_rate: float | None = None
    benchmark_return_pct: float | None = None
    return_observations: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _safe(value: float | None) -> float | None:
    if value is None:
        return None
    return None if not math.isfinite(value) else float(value)


def max_drawdown_pct(equity: list[float] | np.ndarray) -> float | None:
    equity = np.asarray(equity, dtype=float)
    if len(equity) < 2:
        return None
    peak = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, equity / peak - 1.0, 0.0)
    return float(np.nanmin(dd) * 100.0)


def sharpe_ratio(returns: np.ndarray, rf_daily: float = 0.0) -> float | None:
    returns = np.asarray(returns, dtype=float)
    returns = returns[np.isfinite(returns)]
    if len(returns) < MIN_RETURN_OBSERVATIONS:
        return None
    sd = returns.std(ddof=1)
    if sd == 0:
        return None
    return float((returns.mean() - rf_daily) / sd * math.sqrt(TRADING_DAYS))


def sortino_ratio(returns: np.ndarray, rf_daily: float = 0.0) -> float | None:
    returns = np.asarray(returns, dtype=float)
    returns = returns[np.isfinite(returns)]
    if len(returns) < MIN_RETURN_OBSERVATIONS:
        return None
    downside = returns[returns < 0]
    if len(downside) == 0:
        return None
    dd = math.sqrt((downside**2).sum() / len(returns))
    if dd == 0:
        return None
    return float((returns.mean() - rf_daily) / dd * math.sqrt(TRADING_DAYS))


def profit_factor(trades: list[TradeRecord]) -> float | None:
    gains = sum(t.pnl for t in trades if t.pnl > 0)
    losses = -sum(t.pnl for t in trades if t.pnl < 0)
    if losses <= 0:
        # No losing trades: the ratio is undefined, not "infinitely good".
        return None
    return gains / losses


def compute_metrics(
    trades: list[TradeRecord],
    equity_curve: list[float] | None = None,
    benchmark_curve: list[float] | None = None,
    rf_daily: float = 0.0,
) -> PerformanceMetrics:
    m = PerformanceMetrics(trades=len(trades))
    closed = [t for t in trades if t.exit_price is not None]

    if closed:
        returns = np.array([t.return_pct for t in closed], dtype=float)
        r_multiples = np.array([t.r_multiple for t in closed], dtype=float)
        winners = returns[returns > 0]
        losers = returns[returns <= 0]

        m.winners = int(len(winners))
        m.losers = int(len(losers))
        m.win_rate = _safe(len(winners) / len(returns))
        m.avg_return_pct = _safe(float(returns.mean()))
        m.median_return_pct = _safe(float(np.median(returns)))
        m.avg_winner_pct = _safe(float(winners.mean())) if len(winners) else None
        m.avg_loser_pct = _safe(float(losers.mean())) if len(losers) else None
        m.best_trade_pct = _safe(float(returns.max()))
        m.worst_trade_pct = _safe(float(returns.min()))
        m.profit_factor = _safe(profit_factor(closed))
        m.expectancy_r = _safe(float(r_multiples.mean()))
        m.avg_holding_days = _safe(float(np.mean([t.holding_days for t in closed])))
        m.target_hit_rate = _safe(
            sum(1 for t in closed if t.exit_reason in ("TARGET_1", "TARGET_2")) / len(closed)
        )
        m.stop_rate = _safe(
            sum(1 for t in closed if t.exit_reason in ("STOP_LOSS", "TRAILING_STOP")) / len(closed)
        )
        if len(closed) < LOW_SAMPLE_TRADES:
            m.warnings.append(
                f"low_sample: {len(closed)} closed trades — below the {LOW_SAMPLE_TRADES} "
                "needed to treat these figures as evidence"
            )

    if equity_curve and len(equity_curve) > 1:
        equity = np.asarray(equity_curve, dtype=float)
        daily = np.diff(equity) / equity[:-1]
        daily = daily[np.isfinite(daily)]
        m.return_observations = int(len(daily))
        m.max_drawdown_pct = _safe(max_drawdown_pct(equity))
        m.sharpe = _safe(sharpe_ratio(daily, rf_daily))
        m.sortino = _safe(sortino_ratio(daily, rf_daily))
        if equity[0] > 0:
            m.total_return_pct = _safe(float((equity[-1] / equity[0] - 1.0) * 100.0))
            years = len(equity) / TRADING_DAYS
            if years > 0 and equity[-1] > 0:
                m.cagr = _safe(float(((equity[-1] / equity[0]) ** (1.0 / years) - 1.0) * 100.0))
        if m.sharpe is None and m.return_observations:
            m.warnings.append(
                f"insufficient_observations: {m.return_observations} daily returns — "
                f"Sharpe and Sortino need at least {MIN_RETURN_OBSERVATIONS}"
            )

    if benchmark_curve and len(benchmark_curve) > 1 and benchmark_curve[0] > 0:
        m.benchmark_return_pct = _safe(
            float((benchmark_curve[-1] / benchmark_curve[0] - 1.0) * 100.0)
        )

    return m


def monthly_returns(timestamps: list, equity: list[float]) -> list[dict]:
    """Calendar-month returns of the equity curve, for the analytics heat strip."""
    if not timestamps or len(timestamps) != len(equity):
        return []
    buckets: dict[str, list[float]] = {}
    for ts, value in zip(timestamps, equity, strict=True):
        key = f"{ts.year:04d}-{ts.month:02d}"
        buckets.setdefault(key, []).append(value)
    out: list[dict] = []
    previous_close: float | None = None
    for month in sorted(buckets):
        values = buckets[month]
        start = previous_close if previous_close is not None else values[0]
        end = values[-1]
        out.append(
            {"month": month, "return_pct": round((end / start - 1.0) * 100.0, 4) if start else 0.0}
        )
        previous_close = end
    return out


def return_distribution(trades: list[TradeRecord], bucket_size: float = 5.0) -> list[dict]:
    closed = [t for t in trades if t.exit_price is not None]
    if not closed:
        return []
    counts: dict[int, int] = {}
    for t in closed:
        idx = int(math.floor(t.return_pct / bucket_size))
        counts[idx] = counts.get(idx, 0) + 1
    return [
        {
            "bucket": f"{idx * bucket_size:g}..{(idx + 1) * bucket_size:g}",
            "lower": idx * bucket_size,
            "count": counts[idx],
        }
        for idx in sorted(counts)
    ]
