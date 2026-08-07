"""Positions, history and analytics endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_api_key
from app.api.serializers import serialize_alert, serialize_position
from app.db.models import AlertStatus, BuyAlert, Position
from app.services import analytics as analytics_service
from app.services.paper_portfolio import PaperPortfolio

router = APIRouter(tags=["portfolio"], dependencies=[Depends(require_api_key)])


@router.get("/positions")
def positions(
    session: Session = Depends(db_session),
    status: str = "OPEN",
    limit: int = Query(100, le=500),
) -> dict:
    portfolio = PaperPortfolio()
    stmt = select(Position).where(Position.portfolio_id == portfolio.portfolio_id)
    if status.upper() != "ALL":
        stmt = stmt.where(Position.status == status.upper())
    rows = list(session.execute(stmt.order_by(Position.opened_ts_utc.desc()).limit(limit)).scalars())
    return {
        "portfolio": portfolio.state(session).as_dict(),
        "positions": [serialize_position(p) for p in rows],
    }


@router.get("/history")
def history(
    session: Session = Depends(db_session),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    ticker: str | None = None,
    sector: str | None = None,
    strategy_version: str | None = None,
    outcome: str = "all",
    min_return: float | None = None,
    max_return: float | None = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
) -> dict:
    stmt = select(BuyAlert).where(
        BuyAlert.status.in_((AlertStatus.CLOSED.value, AlertStatus.INVALIDATED.value))
    )
    if date_from:
        stmt = stmt.where(BuyAlert.closed_ts_utc >= date_from)
    if date_to:
        stmt = stmt.where(BuyAlert.closed_ts_utc <= date_to)
    if ticker:
        stmt = stmt.where(BuyAlert.ticker == ticker.upper())
    if sector:
        stmt = stmt.where(BuyAlert.sector == sector)
    if strategy_version:
        stmt = stmt.where(BuyAlert.strategy_version == strategy_version)

    rows = list(session.execute(stmt.order_by(BuyAlert.closed_ts_utc.desc())).scalars())

    def matches(alert: BuyAlert) -> bool:
        ret = alert.final_return_pct or 0.0
        reason = alert.sells[-1].exit_reason if alert.sells else None
        if outcome == "winner" and ret <= 0:
            return False
        if outcome == "loser" and ret > 0:
            return False
        if outcome == "stopped" and reason not in ("STOP_LOSS", "TRAILING_STOP"):
            return False
        if outcome == "target" and reason not in ("TARGET_1", "TARGET_2"):
            return False
        if min_return is not None and ret < min_return:
            return False
        if max_return is not None and ret > max_return:
            return False
        return True

    filtered = [a for a in rows if matches(a)]
    page = filtered[offset : offset + limit]
    return {
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "trades": [serialize_alert(a) for a in page],
    }


@router.get("/analytics")
def analytics(session: Session = Depends(db_session), since: datetime | None = None) -> dict:
    return analytics_service.compute_analytics(session, since)


@router.get("/performance/equity-curve")
def equity_curve(session: Session = Depends(db_session), benchmark: str = "SPY") -> dict:
    return analytics_service.equity_curve_payload(session, benchmark)
