# DATABASE_SCHEMA.md

Backend: **PostgreSQL 14+** in production, **SQLite** for tests and local dev
(the SQLAlchemy models are dialect-neutral; JSON columns use `JSON`, which maps to
`JSONB` on Postgres via `postgresql.JSONB` variant).

All timestamps are `TIMESTAMP WITH TIME ZONE`, stored in **UTC**.
Money and prices are `NUMERIC(18,6)` on Postgres to avoid binary-float drift;
ratios and scores are `DOUBLE PRECISION`.

---

## 1. `instruments`

The tradable universe.

| column | type | notes |
|---|---|---|
| `id` | PK int | |
| `ticker` | text, unique, indexed | e.g. `NVDA` |
| `company_name` | text | |
| `exchange` | text | `NASDAQ`, `NYSE`, `NYSE_AMERICAN` |
| `security_type` | text | `COMMON`, `ETF`, `ADR` |
| `sector` | text | |
| `industry` | text | |
| `market_cap` | numeric | latest known |
| `avg_volume_50d` | numeric | shares |
| `avg_dollar_volume_50d` | numeric | USD |
| `is_etf` / `is_adr` / `is_leveraged_etf` / `is_inverse_etf` / `is_otc` | bool | universe filters |
| `eligible` | bool, indexed | passes the configured Fidelity-tradable filters |
| `ineligible_reason` | text | why it was excluded (explainability) |
| `first_seen_utc`, `last_seen_utc` | timestamptz | delisting detection → survivorship bias handling |
| `delisted` | bool | rows are never deleted |
| `data_provider` | text | which adapter supplied it |
| `updated_at_utc` | timestamptz | |

## 2. `market_prices`

Split/dividend-adjusted OHLCV bars.

| column | type | notes |
|---|---|---|
| `id` | PK bigint | |
| `instrument_id` | FK → instruments, indexed | |
| `ts_utc` | timestamptz | bar **close** time |
| `timeframe` | text | `1d`, `1h`, `5m` |
| `open` `high` `low` `close` | numeric | **adjusted** |
| `volume` | numeric | |
| `raw_close` | numeric | unadjusted, kept for auditing corporate actions |
| `split_factor` `dividend` | numeric | applied adjustment factors |
| `data_provider` | text | |
| `ingested_at_utc` | timestamptz | staleness checks |

**Unique constraint** `(instrument_id, timeframe, ts_utc)` — the ingest is idempotent.

## 3. `technical_indicators`

Materialised per-bar indicator snapshot (also computable on the fly; persisted so a
signal can be reproduced byte-for-byte later).

`instrument_id`, `ts_utc`, `timeframe`, then:
`ema9 ema20 ema21 ema50 sma50 sma100 sma200 rsi14 macd macd_signal macd_hist
atr14 atr_pct obv roc21 bb_width vol_avg20 vol_avg50 rel_volume
high_20 high_50 high_252 low_20 low_252 dist_52w_high_pct
realized_vol_20 downside_vol_20 beta_252 rs_21 rs_63 rs_126`
plus `computed_at_utc`. Unique on `(instrument_id, timeframe, ts_utc)`.

## 4. `fundamental_metrics`

`instrument_id`, `as_of_utc`, `period` (`TTM`/`Q`/`FY`), then
`eps revenue revenue_growth_yoy earnings_growth_yoy eps_surprise_pct
gross_margin operating_margin net_margin free_cash_flow total_cash total_debt
debt_to_equity roe pe forward_pe peg institutional_ownership short_interest_pct
next_earnings_date_utc`, `data_provider`, `fetched_at_utc`.

## 5. `market_regimes`

One row per regime evaluation.

`id`, `ts_utc` (indexed), `regime` (`STRONG_BULL|BULL|NEUTRAL|RISK_OFF|BEAR|HIGH_VOLATILITY`),
`regime_score` (0–100), `spy_close`, `spy_above_ema20/sma50/sma200` (bool),
`qqq_rs`, `iwm_rs`, `breadth_pct` (share of sector ETFs above their 50-SMA),
`volatility_proxy` (VIX or realized-vol proxy), `spy_drawdown_pct`,
`sector_participation` (JSON), `components` (JSON), `strategy_version`.

## 6. `stock_scores`

Every scored stock, every scan — the scanner feed and the explainability record.

`id`, `instrument_id`, `ts_utc` (indexed), `strategy_version`,
`trend_score momentum_score volume_score breakout_score relative_strength_score
fundamental_score risk_score regime_score opportunity_score`,
`confidence`, `category` (`EXCEPTIONAL|STRONG_BUY|BUY|WATCH|NEUTRAL|AVOID`),
`components` (JSON — every sub-component and its contribution),
`rules_passed` (JSON array), `rules_failed` (JSON array),
`suggested_entry stop_price target1_price target2_price reward_risk
probability expected_value`, `price`, `data_provider`.

## 7. `buy_alerts`

**Immutable entry snapshot.** Nothing in the "entry" group is ever updated after
insert (requirement §29); mutable tracking lives in the tracking group.

*Identity*: `id` (PK), `alert_uid` (uuid, unique), `instrument_id`, `ticker`,
`company_name`, `strategy_version`, `data_provider`.

*Entry snapshot (immutable)*: `buy_ts_utc`, `buy_price`, `bid`, `ask`, `spread`,
`spread_bps`, `opportunity_score`, `probability`, `probability_sample_size`,
`confidence`, `market_regime`, `sector`, `industry`, `market_cap`, `volume`,
`rel_volume`, `rsi14`, `macd`, `macd_hist`, `atr14`, `atr_pct`,
`ema9 ema20 ema21 ema50 sma50 sma100 sma200`, `rs_21 rs_63 rs_126`,
`breakout_type`, `trend_score momentum_score volume_score breakout_score
relative_strength_score fundamental_score risk_score`,
`stop_price`, `target1_price`, `target2_price`, `initial_risk_per_share`,
`expected_value`, `reward_risk`, `earnings_date_utc`,
`buy_reasons` (JSON array of human-readable strings), `risk_factors` (JSON array),
`entry_features` (JSON — full feature vector used by the probability model).

*Tracking (mutable)*: `status`, `current_price`, `current_return_pct`,
`highest_price_since_buy`, `max_gain_pct`, `lowest_price_since_buy`,
`max_drawdown_pct`, `trailing_stop_price`, `current_stop_price`,
`remaining_fraction` (1.0 → 0.0 with partial exits), `realized_return_pct`,
`thesis_valid` (bool), `thesis_notes` (JSON), `last_evaluated_utc`,
`closed_ts_utc`, `final_return_pct`, `holding_period_days`, `sell_alert_id`.

Indexes: `(status)`, `(ticker, status)`, `(buy_ts_utc)`.
Partial-unique guard: at most one alert per ticker in an *open* status
(enforced in code by `AlertLifecycle.has_open_alert()` and by a unique index on
`(instrument_id)` filtered to open statuses on Postgres).

## 8. `sell_alerts`

| column | notes |
|---|---|
| `id`, `alert_uid` | |
| `buy_alert_id` | **FK → buy_alerts, NOT NULL** — a SELL can never be orphaned |
| `ticker`, `sell_ts_utc`, `sell_price`, `entry_price` | |
| `fraction_closed` | 0.25 for a partial, 1.0 for a full exit |
| `final_return_pct`, `realized_r_multiple`, `holding_period_days` | |
| `exit_reason` (enum), `exit_reason_detail` (text), `exit_rules_fired` (JSON) | |
| `max_gain_pct`, `max_drawdown_pct`, `market_regime`, `strategy_version` | |

`exit_reason ∈ {STOP_LOSS, TRAILING_STOP, TARGET_1, TARGET_2, MOMENTUM_DETERIORATION,
TREND_BREAKDOWN, RS_BREAKDOWN, BREAKOUT_FAILURE, REGIME_DETERIORATION, RISK_INCREASE,
FUNDAMENTAL_DETERIORATION, TIME_EXIT, VOLATILITY_EXIT, THESIS_INVALIDATION}`

## 9. `alert_events`

The permanent timeline (requirement §13). Append-only; nothing is ever deleted.

`id`, `buy_alert_id` (FK, indexed), `ts_utc`, `event_type`, `price`,
`title`, `detail`, `payload` (JSON), `is_user_visible` (bool).

`event_type ∈ {BUY_SIGNAL, PROFIT_MILESTONE, DRAWDOWN_MILESTONE, TARGET_1_HIT,
TARGET_2_HIT, PARTIAL_EXIT, TRAILING_STOP_UPDATED, STOP_UPDATED, THESIS_WARNING,
THESIS_INVALIDATED, REGIME_CHANGE, SELL_SIGNAL, CLOSED, STOPPED}`

## 10. `positions` (paper portfolio)

`id`, `buy_alert_id` (FK), `portfolio_id`, `ticker`, `opened_ts_utc`,
`entry_price`, `shares`, `initial_shares`, `cost_basis`, `stop_price`,
`target1_price`, `target2_price`, `risk_amount`, `risk_pct_of_equity`,
`unrealized_pnl`, `realized_pnl`, `current_price`, `status`, `closed_ts_utc`.

## 11. `position_snapshots`

Time series for the equity curve and per-position charts:
`position_id`, `ts_utc`, `price`, `shares`, `market_value`, `unrealized_pnl`,
`return_pct`, `stop_price`, `trailing_stop_price`.

## 12. `strategy_versions`

`version` (unique, e.g. `momentum_breakout_v1.0.0`), `created_at_utc`,
`description`, `parameters` (JSON — the complete `StrategyConfig` dump),
`is_active` (bool), `weights` (JSON), `notes`.

## 13. `backtest_runs`

`id`, `run_uid`, `created_at_utc`, `strategy_version`, `start_date`, `end_date`,
`universe_size`, `mode` (`BACKTEST|WALK_FORWARD|OOS`), `parameters` (JSON),
`status` (`QUEUED|RUNNING|COMPLETE|FAILED`), `error`,
metrics: `trades win_rate profit_factor expectancy sharpe sortino max_drawdown_pct
avg_return_pct median_return_pct avg_holding_days target_hit_rate stop_rate
total_return_pct benchmark_return_pct`,
`equity_curve` (JSON), `monthly_returns` (JSON), `folds` (JSON — walk-forward folds).

## 14. `backtest_trades`

Every simulated trade of a run: `backtest_run_id`, `ticker`, `entry_ts_utc`,
`entry_price`, `exit_ts_utc`, `exit_price`, `shares`, `return_pct`, `r_multiple`,
`exit_reason`, `max_gain_pct`, `max_drawdown_pct`, `holding_days`,
`opportunity_score`, `market_regime`, `slippage_cost`, `spread_cost`, `commission`,
`fold` (walk-forward fold id), `sample` (`TRAIN|VALIDATION|TEST`).

## 15. `portfolio_snapshots`

`portfolio_id`, `ts_utc`, `equity`, `cash`, `positions_value`, `open_positions`,
`unrealized_pnl`, `realized_pnl_cum`, `drawdown_pct`, `benchmark_equity`.

## 16. `settings`

Key/value configuration overriding defaults at runtime:
`key` (unique), `value` (JSON), `category`, `updated_at_utc`, `updated_by`.

## 17. `audit_logs`

Requirement §50 — the decision record, append-only.

`id`, `ts_utc` (indexed), `ticker`, `decision` (`BUY|NO_BUY|HOLD|SELL|ERROR|SKIP`),
`strategy_version`, `inputs` (JSON), `indicators` (JSON), `scores` (JSON),
`rules_passed` (JSON), `rules_failed` (JSON), `reason`, `error_code`,
`data_provider`, `stage` (`UNIVERSE|SCAN|SCORE|BUY_GATE|MONITOR|SELL_GATE`).

---

## Android Room cache

Room mirrors only what the UI needs offline. It is a cache; server IDs are the keys.

| table | contents |
|---|---|
| `cached_stocks` | ticker, company, price, sector, industry, market cap, day change, `fetched_at_utc` |
| `cached_scanner_results` | rank, ticker, all seven component scores, opportunity score, confidence, category, entry/stop/targets, reward-risk, `fetched_at_utc` |
| `cached_alerts` | full BUY-alert projection incl. status, entry, current, return, max gain, max drawdown, stop, targets, score, plus SELL fields when closed, `fetched_at_utc` |
| `cached_alert_events` | alert timeline rows (`alert_uid`, ts, type, price, title, detail) |
| `cached_positions` | paper positions with shares, cost basis, unrealized P&L |
| `cached_analytics` | the analytics payload as a single JSON row + `fetched_at_utc` |
| `alert_read_status` | `alert_uid`, `read` (bool), `archived` (bool), `read_at_utc` — **local only**, never deleted |
| `user_settings` | mirrors DataStore for queryable settings |

`alert_read_status` is intentionally a separate table so that refreshing
`cached_alerts` from the server can never clobber read/archived state.

---

## Retention

Nothing is auto-deleted. `buy_alerts`, `sell_alerts`, `alert_events`,
`backtest_trades` and `audit_logs` are append-only history. `market_prices` may be
pruned below the daily timeframe, but daily bars are retained permanently because
backtests depend on them.
