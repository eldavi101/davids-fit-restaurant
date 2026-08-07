"""Market regime engine.

Classifies the broad market from SPY/QQQ/IWM, a volatility proxy and the sector ETFs,
and returns both a continuous ``RegimeScore`` (a scoring input) and a discrete regime
label (a gating input). The gate tightening it produces is the mechanism behind
requirement 17: BUY requirements become stricter as conditions worsen, and in a BEAR
regime no new BUY is issued at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from app.core.clock import utc_now
from app.core.config import StrategyConfig
from app.core.errors import RegimeUnknownError
from app.domain.indicators import core as ind
from app.domain.scoring.components import clip, ramp_inv
from app.domain.types import BarWindow


@dataclass
class RegimeResult:
    regime: str
    regime_score: float
    ts_utc: datetime
    allows_new_buys: bool
    score_delta: float
    min_reward_risk: float

    spy_close: float | None = None
    spy_above_ema20: bool | None = None
    spy_above_sma50: bool | None = None
    spy_above_sma200: bool | None = None
    spy_sma200_slope: float | None = None
    spy_drawdown_pct: float | None = None
    spy_realized_vol: float | None = None
    qqq_rs: float | None = None
    iwm_rs: float | None = None
    breadth_pct: float | None = None
    participation_pct: float | None = None
    volatility_proxy: float | None = None
    sector_participation: dict[str, float] = field(default_factory=dict)
    components: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "regime": self.regime,
            "regime_score": round(self.regime_score, 2),
            "allows_new_buys": self.allows_new_buys,
            "score_delta": self.score_delta,
            "min_reward_risk": self.min_reward_risk,
            "spy_above_ema20": self.spy_above_ema20,
            "spy_above_sma50": self.spy_above_sma50,
            "spy_above_sma200": self.spy_above_sma200,
            "breadth_pct": self.breadth_pct,
            "participation_pct": self.participation_pct,
            "volatility_proxy": self.volatility_proxy,
            "spy_drawdown_pct": self.spy_drawdown_pct,
            "qqq_rs_63": self.qqq_rs,
            "iwm_rs_63": self.iwm_rs,
        }


def classify_regime(
    benchmark: BarWindow | None,
    sector_windows: dict[str, BarWindow] | None,
    cfg: StrategyConfig,
    secondary: dict[str, BarWindow] | None = None,
    volatility_level: float | None = None,
    as_of: datetime | None = None,
) -> RegimeResult:
    """Classify the market. Raises ``RegimeUnknownError`` when SPY history is unusable.

    Refusing to guess matters: an unknown regime blocks new BUY signals (requirement 51)
    rather than silently defaulting to NEUTRAL and letting trades through.
    """
    if benchmark is None or len(benchmark) < 200:
        raise RegimeUnknownError(
            "benchmark history insufficient to classify the market regime",
            {"bars": 0 if benchmark is None else len(benchmark)},
        )

    sector_windows = sector_windows or {}
    secondary = secondary or {}
    ts = as_of or utc_now()

    close = benchmark.close
    spy_close = float(close[-1])
    ema20 = ind.last_valid(ind.ema(close, 20))
    sma50 = ind.last_valid(ind.sma(close, 50))
    sma200_series = ind.sma(close, 200)
    sma200 = ind.last_valid(sma200_series)

    above_ema20 = ema20 is not None and spy_close > ema20
    above_sma50 = sma50 is not None and spy_close > sma50
    above_sma200 = sma200 is not None and spy_close > sma200

    clean200 = sma200_series[~np.isnan(sma200_series)]
    sma200_slope = ind.slope_annualized(clean200, 20)

    high252 = float(close[-252:].max()) if len(close) >= 252 else float(close.max())
    spy_drawdown_pct = 100.0 * (spy_close / high252 - 1.0) if high252 > 0 else 0.0

    spy_vol = ind.last_valid(ind.realized_volatility(close, 20))

    # Breadth: sector ETFs above their own 50-day SMA. Participation: sector ETFs
    # outperforming SPY over 63 days.
    breadth_hits, participation_hits, usable = 0, 0, 0
    sector_participation: dict[str, float] = {}
    for symbol, window in sector_windows.items():
        if window is None or len(window) < 63:
            continue
        usable += 1
        s_close = window.close
        s_sma50 = ind.last_valid(ind.sma(s_close, 50))
        if s_sma50 is not None and float(s_close[-1]) > s_sma50:
            breadth_hits += 1
        rs = ind.relative_strength(s_close, close, 63)
        if rs is not None:
            sector_participation[symbol] = round(rs, 2)
            if rs > 0:
                participation_hits += 1

    breadth = breadth_hits / usable if usable else None
    participation = participation_hits / usable if usable else None

    qqq_rs = None
    if (qqq := secondary.get("QQQ")) is not None and len(qqq) > 63:
        qqq_rs = ind.relative_strength(qqq.close, close, 63)
    iwm_rs = None
    if (iwm := secondary.get("IWM")) is not None and len(iwm) > 63:
        iwm_rs = ind.relative_strength(iwm.close, close, 63)

    # Volatility proxy: VIX when supplied, otherwise SPY's annualised realised vol
    # expressed on a comparable 0-100 scale.
    vol_proxy = volatility_level if volatility_level is not None else (
        spy_vol * 100.0 if spy_vol is not None else None
    )

    breadth_v = breadth if breadth is not None else 0.5
    participation_v = participation if participation is not None else 0.5

    regime_score = 100.0 * (
        0.16 * (1.0 if above_ema20 else 0.0)
        + 0.18 * (1.0 if above_sma50 else 0.0)
        + 0.20 * (1.0 if above_sma200 else 0.0)
        + 0.14 * breadth_v
        + 0.12 * participation_v
        + 0.10 * ramp_inv(vol_proxy, 16.0, 34.0, default=0.5)
        + 0.10 * ramp_inv(-spy_drawdown_pct, 3.0, 15.0, default=0.5)
    )
    regime_score = clip(regime_score, 0.0, 100.0)

    rc = cfg.regime
    high_vol = (vol_proxy is not None and vol_proxy >= rc.vix_high) or (
        spy_vol is not None and spy_vol >= rc.realized_vol_high
    )

    if high_vol:
        regime = "HIGH_VOLATILITY"
    elif (not above_sma200) and (sma200_slope is not None and sma200_slope < 0) and (
        spy_drawdown_pct <= rc.bear_drawdown_pct
    ):
        regime = "BEAR"
    elif (not above_sma50) and breadth is not None and breadth < rc.risk_off_breadth:
        regime = "RISK_OFF"
    elif (
        above_ema20
        and above_sma50
        and above_sma200
        and ema20 is not None
        and sma50 is not None
        and sma200 is not None
        and ema20 > sma50 > sma200
        and breadth is not None
        and breadth >= rc.strong_bull_breadth
        and regime_score >= rc.strong_bull_score
    ):
        regime = "STRONG_BULL"
    elif above_sma200 and regime_score >= rc.bull_score:
        regime = "BULL"
    else:
        regime = "NEUTRAL"

    allows_new_buys = regime not in rc.blocked_regimes
    score_delta = rc.score_delta.get(regime, 0.0)
    min_rr = rc.min_reward_risk_override.get(regime, cfg.buy_gate.min_reward_risk)

    return RegimeResult(
        regime=regime,
        regime_score=regime_score,
        ts_utc=ts,
        allows_new_buys=allows_new_buys,
        score_delta=score_delta,
        min_reward_risk=min_rr,
        spy_close=spy_close,
        spy_above_ema20=above_ema20,
        spy_above_sma50=above_sma50,
        spy_above_sma200=above_sma200,
        spy_sma200_slope=sma200_slope,
        spy_drawdown_pct=spy_drawdown_pct,
        spy_realized_vol=spy_vol,
        qqq_rs=qqq_rs,
        iwm_rs=iwm_rs,
        breadth_pct=breadth,
        participation_pct=participation,
        volatility_proxy=vol_proxy,
        sector_participation=sector_participation,
        components={
            "above_ema20": above_ema20,
            "above_sma50": above_sma50,
            "above_sma200": above_sma200,
            "sma200_slope": sma200_slope,
            "breadth": breadth,
            "participation": participation,
            "volatility_proxy": vol_proxy,
            "drawdown_pct": spy_drawdown_pct,
        },
    )


def neutral_regime(cfg: StrategyConfig, as_of: datetime | None = None) -> RegimeResult:
    """A conservative placeholder used only where a regime is contextually irrelevant.

    Never used on the BUY path — an unknown regime there blocks the signal instead.
    """
    return RegimeResult(
        regime="NEUTRAL",
        regime_score=50.0,
        ts_utc=as_of or utc_now(),
        allows_new_buys=True,
        score_delta=cfg.regime.score_delta.get("NEUTRAL", 0.0),
        min_reward_risk=cfg.buy_gate.min_reward_risk,
    )
