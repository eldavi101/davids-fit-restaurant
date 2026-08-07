"""OpportunityScore aggregation.

Combines the seven component scores plus the regime score into a single 0–100 number,
assigns a category, and computes a *separate* confidence figure that measures agreement
between components rather than their level.

Score and confidence are deliberately independent: a stock can score 88 on the strength
of two components while the rest disagree, and confidence is what exposes that.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from app.core.config import StrategyConfig
from app.domain.indicators.snapshot import IndicatorSnapshot
from app.domain.regime.engine import RegimeResult
from app.domain.scoring.components import (
    ComponentScore,
    breakout_score,
    clip,
    fundamental_score,
    momentum_score,
    ramp,
    relative_strength_score,
    risk_score,
    trend_score,
    volume_score,
)
from app.domain.types import Fundamentals

CATEGORY_BANDS: tuple[tuple[float, str], ...] = (
    (90.0, "EXCEPTIONAL"),
    (85.0, "STRONG_BUY"),
    (80.0, "BUY"),
    (70.0, "WATCH"),
    (55.0, "NEUTRAL"),
)


def categorize(score: float) -> str:
    for threshold, label in CATEGORY_BANDS:
        if score >= threshold:
            return label
    return "AVOID"


@dataclass
class ScoreResult:
    ticker: str
    opportunity_score: float
    category: str
    confidence: float

    trend: ComponentScore
    momentum: ComponentScore
    volume: ComponentScore
    breakout: ComponentScore
    relative_strength: ComponentScore
    fundamental: ComponentScore
    risk: ComponentScore
    regime_score: float
    regime: str

    breakout_type: str = "NONE"
    breakout_level: float | None = None
    weights: dict[str, float] = field(default_factory=dict)
    contributions: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def core_scores(self) -> dict[str, float]:
        """The five price-based components — the ones the confirmation rule counts."""
        return {
            "trend": self.trend.score,
            "momentum": self.momentum.score,
            "volume": self.volume.score,
            "breakout": self.breakout.score,
            "relative_strength": self.relative_strength.score,
        }

    def component_dict(self) -> dict[str, float]:
        return {
            **self.core_scores,
            "fundamental": self.fundamental.score,
            "risk": self.risk.score,
            "regime": self.regime_score,
        }

    def breakdown(self) -> dict:
        return {
            "opportunity_score": round(self.opportunity_score, 2),
            "category": self.category,
            "confidence": round(self.confidence, 2),
            "weights": self.weights,
            "contributions": {k: round(v, 3) for k, v in self.contributions.items()},
            "components": {
                "trend": self.trend.as_dict(),
                "momentum": self.momentum.as_dict(),
                "volume": self.volume.as_dict(),
                "breakout": self.breakout.as_dict(),
                "relative_strength": self.relative_strength.as_dict(),
                "fundamental": self.fundamental.as_dict(),
                "risk": self.risk.as_dict(),
            },
            "regime": {"regime": self.regime, "score": round(self.regime_score, 2)},
            "breakout_type": self.breakout_type,
            "notes": self.notes,
        }


def compute_confidence(
    result_scores: dict[str, float],
    data_coverage: float,
    probability_sample_size: int,
) -> float:
    """Agreement × coverage × probability reliability, each in [0,1], weighted."""
    values = list(result_scores.values())
    spread = statistics.pstdev(values) if len(values) > 1 else 0.0
    agreement = 1.0 - clip(spread / 35.0)
    reliability = ramp(float(probability_sample_size), 30.0, 300.0)
    return clip(
        100.0 * (0.45 * agreement + 0.30 * clip(data_coverage) + 0.25 * reliability),
        0.0,
        100.0,
    )


def score_stock(
    snapshot: IndicatorSnapshot,
    regime: RegimeResult,
    cfg: StrategyConfig,
    fundamentals: Fundamentals | None = None,
    days_to_earnings: int | None = None,
    probability_sample_size: int = 0,
) -> ScoreResult:
    """The single scoring entry point, shared by the live scanner and the backtester."""
    trend = trend_score(snapshot, cfg)
    momentum = momentum_score(snapshot, cfg)
    volume = volume_score(snapshot, cfg)
    breakout, breakout_type, breakout_level = breakout_score(snapshot, cfg)
    rel_strength = relative_strength_score(snapshot, cfg)
    fundamental = fundamental_score(fundamentals, cfg)
    risk = risk_score(snapshot, cfg, days_to_earnings=days_to_earnings)

    w = cfg.weights
    contributions = {
        "trend": w.trend * trend.score,
        "momentum": w.momentum * momentum.score,
        "volume": w.volume * volume.score,
        "breakout": w.breakout * breakout.score,
        "relative_strength": w.relative_strength * rel_strength.score,
        "fundamental": w.fundamental * fundamental.score,
        "regime": w.regime * regime.regime_score,
        "risk": w.risk * risk.score,
    }
    total = clip(sum(contributions.values()), 0.0, 100.0)

    # Coverage: how much of the input surface was actually available.
    coverage_parts = [
        1.0 if snapshot.bars_available >= cfg.min_bars_required else
        snapshot.bars_available / max(1, cfg.min_bars_required),
        1.0 if snapshot.rs_21 is not None else 0.0,
        fundamentals.coverage if fundamentals else 0.0,
        1.0 if snapshot.rel_volume is not None else 0.0,
    ]
    coverage = sum(coverage_parts) / len(coverage_parts)

    notes: list[str] = []
    for component in (trend, momentum, volume, breakout, rel_strength, fundamental, risk):
        notes.extend(component.notes)

    result = ScoreResult(
        ticker=snapshot.ticker,
        opportunity_score=total,
        category=categorize(total),
        confidence=0.0,
        trend=trend,
        momentum=momentum,
        volume=volume,
        breakout=breakout,
        relative_strength=rel_strength,
        fundamental=fundamental,
        risk=risk,
        regime_score=regime.regime_score,
        regime=regime.regime,
        breakout_type=breakout_type,
        breakout_level=breakout_level,
        weights=w.as_dict(),
        contributions=contributions,
        notes=notes,
    )
    result.confidence = compute_confidence(
        result.core_scores, coverage, probability_sample_size
    )
    return result
