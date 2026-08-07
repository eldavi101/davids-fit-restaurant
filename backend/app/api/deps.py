"""FastAPI dependencies: authentication, database session, rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, StrategyConfig, get_settings
from app.core.errors import AuthError, EquitySignalError
from app.db.session import get_db

RATE_LIMIT_PER_MINUTE = 120
_hits: dict[str, deque[float]] = defaultdict(deque)


def db_session() -> Session:
    yield from get_db()


def settings_dep() -> Settings:
    return get_settings()


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(settings_dep),
) -> str:
    """Single shared-secret auth.

    The Android client holds only this key. Market-data vendor credentials never leave the
    backend, so a compromised app key exposes no vendor entitlement (requirement 52).
    """
    if not x_api_key or x_api_key not in settings.api_key_set:
        raise AuthError("missing or invalid X-API-Key header")

    now = time.monotonic()
    window = _hits[x_api_key]
    while window and now - window[0] > 60.0:
        window.popleft()
    if len(window) >= RATE_LIMIT_PER_MINUTE:
        raise RateLimitError(f"rate limit of {RATE_LIMIT_PER_MINUTE} requests/minute exceeded")
    window.append(now)

    request.state.api_key = x_api_key
    return x_api_key


class RateLimitError(EquitySignalError):
    code = "rate_limited"
    http_status = 429


def strategy_dep() -> StrategyConfig:
    """Effective strategy configuration, with persisted overrides applied."""
    from app.services.settings_service import effective_strategy

    return effective_strategy()
