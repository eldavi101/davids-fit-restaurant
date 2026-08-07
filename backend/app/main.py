"""FastAPI application entry point.

    uvicorn app.main:app --reload

Notice what is *not* wired in here: there is no email client, no messaging SDK, no webhook
dispatcher, no outbound notification transport of any kind. Alerts live in the database and
are read by the Android app; that is the entire delivery mechanism (requirements 5, 56).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import EquitySignalError
from app.core.logging import configure_logging, get_logger
from app.db.session import init_db, session_scope

log = get_logger(__name__)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()

    with session_scope() as session:
        from app.services.settings_service import effective_strategy, ensure_strategy_version

        cfg = effective_strategy(session)
        ensure_strategy_version(session, cfg)

    scheduler = None
    if settings.enable_scheduler:
        from app.workers.scheduler import Scheduler

        scheduler = Scheduler(settings)
        await scheduler.start()
        log.info("scheduler_started")

    log.info(
        "startup_complete",
        extra={
            "env": settings.app_env,
            "provider": settings.market_data_provider,
            "paper_trading": settings.paper_trading,
        },
    )
    try:
        yield
    finally:
        if scheduler is not None:
            await scheduler.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Equity Signal Tracker API",
        version="1.0.0",
        description=(
            "Market scanning, BUY/SELL signal generation and permanent alert tracking for "
            "the Equity Signal Tracker Android app. Paper trading only — this service does "
            "not route broker orders."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["*"],
    )

    @app.exception_handler(EquitySignalError)
    async def domain_error_handler(_: Request, exc: EquitySignalError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    from app.api.routers import (
        alerts,
        backtests,
        market,
        portfolio,
        scanner,
        stocks,
        system,
    )
    from app.api.routers import (
        settings as settings_router,
    )

    app.include_router(system.router, prefix=API_PREFIX)
    app.include_router(system.secured, prefix=API_PREFIX)
    app.include_router(market.router, prefix=API_PREFIX)
    app.include_router(scanner.router, prefix=API_PREFIX)
    app.include_router(stocks.router, prefix=API_PREFIX)
    app.include_router(alerts.router, prefix=API_PREFIX)
    app.include_router(portfolio.router, prefix=API_PREFIX)
    app.include_router(backtests.router, prefix=API_PREFIX)
    app.include_router(settings_router.router, prefix=API_PREFIX)

    return app


app = create_app()
