"""Position sizing, portfolio limits, paper P&L and universe eligibility."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.data.universe import LiquidityFacts, check_eligibility, sector_etf_for
from app.domain.portfolio.sizing import OpenPositionView, correlation_matrix, position_size
from app.domain.types import InstrumentInfo

EQUITY = 100_000.0


def view(ticker="T", sector="Technology", shares=100, entry=100.0, price=100.0, stop=95.0):
    return OpenPositionView(ticker, sector, shares, entry, price, stop)


# --------------------------------------------------------------------------------------
# Position sizing
# --------------------------------------------------------------------------------------


def test_sizing_follows_the_risk_formula(cfg):
    """shares = floor(equity × risk_pct / (entry − stop)).

    Priced low enough that no portfolio cap binds, so the raw formula is what is tested.
    """
    result = position_size(EQUITY, EQUITY, entry=20.0, stop=15.0, cfg=cfg)
    expected = math.floor(EQUITY * cfg.portfolio.risk_pct_per_trade / 5.0)
    assert result.shares == expected
    assert result.risk_amount == pytest.approx(expected * 5.0)
    assert result.limits_applied == []


def test_a_wider_stop_produces_a_smaller_position(cfg):
    """Both stops are wide enough that the notional cap does not bind, so the equal-risk
    property is what is actually being measured."""
    tight = position_size(EQUITY, EQUITY, 20.0, 18.0, cfg)   # 10% stop
    wide = position_size(EQUITY, EQUITY, 20.0, 15.0, cfg)    # 25% stop
    assert tight.limits_applied == wide.limits_applied == []
    assert tight.shares > wide.shares
    # Risk in dollars is the same either way — that is the point of the method.
    assert tight.risk_amount == pytest.approx(wide.risk_amount, rel=0.02)


def test_the_single_position_cap_binds_on_an_expensive_stock(cfg):
    """The raw risk formula wants 150 shares; the 12%-of-equity cap allows 120."""
    result = position_size(EQUITY, EQUITY, entry=100.0, stop=95.0, cfg=cfg)
    assert result.shares == 120
    assert "max_single_position" in result.limits_applied
    assert result.notional <= EQUITY * cfg.portfolio.max_single_position_pct


def test_risk_per_trade_never_exceeds_the_configured_maximum(cfg):
    result = position_size(EQUITY, EQUITY, 100.0, 99.0, cfg)
    assert result.risk_pct_of_equity <= cfg.portfolio.max_risk_pct_per_trade + 1e-9


def test_invalid_stop_yields_no_position(cfg):
    assert position_size(EQUITY, EQUITY, 100.0, 100.0, cfg).shares == 0
    assert position_size(EQUITY, EQUITY, 100.0, 105.0, cfg).shares == 0


def test_max_single_position_caps_the_notional(cfg):
    loose = cfg.model_copy(deep=True)
    loose.portfolio.risk_pct_per_trade = 0.01
    loose.portfolio.max_risk_pct_per_trade = 0.01
    result = position_size(EQUITY, EQUITY, entry=100.0, stop=99.5, cfg=loose)
    assert result.notional <= EQUITY * loose.portfolio.max_single_position_pct + 1e-6
    assert "max_single_position" in result.limits_applied


def test_max_open_positions_blocks_a_new_trade(cfg):
    positions = [view(f"T{i}") for i in range(cfg.portfolio.max_open_positions)]
    result = position_size(EQUITY, EQUITY, 100.0, 95.0, cfg, open_positions=positions)
    assert not result.allowed
    assert any("max_open_positions" in r for r in result.rejections)


def test_total_open_risk_budget_shrinks_the_position(cfg):
    # Eleven positions each risking ~0.5% of equity leaves little of the 6% budget.
    positions = [view(f"T{i}", shares=100, price=100.0, stop=95.0) for i in range(11)]
    result = position_size(EQUITY, EQUITY, 100.0, 95.0, cfg, open_positions=positions)
    assert result.shares == 0 or "total_open_risk" in result.limits_applied


def test_sector_exposure_cap(cfg):
    positions = [view(f"T{i}", sector="Technology", shares=100, price=100.0) for i in range(3)]
    result = position_size(
        EQUITY, EQUITY, 100.0, 95.0, cfg, sector="Technology", open_positions=positions
    )
    assert result.shares == 0 or "max_sector_exposure" in result.limits_applied or result.rejections


def test_min_cash_reserve_is_respected(cfg):
    result = position_size(EQUITY, cash=EQUITY * 0.04, entry=100.0, stop=95.0, cfg=cfg)
    assert not result.allowed
    assert any("minimum reserve" in r for r in result.rejections)


def test_correlated_cluster_blocks_another_correlated_name(cfg):
    positions = [view(f"T{i}") for i in range(4)]
    correlations = {f"T{i}": 0.9 for i in range(4)}
    result = position_size(
        EQUITY, EQUITY, 100.0, 95.0, cfg, open_positions=positions, correlations=correlations
    )
    assert not result.allowed
    assert any("correlated" in r for r in result.rejections)


def test_open_risk_is_zero_once_the_stop_is_above_the_price():
    assert view(price=100.0, stop=105.0).open_risk == 0.0
    assert view(price=100.0, stop=95.0).open_risk == pytest.approx(500.0)


def test_correlation_matrix_is_symmetric():
    base = np.sin(np.linspace(0, 20, 100))
    returns = {"A": base, "B": base * 1.01, "C": -base}
    matrix = correlation_matrix(returns, window=100)
    assert matrix[("A", "B")] == pytest.approx(matrix[("B", "A")])
    assert matrix[("A", "B")] > 0.99
    assert matrix[("A", "C")] < -0.99


# --------------------------------------------------------------------------------------
# Paper portfolio P&L
# --------------------------------------------------------------------------------------


def test_paper_portfolio_tracks_unrealized_and_realized_pnl(db_session, cfg):
    from app.db.models import BuyAlert, Instrument
    from app.services.paper_portfolio import PaperPortfolio

    instrument = Instrument(ticker="TESTCO", eligible=True, sector="Technology")
    db_session.add(instrument)
    db_session.flush()

    alert = BuyAlert(
        instrument_id=instrument.id, ticker="TESTCO", strategy_version=cfg.version,
        buy_price=20.0, stop_price=15.0, target1_price=27.5, target2_price=35.0,
        initial_risk_per_share=5.0, opportunity_score=88.0, sector="Technology",
        status="ACTIVE", current_price=20.0,
    )
    db_session.add(alert)
    db_session.flush()

    portfolio = PaperPortfolio(cfg)
    position = portfolio.open_from_alert(db_session, alert)
    assert position is not None
    assert position.shares == math.floor(100_000 * cfg.portfolio.risk_pct_per_trade / 5.0)

    portfolio.mark_to_market(db_session, alert, 30.0)
    assert position.unrealized_pnl == pytest.approx(position.shares * 10.0)

    shares_before = position.shares
    portfolio.reduce(db_session, alert, fraction=0.25, price=30.0)
    assert position.shares == pytest.approx(shares_before * 0.75)
    assert position.realized_pnl == pytest.approx(shares_before * 0.25 * 10.0)

    portfolio.reduce(db_session, alert, fraction=0.75, price=32.0)
    assert position.status == "CLOSED"
    assert position.shares == 0.0
    assert position.unrealized_pnl == 0.0

    state = portfolio.state(db_session)
    assert state.open_positions == 0
    assert state.realized_pnl > 0
    assert state.as_dict()["paper_trading"] is True


def test_opening_a_position_twice_is_idempotent(db_session, cfg):
    from app.db.models import BuyAlert, Instrument
    from app.services.paper_portfolio import PaperPortfolio

    instrument = Instrument(ticker="X", eligible=True)
    db_session.add(instrument)
    db_session.flush()
    alert = BuyAlert(
        instrument_id=instrument.id, ticker="X", strategy_version=cfg.version,
        buy_price=50.0, stop_price=48.0, target1_price=53.0, target2_price=56.0,
        initial_risk_per_share=2.0, opportunity_score=85.0, status="ACTIVE",
    )
    db_session.add(alert)
    db_session.flush()

    portfolio = PaperPortfolio(cfg)
    first = portfolio.open_from_alert(db_session, alert)
    second = portfolio.open_from_alert(db_session, alert)
    assert first.id == second.id


# --------------------------------------------------------------------------------------
# Universe eligibility
# --------------------------------------------------------------------------------------


def info(**overrides) -> InstrumentInfo:
    defaults = dict(ticker="ABC", company_name="ABC Corp", exchange="NASDAQ",
                    security_type="COMMON", sector="Technology", market_cap=2e9)
    defaults.update(overrides)
    return InstrumentInfo(**defaults)


def facts(**overrides) -> LiquidityFacts:
    defaults = dict(price=50.0, market_cap=2e9, avg_volume_50d=2_000_000.0,
                    avg_dollar_volume_50d=100_000_000.0)
    defaults.update(overrides)
    return LiquidityFacts(**defaults)


def test_a_liquid_nasdaq_common_stock_is_eligible(cfg):
    result = check_eligibility(info(), facts(), cfg.universe)
    assert result.eligible
    assert result.reason is None


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"is_otc": True}, "OTC"),
        ({"is_leveraged_etf": True}, "leveraged"),
        ({"is_inverse_etf": True}, "inverse"),
        ({"is_etf": True}, "ETFs excluded"),
        ({"is_adr": True}, "ADRs excluded"),
        ({"exchange": "LSE"}, "exchange LSE"),
        ({"exchange": None}, "exchange unknown"),
    ],
)
def test_security_class_and_exchange_exclusions(cfg, kwargs, fragment):
    result = check_eligibility(info(**kwargs), facts(), cfg.universe)
    assert not result.eligible
    assert fragment in result.reason


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"price": 3.0}, "below minimum"),
        ({"market_cap": 1e8}, "market cap"),
        ({"avg_dollar_volume_50d": 2e6}, "average dollar volume"),
        ({"avg_volume_50d": 100_000.0}, "average volume"),
        ({"price": None}, "no price"),
        ({"market_cap": None}, "market cap unknown"),
    ],
)
def test_liquidity_exclusions(cfg, kwargs, fragment):
    row = facts(**kwargs)
    result = check_eligibility(info(market_cap=row.market_cap), row, cfg.universe)
    assert not result.eligible
    assert fragment in result.reason


def test_every_exclusion_states_a_reason(cfg):
    """Requirement: a missing ticker must always be explainable."""
    result = check_eligibility(info(is_otc=True), facts(), cfg.universe)
    assert result.reason and len(result.reason) > 5


def test_etfs_become_eligible_when_configured(cfg):
    permissive = cfg.model_copy(deep=True)
    permissive.universe.include_etf = True
    result = check_eligibility(info(is_etf=True, market_cap=None), facts(market_cap=None),
                               permissive.universe)
    assert result.eligible, result.reason


def test_penny_stocks_stay_out_by_default(cfg):
    assert not check_eligibility(info(), facts(price=2.0), cfg.universe).eligible


def test_sector_etf_mapping():
    assert sector_etf_for("Technology") == "XLK"
    assert sector_etf_for("Financial Services") == "XLF"
    assert sector_etf_for(None) == "SPY"
    assert sector_etf_for("Nonexistent Sector") == "SPY"
