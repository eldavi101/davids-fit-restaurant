"""Backtest orchestration: load data, run the engine, persist the run and its trades."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import StrategyConfig
from app.core.errors import DataIntegrityError, NotFoundError
from app.core.logging import get_logger
from app.data.providers.registry import get_provider
from app.db.models import BacktestRun, BacktestTrade, Instrument
from app.domain.backtest.engine import BacktestEngine, parameter_sensitivity
from app.domain.backtest.metrics import TradeRecord
from app.domain.backtest.walkforward import chronological_split, run_walk_forward
from app.services.market_data import MarketDataService

log = get_logger(__name__)

MAX_UNIVERSE = 60
BARS_TO_LOAD = 1600


def create_run(
    session: Session,
    cfg: StrategyConfig,
    mode: str,
    start: datetime | None,
    end: datetime | None,
    parameters: dict,
    universe_size: int,
) -> BacktestRun:
    run = BacktestRun(
        strategy_version=cfg.version,
        mode=mode.upper(),
        start_date=start.date() if start else None,
        end_date=end.date() if end else None,
        universe_size=universe_size,
        parameters=parameters,
        status="QUEUED",
    )
    session.add(run)
    session.flush()
    return run


def execute_run(
    session: Session,
    run_id: int,
    cfg: StrategyConfig,
    tickers: list[str] | None = None,
    initial_equity: float = 100_000.0,
    walk_forward: dict | None = None,
    include_sensitivity: bool = False,
) -> BacktestRun:
    run = session.get(BacktestRun, run_id)
    if run is None:
        raise NotFoundError(f"backtest run {run_id} not found")

    run.status = "RUNNING"
    session.flush()

    provider = get_provider()
    service = MarketDataService(provider)

    try:
        universe = _load_universe(session, service, tickers)
        benchmarks = service.load_benchmarks(limit=BARS_TO_LOAD)
        if "SPY" not in benchmarks:
            raise DataIntegrityError("SPY history unavailable — a backtest cannot be benchmarked")

        start = _to_datetime(run.start_date) or _default_start(benchmarks)
        end = _to_datetime(run.end_date) or utc_now()
        run.universe_size = len(universe)

        if run.mode == "WALK_FORWARD":
            wf = walk_forward or {}
            result = run_walk_forward(
                universe=universe,
                benchmarks=benchmarks,
                cfg=cfg,
                start=start,
                end=end,
                initial_equity=initial_equity,
                train_years=int(wf.get("train_years", 4)),
                test_years=int(wf.get("test_years", 1)),
                step_years=int(wf.get("step_years", 1)),
                anchored=bool(wf.get("anchored", False)),
                supports_delisted=provider.supports_delisted,
            )
            _store_metrics(run, result.aggregate_test)
            run.folds = [f.as_dict() for f in result.folds]
            run.equity_curve = result.equity_curve
            run.bias_warnings = result.bias_warnings + (
                [f"overfit_gap: {result.overfit_gap:+.4f}R between train and test expectancy"]
                if result.overfit_gap is not None else []
            )
            _store_trades(session, run, result.test_trades)
        else:
            if run.mode == "OOS":
                split = chronological_split(start, end)
                start, end = split.test_start, split.test_end
                run.parameters = {**(run.parameters or {}), "oos_split": split.as_dict()}

            engine = BacktestEngine(
                cfg, initial_equity, supports_delisted=provider.supports_delisted,
                sample="TEST" if run.mode == "OOS" else None,
            )
            result = engine.run(universe, benchmarks, start, end)
            _store_metrics(run, result.metrics)
            run.equity_curve = result.equity_curve
            run.monthly_returns = result.monthly
            run.bias_warnings = result.bias_warnings + result.metrics.warnings
            _store_trades(session, run, result.trades)

            if include_sensitivity:
                run.sensitivity = parameter_sensitivity(
                    lambda c: BacktestEngine(c, initial_equity,
                                             supports_delisted=provider.supports_delisted),
                    universe, benchmarks, cfg,
                )

        run.status = "COMPLETE"
    except Exception as exc:  # noqa: BLE001 — a failed run must be recorded, not lost
        run.status = "FAILED"
        run.error = str(exc)
        log.exception("backtest_failed", extra={"run_uid": run.run_uid})

    session.flush()
    return run


def _load_universe(session: Session, service: MarketDataService, tickers: list[str] | None) -> dict:
    if tickers:
        symbols = [t.upper() for t in tickers][:MAX_UNIVERSE]
    else:
        symbols = [
            row.ticker
            for row in session.execute(
                select(Instrument)
                .where(Instrument.eligible.is_(True))
                .order_by(Instrument.ticker)
                .limit(MAX_UNIVERSE)
            ).scalars()
        ]
    universe: dict = {}
    for symbol in symbols:
        try:
            universe[symbol] = service.load_series(symbol, limit=BARS_TO_LOAD)
        except DataIntegrityError:
            log.warning("backtest_symbol_skipped", extra={"ticker": symbol})
    if not universe:
        raise DataIntegrityError("no usable price history for the requested universe")
    return universe


def _default_start(benchmarks: dict) -> datetime:
    spy = benchmarks["SPY"]
    ts = spy.ts[0]
    return ts if isinstance(ts, datetime) else utc_now() - timedelta(days=365 * 5)


def _to_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    from datetime import time

    return datetime.combine(value, time.min, tzinfo=UTC)


def _store_metrics(run: BacktestRun, metrics) -> None:
    run.trades = metrics.trades
    run.win_rate = metrics.win_rate
    run.profit_factor = metrics.profit_factor
    run.expectancy = metrics.expectancy_r
    run.sharpe = metrics.sharpe
    run.sortino = metrics.sortino
    run.max_drawdown_pct = metrics.max_drawdown_pct
    run.avg_return_pct = metrics.avg_return_pct
    run.median_return_pct = metrics.median_return_pct
    run.avg_holding_days = metrics.avg_holding_days
    run.target_hit_rate = metrics.target_hit_rate
    run.stop_rate = metrics.stop_rate
    run.total_return_pct = metrics.total_return_pct
    run.benchmark_return_pct = metrics.benchmark_return_pct


def _store_trades(session: Session, run: BacktestRun, trades: list[TradeRecord]) -> None:
    for trade in trades:
        session.add(
            BacktestTrade(
                backtest_run_id=run.id,
                ticker=trade.ticker,
                entry_ts_utc=trade.entry_ts,
                entry_price=trade.entry_price,
                exit_ts_utc=trade.exit_ts,
                exit_price=trade.exit_price,
                shares=trade.shares,
                return_pct=trade.return_pct,
                r_multiple=trade.r_multiple,
                exit_reason=trade.exit_reason,
                max_gain_pct=trade.max_gain_pct,
                max_drawdown_pct=trade.max_drawdown_pct,
                holding_days=trade.holding_days,
                opportunity_score=trade.opportunity_score,
                market_regime=trade.market_regime,
                slippage_cost=trade.slippage_cost,
                spread_cost=trade.spread_cost,
                commission=trade.commission,
                fold=trade.fold,
                sample=trade.sample,
            )
        )
