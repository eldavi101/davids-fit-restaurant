"""Risk-based position sizing and portfolio-level risk limits (STRATEGY_SPEC §15–16).

Size follows from risk, never from conviction:

    risk_capital   = equity × risk_pct_per_trade
    risk_per_share = entry − stop
    shares         = floor(risk_capital / risk_per_share)

then clamped by the portfolio limits. When the clamps produce zero shares the *alert is
still created* — signal generation and capital allocation are separate concerns, and a
full portfolio is not a reason to stop recording what the strategy saw.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from app.core.config import StrategyConfig


@dataclass
class OpenPositionView:
    """Minimal view of an open position needed for portfolio-level checks."""

    ticker: str
    sector: str | None
    shares: float
    entry_price: float
    current_price: float
    stop_price: float

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def open_risk(self) -> float:
        """Capital still at risk down to the stop. Never negative: once a stop is above
        entry the position is risk-free in these terms."""
        return max(0.0, self.shares * (self.current_price - self.stop_price))


@dataclass
class SizingResult:
    shares: int
    notional: float
    risk_amount: float
    risk_pct_of_equity: float
    allowed: bool
    limits_applied: list[str] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "shares": self.shares,
            "notional": round(self.notional, 2),
            "risk_amount": round(self.risk_amount, 2),
            "risk_pct_of_equity": round(self.risk_pct_of_equity, 5),
            "allowed": self.allowed,
            "limits_applied": self.limits_applied,
            "rejections": self.rejections,
        }


def position_size(
    equity: float,
    cash: float,
    entry: float,
    stop: float,
    cfg: StrategyConfig,
    sector: str | None = None,
    open_positions: list[OpenPositionView] | None = None,
    correlations: dict[str, float] | None = None,
) -> SizingResult:
    p = cfg.portfolio
    open_positions = open_positions or []
    limits: list[str] = []
    rejections: list[str] = []

    risk_per_share = entry - stop
    if risk_per_share <= 0 or entry <= 0 or equity <= 0:
        return SizingResult(0, 0.0, 0.0, 0.0, False, rejections=["invalid_entry_or_stop"])

    risk_pct = min(p.risk_pct_per_trade, p.max_risk_pct_per_trade)
    risk_capital = equity * risk_pct
    shares = math.floor(risk_capital / risk_per_share)

    # --- hard portfolio gates (reject outright) ----------------------------------------
    if len(open_positions) >= p.max_open_positions:
        rejections.append(f"max_open_positions ({p.max_open_positions}) reached")

    current_open_risk = sum(pos.open_risk for pos in open_positions)
    risk_budget = equity * p.max_total_open_risk_pct - current_open_risk
    if risk_budget <= 0:
        rejections.append(
            f"portfolio open risk {current_open_risk / equity:.2%} at the "
            f"{p.max_total_open_risk_pct:.2%} cap"
        )
    elif shares * risk_per_share > risk_budget:
        shares = math.floor(risk_budget / risk_per_share)
        limits.append("total_open_risk")

    # --- correlation cluster -------------------------------------------------------------
    if correlations:
        correlated = [
            t for t, rho in correlations.items()
            if rho >= p.correlation_threshold and any(pos.ticker == t for pos in open_positions)
        ]
        if len(correlated) >= p.max_correlated_positions:
            rejections.append(
                f"{len(correlated)} existing positions correlated ≥ {p.correlation_threshold:.2f} "
                f"({', '.join(correlated[:4])})"
            )

    # --- soft caps (shrink the size) ------------------------------------------------------
    max_single = equity * p.max_single_position_pct
    if shares * entry > max_single:
        shares = math.floor(max_single / entry)
        limits.append("max_single_position")

    if sector:
        sector_value = sum(pos.market_value for pos in open_positions if pos.sector == sector)
        sector_room = equity * p.max_sector_exposure_pct - sector_value
        if sector_room <= 0:
            rejections.append(f"sector exposure cap reached for {sector}")
        elif shares * entry > sector_room:
            shares = math.floor(sector_room / entry)
            limits.append("max_sector_exposure")

    investable_cash = cash - equity * p.min_cash_pct
    if investable_cash <= 0:
        rejections.append(f"cash below the {p.min_cash_pct:.0%} minimum reserve")
    elif shares * entry > investable_cash:
        shares = math.floor(investable_cash / entry)
        limits.append("min_cash_reserve")

    shares = max(0, shares)
    notional = shares * entry
    risk_amount = shares * risk_per_share

    return SizingResult(
        shares=shares,
        notional=notional,
        risk_amount=risk_amount,
        risk_pct_of_equity=risk_amount / equity if equity > 0 else 0.0,
        allowed=shares > 0 and not rejections,
        limits_applied=limits,
        rejections=rejections,
    )


def correlation_matrix(returns_by_ticker: dict[str, np.ndarray], window: int = 63) -> dict[tuple[str, str], float]:
    """Pairwise correlation of the last ``window`` daily returns.

    Used to stop the portfolio quietly becoming one big bet on a single theme.
    """
    tickers = [t for t, r in returns_by_ticker.items() if r is not None and len(r) >= window]
    out: dict[tuple[str, str], float] = {}
    for i, a in enumerate(tickers):
        ra = np.asarray(returns_by_ticker[a][-window:], dtype=float)
        for b in tickers[i + 1 :]:
            rb = np.asarray(returns_by_ticker[b][-window:], dtype=float)
            mask = np.isfinite(ra) & np.isfinite(rb)
            if mask.sum() < window // 2:
                continue
            if ra[mask].std() == 0 or rb[mask].std() == 0:
                continue
            rho = float(np.corrcoef(ra[mask], rb[mask])[0, 1])
            out[(a, b)] = rho
            out[(b, a)] = rho
    return out
