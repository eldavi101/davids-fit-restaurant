"""Indicator correctness and the look-ahead barrier."""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.indicators import core as ind
from app.domain.indicators.snapshot import compute_snapshot
from app.domain.types import BarWindow
from tests.conftest import breakout_series, build_series, uptrend_closes

# Wilder's original RSI worked example.
WILDER_CLOSES = np.array([
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
    45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
])


def test_sma_matches_hand_calculation():
    values = np.arange(1.0, 11.0)
    result = ind.sma(values, 3)
    assert np.isnan(result[:2]).all()
    assert result[2] == pytest.approx(2.0)
    assert result[-1] == pytest.approx(9.0)


def test_ema_seeds_from_sma_then_smooths():
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    result = ind.ema(values, 3)
    assert result[2] == pytest.approx(2.0)          # seed = SMA(1,2,3)
    assert result[3] == pytest.approx(0.5 * 4.0 + 0.5 * 2.0)


def test_rsi_matches_wilder_reference():
    result = ind.rsi(WILDER_CLOSES, 14)
    assert result[14] == pytest.approx(70.4642, abs=1e-3)
    assert result[15] == pytest.approx(66.2496, abs=1e-3)


def test_rsi_is_100_when_there_are_no_losses():
    result = ind.rsi(np.arange(1.0, 30.0), 14)
    assert result[-1] == pytest.approx(100.0)


def test_true_range_uses_previous_close():
    high = np.array([10.0, 12.0])
    low = np.array([9.0, 11.0])
    close = np.array([9.5, 11.5])
    tr = ind.true_range(high, low, close)
    assert tr[0] == pytest.approx(1.0)
    assert tr[1] == pytest.approx(2.5)   # 12.0 - 9.5 dominates the 1.0 intrabar range


def test_atr_is_wilder_smoothed():
    series = breakout_series()
    atr = ind.atr(series.high, series.low, series.close, 14)
    assert np.isnan(atr[:14]).all()
    assert atr[-1] > 0


def test_max_drawdown():
    assert ind.max_drawdown(np.array([100.0, 120.0, 90.0, 110.0])) == pytest.approx(-0.25)
    assert ind.max_drawdown(np.array([100.0, 110.0, 120.0])) == pytest.approx(0.0)


def test_relative_strength_formula():
    stock = np.array([100.0, 110.0])
    bench = np.array([100.0, 105.0])
    # (1.10 / 1.05 - 1) * 100
    assert ind.relative_strength(stock, bench, 1) == pytest.approx(4.7619, abs=1e-3)


def test_relative_strength_is_negative_when_underperforming():
    stock = np.array([100.0, 102.0])
    bench = np.array([100.0, 110.0])
    assert ind.relative_strength(stock, bench, 1) < 0


def test_beta_of_a_series_against_itself_is_one():
    closes = uptrend_closes(300)
    noisy = closes * (1 + 0.01 * np.sin(np.arange(300)))
    assert ind.beta(noisy, noisy, 252) == pytest.approx(1.0, abs=1e-6)


def test_indicators_return_nan_rather_than_guessing():
    short = np.array([1.0, 2.0, 3.0])
    assert np.isnan(ind.sma(short, 50)).all()
    assert np.isnan(ind.ema(short, 50)).all()
    assert np.isnan(ind.rsi(short, 14)).all()


# --------------------------------------------------------------------------------------
# Look-ahead barrier
# --------------------------------------------------------------------------------------


def test_bar_window_cannot_see_past_its_cursor():
    series = breakout_series()
    window = series.window(200)
    assert len(window) == 201
    assert len(window.close) == 201
    assert window.last_close == pytest.approx(float(series.close[200]))


def test_bar_window_rejects_an_out_of_range_cursor():
    series = breakout_series()
    with pytest.raises(IndexError):
        BarWindow(series, len(series))


def test_no_lookahead_indicators_match_a_truncated_series():
    """The heart of the bias defence.

    Every indicator computed at bar t through a window must equal the same indicator
    computed on a series that physically ends at bar t. If anything peeked past the
    cursor, these two would differ.
    """
    series = breakout_series()
    cursor = 300

    windowed = compute_snapshot(series.window(cursor), None)
    truncated = compute_snapshot(series.window(cursor).truncated_copy().window(-1), None)

    for field, value in windowed.as_dict().items():
        other = truncated.as_dict()[field]
        if isinstance(value, float) and isinstance(other, float):
            assert value == pytest.approx(other, rel=1e-9), f"{field} leaked future data"
        else:
            assert value == other, f"{field} leaked future data"


def test_future_bars_do_not_change_a_past_snapshot():
    """Appending bars after the cursor must not alter the snapshot at the cursor."""
    closes = uptrend_closes(320)
    short = build_series("X", closes)
    extended = build_series("X", np.concatenate([closes, closes[-1] * np.array([1.5, 1.8, 2.4])]))

    a = compute_snapshot(short.window(-1), None)
    b = compute_snapshot(extended.window(len(closes) - 1), None)

    assert a.close == pytest.approx(b.close)
    assert a.rsi14 == pytest.approx(b.rsi14)
    assert a.sma200 == pytest.approx(b.sma200)
    assert a.atr14 == pytest.approx(b.atr14)


def test_prior_highs_exclude_the_current_bar():
    """A breakout must clear the range that existed *before* today, not including today."""
    closes = np.concatenate([np.full(300, 100.0), np.array([150.0])])
    series = build_series("X", closes)
    snap = compute_snapshot(series.window(-1), None)
    assert snap.high_20_prior == pytest.approx(100.0 * 1.012, rel=1e-6)
    assert snap.close > snap.high_20_prior
