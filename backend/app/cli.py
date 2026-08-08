"""Operator CLI — everything needed to take a fresh deployment to live data.

    python -m app.cli check          # is this deployment actually configured?
    python -m app.cli init-db        # create the schema (idempotent)
    python -m app.cli universe       # rebuild the tradable universe
    python -m app.cli scan           # one full scan pass
    python -m app.cli monitor        # one monitor pass over open alerts
    python -m app.cli bootstrap      # init-db + universe + scan + monitor, in order

``bootstrap`` exists because the scheduler alone leaves a first-run deployment looking
broken: it waits for its first interval, and its market-hours guard means a Saturday
install shows an empty app until Monday. Bootstrap fills the database immediately so the
phone has something real to render.

Nothing here prints or accepts a credential. Keys are read from the environment.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from app.core.config import Settings, get_settings

EXIT_OK = 0
EXIT_FAILED = 1


# --------------------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------------------


def _mask(value: str | None) -> str:
    """Enough to tell two keys apart, never enough to use one."""
    if not value:
        return "(unset)"
    return f"set ({len(value)} chars, ends …{value[-4:]})" if len(value) > 8 else "set (short)"


def cmd_check(settings: Settings) -> int:
    """Report whether this deployment can actually produce real signals."""
    from sqlalchemy import text

    from app.data.providers.registry import get_provider
    from app.db.session import get_engine

    problems: list[str] = []
    warnings: list[str] = []

    print(f"environment       : {settings.app_env}")
    print(f"database          : {settings.database_url.split('://')[0]}://…")
    print(f"market data       : {settings.market_data_provider}")
    print(f"fallbacks         : {', '.join(settings.fallback_providers) or '(none)'}")
    print(f"scheduler         : {'enabled' if settings.enable_scheduler else 'DISABLED'}")
    print(f"paper trading     : {settings.paper_trading}")
    print(f"app API keys      : {len(settings.api_key_set)} configured")

    # --- database ---------------------------------------------------------------------
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        print("database          : reachable ✔")
    except Exception as exc:  # noqa: BLE001 — the message is the whole point
        problems.append(f"database unreachable: {exc}")

    # --- provider ---------------------------------------------------------------------
    if settings.market_data_provider == "synthetic":
        warnings.append(
            "MARKET_DATA_PROVIDER=synthetic — the app will show generated prices, "
            "clearly labelled SYNTHETIC. Set a real vendor and its key for live data."
        )
    else:
        key = settings.provider_key(settings.market_data_provider)
        print(f"provider key      : {_mask(key)}")
        if not key:
            problems.append(
                f"MARKET_DATA_PROVIDER={settings.market_data_provider} but its API key is unset"
            )

    if not problems:
        try:
            # Rebuilt from the settings being checked: a registry cached earlier in the
            # process would report the previous configuration, which is the one failure
            # mode this command exists to rule out.
            for health in get_provider(settings, force_rebuild=True).health_all():
                mark = "✔" if health.ok else "✘"
                print(f"provider {health.name:<14}: {mark} {health.detail}")
                if not health.ok:
                    problems.append(f"provider {health.name} unhealthy: {health.detail}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"provider could not be constructed: {exc}")

    # --- credentials hygiene ------------------------------------------------------------
    if not settings.api_key_set:
        problems.append("API_KEYS is empty — the Android app would have no way to authenticate")
    if "dev-local-key" in settings.api_key_set or "change-me-to-a-long-random-string" in settings.api_key_set:
        warnings.append("API_KEYS still holds a placeholder value — replace it before exposing the API")
    if settings.app_env == "production" and settings.cors_origins.strip() == "*":
        warnings.append("CORS_ORIGINS=* in production; the Android client does not need it")
    if not settings.enable_scheduler:
        warnings.append("ENABLE_SCHEDULER=false — nothing will scan or monitor on its own")

    for warning in warnings:
        print(f"WARN  {warning}")
    for problem in problems:
        print(f"ERROR {problem}")

    print("\nresult: " + ("FAILED" if problems else "ok"))
    return EXIT_FAILED if problems else EXIT_OK


# --------------------------------------------------------------------------------------
# schema and pipeline steps
# --------------------------------------------------------------------------------------


def cmd_init_db(settings: Settings) -> int:
    from app.db.session import init_db, session_scope
    from app.services.settings_service import effective_strategy, ensure_strategy_version

    init_db()
    with session_scope() as session:
        ensure_strategy_version(session, effective_strategy(session))
    print("schema created/verified ✔")
    return EXIT_OK


def cmd_universe(settings: Settings, max_symbols: int | None = None) -> int:
    from app.db.session import session_scope
    from app.services.settings_service import effective_strategy
    from app.services.universe_service import UniverseService

    with session_scope() as session:
        cfg = effective_strategy(session)
        result = UniverseService(cfg=cfg).refresh(session, max_symbols=max_symbols)
    print(
        f"universe: {result.total_symbols} listed, {result.eligible} eligible, "
        f"{result.liquidity_probes} liquidity probes, {result.delisted} newly delisted"
    )
    for reason, count in sorted(result.exclusion_reasons.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  excluded {count:>6}  {reason}")
    if result.errors:
        print(f"  {len(result.errors)} symbol errors, first few: {result.errors[:3]}")
    return EXIT_OK if result.eligible else EXIT_FAILED


def cmd_scan(settings: Settings, tickers: list[str] | None = None) -> int:
    from app.api.routers.system import _sync_portfolio
    from app.db.session import session_scope
    from app.services.scanner import Scanner
    from app.services.settings_service import effective_strategy

    with session_scope() as session:
        cfg = effective_strategy(session)
        result = Scanner(cfg=cfg).run(session, tickers)
        _sync_portfolio(session)

    if result.aborted:
        print(f"scan ABORTED: {result.abort_reason}")
        return EXIT_FAILED
    print(
        f"scan: regime={result.regime.regime if result.regime else '?'} "
        f"scanned={result.scanned} scored={result.scored} skipped={result.skipped} "
        f"strong={result.strong_opportunities} new BUY alerts={result.alerts_created}"
    )
    for uid in result.new_alert_uids:
        print(f"  BUY alert {uid}")
    return EXIT_OK


def cmd_monitor(settings: Settings) -> int:
    from app.api.routers.system import _sync_portfolio
    from app.db.session import session_scope
    from app.services.monitor import Monitor
    from app.services.settings_service import effective_strategy

    with session_scope() as session:
        cfg = effective_strategy(session)
        result = Monitor(cfg=cfg).run(session)
        _sync_portfolio(session)
    data = result.as_dict()
    print(f"monitor: {data}")
    return EXIT_OK


def cmd_bootstrap(settings: Settings, max_symbols: int | None = None) -> int:
    """First-run sequence. Stops at the first step that fails, so the failure is visible
    rather than buried under later steps operating on an empty database."""
    steps: list[tuple[str, Callable[[], int]]] = [
        ("check", lambda: cmd_check(settings)),
        ("init-db", lambda: cmd_init_db(settings)),
        ("universe", lambda: cmd_universe(settings, max_symbols)),
        ("scan", lambda: cmd_scan(settings)),
        ("monitor", lambda: cmd_monitor(settings)),
    ]
    for name, step in steps:
        print(f"\n--- {name} " + "-" * (60 - len(name)))
        code = step()
        if code != EXIT_OK:
            print(f"\nbootstrap stopped at '{name}'.")
            return code
    print("\nbootstrap complete — the API now has real rows to serve.")
    return EXIT_OK


# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="Equity Signal Tracker operations")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="validate configuration, database and provider health")
    sub.add_parser("init-db", help="create the schema (idempotent)")

    universe = sub.add_parser("universe", help="rebuild the tradable universe")
    universe.add_argument("--max-symbols", type=int, default=None)

    scan = sub.add_parser("scan", help="run one scan pass")
    scan.add_argument("--tickers", default=None, help="comma-separated subset to scan")

    sub.add_parser("monitor", help="run one monitor pass over open alerts")

    bootstrap = sub.add_parser("bootstrap", help="check + init-db + universe + scan + monitor")
    bootstrap.add_argument("--max-symbols", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()

    from app.core.logging import configure_logging

    configure_logging(settings.log_level)

    if args.command == "check":
        return cmd_check(settings)
    if args.command == "init-db":
        return cmd_init_db(settings)
    if args.command == "universe":
        return cmd_universe(settings, args.max_symbols)
    if args.command == "scan":
        tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
        return cmd_scan(settings, tickers)
    if args.command == "monitor":
        return cmd_monitor(settings)
    if args.command == "bootstrap":
        return cmd_bootstrap(settings, args.max_symbols)
    return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
