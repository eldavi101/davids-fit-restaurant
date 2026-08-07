"""Audit logging (requirement 50).

Every decision the system makes — BUY, NO_BUY, HOLD, SELL, SKIP or ERROR — is written
here with the inputs, indicators, scores and the full rule ledger that produced it. The
table is append-only. Its purpose is to make "why did the system do that on 7 August?"
answerable months later, including for the decisions where it did *nothing*.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.db.models import AuditLog


def record(
    session: Session,
    ticker: str | None,
    decision: str,
    stage: str,
    strategy_version: str | None = None,
    inputs: dict | None = None,
    indicators: dict | None = None,
    scores: dict | None = None,
    rules_passed: list[str] | None = None,
    rules_failed: list[str] | None = None,
    reason: str | None = None,
    error_code: str | None = None,
    data_provider: str | None = None,
    ts: datetime | None = None,
) -> AuditLog:
    entry = AuditLog(
        ts_utc=ts or utc_now(),
        ticker=ticker,
        decision=decision,
        stage=stage,
        strategy_version=strategy_version,
        inputs=inputs or {},
        indicators=indicators or {},
        scores=scores or {},
        rules_passed=rules_passed or [],
        rules_failed=rules_failed or [],
        reason=reason,
        error_code=error_code,
        data_provider=data_provider,
    )
    session.add(entry)
    return entry


def record_data_failure(
    session: Session,
    ticker: str | None,
    stage: str,
    error_code: str,
    reason: str,
    strategy_version: str | None = None,
    data_provider: str | None = None,
) -> AuditLog:
    """The requirement-51 path: a refusal to signal, recorded rather than swallowed."""
    return record(
        session,
        ticker=ticker,
        decision="ERROR",
        stage=stage,
        strategy_version=strategy_version,
        reason=reason,
        error_code=error_code,
        data_provider=data_provider,
        rules_failed=["data_integrity"],
    )


def recent(
    session: Session,
    ticker: str | None = None,
    decision: str | None = None,
    stage: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.ts_utc.desc())
    if ticker:
        stmt = stmt.where(AuditLog.ticker == ticker.upper())
    if decision:
        stmt = stmt.where(AuditLog.decision == decision.upper())
    if stage:
        stmt = stmt.where(AuditLog.stage == stage.upper())
    return list(session.execute(stmt.limit(limit).offset(offset)).scalars())
