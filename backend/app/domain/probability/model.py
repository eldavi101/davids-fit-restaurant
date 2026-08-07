"""Probability estimation and expected value.

Three tiers, in order of preference:

1. **Calibrated logistic regression** on standardised setup features. Interpretable by
   design (a coefficient per feature), calibrated so the reported number means what it
   says. Isotonic calibration once the sample is large enough, sigmoid before that.
2. **Bucketed empirical frequency** (OpportunityScore decile × regime) when the model
   has too few samples.
3. **Configured prior** with ``sample_size = 0`` and reliability ``PRIOR_ONLY``.

Every estimate carries its sample size and a Wilson confidence interval. The API and the
app always display those alongside the number, because a 62% win probability drawn from
11 observations is not a 62% win probability (requirement 27, 61.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression

from app.core.config import StrategyConfig
from app.domain.probability.labeling import LabeledSetup, to_matrix

FEATURE_NAMES: list[str] = [
    "trend",
    "momentum",
    "volume",
    "breakout",
    "relative_strength",
    "fundamental",
    "risk",
    "regime_score",
    "atr_pct",
    "reward_risk",
    "dist_52w_high",
    "rel_volume",
]


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — behaves sensibly at small n, unlike the normal approximation."""
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1.0 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


@dataclass
class ProbabilityEstimate:
    probability: float
    sample_size: int
    historical_win_rate: float | None
    avg_win_r: float
    avg_loss_r: float
    expected_value_r: float
    confidence_interval: tuple[float, float]
    method: str
    reliability: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "probability": round(self.probability, 4),
            "sample_size": self.sample_size,
            "historical_win_rate": (
                None if self.historical_win_rate is None else round(self.historical_win_rate, 4)
            ),
            "expected_return_on_win_r": round(self.avg_win_r, 3),
            "expected_loss_on_loss_r": round(self.avg_loss_r, 3),
            "expected_value_r": round(self.expected_value_r, 4),
            "confidence_interval": [round(v, 4) for v in self.confidence_interval],
            "method": self.method,
            "reliability": self.reliability,
            "notes": self.notes,
        }


def expected_value(p_win: float, avg_win_r: float, avg_loss_r: float) -> float:
    """EV in R-multiples:  p·avg_win − (1−p)·avg_loss  (STRATEGY_SPEC §13)."""
    return p_win * avg_win_r - (1.0 - p_win) * abs(avg_loss_r)


class ProbabilityModel:
    """Fit on historical labelled setups; predict for a live setup.

    ``fit`` is idempotent and safe to call with too little data — the model simply
    reports that it is unfitted and prediction falls through to the empirical tier.
    """

    def __init__(self, cfg: StrategyConfig):
        self.cfg = cfg
        self._pipeline: CalibratedClassifierCV | LogisticRegression | None = None
        self._mean: np.ndarray | None = None
        self._std: np.ndarray | None = None
        self.n_samples = 0
        self.train_win_rate: float | None = None
        self.avg_win_r = cfg.probability.default_avg_win_r
        self.avg_loss_r = cfg.probability.default_avg_loss_r
        self._buckets: dict[tuple[int, str], tuple[int, int]] = {}
        self.coefficients: dict[str, float] = {}

    # -- fitting -----------------------------------------------------------------------

    def fit(self, setups: list[LabeledSetup]) -> ProbabilityModel:
        self.n_samples = len(setups)
        if not setups:
            return self

        y = np.array([s.label for s in setups], dtype=int)
        self.train_win_rate = float(y.mean())

        wins = [s.r_multiple for s in setups if s.label == 1]
        losses = [abs(s.r_multiple) for s in setups if s.label == 0]
        if wins:
            self.avg_win_r = float(np.mean(wins))
        if losses:
            self.avg_loss_r = float(np.mean(losses))

        # Empirical buckets: score decile × regime. Always built — they are the fallback.
        self._buckets = {}
        for s in setups:
            key = self._bucket_key(s.features)
            n, w = self._buckets.get(key, (0, 0))
            self._buckets[key] = (n + 1, w + s.label)

        min_n = self.cfg.probability.min_probability_samples
        # Both classes must be present, or a classifier learns nothing useful.
        if len(setups) < min_n or len(np.unique(y)) < 2:
            return self

        X, _ = to_matrix(setups, FEATURE_NAMES)
        # Standardisation statistics come from TRAINING data only and are frozen here;
        # test-time data is transformed with them, never re-fitted (BACKTESTING_SPEC §2.3).
        self._mean = X.mean(axis=0)
        self._std = X.std(axis=0)
        self._std[self._std == 0] = 1.0
        Xs = (X - self._mean) / self._std

        base = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs")
        method = "isotonic" if len(setups) >= self.cfg.probability.isotonic_min_samples else "sigmoid"
        folds = int(min(5, max(2, np.bincount(y).min())))
        try:
            model = CalibratedClassifierCV(base, method=method, cv=folds)
            model.fit(Xs, y)
            self._pipeline = model
            base.fit(Xs, y)
            self.coefficients = {
                name: float(coef) for name, coef in zip(FEATURE_NAMES, base.coef_[0], strict=True)
            }
        except ValueError:
            # Calibration needs enough of each class per fold; fall back to a plain fit
            # rather than pretending calibration happened.
            base.fit(Xs, y)
            self._pipeline = base
            self.coefficients = {
                name: float(coef) for name, coef in zip(FEATURE_NAMES, base.coef_[0], strict=True)
            }
        return self

    @staticmethod
    def _bucket_key(features: dict[str, float]) -> tuple[int, str]:
        score = float(features.get("opportunity_score", features.get("trend", 0.0)))
        decile = int(max(0, min(9, score // 10)))
        regime = str(features.get("regime_label", "ANY"))
        return decile, regime

    @property
    def is_fitted(self) -> bool:
        return self._pipeline is not None

    # -- prediction --------------------------------------------------------------------

    def predict(self, features: dict[str, float]) -> ProbabilityEstimate:
        pc = self.cfg.probability

        if self.is_fitted and self._mean is not None and self._std is not None:
            x = np.array([[float(features.get(n, 0.0)) for n in FEATURE_NAMES]], dtype=float)
            xs = (x - self._mean) / self._std
            p = float(self._pipeline.predict_proba(xs)[0][1])  # type: ignore[union-attr]
            p = float(np.clip(p, 0.01, 0.99))
            wins = int(round((self.train_win_rate or 0.0) * self.n_samples))
            return self._build(
                p,
                self.n_samples,
                self.train_win_rate,
                wins,
                method="calibrated_logistic",
                reliability="MODEL",
            )

        key = self._bucket_key(features)
        n, wins = self._buckets.get(key, (0, 0))
        if n >= max(10, pc.min_probability_samples // 5):
            p = wins / n
            p = float(np.clip(p, 0.01, 0.99))
            return self._build(
                p, n, p, wins,
                method="empirical_bucket",
                reliability="EMPIRICAL",
                notes=[f"score decile {key[0]}, regime {key[1]}"],
            )

        return self._build(
            pc.prior_win_rate,
            0,
            None,
            0,
            method="prior",
            reliability="PRIOR_ONLY",
            notes=[
                "insufficient historical evidence for this setup; "
                "showing the configured prior, not an estimate from data"
            ],
        )

    def _build(
        self,
        p: float,
        n: int,
        win_rate: float | None,
        wins: int,
        method: str,
        reliability: str,
        notes: list[str] | None = None,
    ) -> ProbabilityEstimate:
        return ProbabilityEstimate(
            probability=p,
            sample_size=n,
            historical_win_rate=win_rate,
            avg_win_r=self.avg_win_r,
            avg_loss_r=self.avg_loss_r,
            expected_value_r=expected_value(p, self.avg_win_r, self.avg_loss_r),
            confidence_interval=wilson_interval(wins, n) if n else (0.0, 1.0),
            method=method,
            reliability=reliability,
            notes=notes or [],
        )


def build_features(score_result, snapshot, levels, regime) -> dict[str, float]:
    """Assemble the model's feature vector from a scored setup.

    Kept in one place so the features used at fit time and at predict time cannot drift
    apart — a classic source of silently wrong probabilities.
    """
    return {
        "trend": score_result.trend.score,
        "momentum": score_result.momentum.score,
        "volume": score_result.volume.score,
        "breakout": score_result.breakout.score,
        "relative_strength": score_result.relative_strength.score,
        "fundamental": score_result.fundamental.score,
        "risk": score_result.risk.score,
        "regime_score": regime.regime_score,
        "atr_pct": snapshot.atr_pct or 0.0,
        "reward_risk": levels.reward_risk,
        "dist_52w_high": snapshot.dist_52w_high_pct or 0.0,
        "rel_volume": snapshot.rel_volume or 0.0,
        # Not model inputs — used to key the empirical fallback buckets.
        "opportunity_score": score_result.opportunity_score,
        "regime_label": regime.regime,
    }
