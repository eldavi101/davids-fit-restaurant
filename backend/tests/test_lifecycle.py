"""Alert lifecycle invariants (ALERT_LIFECYCLE.md §8)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.clock import utc_now
from app.core.errors import DuplicateAlertError, ValidationError
from app.db.models import AlertEvent, AlertStatus, BuyAlert, Instrument, SellAlert
from app.domain.signals.sell_engine import SellDecision
from app.services import lifecycle
from tests.test_scoring_and_buy_gate import make_setup


@pytest.fixture
def instrument(db_session):
    row = Instrument(
        ticker="TESTCO", company_name="Test Corp", exchange="NASDAQ",
        sector="Technology", industry="Software", market_cap=8e11, eligible=True,
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def alert(db_session, instrument, cfg):
    from app.domain.signals.buy_engine import BuyContext, evaluate_buy

    snapshot, score, levels, probability, regime = make_setup(cfg)
    decision = evaluate_buy(
        snapshot, score, levels, probability, regime, cfg,
        BuyContext(market_cap=8e11, spread_bps=3.0),
    )
    assert decision.should_buy
    return lifecycle.create_buy_alert(
        db_session, instrument=instrument, decision=decision, snapshot=snapshot,
        quote=None, strategy_version=cfg.version, data_provider="synthetic",
    )


def exit_decision(reason="TRAILING_STOP", fraction=1.0, status="SELL_SIGNAL") -> SellDecision:
    return SellDecision(
        should_sell=True, exit_reason=reason, detail=f"{reason} fired",
        fraction=fraction, suggested_fill=None, rules_fired=[reason.lower()],
        trailing=None, new_status=status,
    )


# --------------------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------------------


def test_creating_an_alert_stores_the_entry_snapshot_and_opens_the_timeline(alert, db_session):
    assert alert.status == AlertStatus.BUY_SIGNAL.value
    assert alert.buy_price > 0
    assert alert.stop_price < alert.buy_price < alert.target1_price < alert.target2_price
    assert alert.buy_reasons, "requirement 14 — every BUY must say why"
    assert alert.remaining_fraction == 1.0

    events = list(db_session.execute(select(AlertEvent)).scalars())
    assert len(events) == 1
    assert events[0].event_type == "BUY_SIGNAL"


def test_alert_uid_is_assigned_and_unique(alert):
    assert alert.alert_uid and len(alert.alert_uid) == 36


def test_a_failed_decision_cannot_create_an_alert(db_session, instrument, cfg):
    from app.domain.signals.buy_engine import BuyContext, evaluate_buy

    snapshot, score, levels, probability, regime = make_setup(cfg)
    blocked = evaluate_buy(
        snapshot, score, levels, probability, regime, cfg,
        BuyContext(market_cap=1e6, spread_bps=3.0),   # fails the liquidity rule
    )
    assert not blocked.should_buy
    with pytest.raises(ValidationError):
        lifecycle.create_buy_alert(
            db_session, instrument=instrument, decision=blocked, snapshot=snapshot,
            quote=None, strategy_version=cfg.version, data_provider="synthetic",
        )


def test_only_one_open_alert_per_instrument(db_session, instrument, alert, cfg):
    """Invariant 3."""
    from app.domain.signals.buy_engine import BuyContext, evaluate_buy

    snapshot, score, levels, probability, regime = make_setup(cfg)
    decision = evaluate_buy(
        snapshot, score, levels, probability, regime, cfg,
        BuyContext(market_cap=8e11, spread_bps=3.0),
    )
    with pytest.raises(DuplicateAlertError):
        lifecycle.create_buy_alert(
            db_session, instrument=instrument, decision=decision, snapshot=snapshot,
            quote=None, strategy_version=cfg.version, data_provider="synthetic",
        )


def test_a_new_alert_is_allowed_once_the_previous_one_closed(db_session, instrument, alert, cfg):
    from app.domain.signals.buy_engine import BuyContext, evaluate_buy

    lifecycle.record_sell(db_session, alert, exit_decision(), price=alert.target1_price)
    assert alert.status == AlertStatus.CLOSED.value

    snapshot, score, levels, probability, regime = make_setup(cfg)
    decision = evaluate_buy(
        snapshot, score, levels, probability, regime, cfg,
        BuyContext(market_cap=8e11, spread_bps=3.0),
    )
    second = lifecycle.create_buy_alert(
        db_session, instrument=instrument, decision=decision, snapshot=snapshot,
        quote=None, strategy_version=cfg.version, data_provider="synthetic",
    )
    assert second.id != alert.id


# --------------------------------------------------------------------------------------
# Immutability
# --------------------------------------------------------------------------------------


def test_entry_snapshot_is_immutable(db_session, alert):
    """Invariant 2 — the numbers that produced the signal never change."""
    for field in ("buy_price", "stop_price", "opportunity_score", "target1_price",
                  "buy_reasons", "strategy_version"):
        with pytest.raises(ValidationError, match="immutable entry snapshot"):
            lifecycle.update_tracking(db_session, alert, **{field: 1.0})


def test_unknown_tracking_fields_are_rejected(db_session, alert):
    with pytest.raises(ValidationError, match="unknown tracking field"):
        lifecycle.update_tracking(db_session, alert, not_a_real_column=1)


def test_price_updates_do_not_disturb_the_entry_values(db_session, alert):
    original = (alert.buy_price, alert.stop_price, alert.opportunity_score)
    lifecycle.apply_price_update(db_session, alert, price=alert.buy_price * 1.10)
    assert (alert.buy_price, alert.stop_price, alert.opportunity_score) == original


# --------------------------------------------------------------------------------------
# Tracking
# --------------------------------------------------------------------------------------


def test_return_max_gain_and_drawdown_are_ordered(db_session, alert):
    """Invariant 4: max_gain ≥ current ≥ max_drawdown, always."""
    entry = alert.buy_price
    for price, high, low in (
        (entry * 1.05, entry * 1.08, entry * 1.01),
        (entry * 0.97, entry * 1.00, entry * 0.94),
        (entry * 1.02, entry * 1.03, entry * 1.00),
    ):
        lifecycle.apply_price_update(db_session, alert, price=price, bar_high=high, bar_low=low)
        assert alert.max_gain_pct >= alert.current_return_pct >= alert.max_drawdown_pct

    assert alert.max_gain_pct == pytest.approx(8.0, abs=0.01)
    assert alert.max_drawdown_pct == pytest.approx(-6.0, abs=0.01)


def test_max_gain_only_ever_rises(db_session, alert):
    entry = alert.buy_price
    lifecycle.apply_price_update(db_session, alert, price=entry * 1.20, bar_high=entry * 1.20,
                                 bar_low=entry)
    peak = alert.max_gain_pct
    lifecycle.apply_price_update(db_session, alert, price=entry * 0.90, bar_high=entry * 0.95,
                                 bar_low=entry * 0.88)
    assert alert.max_gain_pct == pytest.approx(peak)
    assert alert.current_return_pct < 0


def test_profit_milestones_are_recorded_once(db_session, alert):
    entry = alert.buy_price
    for _ in range(3):
        lifecycle.apply_price_update(db_session, alert, price=entry * 1.06)
    db_session.flush()

    events = list(
        db_session.execute(
            select(AlertEvent).where(AlertEvent.event_type == "PROFIT_MILESTONE")
        ).scalars()
    )
    titles = sorted(e.title for e in events)
    assert titles == ["+2% PROFIT", "+5% PROFIT"]


def test_drawdown_milestones_are_recorded(db_session, alert):
    lifecycle.apply_price_update(db_session, alert, price=alert.buy_price * 0.94)
    db_session.flush()
    events = list(
        db_session.execute(
            select(AlertEvent).where(AlertEvent.event_type == "DRAWDOWN_MILESTONE")
        ).scalars()
    )
    assert {e.title for e in events} == {"-3% DRAWDOWN", "-5% DRAWDOWN"}


def test_trailing_stop_updates_are_logged_and_never_lowered(db_session, alert):
    lifecycle.apply_trailing_stop(db_session, alert, alert.buy_price * 1.02, "chandelier")
    first = alert.trailing_stop_price
    lifecycle.apply_trailing_stop(db_session, alert, alert.buy_price * 0.99, "chandelier")
    assert alert.trailing_stop_price == pytest.approx(first)

    lifecycle.apply_trailing_stop(db_session, alert, alert.buy_price * 1.05, "chandelier")
    assert alert.trailing_stop_price > first
    assert alert.status == AlertStatus.TRAILING.value

    db_session.flush()
    events = list(
        db_session.execute(
            select(AlertEvent).where(AlertEvent.event_type == "TRAILING_STOP_UPDATED")
        ).scalars()
    )
    assert len(events) == 2


# --------------------------------------------------------------------------------------
# Closing
# --------------------------------------------------------------------------------------


def test_sell_always_references_its_buy(db_session, alert):
    """Invariant 1 and requirement 61.11 — a SELL can never be orphaned."""
    sell = lifecycle.record_sell(db_session, alert, exit_decision(), price=alert.buy_price * 1.08)
    db_session.flush()

    assert sell.buy_alert_id == alert.id
    assert sell.buy_alert is alert
    assert sell.entry_price == pytest.approx(alert.buy_price)

    column = SellAlert.__table__.c.buy_alert_id
    assert column.nullable is False


def test_sell_inherits_the_parents_strategy_version(db_session, alert):
    """Requirement 48 — a closed trade is never re-attributed to newer logic."""
    alert.strategy_version = "momentum_breakout_v1.0.0"
    sell = lifecycle.record_sell(db_session, alert, exit_decision(), price=alert.buy_price)
    assert sell.strategy_version == "momentum_breakout_v1.0.0"


def test_closing_computes_the_final_return_and_keeps_the_alert(db_session, alert):
    entry = alert.buy_price
    alert.buy_ts_utc = utc_now() - timedelta(days=3)
    lifecycle.apply_price_update(db_session, alert, price=entry * 1.078)
    lifecycle.record_sell(db_session, alert, exit_decision(), price=entry * 1.078)
    db_session.commit()

    assert alert.status == AlertStatus.CLOSED.value
    assert alert.final_return_pct == pytest.approx(7.8, abs=0.05)
    assert alert.holding_period_days == 3
    assert alert.remaining_fraction == 0.0
    assert alert.closed_ts_utc is not None

    # Invariant 8 — the alert is still there.
    assert db_session.get(BuyAlert, alert.id) is not None


def test_staged_exits_sum_to_exactly_one(db_session, alert):
    """Invariant 7."""
    entry = alert.buy_price
    lifecycle.record_sell(db_session, alert, exit_decision("TARGET_1", 0.25, "TARGET_1_HIT"),
                          price=entry * 1.05)
    assert alert.status == "TARGET_1_HIT"
    assert alert.remaining_fraction == pytest.approx(0.75)

    lifecycle.record_sell(db_session, alert, exit_decision("TARGET_2", 0.25, "TARGET_2_HIT"),
                          price=entry * 1.10)
    assert alert.remaining_fraction == pytest.approx(0.50)

    lifecycle.record_sell(db_session, alert, exit_decision("TRAILING_STOP", 1.0), price=entry * 1.08)
    db_session.flush()

    assert alert.status == AlertStatus.CLOSED.value
    assert alert.remaining_fraction == 0.0
    assert sum(s.fraction_closed for s in alert.sells) == pytest.approx(1.0)


def test_final_return_of_a_staged_exit_is_fraction_weighted(db_session, alert):
    entry = alert.buy_price
    lifecycle.record_sell(db_session, alert, exit_decision("TARGET_1", 0.25, "TARGET_1_HIT"),
                          price=entry * 1.20)
    lifecycle.record_sell(db_session, alert, exit_decision("TRAILING_STOP", 1.0), price=entry * 1.04)
    # 0.25 × 20% + 0.75 × 4% = 8%
    assert alert.final_return_pct == pytest.approx(8.0, abs=0.01)


def test_cannot_sell_more_than_remains(db_session, alert):
    lifecycle.record_sell(db_session, alert, exit_decision(fraction=1.0), price=alert.buy_price)
    with pytest.raises(ValidationError):
        lifecycle.record_sell(db_session, alert, exit_decision(fraction=1.0), price=alert.buy_price)


def test_closed_alert_leaves_the_open_set(db_session, alert):
    assert len(lifecycle.open_alerts(db_session)) == 1
    lifecycle.record_sell(db_session, alert, exit_decision(), price=alert.buy_price)
    db_session.flush()
    assert lifecycle.open_alerts(db_session) == []


def test_invalidated_alert_is_kept_not_deleted(db_session, alert):
    lifecycle.invalidate_alert(db_session, alert, "delisted by the exchange")
    db_session.commit()
    assert alert.status == AlertStatus.INVALIDATED.value
    assert db_session.get(BuyAlert, alert.id) is not None


# --------------------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------------------


def test_the_full_lifecycle_produces_a_readable_timeline(db_session, alert):
    entry = alert.buy_price
    lifecycle.promote_to_active(db_session, alert)
    lifecycle.apply_price_update(db_session, alert, price=entry * 1.02)
    lifecycle.record_sell(db_session, alert, exit_decision("TARGET_1", 0.25, "TARGET_1_HIT"),
                          price=alert.target1_price)
    lifecycle.apply_trailing_stop(db_session, alert, entry * 1.03, "chandelier")
    lifecycle.record_sell(db_session, alert, exit_decision("TRAILING_STOP", 1.0),
                          price=entry * 1.078)
    db_session.commit()

    types = [e.event_type for e in alert.events]
    assert types[0] == "BUY_SIGNAL"
    assert "PROFIT_MILESTONE" in types
    assert "PARTIAL_EXIT" in types
    assert "TRAILING_STOP_UPDATED" in types
    assert "SELL_SIGNAL" in types
    assert types[-1] == "CLOSED"


def test_timeline_survives_a_session_restart(db_session, alert):
    """Requirement 60.29 — alerts and their history outlive the process."""
    from app.db.session import get_session_factory

    alert_uid = alert.alert_uid
    lifecycle.record_sell(db_session, alert, exit_decision(), price=alert.buy_price * 1.05)
    db_session.commit()
    db_session.close()

    fresh = get_session_factory()()
    try:
        reloaded = lifecycle.get_alert(fresh, alert_uid)
        assert reloaded is not None
        assert reloaded.status == AlertStatus.CLOSED.value
        assert len(reloaded.events) >= 2
        assert len(reloaded.sells) == 1
        assert reloaded.sells[0].buy_alert_id == reloaded.id
    finally:
        fresh.close()
