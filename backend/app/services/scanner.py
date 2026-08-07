"""The scanner: universe → scoring → BUY gate → alert.

One pass over the eligible universe. For every stock it produces a persisted
``stock_scores`` row and an ``audit_logs`` entry — including for the ones it rejects,
because "why didn't it alert on X?" is as important a question as "why did it alert on Y?".

Requirement 51 is implemented at two levels: a global check (regime unknown, provider
down) aborts the whole scan without creating anything, and a per-stock check records the
failure and skips that stock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import Settings, StrategyConfig, get_settings, get_strategy
from app.core.errors import DataIntegrityError, DuplicateAlertError, MarketDataUnavailableError
from app.core.logging import get_logger, payload
from app.data.providers.registry import ProviderRegistry, get_provider
from app.db.models import BuyAlert, Instrument, MarketRegimeRow, StockScore
from app.domain.indicators.snapshot import compute_snapshot
from app.domain.probability.model import ProbabilityModel, build_features
from app.domain.regime.engine import RegimeResult, classify_regime
from app.domain.scoring.opportunity import ScoreResult, score_stock
from app.domain.signals.buy_engine import BuyContext, BuyDecision, evaluate_buy
from app.domain.signals.levels import compute_levels
from app.domain.types import BarSeries, Fundamentals
from app.services import audit, lifecycle
from app.services.market_data import MarketDataService

log = get_logger(__name__)


@dataclass
class ScanResult:
    started_at: datetime
    finished_at: datetime | None = None
    regime: RegimeResult | None = None
    scanned: int = 0
    scored: int = 0
    skipped: int = 0
    alerts_created: int = 0
    strong_opportunities: int = 0
    errors: list[str] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str | None = None
    new_alert_uids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "started_at_utc": self.started_at.isoformat(),
            "finished_at_utc": self.finished_at.isoformat() if self.finished_at else None,
            "regime": self.regime.regime if self.regime else None,
            "scanned": self.scanned,
            "scored": self.scored,
            "skipped": self.skipped,
            "alerts_created": self.alerts_created,
            "strong_opportunities": self.strong_opportunities,
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "errors": self.errors[:20],
            "new_alert_uids": self.new_alert_uids,
        }


class Scanner:
    def __init__(
        self,
        provider: ProviderRegistry | None = None,
        cfg: StrategyConfig | None = None,
        settings: Settings | None = None,
        probability_model: ProbabilityModel | None = None,
    ):
        self.settings = settings or get_settings()
        self.cfg = cfg or get_strategy()
        self.provider = provider or get_provider()
        self.market_data = MarketDataService(self.provider, self.settings)
        self.probability_model = probability_model or ProbabilityModel(self.cfg)

    # ----------------------------------------------------------------------------------

    def run(self, session: Session, tickers: list[str] | None = None) -> ScanResult:
        result = ScanResult(started_at=utc_now())

        # --- global preconditions (requirement 51) --------------------------------------
        try:
            benchmarks = self.market_data.load_benchmarks()
            spy = benchmarks.get("SPY")
            if spy is None:
                raise MarketDataUnavailableError("SPY unavailable — cannot classify the regime")
            regime = classify_regime(
                benchmark=spy.window(-1),
                sector_windows={
                    s: series.window(-1)
                    for s, series in benchmarks.items()
                    if s.startswith("XL")
                },
                cfg=self.cfg,
                secondary={
                    s: benchmarks[s].window(-1) for s in ("QQQ", "IWM") if s in benchmarks
                },
            )
        except DataIntegrityError as exc:
            audit.record_data_failure(
                session, None, "SCAN", exc.code, str(exc),
                strategy_version=self.cfg.version, data_provider=self.provider.last_used,
            )
            result.aborted = True
            result.abort_reason = str(exc)
            result.finished_at = utc_now()
            log.error("scan_aborted", extra={"reason": str(exc)})
            return result

        result.regime = regime
        self._persist_regime(session, regime)

        instruments = self._instruments(session, tickers)
        result.scanned = len(instruments)

        for instrument in instruments:
            try:
                outcome = self._evaluate(session, instrument, benchmarks, regime)
            except DataIntegrityError as exc:
                result.skipped += 1
                result.errors.append(f"{instrument.ticker}: {exc}")
                audit.record_data_failure(
                    session, instrument.ticker, "SCAN", exc.code, str(exc),
                    strategy_version=self.cfg.version, data_provider=self.provider.last_used,
                )
                continue
            except Exception as exc:  # noqa: BLE001 — one bad symbol must not stop the scan
                result.skipped += 1
                result.errors.append(f"{instrument.ticker}: {exc}")
                log.exception("scan_symbol_failed", extra={"ticker": instrument.ticker})
                audit.record(
                    session, instrument.ticker, "ERROR", "SCAN",
                    strategy_version=self.cfg.version, reason=str(exc),
                    error_code=type(exc).__name__,
                )
                continue

            if outcome is None:
                result.skipped += 1
                continue

            result.scored += 1
            decision, alert = outcome
            if decision.score.category in ("EXCEPTIONAL", "STRONG_BUY", "BUY"):
                result.strong_opportunities += 1
            if alert is not None:
                result.alerts_created += 1
                result.new_alert_uids.append(alert.alert_uid)

        session.flush()
        result.finished_at = utc_now()
        log.info("scan_complete", extra=payload(result.as_dict()))
        return result

    # ----------------------------------------------------------------------------------

    def _instruments(self, session: Session, tickers: list[str] | None) -> list[Instrument]:
        stmt = select(Instrument).where(Instrument.delisted.is_(False))
        if tickers:
            stmt = stmt.where(Instrument.ticker.in_([t.upper() for t in tickers]))
        else:
            stmt = stmt.where(Instrument.eligible.is_(True))
        return list(session.execute(stmt.order_by(Instrument.ticker)).scalars())

    def _persist_regime(self, session: Session, regime: RegimeResult) -> None:
        session.add(
            MarketRegimeRow(
                ts_utc=regime.ts_utc,
                regime=regime.regime,
                regime_score=regime.regime_score,
                spy_close=regime.spy_close,
                spy_above_ema20=regime.spy_above_ema20,
                spy_above_sma50=regime.spy_above_sma50,
                spy_above_sma200=regime.spy_above_sma200,
                qqq_rs=regime.qqq_rs,
                iwm_rs=regime.iwm_rs,
                breadth_pct=regime.breadth_pct,
                participation_pct=regime.participation_pct,
                volatility_proxy=regime.volatility_proxy,
                spy_drawdown_pct=regime.spy_drawdown_pct,
                sector_participation=regime.sector_participation,
                components=regime.components,
                strategy_version=self.cfg.version,
            )
        )

    def _evaluate(
        self,
        session: Session,
        instrument: Instrument,
        benchmarks: dict[str, BarSeries],
        regime: RegimeResult,
    ) -> tuple[BuyDecision, BuyAlert | None] | None:
        series = self.market_data.load_series(instrument.ticker)
        health = self.market_data.assess_freshness(series, self.cfg)
        self.market_data.persist_bars(session, instrument, [series.bar(i) for i in range(len(series))][-30:])

        if len(series) < self.cfg.min_bars_required:
            audit.record(
                session, instrument.ticker, "SKIP", "SCORE",
                strategy_version=self.cfg.version,
                reason=f"insufficient history: {len(series)} bars",
                rules_failed=["data_integrity"],
            )
            return None

        context = self.market_data.build_context(
            benchmarks, instrument.sector, volatility_level=regime.volatility_proxy
        )
        snapshot = compute_snapshot(series.window(-1), context)

        fundamentals: Fundamentals | None = None
        try:
            fundamentals = self.provider.get_fundamentals(instrument.ticker)
        except Exception:  # noqa: BLE001 — fundamentals are optional, never fatal
            log.warning("fundamentals_unavailable", extra={"ticker": instrument.ticker})

        days_to_earnings = _days_to_earnings(fundamentals)

        score = score_stock(
            snapshot, regime, self.cfg,
            fundamentals=fundamentals,
            days_to_earnings=days_to_earnings,
            probability_sample_size=self.probability_model.n_samples,
        )
        levels = compute_levels(snapshot, self.cfg)
        features = build_features(score, snapshot, levels, regime)
        probability = self.probability_model.predict(features)

        quote = self.provider.get_quote(instrument.ticker)
        ctx = BuyContext(
            market_cap=instrument.market_cap,
            spread_bps=quote.spread_bps if quote else None,
            days_to_earnings=days_to_earnings,
            has_open_alert=lifecycle.has_open_alert(session, instrument.id),
            data_fresh=health.fresh,
            data_issues=health.issues,
            security_type=instrument.security_type,
        )
        decision = evaluate_buy(snapshot, score, levels, probability, regime, self.cfg, ctx)

        self._persist_score(session, instrument, score, levels, probability, decision, snapshot, regime)
        audit.record(
            session,
            instrument.ticker,
            "BUY" if decision.should_buy else "NO_BUY",
            "BUY_GATE",
            strategy_version=self.cfg.version,
            inputs={"price": snapshot.close, "market_cap": instrument.market_cap,
                    "days_to_earnings": days_to_earnings},
            indicators=snapshot.as_dict(),
            scores=score.breakdown(),
            rules_passed=decision.rules_passed,
            rules_failed=decision.rules_failed,
            reason=decision.blocking_reason,
            data_provider=self.provider.last_used,
        )

        alert = None
        if decision.should_buy:
            try:
                alert = lifecycle.create_buy_alert(
                    session,
                    instrument=instrument,
                    decision=decision,
                    snapshot=snapshot,
                    quote=quote,
                    strategy_version=self.cfg.version,
                    data_provider=self.provider.last_used,
                    earnings_date=fundamentals.next_earnings_date if fundamentals else None,
                )
            except DuplicateAlertError as exc:
                log.info("duplicate_alert_suppressed", extra={"ticker": instrument.ticker,
                                                             "detail": str(exc)})
        return decision, alert

    def _persist_score(
        self,
        session: Session,
        instrument: Instrument,
        score: ScoreResult,
        levels,
        probability,
        decision: BuyDecision,
        snapshot,
        regime: RegimeResult,
    ) -> None:
        session.add(
            StockScore(
                instrument_id=instrument.id,
                ticker=instrument.ticker,
                ts_utc=utc_now(),
                strategy_version=self.cfg.version,
                trend_score=score.trend.score,
                momentum_score=score.momentum.score,
                volume_score=score.volume.score,
                breakout_score=score.breakout.score,
                relative_strength_score=score.relative_strength.score,
                fundamental_score=score.fundamental.score,
                risk_score=score.risk.score,
                regime_score=score.regime_score,
                opportunity_score=score.opportunity_score,
                confidence=score.confidence,
                category=score.category,
                components=score.breakdown(),
                rules_passed=decision.rules_passed,
                rules_failed=decision.rules_failed,
                price=snapshot.close,
                suggested_entry=levels.entry,
                stop_price=levels.stop if levels.valid else None,
                target1_price=levels.target1 if levels.valid else None,
                target2_price=levels.target2 if levels.valid else None,
                reward_risk=levels.reward_risk,
                probability=probability.probability,
                probability_sample_size=probability.sample_size,
                expected_value=probability.expected_value_r,
                signal_ready=decision.should_buy,
                rel_volume=snapshot.rel_volume,
                rs_21=snapshot.rs_21,
                atr_pct=snapshot.atr_pct,
                sector=instrument.sector,
                market_cap=instrument.market_cap,
                market_regime=regime.regime,
                data_provider=self.provider.last_used,
            )
        )


def _days_to_earnings(fundamentals: Fundamentals | None) -> int | None:
    if fundamentals is None or fundamentals.next_earnings_date is None:
        return None
    delta = fundamentals.next_earnings_date - utc_now()
    return max(0, delta.days)


def latest_scores(session: Session, limit: int = 500) -> list[StockScore]:
    """Most recent score row per ticker — the scanner feed the app renders."""
    rows = list(
        session.execute(
            select(StockScore).order_by(StockScore.ts_utc.desc()).limit(limit * 4)
        ).scalars()
    )
    seen: set[str] = set()
    out: list[StockScore] = []
    for row in rows:
        if row.ticker in seen:
            continue
        seen.add(row.ticker)
        out.append(row)
        if len(out) >= limit:
            break
    return sorted(out, key=lambda r: r.opportunity_score, reverse=True)
