"""Live performance analytics over the real alert history.

Distinct from the backtester: this measures what the system actually signalled, using
closed alerts only. It reuses ``domain.backtest.metrics`` so the definition of win rate,
profit factor and expectancy is identical in both places.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.db.models import OPEN_STATUSES, AlertStatus, BuyAlert, SellAlert
from app.domain.backtest.metrics import (
    TradeRecord,
    compute_metrics,
    return_distribution,
)
from app.services.paper_portfolio import PaperPortfolio


def _to_trade_record(alert: BuyAlert) -> TradeRecord:
    exit_price = alert.current_price or alert.buy_price
    if alert.sells:
        exit_price = alert.sells[-1].sell_price
    return TradeRecord(
        ticker=alert.ticker,
        entry_ts=alert.buy_ts_utc,
        exit_ts=alert.closed_ts_utc,
        entry_price=alert.buy_price,
        exit_price=exit_price,
        shares=1.0,
        return_pct=alert.final_return_pct if alert.final_return_pct is not None else 0.0,
        r_multiple=alert.final_r_multiple or 0.0,
        exit_reason=alert.sells[-1].exit_reason if alert.sells else "UNKNOWN",
        holding_days=alert.holding_period_days or 0,
        max_gain_pct=alert.max_gain_pct,
        max_drawdown_pct=alert.max_drawdown_pct,
        opportunity_score=alert.opportunity_score,
        market_regime=alert.market_regime,
    )


def closed_alerts(session: Session, since: datetime | None = None) -> list[BuyAlert]:
    stmt = select(BuyAlert).where(BuyAlert.status == AlertStatus.CLOSED.value)
    if since:
        stmt = stmt.where(BuyAlert.closed_ts_utc >= since)
    return list(session.execute(stmt.order_by(BuyAlert.closed_ts_utc)).scalars())


def compute_analytics(session: Session, since: datetime | None = None) -> dict:
    closed = closed_alerts(session, since)
    trades = [_to_trade_record(a) for a in closed]

    portfolio = PaperPortfolio()
    curve_rows = portfolio.equity_curve(session)
    equity_values = [row.equity for row in curve_rows]
    benchmark_values = [row.benchmark_equity for row in curve_rows if row.benchmark_equity]

    metrics = compute_metrics(
        trades,
        equity_values or None,
        benchmark_values or None,
    )

    total_buy = session.execute(select(BuyAlert.id)).all()
    open_count = session.execute(
        select(BuyAlert.id).where(BuyAlert.status.in_(OPEN_STATUSES))
    ).all()

    best = max(trades, key=lambda t: t.return_pct, default=None)
    worst = min(trades, key=lambda t: t.return_pct, default=None)

    return {
        "generated_at_utc": utc_now().isoformat(),
        "total_buy_signals": len(total_buy),
        "open_alerts": len(open_count),
        "closed_trades": len(trades),
        "winners": metrics.winners,
        "losers": metrics.losers,
        "win_rate": metrics.win_rate,
        "avg_return_pct": metrics.avg_return_pct,
        "median_return_pct": metrics.median_return_pct,
        "avg_winner_pct": metrics.avg_winner_pct,
        "avg_loser_pct": metrics.avg_loser_pct,
        "best_trade": {"ticker": best.ticker, "return_pct": round(best.return_pct, 4)} if best else None,
        "worst_trade": {"ticker": worst.ticker, "return_pct": round(worst.return_pct, 4)} if worst else None,
        "profit_factor": metrics.profit_factor,
        "expectancy_r": metrics.expectancy_r,
        "max_drawdown_pct": metrics.max_drawdown_pct,
        "sharpe": metrics.sharpe,
        "sortino": metrics.sortino,
        "avg_holding_days": metrics.avg_holding_days,
        "target_hit_rate": metrics.target_hit_rate,
        "stop_rate": metrics.stop_rate,
        "return_observations": metrics.return_observations,
        "warnings": metrics.warnings,
        "by_regime": _group(trades, lambda t: t.market_regime or "UNKNOWN"),
        "by_exit_reason": _group(trades, lambda t: t.exit_reason),
        "by_month": _group(
            trades,
            lambda t: t.exit_ts.strftime("%Y-%m") if isinstance(t.exit_ts, datetime) else "unknown",
        ),
        "return_distribution": return_distribution(trades),
        "portfolio": portfolio.state(session).as_dict(),
    }


def _group(trades: list[TradeRecord], key) -> dict[str, dict]:
    buckets: dict[str, list[TradeRecord]] = {}
    for trade in trades:
        buckets.setdefault(key(trade), []).append(trade)
    return {
        name: {
            "trades": len(group),
            "win_rate": round(sum(1 for t in group if t.return_pct > 0) / len(group), 4),
            "avg_return_pct": round(sum(t.return_pct for t in group) / len(group), 4),
        }
        for name, group in sorted(buckets.items())
    }


def equity_curve_payload(session: Session, benchmark: str = "SPY") -> dict:
    portfolio = PaperPortfolio()
    rows = portfolio.equity_curve(session)
    points = [
        {
            "ts_utc": row.ts_utc.isoformat(),
            "equity": round(row.equity, 2),
            "benchmark": round(row.benchmark_equity, 2) if row.benchmark_equity else None,
            "drawdown_pct": round(row.drawdown_pct, 4),
        }
        for row in rows
    ]
    trades = [_to_trade_record(a) for a in closed_alerts(session)]
    from app.domain.backtest.metrics import monthly_returns

    return {
        "benchmark": benchmark,
        "points": points,
        "monthly_returns": monthly_returns(
            [row.ts_utc for row in rows], [row.equity for row in rows]
        ),
        "return_distribution": return_distribution(trades),
    }


def sell_alerts(session: Session, limit: int = 200, offset: int = 0) -> list[SellAlert]:
    return list(
        session.execute(
            select(SellAlert).order_by(SellAlert.sell_ts_utc.desc()).limit(limit).offset(offset)
        ).scalars()
    )
