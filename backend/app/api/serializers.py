"""Model → API payload conversion.

Kept in one module so the Android DTOs have a single, stable counterpart. Every timestamp
is emitted as ISO-8601 UTC with a trailing ``Z``; the client renders America/New_York.
"""

from __future__ import annotations

from app.core.clock import iso
from app.db.models import (
    AlertEvent,
    BacktestRun,
    BuyAlert,
    Instrument,
    MarketRegimeRow,
    Position,
    SellAlert,
    StockScore,
)


def _r(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def serialize_sell(sell: SellAlert) -> dict:
    return {
        "id": sell.id,
        "alert_uid": sell.alert_uid,
        "buy_alert_id": sell.buy_alert_id,
        "ticker": sell.ticker,
        "sell_ts_utc": iso(sell.sell_ts_utc),
        "sell_price": _r(sell.sell_price),
        "entry_price": _r(sell.entry_price),
        "fraction_closed": _r(sell.fraction_closed),
        "final_return_pct": _r(sell.final_return_pct),
        "r_multiple": _r(sell.realized_r_multiple),
        "holding_period_days": sell.holding_period_days,
        "exit_reason": sell.exit_reason,
        "exit_reason_detail": sell.exit_reason_detail,
        "exit_rules_fired": sell.exit_rules_fired,
        "max_gain_pct": _r(sell.max_gain_pct),
        "max_drawdown_pct": _r(sell.max_drawdown_pct),
        "market_regime": sell.market_regime,
        "strategy_version": sell.strategy_version,
    }


def serialize_alert(alert: BuyAlert, include_sells: bool = True) -> dict:
    payload = {
        "id": alert.id,
        "alert_uid": alert.alert_uid,
        "ticker": alert.ticker,
        "company_name": alert.company_name,
        "status": alert.status,
        "strategy_version": alert.strategy_version,
        "data_provider": alert.data_provider,
        # entry snapshot
        "buy_ts_utc": iso(alert.buy_ts_utc),
        "buy_price": _r(alert.buy_price),
        "bid": _r(alert.bid),
        "ask": _r(alert.ask),
        "spread_bps": _r(alert.spread_bps, 2),
        "opportunity_score": _r(alert.opportunity_score, 2),
        "confidence": _r(alert.confidence, 2),
        "probability": _r(alert.probability),
        "probability_sample_size": alert.probability_sample_size,
        "probability_method": alert.probability_method,
        "expected_value": _r(alert.expected_value),
        "reward_risk": _r(alert.reward_risk, 3),
        "market_regime": alert.market_regime,
        "sector": alert.sector,
        "industry": alert.industry,
        "market_cap": _r(alert.market_cap, 0),
        "breakout_type": alert.breakout_type,
        # levels
        "stop_price": _r(alert.stop_price),
        "target1_price": _r(alert.target1_price),
        "target2_price": _r(alert.target2_price),
        "initial_risk_per_share": _r(alert.initial_risk_per_share),
        "current_stop_price": _r(alert.current_stop_price),
        "trailing_stop_price": _r(alert.trailing_stop_price),
        # tracking
        "current_price": _r(alert.current_price),
        "current_return_pct": _r(alert.current_return_pct, 2),
        "max_gain_pct": _r(alert.max_gain_pct, 2),
        "max_drawdown_pct": _r(alert.max_drawdown_pct, 2),
        "remaining_fraction": _r(alert.remaining_fraction, 3),
        "realized_return_pct": _r(alert.realized_return_pct, 2),
        "thesis_valid": alert.thesis_valid,
        "thesis_notes": alert.thesis_notes,
        # explainability
        "buy_reasons": alert.buy_reasons,
        "risk_factors": alert.risk_factors,
        "component_scores": {
            "trend": _r(alert.trend_score, 2),
            "momentum": _r(alert.momentum_score, 2),
            "volume": _r(alert.volume_score, 2),
            "breakout": _r(alert.breakout_score, 2),
            "relative_strength": _r(alert.relative_strength_score, 2),
            "fundamental": _r(alert.fundamental_score, 2),
            "risk": _r(alert.risk_score, 2),
        },
        "entry_indicators": {
            "rsi14": _r(alert.rsi14, 2),
            "macd": _r(alert.macd),
            "atr14": _r(alert.atr14),
            "atr_pct": _r(alert.atr_pct, 3),
            "ema20": _r(alert.ema20),
            "ema50": _r(alert.ema50),
            "sma50": _r(alert.sma50),
            "sma200": _r(alert.sma200),
            "rel_volume": _r(alert.rel_volume, 3),
            "rs_21": _r(alert.rs_21, 3),
            "rs_63": _r(alert.rs_63, 3),
        },
        # closure
        "closed_ts_utc": iso(alert.closed_ts_utc),
        "final_return_pct": _r(alert.final_return_pct, 2),
        "final_r_multiple": _r(alert.final_r_multiple, 3),
        "holding_period_days": alert.holding_period_days,
        "earnings_date_utc": iso(alert.earnings_date_utc),
        "updated_at_utc": iso(alert.updated_at_utc),
        "is_open": alert.is_open,
    }
    if include_sells:
        payload["sells"] = [serialize_sell(s) for s in alert.sells]
        payload["sell"] = serialize_sell(alert.sells[-1]) if alert.sells else None
    return payload


def serialize_event(event: AlertEvent) -> dict:
    return {
        "id": event.id,
        "ts_utc": iso(event.ts_utc),
        "event_type": event.event_type,
        "price": _r(event.price),
        "title": event.title,
        "detail": event.detail,
        "payload": event.payload,
    }


def serialize_score(score: StockScore, rank: int | None = None) -> dict:
    return {
        "rank": rank,
        "ticker": score.ticker,
        "ts_utc": iso(score.ts_utc),
        "price": _r(score.price),
        "opportunity_score": _r(score.opportunity_score, 2),
        "confidence": _r(score.confidence, 2),
        "category": score.category,
        "trend_score": _r(score.trend_score, 2),
        "momentum_score": _r(score.momentum_score, 2),
        "volume_score": _r(score.volume_score, 2),
        "breakout_score": _r(score.breakout_score, 2),
        "relative_strength_score": _r(score.relative_strength_score, 2),
        "fundamental_score": _r(score.fundamental_score, 2),
        "risk_score": _r(score.risk_score, 2),
        "regime_score": _r(score.regime_score, 2),
        "rel_volume": _r(score.rel_volume, 3),
        "rs_21": _r(score.rs_21, 3),
        "atr_pct": _r(score.atr_pct, 3),
        "suggested_entry": _r(score.suggested_entry),
        "stop_price": _r(score.stop_price),
        "target1_price": _r(score.target1_price),
        "target2_price": _r(score.target2_price),
        "reward_risk": _r(score.reward_risk, 3),
        "probability": _r(score.probability),
        "probability_sample_size": score.probability_sample_size,
        "expected_value": _r(score.expected_value),
        "signal_ready": score.signal_ready,
        "rules_failed": score.rules_failed,
        "rules_passed": score.rules_passed,
        "sector": score.sector,
        "market_cap": _r(score.market_cap, 0),
        "market_regime": score.market_regime,
        "strategy_version": score.strategy_version,
    }


def serialize_instrument(instrument: Instrument) -> dict:
    return {
        "ticker": instrument.ticker,
        "company_name": instrument.company_name,
        "exchange": instrument.exchange,
        "security_type": instrument.security_type,
        "sector": instrument.sector,
        "industry": instrument.industry,
        "market_cap": _r(instrument.market_cap, 0),
        "last_price": _r(instrument.last_price),
        "avg_volume_50d": _r(instrument.avg_volume_50d, 0),
        "avg_dollar_volume_50d": _r(instrument.avg_dollar_volume_50d, 0),
        "eligible": instrument.eligible,
        "ineligible_reason": instrument.ineligible_reason,
        "delisted": instrument.delisted,
        "data_provider": instrument.data_provider,
        "updated_at_utc": iso(instrument.updated_at_utc),
    }


def serialize_position(position: Position) -> dict:
    current = position.current_price or position.entry_price
    return {
        "id": position.id,
        "buy_alert_id": position.buy_alert_id,
        "ticker": position.ticker,
        "opened_ts_utc": iso(position.opened_ts_utc),
        "entry_price": _r(position.entry_price),
        "current_price": _r(current),
        "shares": _r(position.shares, 4),
        "initial_shares": _r(position.initial_shares, 4),
        "cost_basis": _r(position.cost_basis, 2),
        "market_value": _r(position.shares * current, 2),
        "unrealized_pnl": _r(position.unrealized_pnl, 2),
        "realized_pnl": _r(position.realized_pnl, 2),
        "return_pct": _r(
            100.0 * (current / position.entry_price - 1.0) if position.entry_price else 0.0, 2
        ),
        "stop_price": _r(position.stop_price),
        "target1_price": _r(position.target1_price),
        "target2_price": _r(position.target2_price),
        "risk_amount": _r(position.risk_amount, 2),
        "risk_pct_of_equity": _r(position.risk_pct_of_equity, 5),
        "sector": position.sector,
        "status": position.status,
        "closed_ts_utc": iso(position.closed_ts_utc),
    }


def serialize_regime(row: MarketRegimeRow) -> dict:
    return {
        "regime": row.regime,
        "regime_score": _r(row.regime_score, 2),
        "ts_utc": iso(row.ts_utc),
        "components": {
            "spy_above_ema20": row.spy_above_ema20,
            "spy_above_sma50": row.spy_above_sma50,
            "spy_above_sma200": row.spy_above_sma200,
            "breadth_pct": _r(row.breadth_pct, 4),
            "participation_pct": _r(row.participation_pct, 4),
            "volatility_proxy": _r(row.volatility_proxy, 3),
            "spy_drawdown_pct": _r(row.spy_drawdown_pct, 3),
            "qqq_rs_63": _r(row.qqq_rs, 3),
            "iwm_rs_63": _r(row.iwm_rs, 3),
        },
        "sector_participation": row.sector_participation,
        "strategy_version": row.strategy_version,
    }


def serialize_backtest(run: BacktestRun, include_curve: bool = False) -> dict:
    payload = {
        "id": run.id,
        "run_uid": run.run_uid,
        "created_at_utc": iso(run.created_at_utc),
        "strategy_version": run.strategy_version,
        "mode": run.mode,
        "status": run.status,
        "error": run.error,
        "start_date": run.start_date.isoformat() if run.start_date else None,
        "end_date": run.end_date.isoformat() if run.end_date else None,
        "universe_size": run.universe_size,
        "parameters": run.parameters,
        "metrics": {
            "trades": run.trades,
            "win_rate": _r(run.win_rate),
            "profit_factor": _r(run.profit_factor, 3),
            "expectancy_r": _r(run.expectancy, 4),
            "sharpe": _r(run.sharpe, 3),
            "sortino": _r(run.sortino, 3),
            "max_drawdown_pct": _r(run.max_drawdown_pct, 3),
            "avg_return_pct": _r(run.avg_return_pct, 3),
            "median_return_pct": _r(run.median_return_pct, 3),
            "avg_holding_days": _r(run.avg_holding_days, 2),
            "target_hit_rate": _r(run.target_hit_rate),
            "stop_rate": _r(run.stop_rate),
            "total_return_pct": _r(run.total_return_pct, 3),
            "benchmark_return_pct": _r(run.benchmark_return_pct, 3),
        },
        "folds": run.folds,
        "sensitivity": run.sensitivity,
        "bias_warnings": run.bias_warnings,
    }
    if include_curve:
        payload["equity_curve"] = run.equity_curve
        payload["monthly_returns"] = run.monthly_returns
    return payload
