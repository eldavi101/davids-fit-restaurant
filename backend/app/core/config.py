"""Application and strategy configuration.

Two distinct objects live here:

``Settings``        infrastructure — database, providers, credentials, scheduler.
                    Sourced from environment variables. Never contains strategy logic.

``StrategyConfig``  every quantitative threshold and weight used by the scoring,
                    BUY and SELL engines. Fully serialisable, versioned, and stored
                    alongside each strategy version so historical alerts can always be
                    reproduced under the exact parameters that produced them.

Nothing in ``StrategyConfig`` is hard-coded at a call site: engines read it from the
object they are handed. That is what makes strategy research and the Strategy Lab
screen possible without touching code (requirement 61.13).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# --------------------------------------------------------------------------------------
# Infrastructure settings
# --------------------------------------------------------------------------------------


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    # Comma-separated list of accepted X-API-Key values.
    api_keys: str = "dev-local-key"
    cors_origins: str = "*"

    database_url: str = "sqlite:///./equity_signal.db"

    market_data_provider: str = "synthetic"
    market_data_fallbacks: str = ""
    #: 0 means "use the adapter's own default for that vendor". Set this to the plan's
    #: documented limit — pacing client-side is what keeps a universe refresh from
    #: spending the whole minute budget in the first second and collecting 429s.
    market_data_rate_limit_per_minute: int = 0

    polygon_api_key: str | None = None
    finnhub_api_key: str | None = None
    fmp_api_key: str | None = None
    twelvedata_api_key: str | None = None
    alphavantage_api_key: str | None = None

    paper_trading: bool = True
    paper_starting_equity: float = 100_000.0

    enable_scheduler: bool = False
    scan_interval_minutes: int = 30
    monitor_interval_minutes: int = 5
    universe_refresh_hour_et: int = 7

    #: Hard ceiling on how many listed symbols one universe refresh will consider.
    #: 0 means "no ceiling". A vendor listing is ~10k symbols and each survivor of the
    #: structural filters costs one history request, so this is the knob that decides
    #: whether a refresh takes minutes or hours on a rate-limited plan.
    universe_max_symbols: int = 0

    max_bar_age_minutes: int = 120
    min_bars_required: int = 252

    strategy_version: str = "momentum_breakout_v1.0.0"

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def fallback_providers(self) -> list[str]:
        return [p.strip() for p in self.market_data_fallbacks.split(",") if p.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def provider_key(self, name: str) -> str | None:
        return {
            "polygon": self.polygon_api_key,
            "finnhub": self.finnhub_api_key,
            "fmp": self.fmp_api_key,
            "twelvedata": self.twelvedata_api_key,
            "alphavantage": self.alphavantage_api_key,
            "synthetic": "not-required",
        }.get(name)


@lru_cache
def get_settings() -> Settings:
    return Settings()


# --------------------------------------------------------------------------------------
# Strategy configuration
# --------------------------------------------------------------------------------------


class ScoreWeights(BaseModel):
    """Weights of the seven component scores plus regime. Must sum to 1."""

    trend: float = 0.20
    momentum: float = 0.15
    volume: float = 0.10
    breakout: float = 0.15
    relative_strength: float = 0.15
    fundamental: float = 0.10
    regime: float = 0.10
    risk: float = 0.05

    @model_validator(mode="after")
    def _sum_to_one(self) -> ScoreWeights:
        total = (
            self.trend
            + self.momentum
            + self.volume
            + self.breakout
            + self.relative_strength
            + self.fundamental
            + self.regime
            + self.risk
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"score weights must sum to 1.0, got {total:.6f}")
        return self

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class UniverseConfig(BaseModel):
    """Which U.S. securities are considered reasonably tradable through Fidelity."""

    allowed_exchanges: list[str] = Field(
        default_factory=lambda: ["NASDAQ", "NYSE", "NYSE_AMERICAN"]
    )
    include_common: bool = True
    include_etf: bool = False
    include_adr: bool = False
    include_otc: bool = False
    include_penny: bool = False
    include_leveraged_etf: bool = False
    include_inverse_etf: bool = False

    min_price: float = 5.0
    max_price: float | None = None
    min_market_cap: float = 500_000_000.0
    min_avg_dollar_volume: float = 10_000_000.0
    min_avg_volume: float = 500_000.0


class BuyGateConfig(BaseModel):
    min_opportunity_score: float = 80.0
    min_trend_score: float = 60.0
    min_relative_strength_score: float = 55.0
    min_confirmations: int = 3
    confirmation_threshold: float = 60.0
    min_breakout_score: float = 55.0
    momentum_override_score: float = 65.0
    max_spread_bps: float = 25.0
    min_reward_risk: float = 1.5
    min_expected_value_r: float = 0.0
    earnings_blackout_days: int = 5
    watch_threshold: float = 70.0


class LevelsConfig(BaseModel):
    """Stop and target construction."""

    stop_atr_mult: float = 2.0
    swing_low_lookback: int = 10
    swing_low_atr_buffer: float = 0.25
    max_stop_pct: float = 0.12
    min_stop_atr_mult: float = 0.5
    max_stop_atr_mult: float = 4.0
    target_r1: float = 1.5
    target_r2: float = 3.0


class TrailingConfig(BaseModel):
    use_chandelier: bool = True
    use_percent: bool = False
    use_ma_stop: bool = False
    chandelier_atr_mult: float = 2.5
    percent_trail: float = 0.08
    ma_stop_period: int = 20
    activate_at_r: float = 1.0


class SellConfig(BaseModel):
    staged_exits: bool = True
    target1_fraction: float = 0.25
    target2_fraction: float = 0.25
    trend_breakdown_confirm_bars: int = 2
    momentum_rsi_threshold: float = 45.0
    breakout_failure_atr_buffer: float = 0.5
    breakout_failure_max_bars: int = 15
    risk_increase_atr_mult: float = 2.0
    volatility_exit_mult: float = 2.5
    fundamental_drop_points: float = 25.0
    max_holding_days: int = 60
    time_exit_min_r: float = 0.5
    regime_exit_regimes: list[str] = Field(
        default_factory=lambda: ["BEAR", "HIGH_VOLATILITY"]
    )


class ProbabilityConfig(BaseModel):
    horizon_bars: int = 20
    min_probability_samples: int = 50
    prior_win_rate: float = 0.40
    default_avg_win_r: float = 2.25
    default_avg_loss_r: float = 1.0
    embargo_bars: int = 5
    isotonic_min_samples: int = 1000


class RegimeConfig(BaseModel):
    benchmark: str = "SPY"
    secondary: list[str] = Field(default_factory=lambda: ["QQQ", "IWM"])
    volatility_symbol: str = "VIX"
    sector_etfs: list[str] = Field(
        default_factory=lambda: [
            "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
        ]
    )
    vix_high: float = 30.0
    realized_vol_high: float = 0.30
    strong_bull_breadth: float = 0.65
    strong_bull_score: float = 78.0
    bull_score: float = 58.0
    risk_off_breadth: float = 0.40
    bear_drawdown_pct: float = -10.0

    # Per-regime tightening of the BUY gate.
    score_delta: dict[str, float] = Field(
        default_factory=lambda: {
            "STRONG_BULL": -2.0,
            "BULL": 0.0,
            "NEUTRAL": 4.0,
            "RISK_OFF": 8.0,
            "HIGH_VOLATILITY": 10.0,
            "BEAR": 0.0,
        }
    )
    min_reward_risk_override: dict[str, float] = Field(
        default_factory=lambda: {"RISK_OFF": 2.0, "HIGH_VOLATILITY": 2.2}
    )
    blocked_regimes: list[str] = Field(default_factory=lambda: ["BEAR"])


class PortfolioConfig(BaseModel):
    starting_equity: float = 100_000.0
    risk_pct_per_trade: float = 0.0075
    max_risk_pct_per_trade: float = 0.01
    max_total_open_risk_pct: float = 0.06
    max_open_positions: int = 12
    max_sector_exposure_pct: float = 0.30
    max_single_position_pct: float = 0.12
    min_cash_pct: float = 0.05
    correlation_threshold: float = 0.80
    max_correlated_positions: int = 4


class CostConfig(BaseModel):
    slippage_bps: float = 5.0
    spread_bps: float = 4.0
    commission_per_trade: float = 0.0
    max_participation: float = 0.01


class StrategyConfig(BaseModel):
    """The complete, versioned parameter set of a strategy."""

    version: str = "momentum_breakout_v1.0.0"
    description: str = (
        "Trend-and-breakout continuation strategy with relative-strength confirmation, "
        "ATR-based risk, probability-weighted expected value and regime gating."
    )

    weights: ScoreWeights = Field(default_factory=ScoreWeights)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    buy_gate: BuyGateConfig = Field(default_factory=BuyGateConfig)
    levels: LevelsConfig = Field(default_factory=LevelsConfig)
    trailing: TrailingConfig = Field(default_factory=TrailingConfig)
    sell: SellConfig = Field(default_factory=SellConfig)
    probability: ProbabilityConfig = Field(default_factory=ProbabilityConfig)
    regime: RegimeConfig = Field(default_factory=RegimeConfig)
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    costs: CostConfig = Field(default_factory=CostConfig)

    min_bars_required: int = 252

    @field_validator("version")
    @classmethod
    def _version_shape(cls, v: str) -> str:
        if not v or " " in v:
            raise ValueError("strategy version must be a non-empty token, e.g. name_v1.0.0")
        return v

    def with_overrides(self, overrides: dict) -> StrategyConfig:
        """Return a copy with a (possibly nested) override mapping applied.

        Used by the Strategy Lab, backtest parameter sweeps and the settings endpoint.
        Flat keys are resolved against any nested section that declares them, so
        ``{"min_opportunity_score": 82}`` reaches ``buy_gate.min_opportunity_score``.
        """
        data = self.model_dump()
        sections = [
            "weights", "universe", "buy_gate", "levels", "trailing",
            "sell", "probability", "regime", "portfolio", "costs",
        ]
        for key, value in overrides.items():
            if key in data and not isinstance(data.get(key), dict):
                data[key] = value
            elif key in sections and isinstance(value, dict):
                data[key].update(value)
            else:
                for section in sections:
                    if key in data[section]:
                        data[section][key] = value
                        break
                else:
                    raise KeyError(f"unknown strategy parameter: {key}")
        return StrategyConfig(**data)


DEFAULT_STRATEGY = StrategyConfig()


@lru_cache
def get_strategy() -> StrategyConfig:
    """Active strategy configuration.

    Runtime overrides persisted in the ``settings`` table are layered on top of this
    by ``services.settings_service.effective_strategy()``; this function returns the
    compiled-in defaults.
    """
    return StrategyConfig(version=get_settings().strategy_version)
