"""SELL engine triggers, trailing stops and staged exits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.domain.indicators.snapshot import IndicatorSnapshot
from app.domain.regime.engine import neutral_regime
from app.domain.signals.sell_engine import BarInput, TrackedPosition, evaluate_sell
from app.domain.signals.trailing import compute_trailing_stop, effective_stop, should_activate

ENTRY = 100.0
STOP = 95.0
RISK = 5.0


def make_position(**overrides) -> TrackedPosition:
    defaults = dict(
        ticker="TEST",
        entry_price=ENTRY,
        entry_ts=datetime.now(UTC) - timedelta(days=3),
        initial_stop=STOP,
        target1=ENTRY + 1.5 * RISK,   # 107.5
        target2=ENTRY + 3.0 * RISK,   # 115.0
        risk_per_share=RISK,
        highest_close_since_entry=ENTRY,
        highest_price_since_entry=ENTRY,
        lowest_price_since_entry=ENTRY,
        entry_atr_pct=2.0,
        entry_realized_vol=0.30,
        entry_fundamental_score=70.0,
        holding_days=3,
        bars_held=3,
    )
    defaults.update(overrides)
    return TrackedPosition(**defaults)


def healthy_snapshot(**overrides) -> IndicatorSnapshot:
    """A snapshot in which no discretionary exit condition is met."""
    defaults = dict(
        ticker="TEST", bars_available=300, close=104.0,
        ema20=101.0, sma50=98.0, sma200=90.0,
        rsi14=62.0, rsi14_prev5=58.0,
        macd=1.2, macd_signal=0.8, macd_hist=0.4, macd_hist_prev3=0.2,
        atr14=2.0, atr_pct=2.0, realized_vol_20=0.30,
        rs_21=4.0, rs_63=8.0,
        rs_line_series=np.linspace(0.9, 1.1, 40),
    )
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


def sell(position, bar, snapshot, cfg, regime=None, **kwargs):
    return evaluate_sell(
        position, bar, snapshot, regime or neutral_regime(cfg), cfg, **kwargs
    )


# --------------------------------------------------------------------------------------
# The prohibition that matters most
# --------------------------------------------------------------------------------------


def test_rsi_overbought_alone_does_not_sell(cfg):
    """Requirement 31, explicitly: an overbought RSI is not an exit signal.

    Everything else about this position is healthy; only RSI is extreme. The engine must
    hold. If a future change ever adds an `RSI > 70` exit, this test fails.
    """
    position = make_position()
    snapshot = healthy_snapshot(rsi14=88.0, rsi14_prev5=79.0)
    decision = sell(position, BarInput(104.0, 106.0, 103.0, 105.0), snapshot, cfg)

    assert not decision.should_sell
    assert decision.exit_reason is None
    assert any("bullish" in reason.lower() or "EMA20" in reason for reason in decision.hold_reasons)


def test_rsi_at_100_still_does_not_sell(cfg):
    decision = sell(
        make_position(), BarInput(104.0, 106.0, 103.0, 105.0),
        healthy_snapshot(rsi14=100.0, rsi14_prev5=95.0), cfg,
    )
    assert not decision.should_sell


# --------------------------------------------------------------------------------------
# Triggers, one at a time
# --------------------------------------------------------------------------------------


def test_stop_loss_fires_on_an_intrabar_breach(cfg):
    decision = sell(
        make_position(), BarInput(open=99.0, high=99.5, low=94.0, close=94.5),
        healthy_snapshot(close=94.5), cfg,
    )
    assert decision.should_sell
    assert decision.exit_reason == "STOP_LOSS"
    assert decision.new_status == "STOPPED"


def test_a_gap_down_fills_at_the_open_not_at_the_stop(cfg):
    """The single most flattering error a backtest can make, guarded here."""
    decision = sell(
        make_position(), BarInput(open=88.0, high=89.0, low=86.0, close=87.0),
        healthy_snapshot(close=87.0), cfg,
    )
    assert decision.should_sell
    assert decision.exit_reason == "STOP_LOSS"
    assert decision.suggested_fill == pytest.approx(88.0)   # the open, not the 95.0 stop
    assert decision.suggested_fill < STOP


def test_trailing_stop_takes_precedence_once_it_is_above_the_initial_stop(cfg):
    position = make_position(
        trailing_stop=104.0, trailing_active=True, target1_hit=True,
        highest_close_since_entry=110.0,
    )
    decision = sell(
        position, BarInput(open=105.0, high=105.5, low=103.0, close=103.5),
        healthy_snapshot(close=103.5, atr14=2.0), cfg,
    )
    assert decision.should_sell
    assert decision.exit_reason == "TRAILING_STOP"


def test_target_1_books_a_partial_and_activates_trailing(cfg):
    decision = sell(
        make_position(), BarInput(open=105.0, high=108.0, low=104.0, close=107.0),
        healthy_snapshot(close=107.0), cfg,
    )
    assert decision.should_sell
    assert decision.exit_reason == "TARGET_1"
    assert decision.fraction == pytest.approx(cfg.sell.target1_fraction)
    assert decision.new_status == "TARGET_1_HIT"


def test_target_2_takes_priority_over_target_1(cfg):
    decision = sell(
        make_position(), BarInput(open=110.0, high=118.0, low=109.0, close=116.0),
        healthy_snapshot(close=116.0), cfg,
    )
    assert decision.exit_reason == "TARGET_2"


def test_a_stop_beats_a_target_inside_the_same_bar(cfg):
    """Intrabar order is unknowable; assuming the good outcome is how backtests lie."""
    decision = sell(
        make_position(), BarInput(open=100.0, high=120.0, low=90.0, close=105.0),
        healthy_snapshot(close=105.0), cfg,
    )
    assert decision.exit_reason == "STOP_LOSS"


def test_target_exit_is_disabled_when_staged_exits_are_off(cfg):
    full_exit = cfg.model_copy(deep=True)
    full_exit.sell.staged_exits = False
    decision = sell(
        make_position(), BarInput(open=105.0, high=108.0, low=104.0, close=107.0),
        healthy_snapshot(close=107.0), full_exit,
    )
    assert decision.fraction == pytest.approx(1.0)
    assert decision.new_status == "SELL_SIGNAL"


def test_trend_breakdown_requires_two_consecutive_closes(cfg):
    snapshot = healthy_snapshot(close=96.0, ema20=99.0, sma50=98.0)
    bar = BarInput(open=97.0, high=97.5, low=95.6, close=96.0)

    first = sell(make_position(), bar, snapshot, cfg)
    assert not first.should_sell
    assert first.warnings and "one more close" in first.warnings[0]
    assert first.trend_break_bars == 1

    second = sell(make_position(trend_break_bars=1), bar, snapshot, cfg)
    assert second.should_sell
    assert second.exit_reason == "TREND_BREAKDOWN"


def test_momentum_deterioration_needs_all_three_conditions(cfg):
    bar = BarInput(open=101.0, high=102.0, low=99.0, close=100.5)

    # MACD crossed down and the histogram is falling, but RSI is still healthy → hold.
    partial = healthy_snapshot(close=100.5, macd=0.5, macd_signal=0.9, macd_hist=0.1,
                               macd_hist_prev3=0.4, rsi14=58.0)
    assert not sell(make_position(), bar, partial, cfg).should_sell

    full = healthy_snapshot(close=100.5, macd=0.5, macd_signal=0.9, macd_hist=0.1,
                            macd_hist_prev3=0.4, rsi14=38.0)
    decision = sell(make_position(), bar, full, cfg)
    assert decision.should_sell
    assert decision.exit_reason == "MOMENTUM_DETERIORATION"


def test_relative_strength_breakdown(cfg):
    snapshot = healthy_snapshot(rs_21=-6.0, rs_line_series=np.linspace(1.2, 0.9, 40))
    decision = sell(make_position(), BarInput(103.0, 104.0, 102.0, 103.0), snapshot, cfg)
    assert decision.should_sell
    assert decision.exit_reason == "RS_BREAKDOWN"


def test_breakout_failure_within_the_window(cfg):
    position = make_position(breakout_type="TWENTY_DAY", breakout_level=102.0, bars_held=5)
    snapshot = healthy_snapshot(close=100.0, atr14=2.0)
    decision = sell(position, BarInput(101.0, 101.5, 99.5, 100.0), snapshot, cfg)
    assert decision.should_sell
    assert decision.exit_reason == "BREAKOUT_FAILURE"


def test_breakout_failure_expires_after_the_window(cfg):
    position = make_position(breakout_type="TWENTY_DAY", breakout_level=102.0, bars_held=40)
    snapshot = healthy_snapshot(close=100.0, atr14=2.0)
    assert not sell(position, BarInput(101.0, 101.5, 99.5, 100.0), snapshot, cfg).should_sell


def test_regime_deterioration_only_fires_when_underwater(cfg):
    regime = neutral_regime(cfg)
    regime.regime = "BEAR"

    ahead = sell(make_position(), BarInput(104.0, 105.0, 103.0, 104.0),
                 healthy_snapshot(close=104.0), cfg, regime=regime)
    assert not ahead.should_sell

    behind = sell(make_position(), BarInput(98.0, 99.0, 96.5, 97.0),
                  healthy_snapshot(close=97.0, ema20=96.0, sma50=95.0), cfg, regime=regime)
    assert behind.should_sell
    assert behind.exit_reason == "REGIME_DETERIORATION"


def test_risk_increase_exit(cfg):
    snapshot = healthy_snapshot(close=101.0, atr_pct=6.0)
    decision = sell(make_position(), BarInput(101.0, 102.0, 100.0, 101.0), snapshot, cfg)
    assert decision.should_sell
    assert decision.exit_reason == "RISK_INCREASE"


def test_risk_increase_does_not_fire_on_a_well_ahead_position(cfg):
    position = make_position()
    snapshot = healthy_snapshot(close=107.0, atr_pct=6.0)
    # +1.4R ahead, so the rule's "< 1R" condition is not met.
    decision = sell(position, BarInput(106.0, 107.2, 105.5, 107.0), snapshot, cfg)
    assert decision.exit_reason != "RISK_INCREASE"


def test_fundamental_deterioration(cfg):
    decision = sell(
        make_position(), BarInput(103.0, 104.0, 102.0, 103.0), healthy_snapshot(), cfg,
        current_fundamental_score=30.0,
    )
    assert decision.should_sell
    assert decision.exit_reason == "FUNDAMENTAL_DETERIORATION"


def test_time_exit(cfg):
    position = make_position(holding_days=90)
    decision = sell(position, BarInput(101.0, 102.0, 100.0, 101.0),
                    healthy_snapshot(close=101.0), cfg)
    assert decision.should_sell
    assert decision.exit_reason == "TIME_EXIT"


def test_time_exit_does_not_fire_on_a_profitable_position(cfg):
    position = make_position(holding_days=90)
    decision = sell(position, BarInput(106.0, 106.5, 105.0, 106.0),
                    healthy_snapshot(close=106.0), cfg)
    assert decision.exit_reason != "TIME_EXIT"


def test_volatility_exit(cfg):
    snapshot = healthy_snapshot(close=98.0, realized_vol_20=0.95, ema20=97.0, sma50=96.0)
    decision = sell(make_position(), BarInput(99.0, 99.5, 97.5, 98.0), snapshot, cfg)
    assert decision.should_sell
    assert decision.exit_reason == "VOLATILITY_EXIT"


def test_a_healthy_position_is_held_with_explained_reasons(cfg):
    decision = sell(make_position(), BarInput(104.0, 105.0, 103.0, 104.5),
                    healthy_snapshot(close=104.5), cfg)
    assert not decision.should_sell
    assert len(decision.hold_reasons) >= 3
    assert decision.as_dict()["decision"] == "HOLD"


# --------------------------------------------------------------------------------------
# Trailing stop
# --------------------------------------------------------------------------------------


def test_trailing_does_not_activate_before_one_r(cfg):
    assert not should_activate(0.4, target1_hit=False, cfg=cfg)
    assert should_activate(1.2, target1_hit=False, cfg=cfg)
    assert should_activate(0.1, target1_hit=True, cfg=cfg)


def test_trailing_never_deactivates(cfg):
    assert should_activate(-2.0, target1_hit=False, cfg=cfg, already_active=True)


def test_chandelier_formula(cfg):
    result = compute_trailing_stop(
        highest_close_since_entry=120.0, atr=4.0, ma_value=None,
        previous_trailing=None, cfg=cfg, active=True,
    )
    assert result.stop == pytest.approx(120.0 - cfg.trailing.chandelier_atr_mult * 4.0)
    assert result.mode == "chandelier"


def test_trailing_stop_is_monotonically_non_decreasing(cfg):
    """Invariant 5 — a trailing stop that can loosen is not a trailing stop."""
    previous = None
    stops: list[float] = []
    for high, atr in ((110.0, 4.0), (118.0, 4.0), (112.0, 9.0), (120.0, 12.0), (121.0, 3.0)):
        result = compute_trailing_stop(high, atr, None, previous, cfg, active=True)
        previous = result.stop
        stops.append(result.stop)
    assert stops == sorted(stops), f"trailing stop moved down: {stops}"


def test_multiple_trailing_modes_take_the_highest(cfg):
    both = cfg.model_copy(deep=True)
    both.trailing.use_percent = True
    result = compute_trailing_stop(120.0, 4.0, None, None, both, active=True)
    assert result.stop == pytest.approx(max(120.0 - 2.5 * 4.0, 120.0 * 0.92))
    assert len(result.candidates) == 2


def test_effective_stop_is_the_higher_of_initial_and_trailing():
    assert effective_stop(95.0, None) == 95.0
    assert effective_stop(95.0, 90.0) == 95.0
    assert effective_stop(95.0, 104.0) == 104.0
