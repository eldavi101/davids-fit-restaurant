"""Settings and strategy-version endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_api_key
from app.core.clock import iso
from app.db.models import StrategyVersion
from app.services.settings_service import describe_settings, effective_strategy, update_settings

router = APIRouter(tags=["settings"], dependencies=[Depends(require_api_key)])


class SettingsUpdate(BaseModel):
    updates: dict = Field(default_factory=dict)
    #: Required for any parameter that changes how stocks are judged. Publishing a new
    #: version keeps historical alerts attached to the logic that produced them.
    create_version: bool = False
    new_version: str | None = None


@router.get("/settings")
def get_settings_payload(session: Session = Depends(db_session)) -> dict:
    return describe_settings(effective_strategy(session))


@router.put("/settings")
def put_settings(body: SettingsUpdate, session: Session = Depends(db_session)) -> dict:
    cfg = update_settings(
        session,
        updates=body.updates,
        create_version=body.create_version,
        new_version=body.new_version,
        updated_by="api",
    )
    session.commit()
    return describe_settings(cfg)


@router.get("/strategy-versions")
def strategy_versions(session: Session = Depends(db_session)) -> dict:
    rows = list(
        session.execute(
            select(StrategyVersion).order_by(StrategyVersion.created_at_utc.desc())
        ).scalars()
    )
    return {
        "versions": [
            {
                "version": row.version,
                "created_at_utc": iso(row.created_at_utc),
                "description": row.description,
                "is_active": row.is_active,
                "weights": row.weights,
                "notes": row.notes,
            }
            for row in rows
        ]
    }
