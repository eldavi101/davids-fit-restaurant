"""Trailing stop calculation (STRATEGY_SPEC.md §17).

Three independent candidate stops; when several modes are enabled the trailing stop is
the highest candidate. The result is then clamped to be **monotonically non-decreasing**
for the life of the trade — a trailing stop that can loosen is not a trailing stop, and
that invariant is asserted in the test suite.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import StrategyConfig


@dataclass(frozen=True, slots=True)
class TrailingResult:
    stop: float | None
    active: bool
    candidates: dict[str, float]
    mode: str | None

    def as_dict(self) -> dict:
        return {
            "stop": None if self.stop is None else round(self.stop, 4),
            "active": self.active,
            "mode": self.mode,
            "candidates": {k: round(v, 4) for k, v in self.candidates.items()},
        }


def should_activate(
    unrealized_r: float,
    target1_hit: bool,
    cfg: StrategyConfig,
    already_active: bool = False,
) -> bool:
    """Trailing turns on at +1R or once Target 1 is reached, and never turns off."""
    if already_active:
        return True
    return target1_hit or unrealized_r >= cfg.trailing.activate_at_r


def compute_trailing_stop(
    highest_close_since_entry: float,
    atr: float | None,
    ma_value: float | None,
    previous_trailing: float | None,
    cfg: StrategyConfig,
    active: bool,
) -> TrailingResult:
    tc = cfg.trailing
    candidates: dict[str, float] = {}

    if not active:
        return TrailingResult(stop=previous_trailing, active=False, candidates={}, mode=None)

    if tc.use_chandelier and atr is not None and atr > 0:
        candidates["chandelier"] = highest_close_since_entry - tc.chandelier_atr_mult * atr
    if tc.use_percent:
        candidates["percent"] = highest_close_since_entry * (1.0 - tc.percent_trail)
    if tc.use_ma_stop and ma_value is not None:
        candidates["moving_average"] = ma_value

    if not candidates:
        return TrailingResult(stop=previous_trailing, active=True, candidates={}, mode=None)

    mode, best = max(candidates.items(), key=lambda kv: kv[1])

    # Monotone ratchet: the stop may rise, never fall.
    if previous_trailing is not None and previous_trailing > best:
        return TrailingResult(
            stop=previous_trailing, active=True, candidates=candidates, mode="ratcheted"
        )

    return TrailingResult(stop=best, active=True, candidates=candidates, mode=mode)


def effective_stop(initial_stop: float, trailing_stop: float | None) -> float:
    """The stop actually in force: the higher of the initial and trailing stops."""
    if trailing_stop is None:
        return initial_stop
    return max(initial_stop, trailing_stop)
