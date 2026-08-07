"""Alert lifecycle: creation, tracking, event timeline, closure.

This module owns the invariants listed in ALERT_LIFECYCLE.md §8, and it is the only place
allowed to write to ``buy_alerts``, ``sell_alerts`` and ``alert_events``:

1. every SELL references an existing BUY (``buy_alert_id`` is NOT NULL);
2. a BUY's entry snapshot never changes after insert — ``update_tracking`` refuses to
   touch those columns and raises if asked to;
3. at most one open alert exists per instrument;
4. ``max_gain_pct ≥ current_return_pct ≥ max_drawdown_pct``;
5. the trailing stop never decreases;
6. ``CLOSED`` implies ``remaining_fraction == 0`` and a computed final return;
7. the fractions of an alert's SELLs sum to 1.0 once closed;
8. nothing is ever deleted.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.errors import DuplicateAlertError, ValidationError
from app.core.logging import get_logger
from app.db.models import (
    OPEN_STATUSES,
    AlertEvent,
    AlertStatus,
    BuyAlert,
    EventType,
    Instrument,
    SellAlert,
)
from app.domain.indicators.snapshot import IndicatorSnapshot
from app.domain.signals.buy_engine import BuyDecision
from app.domain.signals.sell_engine import SellDecision, TrackedPosition
from app.domain.types import Quote

log = get_logger(__name__)

PROFIT_MILESTONES: tuple[float, ...] = (2.0, 5.0, 10.0, 20.0)
DRAWDOWN_MILESTONES: tuple[float, ...] = (-3.0, -5.0)


# --------------------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------------------


def has_open_alert(session: Session, instrument_id: int) -> bool:
    stmt = (
        select(BuyAlert.id)
        .where(BuyAlert.instrument_id == instrument_id)
        .where(BuyAlert.status.in_(OPEN_STATUSES))
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def open_alerts(session: Session) -> list[BuyAlert]:
    return list(
        session.execute(
            select(BuyAlert).where(BuyAlert.status.in_(OPEN_STATUSES)).order_by(BuyAlert.buy_ts_utc)
        ).scalars()
    )


def get_alert(session: Session, identifier: str | int) -> BuyAlert | None:
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        return session.get(BuyAlert, int(identifier))
    return session.execute(
        select(BuyAlert).where(BuyAlert.alert_uid == str(identifier))
    ).scalar_one_or_none()


# --------------------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------------------


def add_event(
    session: Session,
    alert: BuyAlert,
    event_type: EventType | str,
    title: str,
    detail: str | None = None,
    price: float | None = None,
    payload: dict | None = None,
    ts: datetime | None = None,
    user_visible: bool = True,
) -> AlertEvent:
    """Append to the permanent timeline. Append-only: there is no update or delete path."""
    event = AlertEvent(
        buy_alert_id=alert.id,
        ts_utc=ts or utc_now(),
        event_type=event_type.value if isinstance(event_type, EventType) else str(event_type),
        title=title,
        detail=detail,
        price=price,
        payload=payload or {},
        is_user_visible=user_visible,
    )
    session.add(event)
    return event


# --------------------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------------------


def create_buy_alert(
    session: Session,
    instrument: Instrument,
    decision: BuyDecision,
    snapshot: IndicatorSnapshot,
    quote: Quote | None,
    strategy_version: str,
    data_provider: str,
    earnings_date: datetime | None = None,
    ts: datetime | None = None,
) -> BuyAlert:
    """Create a BUY alert with its immutable entry snapshot, plus the opening event.

    Raises ``DuplicateAlertError`` if an open alert already exists — the BUY gate checks
    this too, but the check is repeated here because this function is the last line of
    defence and races are possible between a scan and a manual trigger.
    """
    if not decision.should_buy:
        raise ValidationError(
            "refusing to create an alert for a decision that did not pass the BUY gate",
            {"ticker": decision.ticker, "rules_failed": decision.rules_failed},
        )
    if has_open_alert(session, instrument.id):
        raise DuplicateAlertError(
            f"an open alert already exists for {instrument.ticker}",
            {"ticker": instrument.ticker},
        )

    levels = decision.levels
    prob = decision.probability
    score = decision.score
    now = ts or utc_now()

    alert = BuyAlert(
        instrument_id=instrument.id,
        ticker=instrument.ticker,
        company_name=instrument.company_name,
        strategy_version=strategy_version,
        data_provider=data_provider,
        # ---- entry snapshot (never written again) --------------------------------------
        buy_ts_utc=now,
        buy_price=levels.entry,
        bid=quote.bid if quote else None,
        ask=quote.ask if quote else None,
        spread=quote.spread if quote else None,
        spread_bps=quote.spread_bps if quote else None,
        opportunity_score=score.opportunity_score,
        probability=prob.probability,
        probability_sample_size=prob.sample_size,
        probability_method=prob.method,
        confidence=score.confidence,
        market_regime=decision.regime.regime,
        sector=instrument.sector,
        industry=instrument.industry,
        market_cap=instrument.market_cap,
        volume=snapshot.volume,
        rel_volume=snapshot.rel_volume,
        rsi14=snapshot.rsi14,
        macd=snapshot.macd,
        macd_hist=snapshot.macd_hist,
        atr14=snapshot.atr14,
        atr_pct=snapshot.atr_pct,
        ema9=snapshot.ema9,
        ema20=snapshot.ema20,
        ema21=snapshot.ema21,
        ema50=snapshot.ema50,
        sma50=snapshot.sma50,
        sma100=snapshot.sma100,
        sma200=snapshot.sma200,
        rs_21=snapshot.rs_21,
        rs_63=snapshot.rs_63,
        rs_126=snapshot.rs_126,
        realized_vol_20=snapshot.realized_vol_20,
        breakout_type=score.breakout_type,
        breakout_level=score.breakout_level,
        trend_score=score.trend.score,
        momentum_score=score.momentum.score,
        volume_score=score.volume.score,
        breakout_score=score.breakout.score,
        relative_strength_score=score.relative_strength.score,
        fundamental_score=score.fundamental.score,
        risk_score=score.risk.score,
        stop_price=levels.stop,
        target1_price=levels.target1,
        target2_price=levels.target2,
        initial_risk_per_share=levels.risk_per_share,
        expected_value=prob.expected_value_r,
        reward_risk=levels.reward_risk,
        earnings_date_utc=earnings_date,
        buy_reasons=decision.reasons,
        risk_factors=decision.risk_factors,
        entry_features=score.breakdown(),
        # ---- tracking -------------------------------------------------------------------
        status=AlertStatus.BUY_SIGNAL.value,
        current_price=levels.entry,
        current_return_pct=0.0,
        highest_price_since_buy=levels.entry,
        lowest_price_since_buy=levels.entry,
        max_gain_pct=0.0,
        max_drawdown_pct=0.0,
        current_stop_price=levels.stop,
        remaining_fraction=1.0,
        thesis_valid=True,
        thesis_notes=[],
        milestones_hit=[],
        last_evaluated_utc=now,
    )
    session.add(alert)
    session.flush()  # assign the id so the event can reference it

    add_event(
        session,
        alert,
        EventType.BUY_SIGNAL,
        "BUY SIGNAL",
        detail=(
            f"Score {score.opportunity_score:.0f} · R/R {levels.reward_risk:.2f} · "
            f"{len(decision.reasons)} confirming reasons"
        ),
        price=levels.entry,
        payload={
            "rules_passed": decision.rules_passed,
            "reasons": decision.reasons,
            "risk_factors": decision.risk_factors,
            "probability": prob.as_dict(),
            "levels": levels.as_dict(),
        },
        ts=now,
    )
    log.info(
        "buy_alert_created",
        extra={
            "ticker": alert.ticker, "alert_uid": alert.alert_uid,
            "price": levels.entry, "score": score.opportunity_score,
        },
    )
    return alert


# --------------------------------------------------------------------------------------
# Tracking
# --------------------------------------------------------------------------------------

_MUTABLE_COLUMNS: frozenset[str] = frozenset(
    {
        "status", "current_price", "current_return_pct", "highest_price_since_buy",
        "max_gain_pct", "lowest_price_since_buy", "max_drawdown_pct",
        "trailing_stop_price", "current_stop_price", "remaining_fraction",
        "realized_return_pct", "bars_held", "thesis_valid", "thesis_notes",
        "milestones_hit", "last_evaluated_utc", "closed_ts_utc", "final_return_pct",
        "final_r_multiple", "holding_period_days", "sell_alert_id", "notified",
        "updated_at_utc",
    }
)


def update_tracking(session: Session, alert: BuyAlert, **fields) -> BuyAlert:
    """Write mutable tracking fields. Refuses to touch the immutable entry snapshot.

    This is the enforcement point for invariant 2: the entry price, score, stop and every
    other entry-time number stay exactly as they were when the signal fired, no matter
    what later code asks for.
    """
    forbidden = set(fields) & BuyAlert.ENTRY_SNAPSHOT_COLUMNS
    if forbidden:
        raise ValidationError(
            "attempted to modify the immutable entry snapshot of a BUY alert",
            {"alert_uid": alert.alert_uid, "fields": sorted(forbidden)},
        )
    unknown = set(fields) - _MUTABLE_COLUMNS
    if unknown:
        raise ValidationError(
            "unknown tracking field", {"fields": sorted(unknown)}
        )
    for key, value in fields.items():
        setattr(alert, key, value)
    alert.updated_at_utc = utc_now()
    return alert


def apply_price_update(
    session: Session,
    alert: BuyAlert,
    price: float,
    bar_high: float | None = None,
    bar_low: float | None = None,
    ts: datetime | None = None,
) -> BuyAlert:
    """Refresh price-derived tracking and append any milestone events.

    Extremes use the bar's high/low when available, so max gain and max drawdown reflect
    what actually happened intrabar rather than only what the close showed.
    """
    now = ts or utc_now()
    entry = alert.buy_price
    high = max(alert.highest_price_since_buy or entry, bar_high if bar_high is not None else price)
    low = min(alert.lowest_price_since_buy or entry, bar_low if bar_low is not None else price)

    current_return = 100.0 * (price / entry - 1.0) if entry > 0 else 0.0
    max_gain = 100.0 * (high / entry - 1.0) if entry > 0 else 0.0
    max_dd = 100.0 * (low / entry - 1.0) if entry > 0 else 0.0

    # Invariant 4 holds by construction: high ≥ price ≥ low after the max/min above.
    update_tracking(
        session,
        alert,
        current_price=price,
        current_return_pct=current_return,
        highest_price_since_buy=high,
        lowest_price_since_buy=low,
        max_gain_pct=max_gain,
        max_drawdown_pct=min(0.0, max_dd),
        last_evaluated_utc=now,
    )
    _record_milestones(session, alert, current_return, max_dd, price, now)
    return alert


def _record_milestones(
    session: Session,
    alert: BuyAlert,
    current_return: float,
    max_dd: float,
    price: float,
    ts: datetime,
) -> None:
    hit = set(alert.milestones_hit or [])
    changed = False

    for level in PROFIT_MILESTONES:
        key = f"profit_{level:g}"
        if current_return >= level and key not in hit:
            hit.add(key)
            changed = True
            add_event(
                session, alert, EventType.PROFIT_MILESTONE, f"+{level:g}% PROFIT",
                detail=f"Unrealised return reached +{current_return:.2f}%", price=price, ts=ts,
            )

    for level in DRAWDOWN_MILESTONES:
        key = f"drawdown_{level:g}"
        if max_dd <= level and key not in hit:
            hit.add(key)
            changed = True
            add_event(
                session, alert, EventType.DRAWDOWN_MILESTONE, f"{level:g}% DRAWDOWN",
                detail=f"Maximum adverse excursion reached {max_dd:.2f}%", price=price, ts=ts,
            )

    if changed:
        update_tracking(session, alert, milestones_hit=sorted(hit))


def apply_trailing_stop(
    session: Session,
    alert: BuyAlert,
    trailing_stop: float | None,
    mode: str | None,
    ts: datetime | None = None,
) -> None:
    """Ratchet the trailing stop upward and log the move. Never lowers it (invariant 5)."""
    if trailing_stop is None:
        return
    previous = alert.trailing_stop_price
    if previous is not None and trailing_stop <= previous + 1e-9:
        return

    update_tracking(
        session,
        alert,
        trailing_stop_price=trailing_stop,
        current_stop_price=max(alert.stop_price, trailing_stop),
        status=(
            AlertStatus.TRAILING.value
            if alert.status in (AlertStatus.ACTIVE.value, AlertStatus.BUY_SIGNAL.value)
            else alert.status
        ),
    )
    add_event(
        session,
        alert,
        EventType.TRAILING_STOP_UPDATED,
        "TRAILING STOP UPDATED",
        detail=f"Raised to ${trailing_stop:.2f}" + (f" ({mode})" if mode else ""),
        price=trailing_stop,
        ts=ts or utc_now(),
    )


def to_tracked_position(alert: BuyAlert) -> TrackedPosition:
    """Project a persisted alert into the pure-domain state the SELL engine consumes."""
    entry = alert.buy_price
    return TrackedPosition(
        ticker=alert.ticker,
        entry_price=entry,
        entry_ts=alert.buy_ts_utc,
        initial_stop=alert.stop_price,
        target1=alert.target1_price,
        target2=alert.target2_price,
        risk_per_share=alert.initial_risk_per_share,
        highest_close_since_entry=alert.highest_price_since_buy or entry,
        highest_price_since_entry=alert.highest_price_since_buy or entry,
        lowest_price_since_entry=alert.lowest_price_since_buy or entry,
        trailing_stop=alert.trailing_stop_price,
        trailing_active=alert.trailing_stop_price is not None
        or alert.status in (AlertStatus.TRAILING.value, AlertStatus.TARGET_1_HIT.value,
                            AlertStatus.TARGET_2_HIT.value),
        remaining_fraction=alert.remaining_fraction,
        status=alert.status,
        target1_hit=alert.status in (AlertStatus.TARGET_1_HIT.value, AlertStatus.TARGET_2_HIT.value)
        or any(s.exit_reason in ("TARGET_1", "TARGET_2") for s in alert.sells),
        target2_hit=alert.status == AlertStatus.TARGET_2_HIT.value
        or any(s.exit_reason == "TARGET_2" for s in alert.sells),
        bars_held=alert.bars_held,
        holding_days=max(0, (utc_now() - alert.buy_ts_utc).days),
        entry_atr_pct=alert.atr_pct,
        entry_realized_vol=alert.realized_vol_20,
        entry_fundamental_score=alert.fundamental_score,
        breakout_level=alert.breakout_level,
        breakout_type=alert.breakout_type or "NONE",
    )


# --------------------------------------------------------------------------------------
# Closing
# --------------------------------------------------------------------------------------


def record_sell(
    session: Session,
    alert: BuyAlert,
    decision: SellDecision,
    price: float,
    regime: str | None = None,
    ts: datetime | None = None,
) -> SellAlert:
    """Create the SELL alert, reduce the BUY, and close it when nothing remains.

    The SELL always references this BUY, always inherits the BUY's strategy version, and
    the BUY row itself survives as a completed historical trade (requirement 55).
    """
    now = ts or utc_now()
    fraction = min(max(decision.fraction, 0.0), alert.remaining_fraction)
    if fraction <= 0:
        raise ValidationError(
            "sell fraction must be positive and within the remaining position",
            {"alert_uid": alert.alert_uid, "requested": decision.fraction,
             "remaining": alert.remaining_fraction},
        )

    entry = alert.buy_price
    return_pct = 100.0 * (price / entry - 1.0) if entry > 0 else 0.0
    r_multiple = (
        (price - entry) / alert.initial_risk_per_share if alert.initial_risk_per_share > 0 else 0.0
    )
    holding_days = max(0, (now - alert.buy_ts_utc).days)

    sell = SellAlert(
        buy_alert_id=alert.id,
        ticker=alert.ticker,
        sell_ts_utc=now,
        sell_price=price,
        entry_price=entry,
        fraction_closed=fraction,
        final_return_pct=return_pct,
        realized_r_multiple=r_multiple,
        holding_period_days=holding_days,
        exit_reason=decision.exit_reason or "THESIS_INVALIDATION",
        exit_reason_detail=decision.detail,
        exit_rules_fired=decision.rules_fired,
        max_gain_pct=alert.max_gain_pct,
        max_drawdown_pct=alert.max_drawdown_pct,
        market_regime=regime or alert.market_regime,
        # The version always comes from the parent BUY, never from the current strategy —
        # historical trades are never re-attributed to newer logic (requirement 48).
        strategy_version=alert.strategy_version,
    )
    session.add(sell)
    session.flush()

    remaining = round(alert.remaining_fraction - fraction, 10)
    realized = alert.realized_return_pct + fraction * return_pct

    is_partial = remaining > 1e-9
    add_event(
        session,
        alert,
        EventType.PARTIAL_EXIT if is_partial else EventType.SELL_SIGNAL,
        "PARTIAL EXIT" if is_partial else "SELL SIGNAL",
        detail=decision.detail,
        price=price,
        payload={
            "exit_reason": sell.exit_reason,
            "fraction": fraction,
            "return_pct": round(return_pct, 4),
            "r_multiple": round(r_multiple, 4),
            "sell_alert_uid": sell.alert_uid,
        },
        ts=now,
    )

    if is_partial:
        status = decision.new_status or alert.status
        update_tracking(
            session, alert,
            status=status,
            remaining_fraction=remaining,
            realized_return_pct=realized,
            sell_alert_id=sell.id,
        )
    else:
        final_r = (
            sum(s.fraction_closed * s.realized_r_multiple for s in alert.sells)
            if alert.sells else r_multiple
        )
        update_tracking(
            session, alert,
            status=AlertStatus.CLOSED.value,
            remaining_fraction=0.0,
            realized_return_pct=realized,
            final_return_pct=realized,
            final_r_multiple=final_r,
            holding_period_days=holding_days,
            closed_ts_utc=now,
            sell_alert_id=sell.id,
            current_price=price,
        )
        add_event(
            session, alert, EventType.CLOSED, "TRADE CLOSED",
            detail=(
                f"Final return {realized:+.2f}% over {holding_days} day(s) — "
                f"{sell.exit_reason.replace('_', ' ').lower()}"
            ),
            price=price, ts=now,
        )

    log.info(
        "sell_alert_created",
        extra={
            "ticker": alert.ticker, "buy_alert_uid": alert.alert_uid,
            "sell_alert_uid": sell.alert_uid, "reason": sell.exit_reason,
            "fraction": fraction, "return_pct": round(return_pct, 4),
        },
    )
    return sell


def invalidate_alert(
    session: Session, alert: BuyAlert, reason: str, ts: datetime | None = None
) -> BuyAlert:
    """Mark an alert invalidated when it can no longer be tracked (delisting, data loss).

    The row is kept — invalidation is a status, not a deletion.
    """
    now = ts or utc_now()
    update_tracking(
        session, alert,
        status=AlertStatus.INVALIDATED.value,
        thesis_valid=False,
        closed_ts_utc=now,
        remaining_fraction=0.0,
    )
    add_event(
        session, alert, EventType.THESIS_INVALIDATED, "ALERT INVALIDATED",
        detail=reason, price=alert.current_price, ts=now,
    )
    return alert


def promote_to_active(session: Session, alert: BuyAlert) -> None:
    """First monitor pass moves a fresh signal into the ACTIVE state."""
    if alert.status == AlertStatus.BUY_SIGNAL.value:
        update_tracking(session, alert, status=AlertStatus.ACTIVE.value)
