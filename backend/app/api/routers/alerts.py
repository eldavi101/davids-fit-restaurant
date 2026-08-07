"""Alert Center endpoints — the most important surface in the API.

Alerts are never deleted by any endpoint here. There is no DELETE route, by design.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_api_key
from app.api.serializers import serialize_alert, serialize_event, serialize_sell
from app.core.errors import NotFoundError
from app.db.models import OPEN_STATUSES, AlertEvent, AlertStatus, BuyAlert, SellAlert
from app.services.lifecycle import get_alert

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(require_api_key)])


def _query(
    session: Session,
    statuses: tuple[str, ...] | None = None,
    ticker: str | None = None,
    sector: str | None = None,
    strategy_version: str | None = None,
    since: datetime | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    min_return: float | None = None,
    max_return: float | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[BuyAlert], int]:
    stmt = select(BuyAlert)
    if statuses:
        stmt = stmt.where(BuyAlert.status.in_(statuses))
    if ticker:
        stmt = stmt.where(BuyAlert.ticker == ticker.upper())
    if sector:
        stmt = stmt.where(BuyAlert.sector == sector)
    if strategy_version:
        stmt = stmt.where(BuyAlert.strategy_version == strategy_version)
    if since:
        stmt = stmt.where(BuyAlert.updated_at_utc > since)
    if date_from:
        stmt = stmt.where(BuyAlert.buy_ts_utc >= date_from)
    if date_to:
        stmt = stmt.where(BuyAlert.buy_ts_utc <= date_to)

    rows = list(session.execute(stmt.order_by(BuyAlert.buy_ts_utc.desc())).scalars())

    if min_return is not None:
        rows = [r for r in rows if (r.final_return_pct if r.final_return_pct is not None
                                    else r.current_return_pct) >= min_return]
    if max_return is not None:
        rows = [r for r in rows if (r.final_return_pct if r.final_return_pct is not None
                                    else r.current_return_pct) <= max_return]

    return rows[offset : offset + limit], len(rows)


def _envelope(rows: list[BuyAlert], total: int, limit: int, offset: int) -> dict:
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "alerts": [serialize_alert(a) for a in rows],
    }


@router.get("")
def list_alerts(
    session: Session = Depends(db_session),
    status: str | None = None,
    ticker: str | None = None,
    sector: str | None = None,
    strategy_version: str | None = None,
    since: datetime | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    min_return: float | None = None,
    max_return: float | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
) -> dict:
    statuses = (status.upper(),) if status else None
    rows, total = _query(session, statuses, ticker, sector, strategy_version, since,
                         date_from, date_to, min_return, max_return, limit, offset)
    return _envelope(rows, total, limit, offset)


@router.get("/buy")
def buy_alerts(
    session: Session = Depends(db_session),
    limit: int = Query(100, le=500),
    offset: int = 0,
) -> dict:
    rows, total = _query(session, limit=limit, offset=offset)
    return _envelope(rows, total, limit, offset)


@router.get("/sell")
def sell_alerts(
    session: Session = Depends(db_session),
    since: datetime | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
) -> dict:
    stmt = select(SellAlert)
    if since:
        stmt = stmt.where(SellAlert.updated_at_utc > since)
    rows = list(session.execute(stmt.order_by(SellAlert.sell_ts_utc.desc())).scalars())
    page = rows[offset : offset + limit]
    return {
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        # Each SELL carries its parent BUY inline so the app can render the closed-trade
        # card without a second round trip — and so the link is never ambiguous.
        "alerts": [
            {**serialize_sell(s), "buy_alert": serialize_alert(s.buy_alert, include_sells=False)}
            for s in page
        ],
    }


@router.get("/active")
def active_alerts(
    session: Session = Depends(db_session),
    limit: int = Query(100, le=500),
    offset: int = 0,
) -> dict:
    rows, total = _query(session, OPEN_STATUSES, limit=limit, offset=offset)
    return _envelope(rows, total, limit, offset)


@router.get("/closed")
def closed_alerts(
    session: Session = Depends(db_session),
    limit: int = Query(100, le=500),
    offset: int = 0,
) -> dict:
    rows, total = _query(
        session, (AlertStatus.CLOSED.value, AlertStatus.INVALIDATED.value),
        limit=limit, offset=offset,
    )
    return _envelope(rows, total, limit, offset)


@router.get("/{identifier}")
def alert_detail(identifier: str, session: Session = Depends(db_session)) -> dict:
    alert = get_alert(session, identifier)
    if alert is None:
        raise NotFoundError(f"alert {identifier} not found")
    payload = serialize_alert(alert)
    payload["timeline"] = [serialize_event(e) for e in alert.events]
    return payload


@router.get("/{identifier}/timeline")
def alert_timeline(identifier: str, session: Session = Depends(db_session)) -> dict:
    alert = get_alert(session, identifier)
    if alert is None:
        raise NotFoundError(f"alert {identifier} not found")
    events = list(
        session.execute(
            select(AlertEvent)
            .where(AlertEvent.buy_alert_id == alert.id)
            .order_by(AlertEvent.ts_utc)
        ).scalars()
    )
    return {
        "alert_uid": alert.alert_uid,
        "ticker": alert.ticker,
        "status": alert.status,
        "events": [serialize_event(e) for e in events],
    }
