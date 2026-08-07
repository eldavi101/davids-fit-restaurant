"""Paper portfolio (requirement 41).

``PAPER_TRADING`` defaults to true and is the only mode implemented. No broker is
contacted, no order is routed; the portfolio exists so signal quality can be measured
against a realistic capital constraint rather than assumed to be free.

Positions are opened from alerts, sized by risk, and closed when their alert closes, so
the portfolio can never drift out of step with the alert ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import Settings, StrategyConfig, get_settings, get_strategy
from app.core.logging import get_logger
from app.db.models import BuyAlert, PortfolioSnapshot, Position, PositionSnapshot
from app.domain.portfolio.sizing import OpenPositionView, SizingResult, position_size

log = get_logger(__name__)

DEFAULT_PORTFOLIO = "paper"


@dataclass
class PortfolioState:
    portfolio_id: str
    equity: float
    cash: float
    positions_value: float
    open_positions: int
    unrealized_pnl: float
    realized_pnl: float
    open_risk: float
    open_risk_pct: float
    sector_exposure: dict[str, float] = field(default_factory=dict)
    drawdown_pct: float = 0.0
    peak_equity: float = 0.0

    def as_dict(self) -> dict:
        return {
            "portfolio_id": self.portfolio_id,
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "positions_value": round(self.positions_value, 2),
            "open_positions": self.open_positions,
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "open_risk": round(self.open_risk, 2),
            "open_risk_pct": round(self.open_risk_pct, 5),
            "sector_exposure": {k: round(v, 4) for k, v in self.sector_exposure.items()},
            "drawdown_pct": round(self.drawdown_pct, 4),
            "paper_trading": True,
        }


class PaperPortfolio:
    def __init__(
        self,
        cfg: StrategyConfig | None = None,
        settings: Settings | None = None,
        portfolio_id: str = DEFAULT_PORTFOLIO,
    ):
        self.cfg = cfg or get_strategy()
        self.settings = settings or get_settings()
        self.portfolio_id = portfolio_id

    # -- state ---------------------------------------------------------------------------

    def open_positions(self, session: Session) -> list[Position]:
        return list(
            session.execute(
                select(Position)
                .where(Position.portfolio_id == self.portfolio_id)
                .where(Position.status == "OPEN")
                .order_by(Position.opened_ts_utc)
            ).scalars()
        )

    def realized_pnl(self, session: Session) -> float:
        total = session.execute(
            select(func.sum(Position.realized_pnl)).where(
                Position.portfolio_id == self.portfolio_id
            )
        ).scalar()
        return float(total or 0.0)

    def state(self, session: Session) -> PortfolioState:
        positions = self.open_positions(session)
        realized = self.realized_pnl(session)
        starting = self.settings.paper_starting_equity

        positions_value = sum(
            p.shares * (p.current_price or p.entry_price) for p in positions
        )
        cost_basis = sum(p.shares * p.entry_price for p in positions)
        unrealized = positions_value - cost_basis
        cash = starting + realized - cost_basis
        equity = cash + positions_value

        open_risk = sum(
            max(0.0, p.shares * ((p.current_price or p.entry_price) - (p.stop_price or 0.0)))
            for p in positions
        )
        sector_exposure: dict[str, float] = {}
        for p in positions:
            key = p.sector or "Unknown"
            value = p.shares * (p.current_price or p.entry_price)
            sector_exposure[key] = sector_exposure.get(key, 0.0) + (value / equity if equity else 0.0)

        peak = session.execute(
            select(func.max(PortfolioSnapshot.equity)).where(
                PortfolioSnapshot.portfolio_id == self.portfolio_id
            )
        ).scalar()
        peak_equity = max(float(peak or 0.0), equity, starting)

        return PortfolioState(
            portfolio_id=self.portfolio_id,
            equity=equity,
            cash=cash,
            positions_value=positions_value,
            open_positions=len(positions),
            unrealized_pnl=unrealized,
            realized_pnl=realized,
            open_risk=open_risk,
            open_risk_pct=open_risk / equity if equity > 0 else 0.0,
            sector_exposure=sector_exposure,
            drawdown_pct=100.0 * (equity / peak_equity - 1.0) if peak_equity > 0 else 0.0,
            peak_equity=peak_equity,
        )

    # -- lifecycle -----------------------------------------------------------------------

    def size_for_alert(self, session: Session, alert: BuyAlert) -> SizingResult:
        state = self.state(session)
        views = [
            OpenPositionView(
                ticker=p.ticker,
                sector=p.sector,
                shares=p.shares,
                entry_price=p.entry_price,
                current_price=p.current_price or p.entry_price,
                stop_price=p.stop_price or 0.0,
            )
            for p in self.open_positions(session)
        ]
        return position_size(
            equity=state.equity,
            cash=state.cash,
            entry=alert.buy_price,
            stop=alert.stop_price,
            cfg=self.cfg,
            sector=alert.sector,
            open_positions=views,
        )

    def open_from_alert(self, session: Session, alert: BuyAlert) -> Position | None:
        """Open a paper position for an alert, or return None when sizing yields nothing.

        A zero-share result is not an error: the alert still exists and is still tracked.
        Signal generation and capital allocation are separate concerns (STRATEGY_SPEC §15).
        """
        existing = session.execute(
            select(Position).where(Position.buy_alert_id == alert.id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        sizing = self.size_for_alert(session, alert)
        if sizing.shares <= 0:
            log.info(
                "paper_position_skipped",
                extra={"ticker": alert.ticker, "reasons": sizing.rejections or sizing.limits_applied},
            )
            return None

        state = self.state(session)
        position = Position(
            buy_alert_id=alert.id,
            portfolio_id=self.portfolio_id,
            ticker=alert.ticker,
            opened_ts_utc=alert.buy_ts_utc,
            entry_price=alert.buy_price,
            shares=sizing.shares,
            initial_shares=sizing.shares,
            cost_basis=sizing.notional,
            stop_price=alert.stop_price,
            target1_price=alert.target1_price,
            target2_price=alert.target2_price,
            risk_amount=sizing.risk_amount,
            risk_pct_of_equity=sizing.risk_amount / state.equity if state.equity > 0 else None,
            current_price=alert.buy_price,
            sector=alert.sector,
            status="OPEN",
        )
        session.add(position)
        session.flush()
        return position

    def mark_to_market(self, session: Session, alert: BuyAlert, price: float) -> None:
        position = session.execute(
            select(Position).where(Position.buy_alert_id == alert.id).where(Position.status == "OPEN")
        ).scalar_one_or_none()
        if position is None:
            return
        position.current_price = price
        position.stop_price = alert.current_stop_price or position.stop_price
        position.unrealized_pnl = position.shares * (price - position.entry_price)
        session.add(
            PositionSnapshot(
                position_id=position.id,
                ts_utc=utc_now(),
                price=price,
                shares=position.shares,
                market_value=position.shares * price,
                unrealized_pnl=position.unrealized_pnl,
                return_pct=100.0 * (price / position.entry_price - 1.0)
                if position.entry_price > 0 else 0.0,
                stop_price=position.stop_price,
                trailing_stop_price=alert.trailing_stop_price,
            )
        )

    def reduce(
        self, session: Session, alert: BuyAlert, fraction: float, price: float,
        ts: datetime | None = None,
    ) -> None:
        """Book a partial or full exit against the paper position."""
        position = session.execute(
            select(Position).where(Position.buy_alert_id == alert.id).where(Position.status == "OPEN")
        ).scalar_one_or_none()
        if position is None:
            return

        shares_sold = position.initial_shares * fraction
        shares_sold = min(shares_sold, position.shares)
        position.realized_pnl += shares_sold * (price - position.entry_price)
        position.shares -= shares_sold
        position.current_price = price

        if position.shares <= 1e-9:
            position.shares = 0.0
            position.status = "CLOSED"
            position.closed_ts_utc = ts or utc_now()
            position.unrealized_pnl = 0.0
        else:
            position.unrealized_pnl = position.shares * (price - position.entry_price)

    def snapshot(self, session: Session, benchmark_equity: float | None = None) -> PortfolioSnapshot:
        state = self.state(session)
        row = PortfolioSnapshot(
            portfolio_id=self.portfolio_id,
            ts_utc=utc_now(),
            equity=state.equity,
            cash=state.cash,
            positions_value=state.positions_value,
            open_positions=state.open_positions,
            unrealized_pnl=state.unrealized_pnl,
            realized_pnl_cum=state.realized_pnl,
            drawdown_pct=state.drawdown_pct,
            benchmark_equity=benchmark_equity,
        )
        session.add(row)
        return row

    def equity_curve(self, session: Session, limit: int = 2000) -> list[PortfolioSnapshot]:
        rows = list(
            session.execute(
                select(PortfolioSnapshot)
                .where(PortfolioSnapshot.portfolio_id == self.portfolio_id)
                .order_by(PortfolioSnapshot.ts_utc.desc())
                .limit(limit)
            ).scalars()
        )
        rows.reverse()
        return rows
