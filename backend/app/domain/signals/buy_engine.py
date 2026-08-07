"""The BUY gate.

Thirteen independent rules, every one of which must pass (STRATEGY_SPEC.md §14). The
engine is a pure function: it is handed a scored snapshot, levels, a probability estimate
and a small amount of context, and it returns a decision plus the complete rule ledger.

Two properties are load-bearing:

* **A high OpportunityScore is necessary but never sufficient.** Rule 1 is one of
  thirteen, and the confirmation rule (10) additionally requires several independent
  components to agree.
* **Every evaluation is fully explained**, pass or fail. The ledger goes into
  ``stock_scores`` and ``audit_logs`` for every stock the scanner touches, not just the
  ones that fire.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import StrategyConfig
from app.domain.indicators.snapshot import IndicatorSnapshot
from app.domain.probability.model import ProbabilityEstimate
from app.domain.regime.engine import RegimeResult
from app.domain.scoring.opportunity import ScoreResult
from app.domain.signals.levels import Levels


@dataclass(frozen=True, slots=True)
class RuleResult:
    id: str
    passed: bool
    detail: str

    def as_dict(self) -> dict:
        return {"rule": self.id, "passed": self.passed, "detail": self.detail}


@dataclass
class BuyContext:
    """Facts the engine cannot derive from price data alone."""

    market_cap: float | None = None
    spread_bps: float | None = None
    days_to_earnings: int | None = None
    has_open_alert: bool = False
    data_fresh: bool = True
    data_issues: list[str] = field(default_factory=list)
    security_type: str = "COMMON"


@dataclass
class BuyDecision:
    ticker: str
    should_buy: bool
    rules: list[RuleResult]
    reasons: list[str]
    risk_factors: list[str]
    score: ScoreResult
    levels: Levels
    probability: ProbabilityEstimate
    regime: RegimeResult
    effective_min_score: float
    effective_min_reward_risk: float

    @property
    def rules_passed(self) -> list[str]:
        return [r.id for r in self.rules if r.passed]

    @property
    def rules_failed(self) -> list[str]:
        return [r.id for r in self.rules if not r.passed]

    @property
    def blocking_reason(self) -> str | None:
        failed = [r for r in self.rules if not r.passed]
        return failed[0].detail if failed else None

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "decision": "BUY" if self.should_buy else "NO_BUY",
            "rules": [r.as_dict() for r in self.rules],
            "rules_passed": self.rules_passed,
            "rules_failed": self.rules_failed,
            "reasons": self.reasons,
            "risk_factors": self.risk_factors,
            "effective_min_score": self.effective_min_score,
            "effective_min_reward_risk": self.effective_min_reward_risk,
        }


def _confirmations(score: ScoreResult, threshold: float) -> list[str]:
    return [name for name, value in score.core_scores.items() if value >= threshold]


def evaluate_buy(
    snapshot: IndicatorSnapshot,
    score: ScoreResult,
    levels: Levels,
    probability: ProbabilityEstimate,
    regime: RegimeResult,
    cfg: StrategyConfig,
    context: BuyContext | None = None,
) -> BuyDecision:
    ctx = context or BuyContext()
    g = cfg.buy_gate
    u = cfg.universe
    rules: list[RuleResult] = []

    effective_min_score = g.min_opportunity_score + regime.score_delta
    effective_min_rr = max(g.min_reward_risk, regime.min_reward_risk)

    # 1 — opportunity score, tightened by regime
    rules.append(
        RuleResult(
            "min_opportunity_score",
            score.opportunity_score >= effective_min_score,
            f"score {score.opportunity_score:.1f} vs required {effective_min_score:.1f} "
            f"(base {g.min_opportunity_score:.0f}, regime {regime.regime} {regime.score_delta:+.0f})",
        )
    )

    # 2 — bullish trend, structurally confirmed
    c = snapshot.close
    trend_ok = (
        score.trend.score >= g.min_trend_score
        and snapshot.ema20 is not None and c > snapshot.ema20
        and snapshot.sma50 is not None and c > snapshot.sma50
        and snapshot.sma200 is not None and c > snapshot.sma200
    )
    rules.append(
        RuleResult(
            "bullish_trend",
            trend_ok,
            f"TrendScore {score.trend.score:.1f} (min {g.min_trend_score:.0f}), "
            f"price {'above' if trend_ok else 'not above'} all of EMA20/SMA50/SMA200",
        )
    )

    # 3 — liquidity and size
    liquidity_failures = []
    if c < u.min_price:
        liquidity_failures.append(f"price ${c:.2f} < ${u.min_price:.2f}")
    if ctx.market_cap is not None and ctx.market_cap < u.min_market_cap:
        liquidity_failures.append(f"market cap ${ctx.market_cap/1e6:.0f}M < ${u.min_market_cap/1e6:.0f}M")
    if snapshot.dollar_volume_50 is not None and snapshot.dollar_volume_50 < u.min_avg_dollar_volume:
        liquidity_failures.append(
            f"dollar volume ${snapshot.dollar_volume_50/1e6:.1f}M < ${u.min_avg_dollar_volume/1e6:.0f}M"
        )
    if snapshot.vol_avg50 is not None and snapshot.vol_avg50 < u.min_avg_volume:
        liquidity_failures.append(f"avg volume {snapshot.vol_avg50:,.0f} < {u.min_avg_volume:,.0f}")
    rules.append(
        RuleResult(
            "liquidity",
            not liquidity_failures,
            "; ".join(liquidity_failures) if liquidity_failures else "liquidity requirements met",
        )
    )

    # 4 — spread. A missing quote does not fail the rule, but it is recorded.
    if ctx.spread_bps is None:
        rules.append(RuleResult("spread", True, "no quote available — spread check skipped"))
    else:
        rules.append(
            RuleResult(
                "spread",
                ctx.spread_bps <= g.max_spread_bps,
                f"spread {ctx.spread_bps:.1f} bps vs max {g.max_spread_bps:.0f} bps",
            )
        )

    # 5 — positive expected value
    ev = probability.expected_value_r
    rules.append(
        RuleResult(
            "positive_expected_value",
            ev > g.min_expected_value_r,
            f"EV {ev:+.3f}R (p={probability.probability:.2f} from n={probability.sample_size}, "
            f"avg win {probability.avg_win_r:.2f}R, avg loss {probability.avg_loss_r:.2f}R)",
        )
    )

    # 6 — reward/risk
    rules.append(
        RuleResult(
            "min_reward_risk",
            levels.reward_risk >= effective_min_rr,
            f"R/R {levels.reward_risk:.2f} vs min {effective_min_rr:.2f}",
        )
    )

    # 7 — relative strength versus BOTH market and sector
    rs_ok = (
        score.relative_strength.score >= g.min_relative_strength_score
        and snapshot.rs_21 is not None and snapshot.rs_21 > 0
        and snapshot.rs_sector_63 is not None and snapshot.rs_sector_63 > 0
    )
    rules.append(
        RuleResult(
            "relative_strength",
            rs_ok,
            f"RS score {score.relative_strength.score:.1f} (min {g.min_relative_strength_score:.0f}), "
            f"RS21 vs SPY {snapshot.rs_21 if snapshot.rs_21 is not None else float('nan'):+.2f}%, "
            f"RS63 vs sector "
            f"{snapshot.rs_sector_63 if snapshot.rs_sector_63 is not None else float('nan'):+.2f}%",
        )
    )

    # 8 — market regime
    rules.append(
        RuleResult(
            "market_regime",
            regime.allows_new_buys,
            f"regime {regime.regime} "
            f"({'permits' if regime.allows_new_buys else 'blocks'} new BUY signals)",
        )
    )

    # 9 — valid stop
    rules.append(
        RuleResult(
            "valid_stop",
            levels.valid,
            levels.reason
            or f"stop ${levels.stop:.2f} = {levels.stop_atr_mult:.2f} ATR "
               f"({levels.stop_pct:.1%} risk)",
        )
    )

    # 10 — multiple independent confirmations
    confirmed = _confirmations(score, g.confirmation_threshold)
    setup_present = (
        score.breakout.score >= g.min_breakout_score
        or score.momentum.score >= g.momentum_override_score
    )
    rules.append(
        RuleResult(
            "multiple_confirmations",
            len(confirmed) >= g.min_confirmations and setup_present,
            f"{len(confirmed)}/{g.min_confirmations} components ≥ {g.confirmation_threshold:.0f} "
            f"({', '.join(confirmed) if confirmed else 'none'}); "
            f"setup {'present' if setup_present else 'absent'} "
            f"(breakout {score.breakout.score:.0f}, momentum {score.momentum.score:.0f})",
        )
    )

    # 11 — no duplicate open alert
    rules.append(
        RuleResult(
            "no_duplicate_alert",
            not ctx.has_open_alert,
            "an open alert already exists for this ticker" if ctx.has_open_alert
            else "no open alert for this ticker",
        )
    )

    # 12 — earnings blackout
    if ctx.days_to_earnings is None:
        rules.append(RuleResult("earnings_window", True, "no scheduled earnings date known"))
    else:
        rules.append(
            RuleResult(
                "earnings_window",
                ctx.days_to_earnings > g.earnings_blackout_days,
                f"earnings in {ctx.days_to_earnings} day(s) vs blackout "
                f"{g.earnings_blackout_days} day(s)",
            )
        )

    # 13 — data integrity (requirement 51)
    integrity_issues = list(ctx.data_issues)
    if not ctx.data_fresh:
        integrity_issues.append("market data stale")
    if snapshot.bars_available < cfg.min_bars_required:
        integrity_issues.append(
            f"insufficient history ({snapshot.bars_available} < {cfg.min_bars_required} bars)"
        )
    for name in ("atr14", "sma200", "rsi14"):
        if getattr(snapshot, name) is None:
            integrity_issues.append(f"{name} unavailable")
    rules.append(
        RuleResult(
            "data_integrity",
            not integrity_issues,
            "; ".join(integrity_issues) if integrity_issues else "inputs complete and fresh",
        )
    )

    should_buy = all(r.passed for r in rules)

    return BuyDecision(
        ticker=snapshot.ticker,
        should_buy=should_buy,
        rules=rules,
        reasons=build_reasons(snapshot, score, levels, probability, regime) if should_buy else [],
        risk_factors=build_risk_factors(snapshot, score, levels, ctx),
        score=score,
        levels=levels,
        probability=probability,
        regime=regime,
        effective_min_score=effective_min_score,
        effective_min_reward_risk=effective_min_rr,
    )


def build_reasons(
    snapshot: IndicatorSnapshot,
    score: ScoreResult,
    levels: Levels,
    probability: ProbabilityEstimate,
    regime: RegimeResult,
) -> list[str]:
    """Human-readable justification — what the WHY WE BOUGHT panel renders."""
    reasons: list[str] = []

    if score.trend.score >= 70:
        reasons.append(f"Strong bullish trend (TrendScore {score.trend.score:.0f}/100)")
    if snapshot.ema20 and snapshot.sma50 and snapshot.sma200:
        reasons.append("Price above the 20/50/200 moving averages")
    if snapshot.ema20 and snapshot.sma50 and snapshot.sma200 and (
        snapshot.ema20 > snapshot.sma50 > snapshot.sma200
    ):
        reasons.append("Moving averages stacked bullishly (EMA20 > SMA50 > SMA200)")
    if snapshot.rs_21 is not None and snapshot.rs_21 > 0:
        reasons.append(f"Outperforming SPY by {snapshot.rs_21:+.1f}% over 21 days")
    if snapshot.rs_sector_63 is not None and snapshot.rs_sector_63 > 0:
        reasons.append(f"Outperforming its sector by {snapshot.rs_sector_63:+.1f}% over 63 days")
    if snapshot.rel_volume is not None and snapshot.rel_volume >= 1.2:
        reasons.append(f"Relative volume {snapshot.rel_volume:.2f}× the 50-day average")
    if score.breakout_type != "NONE":
        label = score.breakout_type.replace("_", " ").title()
        reasons.append(f"{label} breakout confirmed")
    if snapshot.dist_52w_high_pct is not None and snapshot.dist_52w_high_pct > -5:
        reasons.append(f"Trading {abs(snapshot.dist_52w_high_pct):.1f}% from the 52-week high")
    if probability.expected_value_r > 0:
        reasons.append(
            f"Positive expected value ({probability.expected_value_r:+.2f}R, "
            f"p={probability.probability:.0%} from {probability.sample_size} comparable setups)"
            if probability.sample_size
            else f"Positive expected value ({probability.expected_value_r:+.2f}R, prior estimate)"
        )
    reasons.append(f"Reward/risk {levels.reward_risk:.2f} with the stop at ${levels.stop:.2f}")
    reasons.append(f"Market regime {regime.regime.replace('_', ' ').title()}")
    if score.fundamental.score >= 65:
        reasons.append(f"Supportive fundamentals (score {score.fundamental.score:.0f}/100)")
    return reasons


def build_risk_factors(
    snapshot: IndicatorSnapshot,
    score: ScoreResult,
    levels: Levels,
    ctx: BuyContext,
) -> list[str]:
    """What could go wrong — shown next to the reasons, never hidden behind them."""
    risks: list[str] = []

    if snapshot.atr_pct is not None and snapshot.atr_pct > 4.0:
        risks.append(f"ATR {snapshot.atr_pct:.1f}% — above-average volatility")
    if snapshot.rsi14 is not None and snapshot.rsi14 > 75:
        risks.append(f"RSI {snapshot.rsi14:.0f} — extended in the short term")
    if ctx.days_to_earnings is not None and ctx.days_to_earnings <= 21:
        risks.append(f"Earnings in {ctx.days_to_earnings} days")
    if levels.stop_pct > 0.08:
        risks.append(f"Stop {levels.stop_pct:.1%} away — wider than typical")
    if score.risk.score < 50:
        risks.append(f"Risk quality below average (score {score.risk.score:.0f}/100)")
    if score.fundamental.notes and "fundamental_data_sparse" in score.fundamental.notes:
        risks.append("Fundamental data sparse — that component is neutral, not confirmed")
    if snapshot.max_drawdown_252 is not None and snapshot.max_drawdown_252 < -0.4:
        risks.append(f"Fell {abs(snapshot.max_drawdown_252):.0%} at its worst over the past year")
    if ctx.spread_bps is not None and ctx.spread_bps > 15:
        risks.append(f"Spread {ctx.spread_bps:.0f} bps — execution cost is material")
    return risks
