"""The SELL engine.

Thirteen trigger families evaluated in strict priority order (STRATEGY_SPEC.md §17). The
first one that fires produces the exit, so a stop breach can never be overridden by a
softer signal later in the list.

**Overbought RSI is not a sell trigger anywhere in this module** (requirement 31). RSI
appears only in ``MOMENTUM_DETERIORATION``, and there only *below* 45 in conjunction with
a MACD cross and a falling histogram. ``test_rsi_overbought_alone_does_not_sell`` pins
this behaviour.

Like the BUY engine this is a pure function over an explicit state object, so the live
monitor and the backtester exercise identical logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import StrategyConfig
from app.domain.indicators.snapshot import IndicatorSnapshot
from app.domain.regime.engine import RegimeResult
from app.domain.signals.trailing import (
    TrailingResult,
    compute_trailing_stop,
    effective_stop,
    should_activate,
)


@dataclass
class TrackedPosition:
    """Everything the SELL engine needs to know about an open alert."""

    ticker: str
    entry_price: float
    entry_ts: datetime
    initial_stop: float
    target1: float
    target2: float
    risk_per_share: float

    highest_close_since_entry: float
    highest_price_since_entry: float
    lowest_price_since_entry: float

    trailing_stop: float | None = None
    trailing_active: bool = False
    remaining_fraction: float = 1.0
    status: str = "ACTIVE"

    target1_hit: bool = False
    target2_hit: bool = False

    bars_held: int = 0
    holding_days: int = 0
    trend_break_bars: int = 0

    entry_atr_pct: float | None = None
    entry_realized_vol: float | None = None
    entry_fundamental_score: float | None = None
    breakout_level: float | None = None
    breakout_type: str = "NONE"

    def unrealized_r(self, price: float) -> float:
        if self.risk_per_share <= 0:
            return 0.0
        return (price - self.entry_price) / self.risk_per_share

    def return_pct(self, price: float) -> float:
        if self.entry_price <= 0:
            return 0.0
        return 100.0 * (price / self.entry_price - 1.0)


@dataclass
class SellDecision:
    should_sell: bool
    exit_reason: str | None
    detail: str | None
    fraction: float
    suggested_fill: float | None
    rules_fired: list[str]
    trailing: TrailingResult | None
    new_status: str | None
    hold_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Updated consecutive-close counter the caller must persist back onto the position,
    #: so the two-bar trend-breakdown confirmation survives across monitor passes.
    trend_break_bars: int = 0

    def as_dict(self) -> dict:
        return {
            "decision": "SELL" if self.should_sell else "HOLD",
            "exit_reason": self.exit_reason,
            "detail": self.detail,
            "fraction": self.fraction,
            "rules_fired": self.rules_fired,
            "hold_reasons": self.hold_reasons,
            "warnings": self.warnings,
            "trailing": self.trailing.as_dict() if self.trailing else None,
        }


@dataclass(frozen=True, slots=True)
class BarInput:
    """The bar being evaluated. Kept separate from the snapshot so intrabar stop
    evaluation is explicit rather than inferred from a close price."""

    open: float
    high: float
    low: float
    close: float


def evaluate_sell(
    position: TrackedPosition,
    bar: BarInput,
    snapshot: IndicatorSnapshot,
    regime: RegimeResult,
    cfg: StrategyConfig,
    current_fundamental_score: float | None = None,
) -> SellDecision:
    sc = cfg.sell
    fired: list[str] = []
    warnings: list[str] = []

    # ---- stops in force ENTERING this bar ---------------------------------------------
    # The level a bar can be stopped out against is the one that existed before the bar
    # opened. Deriving it from this bar's own close and then testing it against this bar's
    # own low would be intrabar look-ahead — it would report exits that never happened.
    unrealized_r = position.unrealized_r(bar.close)
    current_stop = effective_stop(position.initial_stop, position.trailing_stop)

    # The updated level, computed from this bar's close, takes effect from the NEXT bar.
    # It is returned so the caller can persist it.
    active_next = should_activate(
        unrealized_r, position.target1_hit, cfg, already_active=position.trailing_active
    )
    trailing = compute_trailing_stop(
        highest_close_since_entry=max(position.highest_close_since_entry, bar.close),
        atr=snapshot.atr14,
        ma_value=snapshot.ema20 if cfg.trailing.ma_stop_period == 20 else snapshot.sma50,
        previous_trailing=position.trailing_stop,
        cfg=cfg,
        active=active_next,
    )

    below_trend = (
        snapshot.sma50 is not None and bar.close < snapshot.sma50
        and snapshot.ema20 is not None and bar.close < snapshot.ema20
    )
    trend_break_bars = position.trend_break_bars + 1 if below_trend else 0

    def sell(reason: str, detail: str, fraction: float, fill: float, status: str) -> SellDecision:
        fired.append(reason.lower())
        return SellDecision(
            should_sell=True,
            exit_reason=reason,
            detail=detail,
            fraction=min(fraction, position.remaining_fraction),
            suggested_fill=fill,
            rules_fired=fired,
            trailing=trailing,
            new_status=status,
            warnings=warnings,
            trend_break_bars=trend_break_bars,
        )

    # ---- 1 & 2: stops (intrabar) ------------------------------------------------------
    if bar.low <= current_stop:
        # A gap-down fills at the open, not at the stop price. Modelling it the other way
        # is the single most flattering error a backtest can make.
        fill = min(bar.open, current_stop)
        trailing_in_force = (
            position.trailing_stop is not None
            and position.trailing_active
            and position.trailing_stop > position.initial_stop
        )
        if trailing_in_force:
            return sell(
                "TRAILING_STOP",
                f"Trailing stop ${position.trailing_stop:.2f} breached on the low ${bar.low:.2f}"
                + (f" — gap fill at ${fill:.2f}" if fill < position.trailing_stop else ""),
                1.0,
                fill,
                "SELL_SIGNAL",
            )
        return sell(
            "STOP_LOSS",
            f"Stop ${position.initial_stop:.2f} breached on the low ${bar.low:.2f}"
            + (f" — gap fill at ${fill:.2f}" if fill < position.initial_stop else ""),
            1.0,
            fill,
            "STOPPED",
        )

    # ---- 3: target 2 -------------------------------------------------------------------
    if bar.high >= position.target2 and not position.target2_hit:
        if sc.staged_exits:
            return sell(
                "TARGET_2",
                f"Target 2 ${position.target2:.2f} reached — closing "
                f"{sc.target2_fraction:.0%}, remainder on the trailing stop",
                sc.target2_fraction,
                position.target2,
                "TARGET_2_HIT",
            )
        return sell(
            "TARGET_2",
            f"Target 2 ${position.target2:.2f} reached — full exit",
            1.0,
            position.target2,
            "SELL_SIGNAL",
        )

    # ---- 4: target 1 -------------------------------------------------------------------
    if bar.high >= position.target1 and not position.target1_hit:
        if sc.staged_exits:
            return sell(
                "TARGET_1",
                f"Target 1 ${position.target1:.2f} reached — closing "
                f"{sc.target1_fraction:.0%}, trailing stop activated",
                sc.target1_fraction,
                position.target1,
                "TARGET_1_HIT",
            )
        return sell(
            "TARGET_1",
            f"Target 1 ${position.target1:.2f} reached — full exit",
            1.0,
            position.target1,
            "SELL_SIGNAL",
        )

    # ---- 5: trend breakdown (needs confirmation over consecutive closes) ---------------
    if below_trend and trend_break_bars >= sc.trend_breakdown_confirm_bars:
        return sell(
            "TREND_BREAKDOWN",
            f"Closed below EMA20 (${snapshot.ema20:.2f}) and SMA50 (${snapshot.sma50:.2f}) "
            f"for {trend_break_bars} consecutive sessions",
            1.0,
            bar.close,
            "SELL_SIGNAL",
        )
    if below_trend:
        warnings.append("Price below EMA20 and SMA50 — one more close confirms a trend breakdown")

    # ---- 6: momentum deterioration -----------------------------------------------------
    # NOTE: this is the only rule referencing RSI, and only on the WEAK side.
    momentum_gone = (
        snapshot.macd is not None and snapshot.macd_signal is not None
        and snapshot.macd < snapshot.macd_signal
        and snapshot.rsi14 is not None and snapshot.rsi14 < sc.momentum_rsi_threshold
        and snapshot.macd_hist is not None and snapshot.macd_hist_prev3 is not None
        and snapshot.macd_hist < snapshot.macd_hist_prev3
    )
    if momentum_gone:
        return sell(
            "MOMENTUM_DETERIORATION",
            f"MACD below its signal line, RSI {snapshot.rsi14:.0f} below "
            f"{sc.momentum_rsi_threshold:.0f}, histogram falling",
            1.0,
            bar.close,
            "SELL_SIGNAL",
        )

    # ---- 7: relative strength breakdown -------------------------------------------------
    rs_broken = (
        snapshot.rs_21 is not None and snapshot.rs_21 < 0
        and len(snapshot.rs_line_series) > 11
        and snapshot.rs_line_series[-1] < snapshot.rs_line_series[-11]
    )
    if rs_broken:
        return sell(
            "RS_BREAKDOWN",
            f"Underperforming SPY by {snapshot.rs_21:.1f}% over 21 days with a falling RS line",
            1.0,
            bar.close,
            "SELL_SIGNAL",
        )

    # ---- 8: breakout failure -------------------------------------------------------------
    if (
        position.breakout_type != "NONE"
        and position.breakout_level is not None
        and snapshot.atr14 is not None
        and position.bars_held <= sc.breakout_failure_max_bars
    ):
        failure_level = position.breakout_level - sc.breakout_failure_atr_buffer * snapshot.atr14
        if bar.close < failure_level:
            return sell(
                "BREAKOUT_FAILURE",
                f"Closed back below the breakout level ${position.breakout_level:.2f} "
                f"(failure threshold ${failure_level:.2f}) {position.bars_held} bars after entry",
                1.0,
                bar.close,
                "SELL_SIGNAL",
            )

    # ---- 9: regime deterioration ----------------------------------------------------------
    if regime.regime in sc.regime_exit_regimes and bar.close < position.entry_price:
        return sell(
            "REGIME_DETERIORATION",
            f"Market regime deteriorated to {regime.regime} while the position is "
            f"{position.return_pct(bar.close):.2f}% underwater",
            1.0,
            bar.close,
            "SELL_SIGNAL",
        )

    # ---- 10: risk increase ------------------------------------------------------------------
    if (
        position.entry_atr_pct
        and snapshot.atr_pct is not None
        and snapshot.atr_pct > sc.risk_increase_atr_mult * position.entry_atr_pct
        and unrealized_r < 1.0
    ):
        return sell(
            "RISK_INCREASE",
            f"ATR rose to {snapshot.atr_pct:.1f}% from {position.entry_atr_pct:.1f}% at entry "
            f"while the position is only {unrealized_r:.2f}R ahead",
            1.0,
            bar.close,
            "SELL_SIGNAL",
        )

    # ---- 11: fundamental deterioration --------------------------------------------------------
    if (
        position.entry_fundamental_score is not None
        and current_fundamental_score is not None
        and position.entry_fundamental_score - current_fundamental_score >= sc.fundamental_drop_points
    ):
        return sell(
            "FUNDAMENTAL_DETERIORATION",
            f"Fundamental score fell from {position.entry_fundamental_score:.0f} to "
            f"{current_fundamental_score:.0f}",
            1.0,
            bar.close,
            "SELL_SIGNAL",
        )

    # ---- 12: time exit ---------------------------------------------------------------------------
    if position.holding_days >= sc.max_holding_days and unrealized_r < sc.time_exit_min_r:
        return sell(
            "TIME_EXIT",
            f"Held {position.holding_days} days without reaching {sc.time_exit_min_r:.1f}R "
            f"(currently {unrealized_r:.2f}R) — capital redeployed",
            1.0,
            bar.close,
            "SELL_SIGNAL",
        )

    # ---- 13: volatility exit -----------------------------------------------------------------------
    if (
        position.entry_realized_vol
        and snapshot.realized_vol_20 is not None
        and snapshot.realized_vol_20 > sc.volatility_exit_mult * position.entry_realized_vol
        and bar.close < position.entry_price
    ):
        return sell(
            "VOLATILITY_EXIT",
            f"Realised volatility rose to {snapshot.realized_vol_20:.0%} from "
            f"{position.entry_realized_vol:.0%} at entry while the position is underwater",
            1.0,
            bar.close,
            "VOLATILITY_EXIT",
        )

    # ---- HOLD ------------------------------------------------------------------------------------
    return SellDecision(
        should_sell=False,
        exit_reason=None,
        detail=None,
        fraction=0.0,
        suggested_fill=None,
        rules_fired=[],
        trailing=trailing,
        new_status=None,
        hold_reasons=build_hold_reasons(position, bar, snapshot, regime, current_stop),
        warnings=warnings,
        trend_break_bars=trend_break_bars,
    )


def build_hold_reasons(
    position: TrackedPosition,
    bar: BarInput,
    snapshot: IndicatorSnapshot,
    regime: RegimeResult,
    current_stop: float,
) -> list[str]:
    """Why the position is still open — the CURRENT THESIS panel (requirement 49)."""
    reasons: list[str] = []
    if snapshot.sma50 is not None and bar.close > snapshot.sma50:
        reasons.append("Trend remains bullish — price above SMA50")
    if snapshot.ema20 is not None and bar.close > snapshot.ema20:
        reasons.append("Price above EMA20")
    if snapshot.rs_21 is not None and snapshot.rs_21 > 0:
        reasons.append(f"Relative strength remains positive ({snapshot.rs_21:+.1f}% vs SPY)")
    if snapshot.macd is not None and snapshot.macd_signal is not None and snapshot.macd > snapshot.macd_signal:
        reasons.append("MACD still above its signal line")
    reasons.append(f"Stop not reached (stop ${current_stop:.2f}, low ${bar.low:.2f})")
    if regime.allows_new_buys:
        reasons.append(f"Market regime {regime.regime.replace('_', ' ').title()} remains supportive")
    return reasons


def thesis_still_valid(decision: SellDecision, position: TrackedPosition, bar: BarInput) -> bool:
    """A position with an active warning is flagged in the UI before it is exited."""
    return not decision.should_sell and not decision.warnings
