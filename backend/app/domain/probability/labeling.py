"""Triple-barrier labelling of historical setups.

Given a setup at bar ``t`` with an entry, a stop and a target, walk forward — and only
forward — to decide whether the target or the stop came first. This is the *only* source
of probability in the system; nothing converts a score into a probability
(requirement 27).

Two deliberately pessimistic conventions:

* when a single bar's range contains both the stop and the target, the label is a loss,
  because intrabar order is unknowable and assuming the good outcome is how backtests
  flatter themselves;
* when neither barrier is touched within the horizon, the label is the sign of the
  holding-period return, and the sample is marked ``time_exit`` so it can be analysed
  separately.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.domain.types import BarSeries


@dataclass(frozen=True, slots=True)
class LabeledSetup:
    ticker: str
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    stop: float
    target: float
    label: int                 # 1 = target first, 0 = stop first / negative time exit
    r_multiple: float
    bars_held: int
    time_exit: bool
    features: dict[str, float]

    @property
    def outcome_end_index(self) -> int:
        """Last bar whose information is embedded in this label — used for purging."""
        return self.exit_index


def label_setup(
    series: BarSeries,
    entry_index: int,
    entry_price: float,
    stop: float,
    target: float,
    horizon: int,
    features: dict[str, float] | None = None,
    ticker: str | None = None,
) -> LabeledSetup | None:
    """Label one setup, or return None when the horizon extends past available data."""
    n = len(series)
    last = entry_index + horizon
    if entry_index < 0 or last >= n:
        return None
    risk = entry_price - stop
    if risk <= 0:
        return None

    for i in range(entry_index + 1, last + 1):
        hit_stop = series.low[i] <= stop
        hit_target = series.high[i] >= target
        if hit_stop:
            # Stop takes precedence even when both are inside the same bar.
            exit_price = min(float(series.open[i]), stop)
            return LabeledSetup(
                ticker=ticker or series.ticker,
                entry_index=entry_index,
                exit_index=i,
                entry_price=entry_price,
                exit_price=exit_price,
                stop=stop,
                target=target,
                label=0,
                r_multiple=(exit_price - entry_price) / risk,
                bars_held=i - entry_index,
                time_exit=False,
                features=features or {},
            )
        if hit_target:
            return LabeledSetup(
                ticker=ticker or series.ticker,
                entry_index=entry_index,
                exit_index=i,
                entry_price=entry_price,
                exit_price=target,
                stop=stop,
                target=target,
                label=1,
                r_multiple=(target - entry_price) / risk,
                bars_held=i - entry_index,
                time_exit=False,
                features=features or {},
            )

    exit_price = float(series.close[last])
    return LabeledSetup(
        ticker=ticker or series.ticker,
        entry_index=entry_index,
        exit_index=last,
        entry_price=entry_price,
        exit_price=exit_price,
        stop=stop,
        target=target,
        label=1 if exit_price > entry_price else 0,
        r_multiple=(exit_price - entry_price) / risk,
        bars_held=last - entry_index,
        time_exit=True,
        features=features or {},
    )


def purge_and_embargo(
    setups: list[LabeledSetup],
    test_start_index: int,
    embargo_bars: int,
) -> list[LabeledSetup]:
    """Drop training setups whose outcome window reaches into (or near) the test window.

    Without this, a training label computed from bars that the test period also contains
    leaks future information into the fitted model — the subtlest and most common way a
    walk-forward result becomes fiction.
    """
    cutoff = test_start_index - embargo_bars
    return [s for s in setups if s.outcome_end_index < cutoff]


def to_matrix(
    setups: list[LabeledSetup], feature_names: list[str]
) -> tuple[np.ndarray, np.ndarray]:
    if not setups:
        return np.empty((0, len(feature_names))), np.empty((0,))
    X = np.array(
        [[float(s.features.get(name, 0.0)) for name in feature_names] for s in setups],
        dtype=float,
    )
    y = np.array([s.label for s in setups], dtype=int)
    return X, y
