"""Market status and regime endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_api_key, strategy_dep
from app.api.serializers import serialize_regime
from app.core.clock import (
    iso,
    market_session,
    next_market_close,
    next_market_open,
    to_market_time,
    utc_now,
)
from app.core.config import StrategyConfig, get_settings
from app.core.errors import DataIntegrityError
from app.data.providers.registry import get_provider, provider_is_synthetic
from app.db.models import MarketRegimeRow
from app.domain.regime.engine import classify_regime
from app.services.market_data import MarketDataService

router = APIRouter(prefix="/market", tags=["market"], dependencies=[Depends(require_api_key)])


@router.get("/status")
def market_status(session: Session = Depends(db_session)) -> dict:
    settings = get_settings()
    provider = get_provider()
    now = utc_now()
    session_state = market_session(now)

    degraded_reasons: list[str] = []
    last_bar_age: float | None = None
    try:
        service = MarketDataService(provider, settings)
        spy = service.load_series("SPY", limit=5)
        last_ts = spy.ts[-1]
        last_bar_age = (now - last_ts).total_seconds()
    except DataIntegrityError as exc:
        degraded_reasons.append(str(exc))

    health = provider.health()
    if not health.ok:
        degraded_reasons.append(f"provider {health.name}: {health.detail}")

    return {
        "session": session_state.value,
        "server_time_utc": iso(now),
        "market_time_et": to_market_time(now).isoformat(),
        "next_open_utc": iso(next_market_open(now)),
        "next_close_utc": iso(next_market_close(now)),
        "data_provider": provider.last_used,
        # The app renders a prominent banner when this is true. Synthetic bars are never
        # presented as real market data (requirement 61.1).
        "synthetic_data": provider_is_synthetic(provider),
        "data_fresh": not degraded_reasons,
        "last_bar_age_seconds": None if last_bar_age is None else round(last_bar_age, 1),
        "degraded": bool(degraded_reasons),
        "degraded_reasons": degraded_reasons,
        "paper_trading": settings.paper_trading,
    }


@router.get("/regime")
def market_regime(
    session: Session = Depends(db_session),
    cfg: StrategyConfig = Depends(strategy_dep),
) -> dict:
    provider = get_provider()
    service = MarketDataService(provider)
    try:
        benchmarks = service.load_benchmarks()
        spy = benchmarks["SPY"]
        result = classify_regime(
            benchmark=spy.window(-1),
            sector_windows={s: b.window(-1) for s, b in benchmarks.items() if s.startswith("XL")},
            cfg=cfg,
            secondary={s: benchmarks[s].window(-1) for s in ("QQQ", "IWM") if s in benchmarks},
        )
    except (DataIntegrityError, KeyError):
        # Fall back to the last persisted classification rather than inventing one.
        row = session.execute(
            select(MarketRegimeRow).order_by(MarketRegimeRow.ts_utc.desc()).limit(1)
        ).scalar_one_or_none()
        if row is None:
            return {"regime": None, "regime_score": None, "allows_new_buys": False,
                    "error": "regime unclassifiable and no prior classification stored"}
        payload = serialize_regime(row)
        payload["stale"] = True
        payload["allows_new_buys"] = row.regime not in cfg.regime.blocked_regimes
        return payload

    return {
        **result.as_dict(),
        "ts_utc": iso(result.ts_utc),
        "sector_participation": result.sector_participation,
        "stale": False,
    }
