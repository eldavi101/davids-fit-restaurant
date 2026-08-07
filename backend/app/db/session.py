"""Engine and session management.

SQLite gets ``check_same_thread=False`` plus a ``StaticPool`` for in-memory test
databases so a single connection is shared across the FastAPI TestClient's threads.
PostgreSQL gets a normal pooled engine with ``pool_pre_ping`` so a recycled backend
connection surfaces as a retryable error rather than a mid-transaction crash.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.models import Base

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _build_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        in_memory = ":memory:" in url
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if in_memory else None,
            future=True,
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine

    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20, future=True)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine(get_settings().database_url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionFactory


def init_db() -> None:
    """Create all tables. Idempotent."""
    Base.metadata.create_all(bind=get_engine())


def reset_engine(url: str | None = None) -> None:
    """Rebuild the engine — used by tests to point at a fresh database."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = _build_engine(url) if url else None
    _SessionFactory = None


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
