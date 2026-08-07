"""Post-signal monitoring and the SELL path.

Runs over every open alert: refreshes price-derived tracking, ratchets the trailing stop,
re-validates the original thesis, and asks the SELL engine for a decision. Every pass
writes a HOLD or SELL audit entry, so the reasoning behind holding a position is recorded
just as thoroughly as the reasoning behind exiting one (requirement 49).

Degraded-data policy: monitoring *continues* under stale data — an open position needs
watching more, not less, when data is imperfect — but a stale quote can only trigger an
exit through a hard stop breach on confirmed prices. Discretionary exits (trend, momentum,
relative strength, regime) require fresh data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import Settings, StrategyConfig, get_settings, get_strategy
from app.core.errors import DataIntegrityError
from app.core.logging import get_logger, payload
from app.data.providers.registry import ProviderRegistry, get_provider
from app.db.models import AlertStatus, BuyAlert, EventType
from app.domain.indicators.snapshot import compute_snapshot
from app.domain.regime.engine import RegimeResult, classify_regime, neutral_regime
from app.domain.scoring.components import fundamental_score
from app.domain.signals.sell_engine import BarInput, SellDecision, evaluate_sell
from app.domain.types import BarSeries
from app.services import audit, lifecycle
from app.services.market_data import MarketDataService

log = get_logger(__name__)

#: Exit reasons that require fresh data. A hard stop is deliberately absent — a confirmed
#: stop breach must always be honoured.
_DISCRETIONARY_EXITS = frozenset(
    {
        "TREND_BREAKDOWN", "MOMENTUM_DETERIORATION", "RS_BREAKDOWN", "BREAKOUT_FAILURE",
        "REGIME_DETERIORATION", "RISK_INCREASE", "FUNDAMENTAL_DETERIORATION",
        "TIME_EXIT", "VOLATILITY_EXIT",
    }
)


@dataclass
class MonitorResult:
    started_at: datetime
    finished_at: datetime | None = None
    monitored: int = 0
    updated: int = 0
    sells_created: int = 0
    closed: int = 0
    partials: int = 0
    errors: list[str] = field(default_factory=list)
    new_sell_uids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "started_at_utc": self.started_at.isoformat(),
            "finished_at_utc": self.finished_at.isoformat() if self.finished_at else None,
            "monitored": self.monitored,
            "updated": self.updated,
            "sells_created": self.sells_created,
            "closed": self.closed,
            "partials": self.partials,
            "errors": self.errors[:20],
            "new_sell_uids": self.new_sell_uids,
        }


class Monitor:
    def __init__(
        self,
        provider: ProviderRegistry | None = None,
        cfg: StrategyConfig | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.cfg = cfg or get_strategy()
        self.provider = provider or get_provider()
        self.market_data = MarketDataService(self.provider, self.settings)

    def run(self, session: Session) -> MonitorResult:
        result = MonitorResult(started_at=utc_now())
        alerts = lifecycle.open_alerts(session)
        result.monitored = len(alerts)
        if not alerts:
            result.finished_at = utc_now()
            return result

        benchmarks = self.market_data.load_benchmarks()
        regime = self._regime(benchmarks)

        for alert in alerts:
            try:
                outcome = self._monitor_one(session, alert, benchmarks, regime)
            except DataIntegrityError as exc:
                result.errors.append(f"{alert.ticker}: {exc}")
                audit.record_data_failure(
                    session, alert.ticker, "MONITOR", exc.code, str(exc),
                    strategy_version=alert.strategy_version,
                    data_provider=self.provider.last_used,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{alert.ticker}: {exc}")
                log.exception("monitor_failed", extra={"ticker": alert.ticker})
                continue

            result.updated += 1
            if outcome is not None:
                result.sells_created += 1
                result.new_sell_uids.append(outcome.alert_uid)
                if alert.status == AlertStatus.CLOSED.value:
                    result.closed += 1
                else:
                    result.partials += 1

        session.flush()
        result.finished_at = utc_now()
        log.info("monitor_complete", extra=payload(result.as_dict()))
        return result

    # ----------------------------------------------------------------------------------

    def _regime(self, benchmarks: dict[str, BarSeries]) -> RegimeResult:
        spy = benchmarks.get("SPY")
        if spy is None:
            return neutral_regime(self.cfg)
        try:
            return classify_regime(
                benchmark=spy.window(-1),
                sector_windows={s: b.window(-1) for s, b in benchmarks.items() if s.startswith("XL")},
                cfg=self.cfg,
                secondary={s: benchmarks[s].window(-1) for s in ("QQQ", "IWM") if s in benchmarks},
            )
        except DataIntegrityError:
            # Monitoring must not stop because the regime is momentarily unclassifiable;
            # the regime-based exit is simply unavailable this pass.
            return neutral_regime(self.cfg)

    def _monitor_one(
        self,
        session: Session,
        alert: BuyAlert,
        benchmarks: dict[str, BarSeries],
        regime: RegimeResult,
    ):
        series = self.market_data.load_series(alert.ticker)
        health = self.market_data.assess_freshness(series, self.cfg)
        window = series.window(-1)
        bar = window.current_bar()

        context = self.market_data.build_context(
            benchmarks, alert.sector, volatility_level=regime.volatility_proxy
        )
        snapshot = compute_snapshot(window, context)

        lifecycle.promote_to_active(session, alert)
        lifecycle.apply_price_update(
            session, alert, price=bar.close, bar_high=bar.high, bar_low=bar.low
        )

        position = lifecycle.to_tracked_position(alert)
        position.bars_held = alert.bars_held + 1
        lifecycle.update_tracking(session, alert, bars_held=position.bars_held)

        current_fundamental = None
        try:
            fundamentals = self.provider.get_fundamentals(alert.ticker)
            if fundamentals is not None:
                current_fundamental = fundamental_score(fundamentals, self.cfg).score
        except Exception:  # noqa: BLE001
            pass

        decision = evaluate_sell(
            position=position,
            bar=BarInput(open=bar.open, high=bar.high, low=bar.low, close=bar.close),
            snapshot=snapshot,
            regime=regime,
            cfg=self.cfg,
            current_fundamental_score=current_fundamental,
        )

        if decision.trailing and decision.trailing.stop is not None:
            lifecycle.apply_trailing_stop(
                session, alert, decision.trailing.stop, decision.trailing.mode
            )

        self._update_thesis(session, alert, decision)

        if decision.should_sell and decision.exit_reason in _DISCRETIONARY_EXITS and not health.fresh:
            # Refuse to act on a discretionary signal derived from stale inputs.
            audit.record(
                session, alert.ticker, "HOLD", "SELL_GATE",
                strategy_version=alert.strategy_version,
                reason=(
                    f"{decision.exit_reason} suppressed — data stale "
                    f"({'; '.join(health.issues)})"
                ),
                rules_failed=["data_integrity"],
                data_provider=self.provider.last_used,
            )
            return None

        if not decision.should_sell:
            audit.record(
                session, alert.ticker, "HOLD", "SELL_GATE",
                strategy_version=alert.strategy_version,
                indicators=snapshot.as_dict(),
                reason="; ".join(decision.hold_reasons[:4]),
                rules_passed=["stop_not_reached"],
                data_provider=self.provider.last_used,
            )
            return None

        sell = lifecycle.record_sell(
            session,
            alert,
            decision,
            price=decision.suggested_fill if decision.suggested_fill is not None else bar.close,
            regime=regime.regime,
        )
        audit.record(
            session, alert.ticker, "SELL", "SELL_GATE",
            strategy_version=alert.strategy_version,
            indicators=snapshot.as_dict(),
            reason=decision.detail,
            rules_passed=decision.rules_fired,
            data_provider=self.provider.last_used,
        )
        return sell

    def _update_thesis(self, session: Session, alert: BuyAlert, decision: SellDecision) -> None:
        notes = decision.hold_reasons if not decision.should_sell else [decision.detail or ""]
        valid = not decision.warnings and not decision.should_sell
        was_valid = alert.thesis_valid

        lifecycle.update_tracking(
            session, alert,
            thesis_valid=valid,
            thesis_notes=(decision.warnings + notes)[:8],
        )
        if was_valid and not valid and decision.warnings:
            lifecycle.add_event(
                session, alert, EventType.THESIS_WARNING, "THESIS WARNING",
                detail="; ".join(decision.warnings), price=alert.current_price,
            )
