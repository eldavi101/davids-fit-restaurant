"""Backtesting endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_api_key, strategy_dep
from app.api.serializers import serialize_backtest
from app.core.clock import iso
from app.core.config import StrategyConfig
from app.core.errors import NotFoundError, ValidationError
from app.db.models import BacktestRun, BacktestTrade
from app.db.session import session_scope
from app.services.backtest_service import create_run, execute_run

router = APIRouter(prefix="/backtests", tags=["backtesting"], dependencies=[Depends(require_api_key)])


class WalkForwardSpec(BaseModel):
    train_years: int = 4
    test_years: int = 1
    step_years: int = 1
    anchored: bool = False


class BacktestRequest(BaseModel):
    mode: str = Field(default="BACKTEST", pattern="^(BACKTEST|WALK_FORWARD|OOS)$")
    start_date: datetime | None = None
    end_date: datetime | None = None
    universe: list[str] | None = None
    parameter_overrides: dict = Field(default_factory=dict)
    initial_equity: float = 100_000.0
    include_sensitivity: bool = False
    walk_forward: WalkForwardSpec = Field(default_factory=WalkForwardSpec)


def _run_in_background(run_id: int, cfg: StrategyConfig, request: BacktestRequest) -> None:
    with session_scope() as session:
        execute_run(
            session,
            run_id=run_id,
            cfg=cfg,
            tickers=request.universe,
            initial_equity=request.initial_equity,
            walk_forward=request.walk_forward.model_dump(),
            include_sensitivity=request.include_sensitivity,
        )


@router.post("", status_code=202)
def start_backtest(
    request: BacktestRequest,
    background: BackgroundTasks,
    session: Session = Depends(db_session),
    cfg: StrategyConfig = Depends(strategy_dep),
) -> dict:
    try:
        effective = cfg.with_overrides(request.parameter_overrides) if request.parameter_overrides else cfg
    except (KeyError, ValueError) as exc:
        raise ValidationError(f"invalid parameter override: {exc}") from exc

    run = create_run(
        session,
        cfg=effective,
        mode=request.mode,
        start=request.start_date,
        end=request.end_date,
        parameters=request.model_dump(mode="json"),
        universe_size=len(request.universe or []),
    )
    session.commit()
    background.add_task(_run_in_background, run.id, effective, request)
    return {"run_uid": run.run_uid, "id": run.id, "status": run.status, "mode": run.mode}


@router.get("")
def list_backtests(
    session: Session = Depends(db_session),
    limit: int = Query(50, le=200),
) -> dict:
    rows = list(
        session.execute(
            select(BacktestRun).order_by(BacktestRun.created_at_utc.desc()).limit(limit)
        ).scalars()
    )
    return {"runs": [serialize_backtest(r) for r in rows]}


def _find(session: Session, identifier: str) -> BacktestRun:
    if identifier.isdigit():
        row = session.get(BacktestRun, int(identifier))
    else:
        row = session.execute(
            select(BacktestRun).where(BacktestRun.run_uid == identifier)
        ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"backtest run {identifier} not found")
    return row


@router.get("/{identifier}")
def backtest_detail(identifier: str, session: Session = Depends(db_session)) -> dict:
    return serialize_backtest(_find(session, identifier), include_curve=True)


@router.get("/{identifier}/trades")
def backtest_trades(
    identifier: str,
    session: Session = Depends(db_session),
    limit: int = Query(500, le=5000),
    offset: int = 0,
    sample: str | None = None,
) -> dict:
    run = _find(session, identifier)
    stmt = select(BacktestTrade).where(BacktestTrade.backtest_run_id == run.id)
    if sample:
        stmt = stmt.where(BacktestTrade.sample == sample.upper())
    rows = list(
        session.execute(stmt.order_by(BacktestTrade.entry_ts_utc).limit(limit).offset(offset)).scalars()
    )
    return {
        "run_uid": run.run_uid,
        "total": len(rows),
        "trades": [
            {
                "ticker": t.ticker,
                "entry_ts_utc": iso(t.entry_ts_utc),
                "entry_price": t.entry_price,
                "exit_ts_utc": iso(t.exit_ts_utc),
                "exit_price": t.exit_price,
                "shares": t.shares,
                "return_pct": t.return_pct,
                "r_multiple": t.r_multiple,
                "exit_reason": t.exit_reason,
                "holding_days": t.holding_days,
                "max_gain_pct": t.max_gain_pct,
                "max_drawdown_pct": t.max_drawdown_pct,
                "opportunity_score": t.opportunity_score,
                "market_regime": t.market_regime,
                "fold": t.fold,
                "sample": t.sample,
            }
            for t in rows
        ],
    }
