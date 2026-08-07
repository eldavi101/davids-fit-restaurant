"""The seven component scores.

Each function implements exactly the table in STRATEGY_SPEC.md for its component and
returns a ``ComponentScore`` carrying not just the number but every sub-score and its
weighted contribution. That breakdown is what the Alert Detail screen renders and what
``audit_logs`` stores, so no score in this system is a black box.

Convention: every sub-score is in [0, 1]; the component score is 100 × Σ wᵢ·sᵢ, so every
component is in [0, 100] and higher is always better — including risk, where higher means
*better risk quality*.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import StrategyConfig
from app.domain.indicators.snapshot import IndicatorSnapshot
from app.domain.types import Fundamentals

# --------------------------------------------------------------------------------------
# Shape helpers
# --------------------------------------------------------------------------------------


def clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ramp(x: float | None, lo: float, hi: float, default: float = 0.0) -> float:
    """Linear 0→1 ramp between lo and hi. ``None`` yields ``default``."""
    if x is None:
        return default
    if hi == lo:
        return 1.0 if x >= hi else 0.0
    return clip((x - lo) / (hi - lo))


def ramp_inv(x: float | None, lo: float, hi: float, default: float = 0.0) -> float:
    """Linear 1→0 ramp: full marks at or below ``lo``, zero at or above ``hi``."""
    if x is None:
        return default
    return 1.0 - ramp(x, lo, hi, default=1.0 - default)


def trapezoid(
    x: float | None,
    rise_start: float,
    plateau_start: float,
    plateau_end: float,
    fall_end: float,
    fall_floor: float = 0.0,
    default: float = 0.0,
) -> float:
    """Rises, holds at 1, then decays to ``fall_floor`` — for "good in a band" inputs."""
    if x is None:
        return default
    if x <= rise_start:
        return 0.0
    if x < plateau_start:
        return clip((x - rise_start) / (plateau_start - rise_start))
    if x <= plateau_end:
        return 1.0
    if x < fall_end:
        span = (x - plateau_end) / (fall_end - plateau_end)
        return clip(1.0 - span * (1.0 - fall_floor), fall_floor, 1.0)
    return fall_floor


@dataclass
class ComponentScore:
    name: str
    score: float
    subscores: dict[str, float] = field(default_factory=dict)
    contributions: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 2),
            "subscores": {k: round(v, 4) for k, v in self.subscores.items()},
            "contributions": {k: round(v, 3) for k, v in self.contributions.items()},
            "notes": self.notes,
        }


def _combine(name: str, parts: dict[str, tuple[float, float]], notes: list[str] | None = None) -> ComponentScore:
    """``parts`` maps sub-score name → (value in [0,1], weight)."""
    subscores = {k: v for k, (v, _) in parts.items()}
    contributions = {k: 100.0 * v * w for k, (v, w) in parts.items()}
    total = sum(contributions.values())
    return ComponentScore(
        name=name,
        score=clip(total, 0.0, 100.0),
        subscores=subscores,
        contributions=contributions,
        notes=notes or [],
    )


# --------------------------------------------------------------------------------------
# Trend
# --------------------------------------------------------------------------------------


def trend_score(s: IndicatorSnapshot, cfg: StrategyConfig) -> ComponentScore:
    c = s.close
    above20 = 1.0 if (s.ema20 is not None and c > s.ema20) else 0.0
    above50 = 1.0 if (s.sma50 is not None and c > s.sma50) else 0.0
    above200 = 1.0 if (s.sma200 is not None and c > s.sma200) else 0.0

    if s.ema20 is not None and s.sma50 is not None and s.sma200 is not None:
        if s.ema20 > s.sma50 > s.sma200:
            stacking = 1.0
        elif s.ema20 > s.sma50:
            stacking = 0.5
        else:
            stacking = 0.0
    else:
        stacking = 0.0

    return _combine(
        "trend",
        {
            "above_ema20": (above20, 0.12),
            "above_sma50": (above50, 0.12),
            "above_sma200": (above200, 0.16),
            "ma_stacking": (stacking, 0.14),
            "sma50_slope": (ramp(s.sma50_slope, 0.0, 0.0015), 0.12),
            "sma200_slope": (ramp(s.sma200_slope, 0.0, 0.0008), 0.10),
            "higher_highs": (s.higher_highs_ratio if s.higher_highs_ratio is not None else 0.0, 0.12),
            "near_52w_high": (
                ramp_inv(-s.dist_52w_high_pct if s.dist_52w_high_pct is not None else None, 3.0, 30.0),
                0.12,
            ),
        },
    )


# --------------------------------------------------------------------------------------
# Momentum
# --------------------------------------------------------------------------------------


def momentum_score(s: IndicatorSnapshot, cfg: StrategyConfig) -> ComponentScore:
    # Deliberately non-monotone in RSI: an extended stock loses momentum credit rather
    # than earning more of it (STRATEGY_SPEC §3).
    rsi_level = trapezoid(s.rsi14, rise_start=40.0, plateau_start=55.0, plateau_end=68.0,
                          fall_end=85.0, fall_floor=0.10)

    rsi_direction = 0.0
    if s.rsi14 is not None and s.rsi14_prev5 is not None:
        rsi_direction = ramp(s.rsi14 - s.rsi14_prev5, -2.0, 6.0)

    if s.macd is not None and s.macd_signal is not None:
        if s.macd > s.macd_signal and s.macd > 0:
            macd_posture = 1.0
        elif s.macd > s.macd_signal:
            macd_posture = 0.5
        else:
            macd_posture = 0.0
    else:
        macd_posture = 0.0

    hist_rising = 0.0
    if s.macd_hist is not None and s.macd_hist_prev3 is not None:
        scale = max(0.05, 0.5 * (s.atr_pct or 2.0) / 100.0 * s.close)
        hist_rising = ramp(s.macd_hist - s.macd_hist_prev3, 0.0, scale)

    acceleration = 0.0
    if s.roc21 is not None and s.roc63 is not None:
        acceleration = ramp(s.roc21 / 21.0 - s.roc63 / 63.0, 0.0, 0.15)

    return _combine(
        "momentum",
        {
            "rsi_level": (rsi_level, 0.18),
            "rsi_direction": (rsi_direction, 0.10),
            "macd_posture": (macd_posture, 0.16),
            "macd_hist_rising": (hist_rising, 0.10),
            "return_1m": (ramp(s.roc21, 0.0, 12.0), 0.14),
            "return_3m": (ramp(s.roc63, 0.0, 25.0), 0.14),
            "return_6m": (ramp(s.roc126, 0.0, 40.0), 0.08),
            "acceleration": (acceleration, 0.10),
        },
    )


# --------------------------------------------------------------------------------------
# Volume
# --------------------------------------------------------------------------------------


def volume_score(s: IndicatorSnapshot, cfg: StrategyConfig) -> ComponentScore:
    acceleration = 0.0
    if s.vol_avg5 and s.vol_avg50 and s.vol_avg50 > 0:
        acceleration = ramp(s.vol_avg5 / s.vol_avg50, 1.0, 2.0)

    obv_slope = 0.5 if s.obv_change_20 is None else ramp(s.obv_change_20, 0.0, 0.10)

    return _combine(
        "volume",
        {
            "relative_volume": (ramp(s.rel_volume, 1.0, 2.5), 0.28),
            "volume_acceleration": (acceleration, 0.20),
            "price_volume_confirmation": (ramp(s.up_volume_ratio, 0.45, 0.70), 0.22),
            "obv_slope": (obv_slope, 0.20),
            "liquidity": (ramp(s.dollar_volume_50, 10e6, 100e6), 0.10),
        },
    )


# --------------------------------------------------------------------------------------
# Breakout
# --------------------------------------------------------------------------------------

BREAKOUT_PRECEDENCE = (
    "FIFTY_TWO_WEEK_HIGH",
    "FIFTY_DAY",
    "TWENTY_DAY",
    "CONSOLIDATION",
    "RETEST",
    "NONE",
)


def _retest_detected(s: IndicatorSnapshot) -> float:
    """Broke out, pulled back to the breakout level, and closed back above it."""
    closes = s.close_series
    if len(closes) < 32 or s.high_20_prior is None or s.atr14 is None:
        return 0.0
    level = s.high_20_prior
    recent = closes[-10:]
    broke = bool((recent > level).any())
    pulled_back = bool((abs(recent - level) <= 0.5 * s.atr14).any())
    back_above = s.close > level
    return 1.0 if (broke and pulled_back and back_above) else 0.0


def breakout_score(s: IndicatorSnapshot, cfg: StrategyConfig) -> tuple[ComponentScore, str, float | None]:
    """Returns the score plus the detected breakout type and its price level."""
    c = s.close

    if s.high_20_prior is not None:
        b20 = 1.0 if c > s.high_20_prior else 0.6 * ramp(c / s.high_20_prior, 0.97, 1.0)
    else:
        b20 = 0.0
    b50 = 1.0 if (s.high_50_prior is not None and c > s.high_50_prior) else 0.0
    b252 = 1.0 if (s.high_252_prior is not None and c > s.high_252_prior) else 0.0

    consolidation = ramp_inv(s.bb_width_rank, 0.20, 0.60)

    expansion = 0.0
    if s.true_range is not None and s.prev_atr14 and s.prev_atr14 > 0:
        expansion = ramp(s.true_range / s.prev_atr14, 1.0, 2.0)

    fired = (
        (s.high_20_prior is not None and c > s.high_20_prior)
        or (s.high_50_prior is not None and c > s.high_50_prior)
        or (s.high_252_prior is not None and c > s.high_252_prior)
    )
    vol_confirm = ramp(s.rel_volume, 1.2, 2.5) if fired else 0.0
    retest = _retest_detected(s)

    score = _combine(
        "breakout",
        {
            "breakout_20d": (b20, 0.20),
            "breakout_50d": (b50, 0.18),
            "breakout_52w": (b252, 0.16),
            "consolidation": (consolidation, 0.14),
            "range_expansion": (expansion, 0.12),
            "volume_confirmation": (vol_confirm, 0.12),
            "retest": (retest, 0.08),
        },
    )

    if b252 >= 1.0:
        btype, level = "FIFTY_TWO_WEEK_HIGH", s.high_252_prior
    elif b50 >= 1.0:
        btype, level = "FIFTY_DAY", s.high_50_prior
    elif s.high_20_prior is not None and c > s.high_20_prior:
        btype, level = "TWENTY_DAY", s.high_20_prior
    elif consolidation >= 0.6:
        btype, level = "CONSOLIDATION", s.high_20_prior
    elif retest >= 1.0:
        btype, level = "RETEST", s.high_20_prior
    else:
        btype, level = "NONE", None

    return score, btype, level


# --------------------------------------------------------------------------------------
# Relative strength
# --------------------------------------------------------------------------------------


def relative_strength_score(s: IndicatorSnapshot, cfg: StrategyConfig) -> ComponentScore:
    if s.rs_line_rising_21:
        rs_slope = 1.0
    elif s.rs_line_rising_10:
        rs_slope = 0.5
    else:
        rs_slope = 0.0

    notes: list[str] = []
    if s.rs_21 is None:
        notes.append("benchmark unavailable — relative strength scored as zero, not neutral")

    return _combine(
        "relative_strength",
        {
            "rs_21_vs_spy": (ramp(s.rs_21, 0.0, 10.0), 0.24),
            "rs_63_vs_spy": (ramp(s.rs_63, 0.0, 18.0), 0.22),
            "rs_126_vs_spy": (ramp(s.rs_126, 0.0, 30.0), 0.14),
            "rs_63_vs_sector": (ramp(s.rs_sector_63, 0.0, 15.0), 0.20),
            "rs_line_slope": (rs_slope, 0.20),
        },
        notes=notes,
    )


# --------------------------------------------------------------------------------------
# Fundamentals
# --------------------------------------------------------------------------------------

SPARSE_FUNDAMENTAL_COVERAGE = 0.34


def fundamental_score(f: Fundamentals | None, cfg: StrategyConfig) -> ComponentScore:
    if f is None or f.coverage < SPARSE_FUNDAMENTAL_COVERAGE:
        coverage = 0.0 if f is None else f.coverage
        return ComponentScore(
            name="fundamental",
            score=50.0,
            subscores={},
            contributions={},
            notes=[
                "fundamental_data_sparse",
                f"coverage {coverage:.0%} below {SPARSE_FUNDAMENTAL_COVERAGE:.0%} — "
                "held at neutral 50 rather than scored from defaults",
            ],
        )

    fcf = 0.5 if f.free_cash_flow is None else (1.0 if f.free_cash_flow > 0 else 0.0)
    peg = 0.5 if (f.peg is None or f.peg <= 0) else ramp_inv(f.peg, 1.0, 3.5)

    return _combine(
        "fundamental",
        {
            "revenue_growth": (ramp(f.revenue_growth_yoy, 0.0, 0.25, default=0.5), 0.18),
            "eps_growth": (ramp(f.earnings_growth_yoy, 0.0, 0.30, default=0.5), 0.18),
            "earnings_surprise": (ramp(f.eps_surprise_pct, -2.0, 10.0, default=0.5), 0.10),
            "operating_margin": (ramp(f.operating_margin, 0.0, 0.25, default=0.5), 0.12),
            "free_cash_flow": (fcf, 0.10),
            "debt_to_equity": (ramp_inv(f.debt_to_equity, 0.5, 2.5, default=0.5), 0.10),
            "roe": (ramp(f.roe, 0.05, 0.25, default=0.5), 0.10),
            "valuation_peg": (peg, 0.12),
        },
        notes=[f"coverage {f.coverage:.0%}"],
    )


# --------------------------------------------------------------------------------------
# Risk (higher = better risk quality)
# --------------------------------------------------------------------------------------


def risk_score(
    s: IndicatorSnapshot,
    cfg: StrategyConfig,
    days_to_earnings: int | None = None,
) -> ComponentScore:
    atr_quality = trapezoid(s.atr_pct, rise_start=0.8, plateau_start=1.5,
                            plateau_end=4.0, fall_end=9.0, fall_floor=0.0)

    mdd = None if s.max_drawdown_252 is None else abs(s.max_drawdown_252)
    recent_dd = None if s.recent_drawdown is None else abs(s.recent_drawdown)
    beta_dev = None if s.beta_252 is None else abs(s.beta_252 - 1.0)

    blackout = cfg.buy_gate.earnings_blackout_days
    if days_to_earnings is None:
        earnings = 1.0
    elif days_to_earnings <= blackout:
        earnings = 0.0
    elif days_to_earnings <= 2 * blackout:
        earnings = 0.5
    else:
        earnings = 1.0

    return _combine(
        "risk",
        {
            "atr_moderation": (atr_quality, 0.18),
            "realized_vol": (ramp_inv(s.realized_vol_20, 0.25, 0.90, default=0.5), 0.14),
            "downside_vol": (ramp_inv(s.downside_vol_20, 0.20, 0.70, default=0.5), 0.12),
            "beta": (ramp_inv(beta_dev, 0.30, 1.50, default=0.5), 0.08),
            "max_drawdown_1y": (ramp_inv(mdd, 0.20, 0.60, default=0.5), 0.12),
            "recent_drawdown": (ramp_inv(recent_dd, 0.03, 0.20, default=0.5), 0.10),
            "gap_risk": (ramp_inv(s.avg_gap_pct, 0.5, 3.0, default=0.5), 0.10),
            "liquidity": (ramp(s.dollar_volume_50, 10e6, 150e6), 0.08),
            "earnings_proximity": (earnings, 0.08),
        },
    )
