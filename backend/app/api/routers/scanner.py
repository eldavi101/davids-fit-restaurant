"""Scanner endpoint — the ranked opportunity feed."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_api_key
from app.api.serializers import serialize_score
from app.core.clock import iso, utc_now
from app.db.models import MarketRegimeRow, StockScore
from app.services.scanner import latest_scores

router = APIRouter(prefix="/scanner", tags=["scanner"], dependencies=[Depends(require_api_key)])

SORT_FIELDS = {
    "score": "opportunity_score",
    "momentum": "momentum_score",
    "rel_volume": "rel_volume",
    "reward_risk": "reward_risk",
    "price": "price",
    "ticker": "ticker",
    "confidence": "confidence",
}


@router.get("")
def scan(
    session: Session = Depends(db_session),
    min_score: float | None = None,
    max_score: float | None = None,
    sector: str | None = None,
    category: str | None = None,
    min_market_cap: float | None = None,
    max_market_cap: float | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_rel_volume: float | None = None,
    min_risk_score: float | None = None,
    signal_ready: bool | None = None,
    regime: str | None = None,
    search: str | None = None,
    sort: str = "score",
    order: str = "desc",
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> dict:
    rows = latest_scores(session, limit=1000)

    def keep(row: StockScore) -> bool:
        if min_score is not None and row.opportunity_score < min_score:
            return False
        if max_score is not None and row.opportunity_score > max_score:
            return False
        if sector and (row.sector or "").lower() != sector.lower():
            return False
        if category and row.category != category.upper():
            return False
        if min_market_cap is not None and (row.market_cap or 0) < min_market_cap:
            return False
        if max_market_cap is not None and (row.market_cap or 0) > max_market_cap:
            return False
        if min_price is not None and (row.price or 0) < min_price:
            return False
        if max_price is not None and (row.price or 0) > max_price:
            return False
        if min_rel_volume is not None and (row.rel_volume or 0) < min_rel_volume:
            return False
        if min_risk_score is not None and row.risk_score < min_risk_score:
            return False
        if signal_ready is not None and row.signal_ready is not signal_ready:
            return False
        if regime and (row.market_regime or "") != regime.upper():
            return False
        if search:
            needle = search.lower()
            if needle not in row.ticker.lower() and needle not in (row.sector or "").lower():
                return False
        return True

    filtered = [r for r in rows if keep(r)]
    field = SORT_FIELDS.get(sort, "opportunity_score")
    filtered.sort(key=lambda r: (getattr(r, field) is None, getattr(r, field)), reverse=(order == "desc"))

    page = filtered[offset : offset + limit]
    regime_row = session.execute(
        select(MarketRegimeRow).order_by(MarketRegimeRow.ts_utc.desc()).limit(1)
    ).scalar_one_or_none()

    return {
        "generated_at_utc": iso(rows[0].ts_utc) if rows else iso(utc_now()),
        "regime": regime_row.regime if regime_row else None,
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "results": [serialize_score(row, rank=offset + i + 1) for i, row in enumerate(page)],
    }
