"""System status, audit log, manual triggers, and the Android delta-sync endpoint."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_api_key, strategy_dep
from app.api.routers.market import market_status
from app.api.serializers import serialize_alert, serialize_position, serialize_score, serialize_sell
from app.core.clock import iso, utc_now
from app.core.config import StrategyConfig, get_settings
from app.data.providers.registry import get_provider
from app.db.models import (
    OPEN_STATUSES,
    AuditLog,
    BuyAlert,
    Instrument,
    MarketRegimeRow,
    Position,
    SellAlert,
    StockScore,
)
from app.services import analytics as analytics_service
from app.services import audit
from app.services.monitor import Monitor
from app.services.paper_portfolio import PaperPortfolio
from app.services.scanner import Scanner, latest_scores

router = APIRouter(tags=["system"])
secured = APIRouter(tags=["system"], dependencies=[Depends(require_api_key)])


@router.get("/health")
def health() -> dict:
    """Liveness only — deliberately unauthenticated so orchestrators can probe it."""
    return {"status": "ok", "time_utc": iso(utc_now())}


@secured.get("/system/status")
def system_status(session: Session = Depends(db_session)) -> dict:
    provider = get_provider()
    settings = get_settings()

    try:
        session.execute(select(func.count(Instrument.id))).scalar()
        db_ok, db_detail = True, "reachable"
    except Exception as exc:  # noqa: BLE001
        db_ok, db_detail = False, str(exc)

    last_scan = session.execute(
        select(StockScore.ts_utc).order_by(StockScore.ts_utc.desc()).limit(1)
    ).scalar()
    last_regime = session.execute(
        select(MarketRegimeRow).order_by(MarketRegimeRow.ts_utc.desc()).limit(1)
    ).scalar_one_or_none()
    error_count = session.execute(
        select(func.count(AuditLog.id)).where(AuditLog.decision == "ERROR")
    ).scalar()

    return {
        "time_utc": iso(utc_now()),
        "database": {"ok": db_ok, "detail": db_detail, "url_scheme": settings.database_url.split(":")[0]},
        "providers": [
            {"name": h.name, "ok": h.ok, "detail": h.detail, "checked_at_utc": iso(h.checked_at)}
            for h in provider.health_all()
        ],
        "active_provider": provider.last_used,
        "last_provider_error": provider.last_error,
        "last_scan_utc": iso(last_scan),
        "last_regime": last_regime.regime if last_regime else None,
        "last_regime_utc": iso(last_regime.ts_utc) if last_regime else None,
        "instruments": session.execute(select(func.count(Instrument.id))).scalar(),
        "eligible_instruments": session.execute(
            select(func.count(Instrument.id)).where(Instrument.eligible.is_(True))
        ).scalar(),
        "open_alerts": session.execute(
            select(func.count(BuyAlert.id)).where(BuyAlert.status.in_(OPEN_STATUSES))
        ).scalar(),
        "total_alerts": session.execute(select(func.count(BuyAlert.id))).scalar(),
        "total_sells": session.execute(select(func.count(SellAlert.id))).scalar(),
        "audit_errors": error_count,
        "scheduler_enabled": settings.enable_scheduler,
        "paper_trading": settings.paper_trading,
        "strategy_version": settings.strategy_version,
    }


@secured.get("/audit")
def audit_log(
    session: Session = Depends(db_session),
    ticker: str | None = None,
    decision: str | None = None,
    stage: str | None = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
) -> dict:
    rows = audit.recent(session, ticker, decision, stage, limit, offset)
    return {
        "entries": [
            {
                "ts_utc": iso(r.ts_utc),
                "ticker": r.ticker,
                "decision": r.decision,
                "stage": r.stage,
                "strategy_version": r.strategy_version,
                "reason": r.reason,
                "error_code": r.error_code,
                "rules_passed": r.rules_passed,
                "rules_failed": r.rules_failed,
                "scores": r.scores,
                "data_provider": r.data_provider,
            }
            for r in rows
        ]
    }


@secured.post("/system/scan")
def trigger_scan(
    session: Session = Depends(db_session),
    cfg: StrategyConfig = Depends(strategy_dep),
    tickers: str | None = None,
) -> dict:
    result = Scanner(cfg=cfg).run(session, tickers.split(",") if tickers else None)
    _sync_portfolio(session)
    session.commit()
    return result.as_dict()


@secured.post("/system/monitor")
def trigger_monitor(
    session: Session = Depends(db_session),
    cfg: StrategyConfig = Depends(strategy_dep),
) -> dict:
    result = Monitor(cfg=cfg).run(session)
    _sync_portfolio(session)
    session.commit()
    return result.as_dict()


@secured.post("/system/universe")
def trigger_universe_refresh(
    session: Session = Depends(db_session),
    cfg: StrategyConfig = Depends(strategy_dep),
) -> dict:
    from app.services.universe_service import UniverseService

    result = UniverseService(cfg=cfg).refresh(session)
    session.commit()
    return result.as_dict()


def _sync_portfolio(session: Session) -> None:
    """Keep paper positions aligned with alerts after a scan or monitor pass."""
    portfolio = PaperPortfolio()
    for alert in session.execute(
        select(BuyAlert).where(BuyAlert.status.in_(OPEN_STATUSES))
    ).scalars():
        portfolio.open_from_alert(session, alert)
        if alert.current_price:
            portfolio.mark_to_market(session, alert, alert.current_price)
    for alert in session.execute(
        select(BuyAlert).where(BuyAlert.status == "CLOSED")
    ).scalars():
        if alert.sells:
            portfolio.reduce(session, alert, 1.0, alert.sells[-1].sell_price, alert.closed_ts_utc)
    portfolio.snapshot(session)


@secured.get("/sync")
def sync(
    session: Session = Depends(db_session),
    since: datetime | None = None,
    scanner_limit: int = Query(50, le=200),
) -> dict:
    """One round trip for the Android background worker.

    Returns everything the app needs to refresh its Room cache, plus ``next_since`` for
    the following delta call. Alerts changed since ``since`` are returned in full so the
    client never has to reconcile partial objects.
    """
    now = utc_now()

    alert_stmt = select(BuyAlert)
    sell_stmt = select(SellAlert)
    if since:
        alert_stmt = alert_stmt.where(BuyAlert.updated_at_utc > since)
        sell_stmt = sell_stmt.where(SellAlert.updated_at_utc > since)

    alerts = list(session.execute(alert_stmt.order_by(BuyAlert.updated_at_utc.desc())).scalars())
    sells = list(session.execute(sell_stmt.order_by(SellAlert.updated_at_utc.desc())).scalars())
    positions = list(
        session.execute(select(Position).where(Position.status == "OPEN")).scalars()
    )

    portfolio = PaperPortfolio()
    scores = latest_scores(session, limit=scanner_limit)

    return {
        "server_time_utc": iso(now),
        "next_since": iso(now),
        "market_status": market_status(session),
        # The last persisted classification, not a fresh one: sync must stay cheap and
        # must never fail because the regime is momentarily unclassifiable.
        "regime": _last_regime(session),
        "alerts": [serialize_alert(a) for a in alerts],
        "sell_alerts": [serialize_sell(s) for s in sells],
        "positions": [serialize_position(p) for p in positions],
        "portfolio": portfolio.state(session).as_dict(),
        "scanner": [serialize_score(s, rank=i + 1) for i, s in enumerate(scores)],
        "analytics": analytics_service.compute_analytics(session),
    }


def _last_regime(session: Session) -> dict | None:
    from app.api.serializers import serialize_regime

    row = session.execute(
        select(MarketRegimeRow).order_by(MarketRegimeRow.ts_utc.desc()).limit(1)
    ).scalar_one_or_none()
    return serialize_regime(row) if row else None
