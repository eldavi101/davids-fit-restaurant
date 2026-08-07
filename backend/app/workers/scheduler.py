"""Background scheduler: universe refresh, scanning, monitoring, portfolio snapshots.

Runs inside the FastAPI process as asyncio tasks. The blocking work (provider I/O, numpy)
happens in a thread executor so the event loop stays responsive.

Cadence is market-aware: scanning and monitoring only run while the market is open or
shortly after the close, because scoring stale intraday data adds noise rather than
information.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.core.clock import MarketSession, market_session, to_market_time, utc_now
from app.core.config import Settings, get_settings
from app.core.logging import get_logger, payload
from app.db.session import session_scope

log = get_logger(__name__)


class Scheduler:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()
        self._last_universe_refresh: datetime | None = None

    async def start(self) -> None:
        self._stopping.clear()
        self._tasks = [
            asyncio.create_task(self._loop("scan", self.settings.scan_interval_minutes, self._scan)),
            asyncio.create_task(
                self._loop("monitor", self.settings.monitor_interval_minutes, self._monitor)
            ),
            asyncio.create_task(self._loop("universe", 60, self._universe)),
        ]

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def _loop(self, name: str, interval_minutes: int, job) -> None:
        # Stagger startup so a restart does not fire every job simultaneously.
        await asyncio.sleep(5 + 5 * len(name) % 20)
        while not self._stopping.is_set():
            try:
                await asyncio.to_thread(job)
            except Exception:  # noqa: BLE001 — a failed cycle must not kill the loop
                log.exception("scheduled_job_failed", extra={"job": name})
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=max(60, interval_minutes * 60)
                )
            except TimeoutError:
                continue

    # -- jobs ---------------------------------------------------------------------------

    def _should_run_market_job(self) -> bool:
        session_state = market_session()
        return session_state in (MarketSession.OPEN, MarketSession.POST, MarketSession.PRE)

    def _scan(self) -> None:
        if not self._should_run_market_job():
            return
        from app.services.scanner import Scanner
        from app.services.settings_service import effective_strategy

        with session_scope() as session:
            cfg = effective_strategy(session)
            result = Scanner(cfg=cfg).run(session)
            log.info("scheduled_scan", extra=payload(result.as_dict()))

    def _monitor(self) -> None:
        if not self._should_run_market_job():
            return
        from app.api.routers.system import _sync_portfolio
        from app.services.monitor import Monitor
        from app.services.settings_service import effective_strategy

        with session_scope() as session:
            cfg = effective_strategy(session)
            result = Monitor(cfg=cfg).run(session)
            _sync_portfolio(session)
            log.info("scheduled_monitor", extra=payload(result.as_dict()))

    def _universe(self) -> None:
        now_et = to_market_time(utc_now())
        if now_et.hour != self.settings.universe_refresh_hour_et:
            return
        if (
            self._last_universe_refresh
            and self._last_universe_refresh.date() == now_et.date()
        ):
            return

        from app.services.settings_service import effective_strategy
        from app.services.universe_service import UniverseService

        with session_scope() as session:
            cfg = effective_strategy(session)
            result = UniverseService(cfg=cfg).refresh(session)
            log.info("scheduled_universe_refresh", extra=payload(result.as_dict()))
        self._last_universe_refresh = now_et
