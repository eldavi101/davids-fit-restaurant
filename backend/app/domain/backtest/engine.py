"""The backtesting engine.

Bar-by-bar, cash-constrained, next-open execution. It calls the *same* scoring, BUY and
SELL functions the live scanner uses (BACKTESTING_SPEC.md §1), so there is no second
implementation of the strategy that could quietly diverge.

The bias controls that matter are structural rather than advisory:

* signals are computed from a ``BarWindow`` cut at bar ``t`` and can never see bar ``t+1``;
* orders generated on bar ``t`` fill at the **open of ``t+1``**, with slippage and half the
  spread against the trade;
* when a bar's range contains both the stop and the target, the **stop** wins;
* a gap through the stop fills at the open, not at the stop price;
* a split inside an open position rescales entry, stop, targets and share count in the
  same bar, so no phantom gap-down stop fires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import StrategyConfig
from app.core.errors import DataIntegrityError
from app.domain.backtest.metrics import (
    PerformanceMetrics,
    TradeRecord,
    compute_metrics,
    monthly_returns,
)
from app.domain.indicators.snapshot import compute_snapshot
from app.domain.portfolio.sizing import OpenPositionView, position_size
from app.domain.probability.model import ProbabilityModel, build_features
from app.domain.regime.engine import classify_regime, neutral_regime
from app.domain.scoring.opportunity import score_stock
from app.domain.signals.buy_engine import BuyContext, evaluate_buy
from app.domain.signals.levels import compute_levels
from app.domain.signals.sell_engine import BarInput, TrackedPosition, evaluate_sell
from app.domain.types import BarSeries, Fundamentals, MarketContext


@dataclass
class OpenTrade:
    ticker: str
    entry_index: int
    entry_ts: datetime
    entry_price: float
    shares: float
    position: TrackedPosition
    opportunity_score: float
    regime: str
    sector: str | None
    slippage_cost: float = 0.0
    spread_cost: float = 0.0
    commission: float = 0.0
    fold: int | None = None
    sample: str | None = None


@dataclass
class PendingOrder:
    ticker: str
    signal_index: int
    levels: object
    opportunity_score: float
    regime: str
    sector: str | None
    snapshot: object


@dataclass
class BacktestResult:
    metrics: PerformanceMetrics
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    monthly: list[dict] = field(default_factory=list)
    bias_warnings: list[str] = field(default_factory=list)
    skipped_insufficient_capital: int = 0
    signals_generated: int = 0
    bars_processed: int = 0

    def as_dict(self) -> dict:
        return {
            "metrics": self.metrics.as_dict(),
            "equity_curve": self.equity_curve,
            "monthly_returns": self.monthly,
            "bias_warnings": self.bias_warnings,
            "skipped_insufficient_capital": self.skipped_insufficient_capital,
            "signals_generated": self.signals_generated,
            "bars_processed": self.bars_processed,
            "trades": len(self.trades),
        }


class BacktestEngine:
    def __init__(
        self,
        cfg: StrategyConfig,
        initial_equity: float = 100_000.0,
        probability_model: ProbabilityModel | None = None,
        fundamentals: dict[str, Fundamentals] | None = None,
        supports_delisted: bool = False,
        fold: int | None = None,
        sample: str | None = None,
    ):
        self.cfg = cfg
        self.initial_equity = initial_equity
        self.probability_model = probability_model or ProbabilityModel(cfg)
        self.fundamentals = fundamentals or {}
        self.supports_delisted = supports_delisted
        self.fold = fold
        self.sample = sample

    # ----------------------------------------------------------------------------------

    def run(
        self,
        universe: dict[str, BarSeries],
        benchmarks: dict[str, BarSeries],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> BacktestResult:
        spy = benchmarks.get("SPY")
        if spy is None or len(spy) < self.cfg.min_bars_required:
            raise DataIntegrityError("SPY history is required to run a backtest")

        calendar = [ts for ts in spy.ts]
        index_maps = {t: {ts: i for i, ts in enumerate(s.ts)} for t, s in universe.items()}
        bench_index = {t: {ts: i for i, ts in enumerate(s.ts)} for t, s in benchmarks.items()}

        cash = self.initial_equity
        equity = self.initial_equity
        peak_equity = equity
        open_trades: dict[str, OpenTrade] = {}
        pending: list[PendingOrder] = []
        closed: list[TradeRecord] = []
        curve: list[dict] = []
        curve_ts: list[datetime] = []
        bench_curve: list[float] = []
        bench_start_price: float | None = None
        result = BacktestResult(metrics=PerformanceMetrics())

        start_at = max(self.cfg.min_bars_required, 1)
        for t in range(start_at, len(calendar)):
            ts = calendar[t]
            if start and ts < start:
                continue
            if end and ts > end:
                break
            result.bars_processed += 1

            # ---- 1. fill orders queued on the previous close, at THIS bar's open -------
            for order in pending:
                series = universe.get(order.ticker)
                idx = index_maps.get(order.ticker, {}).get(ts)
                if series is None or idx is None or order.ticker in open_trades:
                    continue
                filled = self._open_trade(
                    order, series, idx, ts, cash, equity, open_trades, universe, index_maps
                )
                if filled is None:
                    result.skipped_insufficient_capital += 1
                    continue
                trade, cost = filled
                cash -= cost
                open_trades[order.ticker] = trade
            pending = []

            # ---- 2. mark to market, handle splits, evaluate exits ------------------------
            regime = self._regime_at(benchmarks, bench_index, ts)
            for ticker in list(open_trades):
                trade = open_trades[ticker]
                series = universe[ticker]
                idx = index_maps[ticker].get(ts)
                if idx is None:
                    continue

                self._apply_split(trade, series, idx)

                window = series.window(idx)
                context = self._context(benchmarks, bench_index, ts, trade.sector)
                snapshot = compute_snapshot(window, context)
                bar = series.bar(idx)

                trade.position.bars_held = idx - trade.entry_index
                trade.position.holding_days = max(0, (ts - trade.entry_ts).days)
                trade.position.highest_close_since_entry = max(
                    trade.position.highest_close_since_entry, bar.close
                )
                trade.position.highest_price_since_entry = max(
                    trade.position.highest_price_since_entry, bar.high
                )
                trade.position.lowest_price_since_entry = min(
                    trade.position.lowest_price_since_entry, bar.low
                )

                decision = evaluate_sell(
                    position=trade.position,
                    bar=BarInput(open=bar.open, high=bar.high, low=bar.low, close=bar.close),
                    snapshot=snapshot,
                    regime=regime,
                    cfg=self.cfg,
                )
                trade.position.trend_break_bars = decision.trend_break_bars
                if decision.trailing and decision.trailing.stop is not None:
                    trade.position.trailing_stop = decision.trailing.stop
                    trade.position.trailing_active = decision.trailing.active

                if not decision.should_sell:
                    continue

                # Stops and targets fill intrabar at the modelled price; everything else
                # is a market order placed on the close and filled here conservatively.
                fill = decision.suggested_fill if decision.suggested_fill is not None else bar.close
                if decision.exit_reason not in ("STOP_LOSS", "TRAILING_STOP", "TARGET_1", "TARGET_2"):
                    fill = self._sell_fill(bar.close)
                elif decision.exit_reason in ("STOP_LOSS", "TRAILING_STOP"):
                    fill = self._sell_fill(fill)

                proceeds, record = self._close_trade(trade, fill, ts, idx, decision)
                cash += proceeds
                closed.append(record)
                if decision.exit_reason in ("TARGET_1", "TARGET_2") and self.cfg.sell.staged_exits:
                    if decision.exit_reason == "TARGET_1":
                        trade.position.target1_hit = True
                        trade.position.trailing_active = True
                    else:
                        trade.position.target2_hit = True
                    remaining = trade.position.remaining_fraction - decision.fraction
                    if remaining > 1e-9:
                        trade.position.remaining_fraction = remaining
                        continue
                del open_trades[ticker]

            # ---- 3. mark equity ---------------------------------------------------------
            positions_value = 0.0
            for ticker, trade in open_trades.items():
                idx = index_maps[ticker].get(ts)
                price = float(universe[ticker].close[idx]) if idx is not None else trade.entry_price
                positions_value += trade.shares * price
            equity = cash + positions_value
            peak_equity = max(peak_equity, equity)

            bench_idx = bench_index["SPY"].get(ts)
            if bench_idx is not None:
                bench_price = float(spy.close[bench_idx])
                if bench_start_price is None:
                    bench_start_price = bench_price
                bench_curve.append(self.initial_equity * bench_price / bench_start_price)
            elif bench_curve:
                bench_curve.append(bench_curve[-1])

            curve_ts.append(ts)
            curve.append(
                {
                    "ts_utc": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                    "equity": round(equity, 2),
                    "cash": round(cash, 2),
                    "open_positions": len(open_trades),
                    "benchmark": round(bench_curve[-1], 2) if bench_curve else None,
                    "drawdown_pct": round(100.0 * (equity / peak_equity - 1.0), 4)
                    if peak_equity > 0 else 0.0,
                }
            )

            # ---- 4. generate signals from THIS close, for execution next open -----------
            if end and ts >= end:
                continue
            pending = self._generate_signals(
                universe, index_maps, benchmarks, bench_index, ts, regime,
                open_trades, equity, cash, result,
            )

        # ---- final: close anything still open at the last available price ---------------
        if open_trades:
            last_ts = curve_ts[-1] if curve_ts else calendar[-1]
            for ticker, trade in list(open_trades.items()):
                idx = index_maps[ticker].get(last_ts)
                price = float(universe[ticker].close[idx]) if idx is not None else trade.entry_price
                proceeds, record = self._close_trade(
                    trade, self._sell_fill(price), last_ts, idx or 0, None,
                    forced_reason="TIME_EXIT",
                )
                cash += proceeds
                closed.append(record)
                del open_trades[ticker]

        equity_values = [point["equity"] for point in curve]
        result.trades = closed
        result.equity_curve = curve
        result.monthly = monthly_returns(curve_ts, equity_values)
        result.metrics = compute_metrics(closed, equity_values, bench_curve)
        result.bias_warnings = self._bias_warnings()
        return result

    # ----------------------------------------------------------------------------------

    def _bias_warnings(self) -> list[str]:
        warnings: list[str] = []
        if not self.supports_delisted:
            warnings.append(
                "survivorship: the configured provider supplied only currently-listed "
                "symbols, so companies that failed during the period are absent. Results "
                "are optimistic by an amount this run cannot quantify."
            )
        return warnings

    def _buy_fill(self, open_price: float) -> float:
        c = self.cfg.costs
        return open_price * (1.0 + c.slippage_bps / 1e4) + open_price * (c.spread_bps / 2e4)

    def _sell_fill(self, price: float) -> float:
        c = self.cfg.costs
        return price * (1.0 - c.slippage_bps / 1e4) - price * (c.spread_bps / 2e4)

    def _regime_at(self, benchmarks, bench_index, ts):
        spy = benchmarks.get("SPY")
        idx = bench_index.get("SPY", {}).get(ts) if spy else None
        if spy is None or idx is None or idx < 200:
            return neutral_regime(self.cfg)
        try:
            return classify_regime(
                benchmark=spy.window(idx),
                sector_windows={
                    s: benchmarks[s].window(bench_index[s][ts])
                    for s in benchmarks
                    if s.startswith("XL") and ts in bench_index.get(s, {})
                },
                cfg=self.cfg,
                secondary={
                    s: benchmarks[s].window(bench_index[s][ts])
                    for s in ("QQQ", "IWM")
                    if s in benchmarks and ts in bench_index.get(s, {})
                },
            )
        except DataIntegrityError:
            return neutral_regime(self.cfg)

    def _context(self, benchmarks, bench_index, ts, sector) -> MarketContext:
        from app.data.universe import sector_etf_for

        def window(symbol):
            series = benchmarks.get(symbol)
            idx = bench_index.get(symbol, {}).get(ts)
            return series.window(idx) if series is not None and idx is not None else None

        spy = window("SPY")
        sector_symbol = sector_etf_for(sector)
        sector_window = window(sector_symbol) or spy
        return MarketContext(
            benchmark=spy,
            sector_windows={sector_symbol: sector_window} if sector_window else {},
            secondary={s: w for s in ("QQQ", "IWM") if (w := window(s)) is not None},
            as_of=ts,
        )

    def _apply_split(self, trade: OpenTrade, series: BarSeries, idx: int) -> None:
        """Rescale an open position through a split so no phantom stop fires.

        Split detection: an unexplained close-to-close ratio near a simple fraction while
        the intrabar range stays normal. Adjusted feeds rarely need this, but a raw feed
        would silently gap the stop without it.
        """
        if idx < 1:
            return
        prev_close = float(series.close[idx - 1])
        today_open = float(series.open[idx])
        if prev_close <= 0 or today_open <= 0:
            return
        ratio = prev_close / today_open
        for factor in (2.0, 3.0, 4.0, 5.0, 10.0, 1.5):
            if abs(ratio - factor) / factor < 0.02:
                trade.shares *= factor
                p = trade.position
                p.entry_price /= factor
                p.initial_stop /= factor
                p.target1 /= factor
                p.target2 /= factor
                p.risk_per_share /= factor
                p.highest_close_since_entry /= factor
                p.highest_price_since_entry /= factor
                p.lowest_price_since_entry /= factor
                if p.trailing_stop is not None:
                    p.trailing_stop /= factor
                if p.breakout_level is not None:
                    p.breakout_level /= factor
                trade.entry_price /= factor
                return

    def _generate_signals(
        self, universe, index_maps, benchmarks, bench_index, ts, regime,
        open_trades, equity, cash, result,
    ) -> list[PendingOrder]:
        if not regime.allows_new_buys:
            return []

        candidates: list[PendingOrder] = []
        for ticker, series in universe.items():
            if ticker in open_trades:
                continue
            idx = index_maps[ticker].get(ts)
            if idx is None or idx < self.cfg.min_bars_required:
                continue
            if idx + 1 >= len(series):  # no next bar to execute against
                continue

            window = series.window(idx)
            sector = None
            context = self._context(benchmarks, bench_index, ts, sector)
            snapshot = compute_snapshot(window, context)
            fundamentals = self.fundamentals.get(ticker)
            score = score_stock(
                snapshot, regime, self.cfg,
                fundamentals=fundamentals,
                probability_sample_size=self.probability_model.n_samples,
            )
            levels = compute_levels(snapshot, self.cfg)
            if not levels.valid:
                continue
            probability = self.probability_model.predict(
                build_features(score, snapshot, levels, regime)
            )
            decision = evaluate_buy(
                snapshot, score, levels, probability, regime, self.cfg,
                BuyContext(has_open_alert=False, data_fresh=True),
            )
            if decision.should_buy:
                result.signals_generated += 1
                candidates.append(
                    PendingOrder(
                        ticker=ticker,
                        signal_index=idx,
                        levels=levels,
                        opportunity_score=score.opportunity_score,
                        regime=regime.regime,
                        sector=sector,
                        snapshot=snapshot,
                    )
                )

        # Best-scoring signals get first claim on limited capital.
        candidates.sort(key=lambda o: o.opportunity_score, reverse=True)
        return candidates

    def _open_trade(
        self, order: PendingOrder, series: BarSeries, idx: int, ts, cash, equity,
        open_trades, universe, index_maps,
    ):
        open_price = float(series.open[idx])
        fill = self._buy_fill(open_price)
        levels = order.levels
        # The stop moves with the fill so the risk-per-share stays the intended size.
        stop = fill - levels.risk_per_share
        if stop <= 0:
            return None

        views = [
            OpenPositionView(
                ticker=t,
                sector=tr.sector,
                shares=tr.shares,
                entry_price=tr.entry_price,
                current_price=float(universe[t].close[index_maps[t][ts]])
                if ts in index_maps.get(t, {}) else tr.entry_price,
                stop_price=tr.position.trailing_stop or tr.position.initial_stop,
            )
            for t, tr in open_trades.items()
        ]
        sizing = position_size(
            equity=equity, cash=cash, entry=fill, stop=stop, cfg=self.cfg,
            sector=order.sector, open_positions=views,
        )
        if sizing.shares <= 0:
            return None

        # Liquidity cap: never assume more than a small share of the bar's dollar volume.
        bar_dollar_volume = float(series.close[idx] * series.volume[idx])
        max_shares = int((bar_dollar_volume * self.cfg.costs.max_participation) / fill) if fill > 0 else 0
        shares = min(sizing.shares, max_shares) if max_shares > 0 else sizing.shares
        if shares <= 0:
            return None

        cost = shares * fill + self.cfg.costs.commission_per_trade
        if cost > cash:
            return None

        risk = fill - stop
        position = TrackedPosition(
            ticker=order.ticker,
            entry_price=fill,
            entry_ts=ts,
            initial_stop=stop,
            target1=fill + self.cfg.levels.target_r1 * risk,
            target2=fill + self.cfg.levels.target_r2 * risk,
            risk_per_share=risk,
            highest_close_since_entry=fill,
            highest_price_since_entry=fill,
            lowest_price_since_entry=fill,
            entry_atr_pct=getattr(order.snapshot, "atr_pct", None),
            entry_realized_vol=getattr(order.snapshot, "realized_vol_20", None),
            breakout_level=None,
        )
        trade = OpenTrade(
            ticker=order.ticker,
            entry_index=idx,
            entry_ts=ts,
            entry_price=fill,
            shares=shares,
            position=position,
            opportunity_score=order.opportunity_score,
            regime=order.regime,
            sector=order.sector,
            slippage_cost=shares * open_price * self.cfg.costs.slippage_bps / 1e4,
            spread_cost=shares * open_price * self.cfg.costs.spread_bps / 2e4,
            commission=self.cfg.costs.commission_per_trade,
            fold=self.fold,
            sample=self.sample,
        )
        return trade, cost

    def _close_trade(self, trade: OpenTrade, fill: float, ts, idx: int, decision, forced_reason=None):
        fraction = decision.fraction if decision and decision.fraction else 1.0
        if not self.cfg.sell.staged_exits or forced_reason:
            fraction = trade.position.remaining_fraction
        shares = trade.shares * fraction
        proceeds = shares * fill - self.cfg.costs.commission_per_trade
        entry = trade.entry_price
        record = TradeRecord(
            ticker=trade.ticker,
            entry_ts=trade.entry_ts,
            exit_ts=ts,
            entry_price=entry,
            exit_price=fill,
            shares=shares,
            return_pct=100.0 * (fill / entry - 1.0) if entry > 0 else 0.0,
            r_multiple=(fill - entry) / trade.position.risk_per_share
            if trade.position.risk_per_share > 0 else 0.0,
            exit_reason=forced_reason or (decision.exit_reason if decision else "TIME_EXIT"),
            holding_days=max(0, (ts - trade.entry_ts).days),
            max_gain_pct=100.0 * (trade.position.highest_price_since_entry / entry - 1.0)
            if entry > 0 else 0.0,
            max_drawdown_pct=100.0 * (trade.position.lowest_price_since_entry / entry - 1.0)
            if entry > 0 else 0.0,
            opportunity_score=trade.opportunity_score,
            market_regime=trade.regime,
            slippage_cost=trade.slippage_cost,
            spread_cost=trade.spread_cost,
            commission=trade.commission,
            fold=trade.fold,
            sample=trade.sample,
        )
        trade.shares -= shares
        return proceeds, record


def parameter_sensitivity(
    engine_factory,
    universe: dict[str, BarSeries],
    benchmarks: dict[str, BarSeries],
    cfg: StrategyConfig,
    parameters: tuple[str, ...] = ("min_opportunity_score", "stop_atr_mult", "target_r1", "chandelier_atr_mult"),
    nudge: float = 0.20,
) -> dict:
    """Re-run at ±20% on the key parameters (BACKTESTING_SPEC §8).

    An edge that survives only at one exact parameter value is a curve fit, and this is
    what makes that visible instead of leaving it to be discovered live.
    """
    out: dict[str, dict] = {}
    for name in parameters:
        try:
            base_value = _lookup(cfg, name)
        except KeyError:
            continue
        variants: dict[str, float | None] = {}
        for label, factor in (("minus_20pct", 1 - nudge), ("plus_20pct", 1 + nudge)):
            variant_cfg = cfg.with_overrides({name: base_value * factor})
            engine = engine_factory(variant_cfg)
            try:
                result = engine.run(universe, benchmarks)
                variants[label] = result.metrics.expectancy_r
            except DataIntegrityError:
                variants[label] = None
        out[name] = {"base_value": base_value, **variants}
    return out


def _lookup(cfg: StrategyConfig, name: str) -> float:
    data = cfg.model_dump()
    for section in ("buy_gate", "levels", "trailing", "sell", "probability", "portfolio", "costs"):
        if name in data[section]:
            return float(data[section][name])
    raise KeyError(name)
