"""Stop, targets and reward/risk construction (STRATEGY_SPEC.md §11).

The stop is the anchor of everything downstream: position size, R-multiples, expected
value and every exit rule are expressed relative to ``risk_per_share``. It is therefore
computed once, validated hard, and never silently repaired — an invalid stop blocks the
BUY rather than being nudged into range.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import StrategyConfig
from app.domain.indicators.snapshot import IndicatorSnapshot


@dataclass
class Levels:
    entry: float
    stop: float
    target1: float
    target2: float
    risk_per_share: float
    reward_risk: float
    stop_pct: float
    stop_atr_mult: float | None
    valid: bool
    reason: str | None = None
    stop_source: str = "atr"

    def as_dict(self) -> dict:
        return {
            "entry": round(self.entry, 4),
            "stop": round(self.stop, 4),
            "target1": round(self.target1, 4),
            "target2": round(self.target2, 4),
            "risk_per_share": round(self.risk_per_share, 4),
            "reward_risk": round(self.reward_risk, 3),
            "stop_pct": round(self.stop_pct, 4),
            "stop_source": self.stop_source,
            "valid": self.valid,
            "reason": self.reason,
        }


def compute_levels(snapshot: IndicatorSnapshot, cfg: StrategyConfig) -> Levels:
    lc = cfg.levels
    entry = snapshot.close
    atr = snapshot.atr14

    if entry <= 0:
        return Levels(entry, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, None, False, "non_positive_price")
    if atr is None or atr <= 0:
        return Levels(entry, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, None, False, "atr_unavailable")

    stop_atr = entry - lc.stop_atr_mult * atr

    # Structure first: place the stop under the recent swing low when there is one, since
    # that is where the trade is actually wrong. But a stock that has run far from its base
    # has a swing low too distant to risk against, so beyond the configured ATR band we
    # fall back to the volatility stop rather than accepting an oversized loss.
    stop = stop_atr
    stop_source = "atr"
    if snapshot.low_10 is not None and snapshot.low_10 > 0:
        stop_swing = snapshot.low_10 - lc.swing_low_atr_buffer * atr
        if stop_swing < stop_atr and (entry - stop_swing) <= lc.max_stop_atr_mult * atr:
            stop, stop_source = stop_swing, "swing_low"

    # Cap total risk. This can only tighten the stop, never loosen it.
    floor_stop = entry * (1.0 - lc.max_stop_pct)
    if floor_stop > stop:
        stop, stop_source = floor_stop, "max_risk_cap"

    risk = entry - stop
    if risk <= 0:
        return Levels(entry, stop, 0.0, 0.0, 0.0, 0.0, 0.0, None, False, "non_positive_risk")

    atr_mult = risk / atr
    stop_pct = risk / entry

    target1 = entry + lc.target_r1 * risk
    target2 = entry + lc.target_r2 * risk
    # Blended reward/risk across both targets, matching how the staged exit actually works.
    reward_risk = (0.5 * (target1 - entry) + 0.5 * (target2 - entry)) / risk

    valid, reason = True, None
    if not (0.0 < stop < entry):
        valid, reason = False, "stop_outside_valid_range"
    elif atr_mult < lc.min_stop_atr_mult:
        valid, reason = False, f"stop_too_tight ({atr_mult:.2f} ATR < {lc.min_stop_atr_mult})"
    elif atr_mult > lc.max_stop_atr_mult:
        valid, reason = False, f"stop_too_wide ({atr_mult:.2f} ATR > {lc.max_stop_atr_mult})"
    elif stop_pct > lc.max_stop_pct + 1e-9:
        valid, reason = False, f"risk_exceeds_max_stop_pct ({stop_pct:.2%})"

    return Levels(
        entry=entry,
        stop=stop,
        target1=target1,
        target2=target2,
        risk_per_share=risk,
        reward_risk=reward_risk,
        stop_pct=stop_pct,
        stop_atr_mult=atr_mult,
        valid=valid,
        reason=reason,
        stop_source=stop_source,
    )
