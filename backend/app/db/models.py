"""SQLAlchemy models — the 17 backend tables of DATABASE_SCHEMA.md.

Dialect-neutral: ``Numeric(18, 6, asdecimal=False)`` emits NUMERIC DDL on PostgreSQL
(exact decimal storage, no binary-float drift) while yielding plain floats in Python on
every dialect, so application code and tests behave identically on SQLite and Postgres.

Append-only tables (``alert_events``, ``audit_logs``, ``sell_alerts``, ``backtest_trades``)
have no delete path anywhere in the codebase — history is permanent (requirement 61.8).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.core.clock import UTC, utc_now


class Base(DeclarativeBase):
    pass


class UtcDateTime(TypeDecorator):
    """A timestamp that is always timezone-aware UTC in Python, on every dialect.

    PostgreSQL round-trips ``timestamptz`` correctly, but SQLite discards the offset and
    hands back naive datetimes. Since the whole system's time contract is "UTC internally,
    New York at the edges" — and ``clock.ensure_utc`` deliberately raises on a naive value
    rather than guessing — the adaptation belongs here, once, instead of in every caller.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected; all timestamps must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


Price = Numeric(18, 6, asdecimal=False)
Qty = Numeric(24, 6, asdecimal=False)


def _uid() -> str:
    return str(uuid.uuid4())


def _ts() -> Mapped[datetime]:
    return mapped_column(UtcDateTime, default=utc_now, nullable=False)


# --------------------------------------------------------------------------------------
# Enumerations (stored as strings so the database stays readable and migration-friendly)
# --------------------------------------------------------------------------------------


class AlertStatus(str, enum.Enum):
    WATCHING = "WATCHING"
    BUY_SIGNAL = "BUY_SIGNAL"
    ACTIVE = "ACTIVE"
    TARGET_1_HIT = "TARGET_1_HIT"
    TARGET_2_HIT = "TARGET_2_HIT"
    TRAILING = "TRAILING"
    STOPPED = "STOPPED"
    SELL_SIGNAL = "SELL_SIGNAL"
    CLOSED = "CLOSED"
    INVALIDATED = "INVALIDATED"


OPEN_STATUSES: tuple[str, ...] = (
    AlertStatus.WATCHING.value,
    AlertStatus.BUY_SIGNAL.value,
    AlertStatus.ACTIVE.value,
    AlertStatus.TARGET_1_HIT.value,
    AlertStatus.TARGET_2_HIT.value,
    AlertStatus.TRAILING.value,
)

TERMINAL_STATUSES: tuple[str, ...] = (
    AlertStatus.CLOSED.value,
    AlertStatus.INVALIDATED.value,
)


class ExitReason(str, enum.Enum):
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    TARGET_1 = "TARGET_1"
    TARGET_2 = "TARGET_2"
    MOMENTUM_DETERIORATION = "MOMENTUM_DETERIORATION"
    TREND_BREAKDOWN = "TREND_BREAKDOWN"
    RS_BREAKDOWN = "RS_BREAKDOWN"
    BREAKOUT_FAILURE = "BREAKOUT_FAILURE"
    REGIME_DETERIORATION = "REGIME_DETERIORATION"
    RISK_INCREASE = "RISK_INCREASE"
    FUNDAMENTAL_DETERIORATION = "FUNDAMENTAL_DETERIORATION"
    TIME_EXIT = "TIME_EXIT"
    VOLATILITY_EXIT = "VOLATILITY_EXIT"
    THESIS_INVALIDATION = "THESIS_INVALIDATION"


class EventType(str, enum.Enum):
    BUY_SIGNAL = "BUY_SIGNAL"
    PROFIT_MILESTONE = "PROFIT_MILESTONE"
    DRAWDOWN_MILESTONE = "DRAWDOWN_MILESTONE"
    TARGET_1_HIT = "TARGET_1_HIT"
    TARGET_2_HIT = "TARGET_2_HIT"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    TRAILING_STOP_UPDATED = "TRAILING_STOP_UPDATED"
    STOP_UPDATED = "STOP_UPDATED"
    THESIS_WARNING = "THESIS_WARNING"
    THESIS_INVALIDATED = "THESIS_INVALIDATED"
    REGIME_CHANGE = "REGIME_CHANGE"
    SELL_SIGNAL = "SELL_SIGNAL"
    STOPPED = "STOPPED"
    CLOSED = "CLOSED"


class ScoreCategory(str, enum.Enum):
    EXCEPTIONAL = "EXCEPTIONAL"
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    WATCH = "WATCH"
    NEUTRAL = "NEUTRAL"
    AVOID = "AVOID"


class Regime(str, enum.Enum):
    STRONG_BULL = "STRONG_BULL"
    BULL = "BULL"
    NEUTRAL = "NEUTRAL"
    RISK_OFF = "RISK_OFF"
    BEAR = "BEAR"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"


# --------------------------------------------------------------------------------------
# 1. instruments
# --------------------------------------------------------------------------------------


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(256))
    exchange: Mapped[str | None] = mapped_column(String(32))
    security_type: Mapped[str] = mapped_column(String(16), default="COMMON")
    sector: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(128))

    market_cap: Mapped[float | None] = mapped_column(Qty)
    avg_volume_50d: Mapped[float | None] = mapped_column(Qty)
    avg_dollar_volume_50d: Mapped[float | None] = mapped_column(Qty)
    last_price: Mapped[float | None] = mapped_column(Price)

    is_etf: Mapped[bool] = mapped_column(Boolean, default=False)
    is_adr: Mapped[bool] = mapped_column(Boolean, default=False)
    is_leveraged_etf: Mapped[bool] = mapped_column(Boolean, default=False)
    is_inverse_etf: Mapped[bool] = mapped_column(Boolean, default=False)
    is_otc: Mapped[bool] = mapped_column(Boolean, default=False)

    eligible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ineligible_reason: Mapped[str | None] = mapped_column(String(256))

    first_seen_utc: Mapped[datetime] = _ts()
    last_seen_utc: Mapped[datetime] = _ts()
    delisted: Mapped[bool] = mapped_column(Boolean, default=False)
    delisted_at_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)

    data_provider: Mapped[str | None] = mapped_column(String(32))
    updated_at_utc: Mapped[datetime] = _ts()

    bars: Mapped[list[MarketPrice]] = relationship(back_populates="instrument")


# --------------------------------------------------------------------------------------
# 2. market_prices
# --------------------------------------------------------------------------------------


class MarketPrice(Base):
    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint("instrument_id", "timeframe", "ts_utc", name="uq_bar"),
        Index("ix_bar_lookup", "instrument_id", "timeframe", "ts_utc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    ts_utc: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), default="1d")

    open: Mapped[float] = mapped_column(Price, nullable=False)
    high: Mapped[float] = mapped_column(Price, nullable=False)
    low: Mapped[float] = mapped_column(Price, nullable=False)
    close: Mapped[float] = mapped_column(Price, nullable=False)
    volume: Mapped[float] = mapped_column(Qty, default=0.0)

    raw_close: Mapped[float | None] = mapped_column(Price)
    split_factor: Mapped[float] = mapped_column(Float, default=1.0)
    dividend: Mapped[float] = mapped_column(Float, default=0.0)

    data_provider: Mapped[str | None] = mapped_column(String(32))
    ingested_at_utc: Mapped[datetime] = _ts()

    instrument: Mapped[Instrument] = relationship(back_populates="bars")


# --------------------------------------------------------------------------------------
# 3. technical_indicators
# --------------------------------------------------------------------------------------


class TechnicalIndicator(Base):
    __tablename__ = "technical_indicators"
    __table_args__ = (
        UniqueConstraint("instrument_id", "timeframe", "ts_utc", name="uq_indicator"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    ts_utc: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), default="1d")

    ema9: Mapped[float | None] = mapped_column(Float)
    ema20: Mapped[float | None] = mapped_column(Float)
    ema21: Mapped[float | None] = mapped_column(Float)
    ema50: Mapped[float | None] = mapped_column(Float)
    sma50: Mapped[float | None] = mapped_column(Float)
    sma100: Mapped[float | None] = mapped_column(Float)
    sma200: Mapped[float | None] = mapped_column(Float)

    rsi14: Mapped[float | None] = mapped_column(Float)
    macd: Mapped[float | None] = mapped_column(Float)
    macd_signal: Mapped[float | None] = mapped_column(Float)
    macd_hist: Mapped[float | None] = mapped_column(Float)

    atr14: Mapped[float | None] = mapped_column(Float)
    atr_pct: Mapped[float | None] = mapped_column(Float)
    obv: Mapped[float | None] = mapped_column(Float)
    roc21: Mapped[float | None] = mapped_column(Float)
    bb_width: Mapped[float | None] = mapped_column(Float)

    vol_avg20: Mapped[float | None] = mapped_column(Qty)
    vol_avg50: Mapped[float | None] = mapped_column(Qty)
    rel_volume: Mapped[float | None] = mapped_column(Float)

    high_20: Mapped[float | None] = mapped_column(Float)
    high_50: Mapped[float | None] = mapped_column(Float)
    high_252: Mapped[float | None] = mapped_column(Float)
    low_20: Mapped[float | None] = mapped_column(Float)
    low_252: Mapped[float | None] = mapped_column(Float)
    dist_52w_high_pct: Mapped[float | None] = mapped_column(Float)

    realized_vol_20: Mapped[float | None] = mapped_column(Float)
    downside_vol_20: Mapped[float | None] = mapped_column(Float)
    beta_252: Mapped[float | None] = mapped_column(Float)
    rs_21: Mapped[float | None] = mapped_column(Float)
    rs_63: Mapped[float | None] = mapped_column(Float)
    rs_126: Mapped[float | None] = mapped_column(Float)

    computed_at_utc: Mapped[datetime] = _ts()


# --------------------------------------------------------------------------------------
# 4. fundamental_metrics
# --------------------------------------------------------------------------------------


class FundamentalMetric(Base):
    __tablename__ = "fundamental_metrics"
    __table_args__ = (UniqueConstraint("instrument_id", "as_of_utc", "period", name="uq_fund"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    as_of_utc: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    period: Mapped[str] = mapped_column(String(8), default="TTM")

    eps: Mapped[float | None] = mapped_column(Float)
    revenue: Mapped[float | None] = mapped_column(Qty)
    revenue_growth_yoy: Mapped[float | None] = mapped_column(Float)
    earnings_growth_yoy: Mapped[float | None] = mapped_column(Float)
    eps_surprise_pct: Mapped[float | None] = mapped_column(Float)
    gross_margin: Mapped[float | None] = mapped_column(Float)
    operating_margin: Mapped[float | None] = mapped_column(Float)
    net_margin: Mapped[float | None] = mapped_column(Float)
    free_cash_flow: Mapped[float | None] = mapped_column(Qty)
    total_cash: Mapped[float | None] = mapped_column(Qty)
    total_debt: Mapped[float | None] = mapped_column(Qty)
    debt_to_equity: Mapped[float | None] = mapped_column(Float)
    roe: Mapped[float | None] = mapped_column(Float)
    pe: Mapped[float | None] = mapped_column(Float)
    forward_pe: Mapped[float | None] = mapped_column(Float)
    peg: Mapped[float | None] = mapped_column(Float)
    institutional_ownership: Mapped[float | None] = mapped_column(Float)
    short_interest_pct: Mapped[float | None] = mapped_column(Float)
    next_earnings_date_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)

    data_provider: Mapped[str | None] = mapped_column(String(32))
    fetched_at_utc: Mapped[datetime] = _ts()


# --------------------------------------------------------------------------------------
# 5. market_regimes
# --------------------------------------------------------------------------------------


class MarketRegimeRow(Base):
    __tablename__ = "market_regimes"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts_utc: Mapped[datetime] = mapped_column(UtcDateTime, index=True, default=utc_now)
    regime: Mapped[str] = mapped_column(String(24), nullable=False)
    regime_score: Mapped[float] = mapped_column(Float, default=50.0)

    spy_close: Mapped[float | None] = mapped_column(Price)
    spy_above_ema20: Mapped[bool | None] = mapped_column(Boolean)
    spy_above_sma50: Mapped[bool | None] = mapped_column(Boolean)
    spy_above_sma200: Mapped[bool | None] = mapped_column(Boolean)
    qqq_rs: Mapped[float | None] = mapped_column(Float)
    iwm_rs: Mapped[float | None] = mapped_column(Float)
    breadth_pct: Mapped[float | None] = mapped_column(Float)
    participation_pct: Mapped[float | None] = mapped_column(Float)
    volatility_proxy: Mapped[float | None] = mapped_column(Float)
    spy_drawdown_pct: Mapped[float | None] = mapped_column(Float)

    sector_participation: Mapped[dict] = mapped_column(JSON, default=dict)
    components: Mapped[dict] = mapped_column(JSON, default=dict)
    strategy_version: Mapped[str | None] = mapped_column(String(64))


# --------------------------------------------------------------------------------------
# 6. stock_scores
# --------------------------------------------------------------------------------------


class StockScore(Base):
    __tablename__ = "stock_scores"
    __table_args__ = (Index("ix_score_lookup", "instrument_id", "ts_utc"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    ts_utc: Mapped[datetime] = mapped_column(UtcDateTime, index=True, default=utc_now)
    strategy_version: Mapped[str] = mapped_column(String(64))

    trend_score: Mapped[float] = mapped_column(Float, default=0.0)
    momentum_score: Mapped[float] = mapped_column(Float, default=0.0)
    volume_score: Mapped[float] = mapped_column(Float, default=0.0)
    breakout_score: Mapped[float] = mapped_column(Float, default=0.0)
    relative_strength_score: Mapped[float] = mapped_column(Float, default=0.0)
    fundamental_score: Mapped[float] = mapped_column(Float, default=50.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    regime_score: Mapped[float] = mapped_column(Float, default=50.0)
    opportunity_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    category: Mapped[str] = mapped_column(String(16), default=ScoreCategory.AVOID.value)

    components: Mapped[dict] = mapped_column(JSON, default=dict)
    rules_passed: Mapped[list] = mapped_column(JSON, default=list)
    rules_failed: Mapped[list] = mapped_column(JSON, default=list)

    price: Mapped[float | None] = mapped_column(Price)
    suggested_entry: Mapped[float | None] = mapped_column(Price)
    stop_price: Mapped[float | None] = mapped_column(Price)
    target1_price: Mapped[float | None] = mapped_column(Price)
    target2_price: Mapped[float | None] = mapped_column(Price)
    reward_risk: Mapped[float | None] = mapped_column(Float)
    probability: Mapped[float | None] = mapped_column(Float)
    probability_sample_size: Mapped[int | None] = mapped_column(Integer)
    expected_value: Mapped[float | None] = mapped_column(Float)
    signal_ready: Mapped[bool] = mapped_column(Boolean, default=False)

    rel_volume: Mapped[float | None] = mapped_column(Float)
    rs_21: Mapped[float | None] = mapped_column(Float)
    atr_pct: Mapped[float | None] = mapped_column(Float)
    sector: Mapped[str | None] = mapped_column(String(64))
    market_cap: Mapped[float | None] = mapped_column(Qty)
    market_regime: Mapped[str | None] = mapped_column(String(24))
    data_provider: Mapped[str | None] = mapped_column(String(32))


# --------------------------------------------------------------------------------------
# 7. buy_alerts
# --------------------------------------------------------------------------------------


class BuyAlert(Base):
    """A BUY alert. The entry-snapshot group is written once and never updated."""

    __tablename__ = "buy_alerts"
    __table_args__ = (
        Index("ix_alert_status", "status"),
        Index("ix_alert_ticker_status", "ticker", "status"),
        Index("ix_alert_buy_ts", "buy_ts_utc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_uid: Mapped[str] = mapped_column(String(40), unique=True, default=_uid, index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    company_name: Mapped[str | None] = mapped_column(String(256))
    strategy_version: Mapped[str] = mapped_column(String(64))
    data_provider: Mapped[str | None] = mapped_column(String(32))

    # ---- entry snapshot (IMMUTABLE after insert) --------------------------------------
    buy_ts_utc: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    buy_price: Mapped[float] = mapped_column(Price, nullable=False)
    bid: Mapped[float | None] = mapped_column(Price)
    ask: Mapped[float | None] = mapped_column(Price)
    spread: Mapped[float | None] = mapped_column(Price)
    spread_bps: Mapped[float | None] = mapped_column(Float)

    opportunity_score: Mapped[float] = mapped_column(Float)
    probability: Mapped[float | None] = mapped_column(Float)
    probability_sample_size: Mapped[int | None] = mapped_column(Integer)
    probability_method: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    market_regime: Mapped[str | None] = mapped_column(String(24))
    sector: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(128))
    market_cap: Mapped[float | None] = mapped_column(Qty)

    volume: Mapped[float | None] = mapped_column(Qty)
    rel_volume: Mapped[float | None] = mapped_column(Float)
    rsi14: Mapped[float | None] = mapped_column(Float)
    macd: Mapped[float | None] = mapped_column(Float)
    macd_hist: Mapped[float | None] = mapped_column(Float)
    atr14: Mapped[float | None] = mapped_column(Float)
    atr_pct: Mapped[float | None] = mapped_column(Float)
    ema9: Mapped[float | None] = mapped_column(Float)
    ema20: Mapped[float | None] = mapped_column(Float)
    ema21: Mapped[float | None] = mapped_column(Float)
    ema50: Mapped[float | None] = mapped_column(Float)
    sma50: Mapped[float | None] = mapped_column(Float)
    sma100: Mapped[float | None] = mapped_column(Float)
    sma200: Mapped[float | None] = mapped_column(Float)
    rs_21: Mapped[float | None] = mapped_column(Float)
    rs_63: Mapped[float | None] = mapped_column(Float)
    rs_126: Mapped[float | None] = mapped_column(Float)
    realized_vol_20: Mapped[float | None] = mapped_column(Float)
    breakout_type: Mapped[str | None] = mapped_column(String(32))
    breakout_level: Mapped[float | None] = mapped_column(Price)

    trend_score: Mapped[float | None] = mapped_column(Float)
    momentum_score: Mapped[float | None] = mapped_column(Float)
    volume_score: Mapped[float | None] = mapped_column(Float)
    breakout_score: Mapped[float | None] = mapped_column(Float)
    relative_strength_score: Mapped[float | None] = mapped_column(Float)
    fundamental_score: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)

    stop_price: Mapped[float] = mapped_column(Price, nullable=False)
    target1_price: Mapped[float] = mapped_column(Price, nullable=False)
    target2_price: Mapped[float] = mapped_column(Price, nullable=False)
    initial_risk_per_share: Mapped[float] = mapped_column(Price, nullable=False)
    expected_value: Mapped[float | None] = mapped_column(Float)
    reward_risk: Mapped[float | None] = mapped_column(Float)
    earnings_date_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)

    buy_reasons: Mapped[list] = mapped_column(JSON, default=list)
    risk_factors: Mapped[list] = mapped_column(JSON, default=list)
    entry_features: Mapped[dict] = mapped_column(JSON, default=dict)

    #: Column names of the immutable group. ``AlertLifecycle`` refuses to write these.
    ENTRY_SNAPSHOT_COLUMNS: frozenset[str] = frozenset(
        {
            "buy_ts_utc", "buy_price", "bid", "ask", "spread", "spread_bps",
            "opportunity_score", "probability", "probability_sample_size",
            "probability_method", "confidence", "market_regime", "sector", "industry",
            "market_cap", "volume", "rel_volume", "rsi14", "macd", "macd_hist", "atr14",
            "atr_pct", "ema9", "ema20", "ema21", "ema50", "sma50", "sma100", "sma200",
            "rs_21", "rs_63", "rs_126", "realized_vol_20", "breakout_type",
            "breakout_level", "trend_score", "momentum_score", "volume_score",
            "breakout_score", "relative_strength_score", "fundamental_score",
            "risk_score", "stop_price", "target1_price", "target2_price",
            "initial_risk_per_share", "expected_value", "reward_risk",
            "earnings_date_utc", "buy_reasons", "risk_factors", "entry_features",
            "strategy_version",
        }
    )

    # ---- tracking (mutable) ------------------------------------------------------------
    status: Mapped[str] = mapped_column(String(24), default=AlertStatus.BUY_SIGNAL.value)
    current_price: Mapped[float | None] = mapped_column(Price)
    current_return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    highest_price_since_buy: Mapped[float | None] = mapped_column(Price)
    max_gain_pct: Mapped[float] = mapped_column(Float, default=0.0)
    lowest_price_since_buy: Mapped[float | None] = mapped_column(Price)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    trailing_stop_price: Mapped[float | None] = mapped_column(Price)
    current_stop_price: Mapped[float | None] = mapped_column(Price)
    remaining_fraction: Mapped[float] = mapped_column(Float, default=1.0)
    realized_return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    bars_held: Mapped[int] = mapped_column(Integer, default=0)

    thesis_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    thesis_notes: Mapped[list] = mapped_column(JSON, default=list)
    milestones_hit: Mapped[list] = mapped_column(JSON, default=list)

    last_evaluated_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)
    closed_ts_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)
    final_return_pct: Mapped[float | None] = mapped_column(Float)
    final_r_multiple: Mapped[float | None] = mapped_column(Float)
    holding_period_days: Mapped[int | None] = mapped_column(Integer)
    sell_alert_id: Mapped[int | None] = mapped_column(Integer)

    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at_utc: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utc_now, onupdate=utc_now, index=True
    )

    sells: Mapped[list[SellAlert]] = relationship(
        back_populates="buy_alert", order_by="SellAlert.sell_ts_utc"
    )
    events: Mapped[list[AlertEvent]] = relationship(
        back_populates="buy_alert", order_by="AlertEvent.ts_utc"
    )

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES


# --------------------------------------------------------------------------------------
# 8. sell_alerts
# --------------------------------------------------------------------------------------


class SellAlert(Base):
    """Always references its parent BUY — ``buy_alert_id`` is NOT NULL by design."""

    __tablename__ = "sell_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_uid: Mapped[str] = mapped_column(String(40), unique=True, default=_uid, index=True)
    buy_alert_id: Mapped[int] = mapped_column(
        ForeignKey("buy_alerts.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(16), index=True)

    sell_ts_utc: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    sell_price: Mapped[float] = mapped_column(Price, nullable=False)
    entry_price: Mapped[float] = mapped_column(Price, nullable=False)
    fraction_closed: Mapped[float] = mapped_column(Float, default=1.0)

    final_return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    realized_r_multiple: Mapped[float] = mapped_column(Float, default=0.0)
    holding_period_days: Mapped[int] = mapped_column(Integer, default=0)

    exit_reason: Mapped[str] = mapped_column(String(40), nullable=False)
    exit_reason_detail: Mapped[str | None] = mapped_column(Text)
    exit_rules_fired: Mapped[list] = mapped_column(JSON, default=list)

    max_gain_pct: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    market_regime: Mapped[str | None] = mapped_column(String(24))
    strategy_version: Mapped[str] = mapped_column(String(64))
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at_utc: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utc_now, onupdate=utc_now, index=True
    )

    buy_alert: Mapped[BuyAlert] = relationship(back_populates="sells")


# --------------------------------------------------------------------------------------
# 9. alert_events
# --------------------------------------------------------------------------------------


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    buy_alert_id: Mapped[int] = mapped_column(ForeignKey("buy_alerts.id"), index=True)
    ts_utc: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[float | None] = mapped_column(Price)
    title: Mapped[str] = mapped_column(String(128))
    detail: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    is_user_visible: Mapped[bool] = mapped_column(Boolean, default=True)

    buy_alert: Mapped[BuyAlert] = relationship(back_populates="events")


# --------------------------------------------------------------------------------------
# 10. positions  /  11. position_snapshots
# --------------------------------------------------------------------------------------


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    buy_alert_id: Mapped[int | None] = mapped_column(ForeignKey("buy_alerts.id"), index=True)
    portfolio_id: Mapped[str] = mapped_column(String(32), default="paper", index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)

    opened_ts_utc: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    entry_price: Mapped[float] = mapped_column(Price)
    shares: Mapped[float] = mapped_column(Qty)
    initial_shares: Mapped[float] = mapped_column(Qty)
    cost_basis: Mapped[float] = mapped_column(Price)

    stop_price: Mapped[float | None] = mapped_column(Price)
    target1_price: Mapped[float | None] = mapped_column(Price)
    target2_price: Mapped[float | None] = mapped_column(Price)
    risk_amount: Mapped[float | None] = mapped_column(Price)
    risk_pct_of_equity: Mapped[float | None] = mapped_column(Float)

    current_price: Mapped[float | None] = mapped_column(Price)
    unrealized_pnl: Mapped[float] = mapped_column(Price, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Price, default=0.0)
    sector: Mapped[str | None] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    closed_ts_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)


class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"), index=True)
    ts_utc: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now, index=True)
    price: Mapped[float] = mapped_column(Price)
    shares: Mapped[float] = mapped_column(Qty)
    market_value: Mapped[float] = mapped_column(Price)
    unrealized_pnl: Mapped[float] = mapped_column(Price)
    return_pct: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float | None] = mapped_column(Price)
    trailing_stop_price: Mapped[float | None] = mapped_column(Price)


# --------------------------------------------------------------------------------------
# 12. strategy_versions
# --------------------------------------------------------------------------------------


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at_utc: Mapped[datetime] = _ts()
    description: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    weights: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------------------
# 13. backtest_runs  /  14. backtest_trades
# --------------------------------------------------------------------------------------


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_uid: Mapped[str] = mapped_column(String(40), unique=True, default=_uid, index=True)
    created_at_utc: Mapped[datetime] = _ts()
    strategy_version: Mapped[str] = mapped_column(String(64))
    start_date: Mapped[datetime | None] = mapped_column(Date)
    end_date: Mapped[datetime | None] = mapped_column(Date)
    universe_size: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(16), default="BACKTEST")
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", index=True)
    error: Mapped[str | None] = mapped_column(Text)

    trades: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    expectancy: Mapped[float | None] = mapped_column(Float)
    sharpe: Mapped[float | None] = mapped_column(Float)
    sortino: Mapped[float | None] = mapped_column(Float)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float)
    avg_return_pct: Mapped[float | None] = mapped_column(Float)
    median_return_pct: Mapped[float | None] = mapped_column(Float)
    avg_holding_days: Mapped[float | None] = mapped_column(Float)
    target_hit_rate: Mapped[float | None] = mapped_column(Float)
    stop_rate: Mapped[float | None] = mapped_column(Float)
    total_return_pct: Mapped[float | None] = mapped_column(Float)
    benchmark_return_pct: Mapped[float | None] = mapped_column(Float)

    equity_curve: Mapped[list] = mapped_column(JSON, default=list)
    monthly_returns: Mapped[list] = mapped_column(JSON, default=list)
    folds: Mapped[list] = mapped_column(JSON, default=list)
    sensitivity: Mapped[dict] = mapped_column(JSON, default=dict)
    bias_warnings: Mapped[list] = mapped_column(JSON, default=list)


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    entry_ts_utc: Mapped[datetime] = mapped_column(UtcDateTime)
    entry_price: Mapped[float] = mapped_column(Price)
    exit_ts_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)
    exit_price: Mapped[float | None] = mapped_column(Price)
    shares: Mapped[float] = mapped_column(Qty, default=0.0)
    return_pct: Mapped[float | None] = mapped_column(Float)
    r_multiple: Mapped[float | None] = mapped_column(Float)
    exit_reason: Mapped[str | None] = mapped_column(String(40))
    max_gain_pct: Mapped[float | None] = mapped_column(Float)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float)
    holding_days: Mapped[int | None] = mapped_column(Integer)
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    market_regime: Mapped[str | None] = mapped_column(String(24))
    slippage_cost: Mapped[float] = mapped_column(Float, default=0.0)
    spread_cost: Mapped[float] = mapped_column(Float, default=0.0)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    fold: Mapped[int | None] = mapped_column(Integer)
    sample: Mapped[str | None] = mapped_column(String(16))


# --------------------------------------------------------------------------------------
# 15. portfolio_snapshots
# --------------------------------------------------------------------------------------


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(32), default="paper", index=True)
    ts_utc: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now, index=True)
    equity: Mapped[float] = mapped_column(Price)
    cash: Mapped[float] = mapped_column(Price)
    positions_value: Mapped[float] = mapped_column(Price, default=0.0)
    open_positions: Mapped[int] = mapped_column(Integer, default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Price, default=0.0)
    realized_pnl_cum: Mapped[float] = mapped_column(Price, default=0.0)
    drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    benchmark_equity: Mapped[float | None] = mapped_column(Price)


# --------------------------------------------------------------------------------------
# 16. settings
# --------------------------------------------------------------------------------------


class SettingRow(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    category: Mapped[str] = mapped_column(String(32), default="general")
    updated_at_utc: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utc_now, onupdate=utc_now
    )
    updated_by: Mapped[str | None] = mapped_column(String(64))


# --------------------------------------------------------------------------------------
# 17. audit_logs
# --------------------------------------------------------------------------------------


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_lookup", "ticker", "ts_utc"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ts_utc: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now, index=True)
    ticker: Mapped[str | None] = mapped_column(String(16), index=True)
    decision: Mapped[str] = mapped_column(String(16), index=True)
    stage: Mapped[str] = mapped_column(String(24), default="SCAN")
    strategy_version: Mapped[str | None] = mapped_column(String(64))
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    indicators: Mapped[dict] = mapped_column(JSON, default=dict)
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    rules_passed: Mapped[list] = mapped_column(JSON, default=list)
    rules_failed: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    data_provider: Mapped[str | None] = mapped_column(String(32))
