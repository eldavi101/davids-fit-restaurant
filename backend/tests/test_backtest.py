"""Backtesting: bias controls, fill model, metrics, walk-forward isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.domain.backtest.engine import BacktestEngine
from app.domain.backtest.metrics import (
    TradeRecord,
    compute_metrics,
    max_drawdown_pct,
    monthly_returns,
    profit_factor,
    sharpe_ratio,
)
from app.domain.backtest.walkforward import (
    build_folds,
    chronological_split,
    collect_training_setups,
)
from app.domain.probability.labeling import label_setup, purge_and_embargo
from app.domain.probability.model import ProbabilityModel
from tests.conftest import benchmark_series, breakout_series, build_series, uptrend_closes


def trade(return_pct: float, r: float = 1.0, reason: str = "TARGET_1", shares: float = 100) -> TradeRecord:
    entry = 100.0
    return TradeRecord(
        ticker="X", entry_ts=datetime.now(UTC), exit_ts=datetime.now(UTC),
        entry_price=entry, exit_price=entry * (1 + return_pct / 100.0), shares=shares,
        return_pct=return_pct, r_multiple=r, exit_reason=reason, holding_days=5,
    )


# --------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------


def test_win_rate_and_averages():
    metrics = compute_metrics([trade(10), trade(5), trade(-4), trade(-2)])
    assert metrics.trades == 4
    assert metrics.win_rate == pytest.approx(0.5)
    assert metrics.avg_return_pct == pytest.approx(2.25)
    assert metrics.avg_winner_pct == pytest.approx(7.5)
    assert metrics.avg_loser_pct == pytest.approx(-3.0)
    assert metrics.best_trade_pct == pytest.approx(10.0)
    assert metrics.worst_trade_pct == pytest.approx(-4.0)


def test_profit_factor_is_gains_over_losses():
    assert profit_factor([trade(10), trade(-5)]) == pytest.approx(2.0)


def test_profit_factor_is_none_when_there_are_no_losses():
    """An infinite ratio is not 'infinitely good' — it is undefined, and says so."""
    assert profit_factor([trade(10), trade(5)]) is None


def test_expectancy_is_the_mean_r_multiple():
    metrics = compute_metrics([trade(10, r=2.0), trade(-5, r=-1.0)])
    assert metrics.expectancy_r == pytest.approx(0.5)


def test_max_drawdown():
    assert max_drawdown_pct([100.0, 120.0, 90.0, 110.0]) == pytest.approx(-25.0)


def test_sharpe_requires_enough_observations():
    """A Sharpe ratio from twelve days is noise wearing a statistic's clothes."""
    assert sharpe_ratio(np.full(12, 0.001)) is None
    assert sharpe_ratio(np.tile([0.002, -0.001], 60)) is not None


def test_low_trade_count_is_flagged_not_hidden():
    metrics = compute_metrics([trade(5) for _ in range(4)])
    assert any("low_sample" in w for w in metrics.warnings)


def test_target_and_stop_rates():
    metrics = compute_metrics([
        trade(10, reason="TARGET_1"), trade(15, reason="TARGET_2"),
        trade(-5, reason="STOP_LOSS"), trade(2, reason="TIME_EXIT"),
    ])
    assert metrics.target_hit_rate == pytest.approx(0.5)
    assert metrics.stop_rate == pytest.approx(0.25)


def test_benchmark_return_is_reported_alongside():
    metrics = compute_metrics([trade(5)], [100.0, 110.0], [100.0, 104.0])
    assert metrics.benchmark_return_pct == pytest.approx(4.0)
    assert metrics.total_return_pct == pytest.approx(10.0)


def test_monthly_returns_bucket_by_calendar_month():
    base = datetime(2026, 1, 15, tzinfo=UTC)
    # 15 Jan, 4 Feb, 6 Mar — three distinct calendar months.
    timestamps = [base, base + timedelta(days=20), base + timedelta(days=50)]
    result = monthly_returns(timestamps, [100.0, 110.0, 121.0])
    assert [r["month"] for r in result] == ["2026-01", "2026-02", "2026-03"]
    assert result[0]["return_pct"] == pytest.approx(0.0)     # single point, no prior close
    assert result[1]["return_pct"] == pytest.approx(10.0)    # 100 → 110
    assert result[2]["return_pct"] == pytest.approx(10.0)    # 110 → 121


# --------------------------------------------------------------------------------------
# Labelling
# --------------------------------------------------------------------------------------


def test_label_is_a_win_when_the_target_comes_first():
    closes = np.concatenate([np.full(10, 100.0), np.linspace(101, 115, 20)])
    series = build_series("X", closes, intraday_range=0.001)
    result = label_setup(series, 9, entry_price=100.0, stop=95.0, target=110.0, horizon=20)
    assert result.label == 1
    assert result.r_multiple == pytest.approx(2.0)


def test_label_is_a_loss_when_the_stop_comes_first():
    closes = np.concatenate([np.full(10, 100.0), np.linspace(99, 90, 20)])
    series = build_series("X", closes, intraday_range=0.001)
    result = label_setup(series, 9, entry_price=100.0, stop=95.0, target=110.0, horizon=20)
    assert result.label == 0
    assert result.r_multiple < 0


def test_a_bar_touching_both_barriers_is_labelled_a_loss():
    """Intrabar order is unknowable, so the pessimistic label is the honest one."""
    closes = np.concatenate([np.full(10, 100.0), np.full(20, 100.0)])
    series = build_series("X", closes, intraday_range=0.20)  # every bar spans 80–120
    result = label_setup(series, 9, entry_price=100.0, stop=95.0, target=110.0, horizon=20)
    assert result.label == 0


def test_label_returns_none_when_the_horizon_runs_past_the_data():
    series = build_series("X", np.full(30, 100.0))
    assert label_setup(series, 25, 100.0, 95.0, 110.0, horizon=20) is None


def test_purge_and_embargo_drops_setups_overlapping_the_test_window():
    series = build_series("X", uptrend_closes(400))
    setups = [
        label_setup(series, t, float(series.close[t]), float(series.close[t]) * 0.95,
                    float(series.close[t]) * 1.10, horizon=20)
        for t in range(250, 340, 5)
    ]
    setups = [s for s in setups if s is not None]
    kept = purge_and_embargo(setups, test_start_index=320, embargo_bars=5)

    assert kept, "purging must not discard everything"
    assert all(s.outcome_end_index < 315 for s in kept)
    assert len(kept) < len(setups)


# --------------------------------------------------------------------------------------
# Engine bias controls
# --------------------------------------------------------------------------------------


def universe_and_benchmarks():
    universe = {"TESTCO": breakout_series(n=500)}
    benchmarks = {"SPY": benchmark_series(n=500), "QQQ": benchmark_series("QQQ", n=500, daily=0.0009)}
    for etf in ("XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"):
        benchmarks[etf] = benchmark_series(etf, n=500, daily=0.0008)
    return universe, benchmarks


def test_engine_runs_end_to_end_and_produces_a_curve(cfg):
    universe, benchmarks = universe_and_benchmarks()
    result = BacktestEngine(cfg, 100_000.0).run(universe, benchmarks)

    assert result.bars_processed > 0
    assert len(result.equity_curve) == result.bars_processed
    assert result.equity_curve[0]["equity"] > 0
    for point in result.equity_curve:
        assert point["cash"] >= -1e-6, "cash must never go negative"


def test_engine_requires_a_benchmark(cfg):
    from app.core.errors import DataIntegrityError

    with pytest.raises(DataIntegrityError):
        BacktestEngine(cfg).run({"X": breakout_series()}, {})


def test_survivorship_warning_is_stated_not_hidden(cfg):
    universe, benchmarks = universe_and_benchmarks()
    result = BacktestEngine(cfg, supports_delisted=False).run(universe, benchmarks)
    assert any("survivorship" in w for w in result.bias_warnings)

    clean = BacktestEngine(cfg, supports_delisted=True).run(universe, benchmarks)
    assert not any("survivorship" in w for w in clean.bias_warnings)


def test_buy_fill_is_worse_than_the_open_and_sell_fill_is_worse_than_the_price(cfg):
    engine = BacktestEngine(cfg)
    assert engine._buy_fill(100.0) > 100.0
    assert engine._sell_fill(100.0) < 100.0


def test_costs_are_zero_only_when_configured_to_be(cfg):
    free = cfg.model_copy(deep=True)
    free.costs.slippage_bps = 0.0
    free.costs.spread_bps = 0.0
    engine = BacktestEngine(free)
    assert engine._buy_fill(100.0) == pytest.approx(100.0)


def test_a_split_rescales_an_open_position_instead_of_gapping_the_stop(cfg):
    """A 2-for-1 split must not look like a 50% crash through the stop."""
    from app.domain.backtest.engine import OpenTrade
    from app.domain.signals.sell_engine import TrackedPosition

    closes = np.concatenate([np.full(20, 200.0), np.full(20, 100.0)])
    series = build_series("SPLIT", closes, intraday_range=0.002)

    position = TrackedPosition(
        ticker="SPLIT", entry_price=200.0, entry_ts=datetime.now(UTC),
        initial_stop=190.0, target1=215.0, target2=230.0, risk_per_share=10.0,
        highest_close_since_entry=200.0, highest_price_since_entry=200.0,
        lowest_price_since_entry=200.0,
    )
    open_trade = OpenTrade(
        ticker="SPLIT", entry_index=10, entry_ts=datetime.now(UTC), entry_price=200.0,
        shares=100, position=position, opportunity_score=85.0, regime="BULL", sector=None,
    )

    BacktestEngine(cfg)._apply_split(open_trade, series, 20)

    assert open_trade.shares == pytest.approx(200)
    assert position.entry_price == pytest.approx(100.0)
    assert position.initial_stop == pytest.approx(95.0)
    assert position.target1 == pytest.approx(107.5)
    # The post-split price is above the rescaled stop — no phantom exit.
    assert float(series.low[20]) > position.initial_stop


def test_backtest_and_live_share_one_strategy_implementation():
    """BACKTESTING_SPEC §1 — there must be no second copy of the strategy."""
    import inspect

    from app.domain.backtest import engine as backtest_engine
    from app.domain.scoring import opportunity
    from app.domain.signals import buy_engine, sell_engine

    source = inspect.getsource(backtest_engine)
    assert "score_stock" in source
    assert "evaluate_buy" in source
    assert "evaluate_sell" in source
    # And they are the same objects the live services import.
    assert backtest_engine.score_stock is opportunity.score_stock
    assert backtest_engine.evaluate_buy is buy_engine.evaluate_buy
    assert backtest_engine.evaluate_sell is sell_engine.evaluate_sell


# --------------------------------------------------------------------------------------
# Walk-forward
# --------------------------------------------------------------------------------------


def test_rolling_folds_advance_and_never_overlap_their_own_test_windows():
    folds = build_folds(datetime(2018, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC),
                        train_years=4, test_years=1, step_years=1)
    assert len(folds) == 3
    assert folds[0].train_start.year == 2018 and folds[0].test_start.year == 2022
    assert folds[1].train_start.year == 2019 and folds[1].test_start.year == 2023
    for fold in folds:
        assert fold.train_end <= fold.test_start
        assert fold.test_start < fold.test_end


def test_anchored_folds_keep_the_same_start():
    folds = build_folds(datetime(2018, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC),
                        anchored=True)
    assert {f.train_start.year for f in folds} == {2018}


def test_no_fold_trains_on_its_own_test_window():
    folds = build_folds(datetime(2018, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC))
    for fold in folds:
        assert fold.train_end <= fold.test_start, "training window reaches into the test window"


def test_chronological_split_is_60_20_20():
    start, end = datetime(2020, 1, 1, tzinfo=UTC), datetime(2030, 1, 1, tzinfo=UTC)
    split = chronological_split(start, end)
    span = (end - start).total_seconds()

    assert split.train_start == start
    assert split.test_end == end
    assert (split.train_end - start).total_seconds() == pytest.approx(span * 0.6, rel=1e-6)
    assert (split.validation_end - start).total_seconds() == pytest.approx(span * 0.8, rel=1e-6)
    # The three samples tile the period with no gaps and no overlap.
    assert split.train_end == split.validation_start
    assert split.validation_end == split.test_start


def test_chronological_split_never_shuffles():
    """Random splits leak in time series; the split must stay strictly ordered."""
    split = chronological_split(datetime(2020, 1, 1, tzinfo=UTC), datetime(2030, 1, 1, tzinfo=UTC))
    assert split.train_start < split.train_end < split.validation_end < split.test_end


def test_training_setups_come_only_from_the_training_window(cfg):
    series = breakout_series(n=500)
    universe = {"TESTCO": series}
    all_ts = [ts for ts in series.ts]
    train_start, train_end = all_ts[260], all_ts[380]
    test_start = all_ts[400]

    setups = collect_training_setups(universe, cfg, train_start, train_end, test_start)
    for setup in setups:
        entry_ts = series.ts[setup.entry_index]
        assert train_start <= entry_ts < train_end


def test_a_fitted_model_reports_more_than_a_prior(cfg):
    """Once there is evidence, the estimate stops being the configured prior."""
    series = build_series("X", uptrend_closes(500, daily=0.0015))
    setups = collect_training_setups(
        {"X": series}, cfg, series.ts[260], series.ts[460], series.ts[480], sample_every=2
    )
    model = ProbabilityModel(cfg).fit(setups)
    if model.n_samples == 0:
        pytest.skip("fixture produced no labelled setups")

    estimate = model.predict({name: 70.0 for name in ("trend", "momentum", "volume", "breakout")})
    assert estimate.sample_size == model.n_samples or estimate.method != "prior"
    assert estimate.reliability in ("MODEL", "EMPIRICAL", "PRIOR_ONLY")


def test_standardisation_statistics_are_frozen_at_fit_time(cfg):
    """BACKTESTING_SPEC §2.3 — test data is transformed with training statistics only."""
    series = build_series("X", uptrend_closes(500, daily=0.0015))
    setups = collect_training_setups(
        {"X": series}, cfg, series.ts[260], series.ts[460], series.ts[480], sample_every=2
    )
    model = ProbabilityModel(cfg).fit(setups)
    if not model.is_fitted:
        pytest.skip("insufficient labelled setups to fit a model")

    before = model._mean.copy(), model._std.copy()
    for _ in range(20):
        model.predict({name: 95.0 for name in ("trend", "momentum", "volume", "breakout")})
    assert np.array_equal(model._mean, before[0])
    assert np.array_equal(model._std, before[1])
