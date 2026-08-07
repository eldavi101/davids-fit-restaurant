"""Walk-forward validation and out-of-sample splitting (BACKTESTING_SPEC.md §6–7).

The discipline this module enforces:

* the probability model for fold *k* is fitted **only** on fold *k*'s training window,
  with purging and an embargo so no training label's outcome window reaches into the test
  window;
* parameter selection uses a validation slice carved from the *end of the training
  window*, never the test window;
* the test window is run once, with everything frozen;
* the headline number is the aggregate of **test folds only**, and the train-versus-test
  gap is reported as ``overfit_gap`` rather than left for the user to notice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.config import StrategyConfig
from app.domain.backtest.engine import BacktestEngine, BacktestResult
from app.domain.backtest.metrics import PerformanceMetrics, TradeRecord, compute_metrics
from app.domain.probability.labeling import LabeledSetup, label_setup, purge_and_embargo
from app.domain.probability.model import ProbabilityModel
from app.domain.types import BarSeries


@dataclass
class Fold:
    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_metrics: PerformanceMetrics | None = None
    validation_metrics: PerformanceMetrics | None = None
    test_metrics: PerformanceMetrics | None = None
    training_samples: int = 0
    selected_parameters: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "fold": self.index,
            "train": {"start": self.train_start.date().isoformat(),
                      "end": self.train_end.date().isoformat()},
            "test": {"start": self.test_start.date().isoformat(),
                     "end": self.test_end.date().isoformat()},
            "training_samples": self.training_samples,
            "selected_parameters": self.selected_parameters,
            "train_metrics": self.train_metrics.as_dict() if self.train_metrics else None,
            "validation_metrics": self.validation_metrics.as_dict() if self.validation_metrics else None,
            "test_metrics": self.test_metrics.as_dict() if self.test_metrics else None,
        }


@dataclass
class WalkForwardResult:
    folds: list[Fold] = field(default_factory=list)
    aggregate_test: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    aggregate_train: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    overfit_gap: float | None = None
    test_trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    bias_warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "folds": [f.as_dict() for f in self.folds],
            # The headline is out-of-sample only. Train metrics are reported beside it
            # for comparison, never merged into it.
            "aggregate_test": self.aggregate_test.as_dict(),
            "aggregate_train": self.aggregate_train.as_dict(),
            "overfit_gap": self.overfit_gap,
            "equity_curve": self.equity_curve,
            "bias_warnings": self.bias_warnings,
        }


def build_folds(
    start: datetime,
    end: datetime,
    train_years: int = 4,
    test_years: int = 1,
    step_years: int = 1,
    anchored: bool = False,
) -> list[Fold]:
    folds: list[Fold] = []
    index = 1
    train_start = start
    train_end = _add_years(start, train_years)

    while _add_years(train_end, test_years) <= end:
        test_start = train_end
        test_end = _add_years(train_end, test_years)
        folds.append(
            Fold(
                index=index,
                train_start=train_start if not anchored else start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        index += 1
        train_end = _add_years(train_end, step_years)
        if not anchored:
            train_start = _add_years(train_start, step_years)
    return folds


def _add_years(dt: datetime, years: int) -> datetime:
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # 29 February
        return dt.replace(year=dt.year + years, day=28)


def collect_training_setups(
    universe: dict[str, BarSeries],
    cfg: StrategyConfig,
    train_start: datetime,
    train_end: datetime,
    test_start: datetime,
    sample_every: int = 5,
) -> list[LabeledSetup]:
    """Label historical setups inside the training window only, then purge and embargo.

    ``sample_every`` thins the sampling so overlapping windows do not flood the fit with
    near-duplicate observations.
    """
    from app.domain.indicators.snapshot import compute_snapshot
    from app.domain.regime.engine import neutral_regime
    from app.domain.scoring.opportunity import score_stock
    from app.domain.signals.levels import compute_levels

    horizon = cfg.probability.horizon_bars
    regime = neutral_regime(cfg)
    setups: list[LabeledSetup] = []

    for ticker, series in universe.items():
        test_start_index = _index_of(series, test_start) or len(series)
        for t in range(cfg.min_bars_required, len(series) - horizon, sample_every):
            ts = series.ts[t]
            if not isinstance(ts, datetime) or not (train_start <= ts < train_end):
                continue
            window = series.window(t)
            snapshot = compute_snapshot(window, None)
            levels = compute_levels(snapshot, cfg)
            if not levels.valid:
                continue
            score = score_stock(snapshot, regime, cfg)
            labeled = label_setup(
                series=series,
                entry_index=t,
                entry_price=levels.entry,
                stop=levels.stop,
                target=levels.target1,
                horizon=horizon,
                ticker=ticker,
                features={
                    "trend": score.trend.score,
                    "momentum": score.momentum.score,
                    "volume": score.volume.score,
                    "breakout": score.breakout.score,
                    "relative_strength": score.relative_strength.score,
                    "fundamental": score.fundamental.score,
                    "risk": score.risk.score,
                    "regime_score": regime.regime_score,
                    "atr_pct": snapshot.atr_pct or 0.0,
                    "reward_risk": levels.reward_risk,
                    "dist_52w_high": snapshot.dist_52w_high_pct or 0.0,
                    "rel_volume": snapshot.rel_volume or 0.0,
                    "opportunity_score": score.opportunity_score,
                    "regime_label": regime.regime,
                },
            )
            if labeled is not None:
                setups.append(labeled)

        setups = purge_and_embargo(setups, test_start_index, cfg.probability.embargo_bars)

    return setups


def _index_of(series: BarSeries, ts: datetime) -> int | None:
    for i, bar_ts in enumerate(series.ts):
        if isinstance(bar_ts, datetime) and bar_ts >= ts:
            return i
    return None


def run_walk_forward(
    universe: dict[str, BarSeries],
    benchmarks: dict[str, BarSeries],
    cfg: StrategyConfig,
    start: datetime,
    end: datetime,
    initial_equity: float = 100_000.0,
    train_years: int = 4,
    test_years: int = 1,
    step_years: int = 1,
    anchored: bool = False,
    supports_delisted: bool = False,
) -> WalkForwardResult:
    result = WalkForwardResult()
    folds = build_folds(start, end, train_years, test_years, step_years, anchored)

    all_test_trades: list[TradeRecord] = []
    all_train_trades: list[TradeRecord] = []
    combined_curve: list[dict] = []

    for fold in folds:
        # 1. Fit the probability model on TRAINING data only, purged and embargoed.
        setups = collect_training_setups(
            universe, cfg, fold.train_start, fold.train_end, fold.test_start
        )
        model = ProbabilityModel(cfg).fit(setups)
        fold.training_samples = len(setups)
        fold.selected_parameters = {
            "min_opportunity_score": cfg.buy_gate.min_opportunity_score,
            "stop_atr_mult": cfg.levels.stop_atr_mult,
            "probability_method": "calibrated_logistic" if model.is_fitted else "empirical/prior",
        }

        # 2. In-sample reference run (reported for comparison only).
        train_engine = BacktestEngine(
            cfg, initial_equity, probability_model=model,
            supports_delisted=supports_delisted, fold=fold.index, sample="TRAIN",
        )
        train_result = train_engine.run(universe, benchmarks, fold.train_start, fold.train_end)
        fold.train_metrics = train_result.metrics
        all_train_trades.extend(train_result.trades)

        # 3. Validation slice = final 20% of the training window. Never the test window.
        validation_start = fold.train_end - (fold.train_end - fold.train_start) * 0.2
        validation_engine = BacktestEngine(
            cfg, initial_equity, probability_model=model,
            supports_delisted=supports_delisted, fold=fold.index, sample="VALIDATION",
        )
        fold.validation_metrics = validation_engine.run(
            universe, benchmarks, validation_start, fold.train_end
        ).metrics

        # 4. Test window, run once, everything frozen.
        test_engine = BacktestEngine(
            cfg, initial_equity, probability_model=model,
            supports_delisted=supports_delisted, fold=fold.index, sample="TEST",
        )
        test_result: BacktestResult = test_engine.run(
            universe, benchmarks, fold.test_start, fold.test_end
        )
        fold.test_metrics = test_result.metrics
        all_test_trades.extend(test_result.trades)
        combined_curve.extend(test_result.equity_curve)
        result.bias_warnings = test_result.bias_warnings

        result.folds.append(fold)

    result.test_trades = all_test_trades
    result.aggregate_test = compute_metrics(
        all_test_trades, [p["equity"] for p in combined_curve] or None
    )
    result.aggregate_train = compute_metrics(all_train_trades)
    result.equity_curve = combined_curve

    if (
        result.aggregate_train.expectancy_r is not None
        and result.aggregate_test.expectancy_r is not None
    ):
        result.overfit_gap = round(
            result.aggregate_train.expectancy_r - result.aggregate_test.expectancy_r, 4
        )
    return result


@dataclass
class OutOfSampleSplit:
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime

    def as_dict(self) -> dict:
        return {
            "TRAIN": [self.train_start.date().isoformat(), self.train_end.date().isoformat()],
            "VALIDATION": [self.validation_start.date().isoformat(), self.validation_end.date().isoformat()],
            "TEST": [self.test_start.date().isoformat(), self.test_end.date().isoformat()],
        }


def chronological_split(start: datetime, end: datetime) -> OutOfSampleSplit:
    """60 / 20 / 20 chronological split. Never random — shuffling time series leaks."""
    span = end - start
    train_end = start + timedelta(seconds=span.total_seconds() * 0.6)
    validation_end = start + timedelta(seconds=span.total_seconds() * 0.8)
    return OutOfSampleSplit(
        train_start=start,
        train_end=train_end,
        validation_start=train_end,
        validation_end=validation_end,
        test_start=validation_end,
        test_end=end,
    )
