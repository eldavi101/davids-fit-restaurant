"""Scoring, levels, expected value and the thirteen-rule BUY gate."""

from __future__ import annotations

import numpy as np
import pytest

from app.core.config import ScoreWeights, StrategyConfig
from app.domain.indicators.snapshot import compute_snapshot
from app.domain.probability.model import (
    ProbabilityModel,
    build_features,
    expected_value,
    wilson_interval,
)
from app.domain.regime.engine import classify_regime, neutral_regime
from app.domain.scoring.components import ramp, ramp_inv, trapezoid
from app.domain.scoring.opportunity import categorize, score_stock
from app.domain.signals.buy_engine import BuyContext, evaluate_buy
from app.domain.signals.levels import compute_levels
from app.domain.types import Fundamentals, MarketContext
from tests.conftest import (
    bear_series,
    benchmark_series,
    breakout_series,
    build_series,
    uptrend_closes,
)

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def make_setup(cfg: StrategyConfig, stock=None, benchmarks=None):
    """Score a stock end-to-end and return every intermediate object."""
    stock = stock or breakout_series()
    if benchmarks is None:
        benchmarks = {"SPY": benchmark_series(), "QQQ": benchmark_series("QQQ", daily=0.0009)}
        for etf in ("XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"):
            benchmarks[etf] = benchmark_series(etf, daily=0.0008)

    regime = classify_regime(
        benchmark=benchmarks["SPY"].window(-1),
        sector_windows={s: b.window(-1) for s, b in benchmarks.items() if s.startswith("XL")},
        cfg=cfg,
        secondary={s: benchmarks[s].window(-1) for s in ("QQQ", "IWM") if s in benchmarks},
    )
    context = MarketContext(
        benchmark=benchmarks["SPY"].window(-1),
        sector_windows={"XLK": benchmarks["XLK"].window(-1)},
        secondary={"QQQ": benchmarks["QQQ"].window(-1)},
    )
    snapshot = compute_snapshot(stock.window(-1), context)
    score = score_stock(snapshot, regime, cfg)
    levels = compute_levels(snapshot, cfg)
    probability = ProbabilityModel(cfg).predict(build_features(score, snapshot, levels, regime))
    return snapshot, score, levels, probability, regime


def decide(cfg: StrategyConfig, context: BuyContext | None = None, **kwargs):
    snapshot, score, levels, probability, regime = make_setup(cfg, **kwargs)
    ctx = context or BuyContext(market_cap=8e11, spread_bps=3.0)
    return evaluate_buy(snapshot, score, levels, probability, regime, cfg, ctx)


def failed(decision) -> set[str]:
    return set(decision.rules_failed)


# --------------------------------------------------------------------------------------
# Shape helpers
# --------------------------------------------------------------------------------------


def test_ramp_bounds():
    assert ramp(5.0, 0.0, 10.0) == pytest.approx(0.5)
    assert ramp(-1.0, 0.0, 10.0) == 0.0
    assert ramp(99.0, 0.0, 10.0) == 1.0
    assert ramp(None, 0.0, 10.0, default=0.3) == 0.3


def test_ramp_inv_is_the_mirror_of_ramp():
    for x in (0.0, 2.5, 5.0, 7.5, 10.0):
        assert ramp_inv(x, 0.0, 10.0) == pytest.approx(1.0 - ramp(x, 0.0, 10.0))


def test_trapezoid_rises_holds_then_decays():
    assert trapezoid(0.5, 1.0, 2.0, 4.0, 8.0) == 0.0
    assert trapezoid(1.5, 1.0, 2.0, 4.0, 8.0) == pytest.approx(0.5)
    assert trapezoid(3.0, 1.0, 2.0, 4.0, 8.0) == 1.0
    assert trapezoid(6.0, 1.0, 2.0, 4.0, 8.0) == pytest.approx(0.5)
    assert trapezoid(20.0, 1.0, 2.0, 4.0, 8.0) == 0.0


# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError, match="must sum to 1.0"):
        ScoreWeights(trend=0.9, momentum=0.9)


def test_every_component_score_is_bounded(cfg):
    _, score, _, _, _ = make_setup(cfg)
    for name, value in score.component_dict().items():
        assert 0.0 <= value <= 100.0, f"{name} out of bounds: {value}"
    assert 0.0 <= score.opportunity_score <= 100.0
    assert 0.0 <= score.confidence <= 100.0


def test_category_bands():
    assert categorize(95.0) == "EXCEPTIONAL"
    assert categorize(87.0) == "STRONG_BUY"
    assert categorize(82.0) == "BUY"
    assert categorize(74.0) == "WATCH"
    assert categorize(60.0) == "NEUTRAL"
    assert categorize(20.0) == "AVOID"


def test_opportunity_score_equals_the_weighted_sum(cfg):
    _, score, _, _, _ = make_setup(cfg)
    expected = sum(
        getattr(cfg.weights, name) * value for name, value in score.component_dict().items()
    )
    assert score.opportunity_score == pytest.approx(min(expected, 100.0), abs=1e-6)


def test_downtrend_scores_far_below_an_uptrend(cfg):
    strong = decide(cfg).score.opportunity_score
    weak_series = build_series("WEAK", uptrend_closes(400, daily=-0.0020))
    weak = decide(cfg, stock=weak_series).score.opportunity_score
    assert weak < strong - 20


def test_sparse_fundamentals_are_held_at_neutral_not_invented(cfg):
    from app.domain.scoring.components import fundamental_score

    result = fundamental_score(Fundamentals(ticker="X", roe=0.2), cfg)
    assert result.score == 50.0
    assert "fundamental_data_sparse" in result.notes


def test_rich_fundamentals_are_actually_scored(cfg):
    from app.domain.scoring.components import fundamental_score

    strong = fundamental_score(
        Fundamentals(
            ticker="X", revenue_growth_yoy=0.35, earnings_growth_yoy=0.40, eps_surprise_pct=12.0,
            operating_margin=0.30, free_cash_flow=5e9, debt_to_equity=0.3, roe=0.30, peg=1.0,
        ),
        cfg,
    )
    weak = fundamental_score(
        Fundamentals(
            ticker="Y", revenue_growth_yoy=-0.10, earnings_growth_yoy=-0.20, eps_surprise_pct=-8.0,
            operating_margin=-0.05, free_cash_flow=-1e9, debt_to_equity=3.5, roe=-0.05, peg=6.0,
        ),
        cfg,
    )
    assert strong.score > 80
    assert weak.score < 20


def test_momentum_score_falls_when_rsi_becomes_extreme(cfg):
    """Momentum must not reward an already-extended stock (STRATEGY_SPEC §3)."""
    from app.domain.indicators.snapshot import IndicatorSnapshot
    from app.domain.scoring.components import momentum_score

    def snap(rsi: float) -> IndicatorSnapshot:
        return IndicatorSnapshot(
            ticker="X", bars_available=300, close=100.0, rsi14=rsi, rsi14_prev5=rsi - 3,
            macd=1.0, macd_signal=0.5, macd_hist=0.4, macd_hist_prev3=0.2,
            roc21=8.0, roc63=18.0, roc126=30.0, atr_pct=2.0,
        )

    healthy = momentum_score(snap(62.0), cfg).score
    extended = momentum_score(snap(88.0), cfg).score
    assert extended < healthy


# --------------------------------------------------------------------------------------
# Levels
# --------------------------------------------------------------------------------------


def test_stop_and_targets_follow_the_r_multiples(cfg):
    _, _, levels, _, _ = make_setup(cfg)
    assert levels.valid
    r = levels.risk_per_share
    assert levels.stop == pytest.approx(levels.entry - r)
    assert levels.target1 == pytest.approx(levels.entry + cfg.levels.target_r1 * r)
    assert levels.target2 == pytest.approx(levels.entry + cfg.levels.target_r2 * r)


def test_reward_risk_is_the_blend_of_both_targets(cfg):
    _, _, levels, _, _ = make_setup(cfg)
    expected = (cfg.levels.target_r1 + cfg.levels.target_r2) / 2.0
    assert levels.reward_risk == pytest.approx(expected)


def test_stop_is_never_above_the_entry(cfg):
    _, _, levels, _, _ = make_setup(cfg)
    assert 0 < levels.stop < levels.entry


def test_risk_is_capped_by_max_stop_pct(cfg):
    tight = cfg.model_copy(deep=True)
    tight.levels.max_stop_pct = 0.02
    tight.levels.stop_atr_mult = 8.0
    _, _, levels, _, _ = make_setup(tight)
    assert levels.stop_pct <= 0.02 + 1e-9


def test_levels_are_invalid_without_atr(cfg):
    from app.domain.indicators.snapshot import IndicatorSnapshot

    levels = compute_levels(IndicatorSnapshot(ticker="X", bars_available=300, close=50.0), cfg)
    assert not levels.valid
    assert levels.reason == "atr_unavailable"


# --------------------------------------------------------------------------------------
# Probability and expected value
# --------------------------------------------------------------------------------------


def test_expected_value_formula():
    # 0.5 × 2.0 − 0.5 × 1.0
    assert expected_value(0.5, 2.0, 1.0) == pytest.approx(0.5)
    assert expected_value(0.3, 1.5, 1.0) == pytest.approx(0.3 * 1.5 - 0.7)


def test_expected_value_is_negative_for_a_poor_edge():
    assert expected_value(0.25, 1.5, 1.0) < 0


def test_probability_without_evidence_reports_a_prior_and_zero_samples(cfg):
    estimate = ProbabilityModel(cfg).predict({"trend": 90.0, "opportunity_score": 90.0})
    assert estimate.method == "prior"
    assert estimate.reliability == "PRIOR_ONLY"
    assert estimate.sample_size == 0
    assert estimate.probability == pytest.approx(cfg.probability.prior_win_rate)
    assert "insufficient historical evidence" in estimate.notes[0]


def test_probability_is_never_derived_from_the_score(cfg):
    """Two very different scores with no history must return the same prior."""
    model = ProbabilityModel(cfg)
    low = model.predict({"opportunity_score": 55.0})
    high = model.predict({"opportunity_score": 99.0})
    assert low.probability == high.probability


def test_wilson_interval_widens_with_a_small_sample():
    narrow = wilson_interval(500, 1000)
    wide = wilson_interval(5, 10)
    assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])
    assert 0.0 <= wide[0] <= wide[1] <= 1.0


# --------------------------------------------------------------------------------------
# The BUY gate — each rule must be able to block on its own
# --------------------------------------------------------------------------------------


def test_the_reference_setup_passes_every_rule(cfg):
    decision = decide(cfg)
    assert decision.should_buy, f"blocked by {decision.rules_failed}: {decision.blocking_reason}"
    assert len(decision.rules) == 13
    assert decision.reasons, "a passing BUY must be explainable"


def test_a_high_score_alone_does_not_create_a_signal(cfg):
    """Requirement 25: score is necessary, never sufficient."""
    lenient = cfg.model_copy(deep=True)
    lenient.buy_gate.min_opportunity_score = 0.0   # rule 1 can no longer block anything

    flat = build_series("FLAT", np.full(400, 100.0) * (1 + 0.001 * np.sin(np.arange(400) / 5)))
    decision = decide(lenient, stock=flat)
    assert not decision.should_buy
    assert "min_opportunity_score" not in failed(decision)
    assert failed(decision), "other rules must still block a poor setup"


def test_rule_min_opportunity_score_blocks(cfg):
    strict = cfg.model_copy(deep=True)
    strict.buy_gate.min_opportunity_score = 99.9
    decision = decide(strict)
    assert not decision.should_buy
    assert "min_opportunity_score" in failed(decision)


def test_rule_bullish_trend_blocks_a_downtrend(cfg):
    decision = decide(cfg, stock=build_series("DOWN", uptrend_closes(400, daily=-0.002)))
    assert "bullish_trend" in failed(decision)


def test_rule_liquidity_blocks_a_small_company(cfg):
    decision = decide(cfg, context=BuyContext(market_cap=1e8, spread_bps=3.0))
    assert "liquidity" in failed(decision)
    assert "market cap" in decision.rules[2].detail


def test_rule_liquidity_blocks_a_thin_tape(cfg):
    thin = breakout_series()
    thin.volume[:] = 50_000.0
    decision = decide(cfg, stock=thin, context=BuyContext(market_cap=8e11, spread_bps=3.0))
    assert "liquidity" in failed(decision)


def test_rule_spread_blocks_a_wide_market(cfg):
    decision = decide(cfg, context=BuyContext(market_cap=8e11, spread_bps=90.0))
    assert "spread" in failed(decision)


def test_rule_spread_is_skipped_when_no_quote_exists(cfg):
    decision = decide(cfg, context=BuyContext(market_cap=8e11, spread_bps=None))
    spread_rule = next(r for r in decision.rules if r.id == "spread")
    assert spread_rule.passed
    assert "skipped" in spread_rule.detail


def test_rule_expected_value_blocks_a_negative_edge(cfg):
    hostile = cfg.model_copy(deep=True)
    hostile.probability.prior_win_rate = 0.05      # EV = 0.05·2.25 − 0.95·1.0 < 0
    decision = decide(hostile)
    assert "positive_expected_value" in failed(decision)


def test_rule_reward_risk_blocks(cfg):
    demanding = cfg.model_copy(deep=True)
    demanding.buy_gate.min_reward_risk = 9.0
    decision = decide(demanding)
    assert "min_reward_risk" in failed(decision)


def test_rule_relative_strength_blocks_a_laggard(cfg):
    """A rising stock that rises more slowly than SPY must not qualify."""
    fast_market = {"SPY": benchmark_series(daily=0.0060), "QQQ": benchmark_series("QQQ", daily=0.0060)}
    for etf in ("XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"):
        fast_market[etf] = benchmark_series(etf, daily=0.0060)
    decision = decide(cfg, benchmarks=fast_market)
    assert "relative_strength" in failed(decision)


def test_rule_market_regime_blocks_new_buys_in_a_bear(cfg):
    bear = {"SPY": bear_series(), "QQQ": bear_series("QQQ")}
    for etf in ("XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"):
        bear[etf] = bear_series(etf)
    _, _, _, _, regime = make_setup(cfg, benchmarks=bear)
    assert regime.regime in ("BEAR", "HIGH_VOLATILITY", "RISK_OFF")

    decision = decide(cfg, benchmarks=bear)
    if regime.regime == "BEAR":
        assert "market_regime" in failed(decision)
    assert not decision.should_buy


def test_rule_valid_stop_blocks_an_out_of_band_stop(cfg):
    impossible = cfg.model_copy(deep=True)
    impossible.levels.min_stop_atr_mult = 50.0
    decision = decide(impossible)
    assert "valid_stop" in failed(decision)


def test_rule_multiple_confirmations_blocks(cfg):
    demanding = cfg.model_copy(deep=True)
    demanding.buy_gate.min_confirmations = 5
    demanding.buy_gate.confirmation_threshold = 95.0
    decision = decide(demanding)
    assert "multiple_confirmations" in failed(decision)


def test_rule_no_duplicate_alert_blocks(cfg):
    decision = decide(cfg, context=BuyContext(market_cap=8e11, spread_bps=3.0, has_open_alert=True))
    assert "no_duplicate_alert" in failed(decision)


def test_rule_earnings_window_blocks(cfg):
    decision = decide(
        cfg, context=BuyContext(market_cap=8e11, spread_bps=3.0, days_to_earnings=2)
    )
    assert "earnings_window" in failed(decision)


def test_rule_earnings_window_passes_outside_the_blackout(cfg):
    decision = decide(
        cfg, context=BuyContext(market_cap=8e11, spread_bps=3.0, days_to_earnings=30)
    )
    assert "earnings_window" not in failed(decision)


def test_rule_data_integrity_blocks_stale_data(cfg):
    """Requirement 51 — stale data must never produce a new BUY."""
    decision = decide(
        cfg,
        context=BuyContext(
            market_cap=8e11, spread_bps=3.0, data_fresh=False, data_issues=["last bar 3 days old"]
        ),
    )
    assert "data_integrity" in failed(decision)
    assert not decision.should_buy


def test_rule_data_integrity_blocks_short_history(cfg):
    decision = decide(cfg, stock=build_series("SHORT", uptrend_closes(120)))
    assert "data_integrity" in failed(decision)


# --------------------------------------------------------------------------------------
# Regime gating
# --------------------------------------------------------------------------------------


def test_regime_tightens_the_score_requirement(cfg):
    snapshot, score, levels, probability, _ = make_setup(cfg)

    results = {}
    for regime_name, delta in (("STRONG_BULL", -2.0), ("NEUTRAL", 4.0), ("HIGH_VOLATILITY", 10.0)):
        regime = neutral_regime(cfg)
        regime.regime = regime_name
        regime.score_delta = delta
        regime.min_reward_risk = cfg.regime.min_reward_risk_override.get(
            regime_name, cfg.buy_gate.min_reward_risk
        )
        decision = evaluate_buy(
            snapshot, score, levels, probability, regime, cfg,
            BuyContext(market_cap=8e11, spread_bps=3.0),
        )
        results[regime_name] = decision.effective_min_score

    assert results["STRONG_BULL"] < results["NEUTRAL"] < results["HIGH_VOLATILITY"]


def test_regime_engine_refuses_to_guess_without_history(cfg):
    from app.core.errors import RegimeUnknownError

    with pytest.raises(RegimeUnknownError):
        classify_regime(benchmark=None, sector_windows={}, cfg=cfg)


def test_regime_classifies_a_broad_advance_as_bullish(cfg, bull_benchmarks):
    regime = classify_regime(
        benchmark=bull_benchmarks["SPY"].window(-1),
        sector_windows={s: b.window(-1) for s, b in bull_benchmarks.items() if s.startswith("XL")},
        cfg=cfg,
        secondary={s: bull_benchmarks[s].window(-1) for s in ("QQQ", "IWM")},
    )
    assert regime.regime in ("STRONG_BULL", "BULL")
    assert regime.allows_new_buys
    assert regime.breadth_pct == pytest.approx(1.0)
