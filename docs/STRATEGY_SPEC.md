# STRATEGY_SPEC.md

**Strategy version:** `momentum_breakout_v1.0.0`

Every quantity below is defined mathematically and implemented in
`backend/app/domain/`. Every threshold named here is a field of `StrategyConfig`
(`backend/app/core/config.py`) and is therefore configurable — nothing is
permanently hard-coded (requirement §25, §61.13).

Notation: bars are daily, split/dividend-adjusted. `C_t` close, `H_t` high, `L_t`
low, `V_t` volume, index `t = 0` = most recent bar. `x_t^{(n)}` = value `n` bars ago.

A clamp helper is used throughout: `clip(x, a, b) = min(max(x, a), b)`.
A linear ramp is used throughout:

```
ramp(x; lo, hi) = clip((x - lo) / (hi - lo), 0, 1)        # rising
ramp_inv(x; lo, hi) = 1 - ramp(x; lo, hi)                  # falling
```

Every component score below is expressed as a weighted sum of sub-scores in `[0,1]`,
multiplied by 100. **Every component score is in `[0,100]` and higher is always
better** — including `RiskScore`, where higher means *better risk quality*
(requirement §24).

---

## 1. Indicators

| Indicator | Definition |
|---|---|
| `SMA(n)_t` | `(1/n) Σ_{i=0}^{n-1} C_{t-i}` |
| `EMA(n)_t` | `α·C_t + (1-α)·EMA(n)_{t-1}`, `α = 2/(n+1)`, seeded with `SMA(n)` |
| `RSI(14)` | Wilder: `RS = avgGain/avgLoss`, `RSI = 100 - 100/(1+RS)`, Wilder smoothing |
| `MACD` | `EMA(12) - EMA(26)`; `signal = EMA(9)` of MACD; `hist = MACD - signal` |
| `TR_t` | `max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)` |
| `ATR(14)` | Wilder smoothing of `TR` |
| `ATR%` | `100 · ATR(14)_t / C_t` |
| `OBV_t` | `OBV_{t-1} + sign(C_t - C_{t-1})·V_t` |
| `ROC(n)` | `100 · (C_t / C_{t-n} - 1)` |
| `σ_r(n)` | annualised realised vol `= std(daily log returns, n) · √252` |
| `σ_down(n)` | same but over negative returns only |
| `β(252)` | `cov(r_stock, r_SPY) / var(r_SPY)` over 252 days |
| `BBW(20)` | Bollinger bandwidth `= (upper - lower)/middle`, 20-period, 2σ |
| `RelVol` | `V_t / mean(V, 50)` |
| `DollarVol50` | `mean(C·V, 50)` |
| `Dist52W` | `100 · (C_t / max(H, 252) - 1)` (≤ 0; 0 = at the 52-week high) |

Minimum history to score a stock: **252 bars**. Fewer bars ⇒ the stock is skipped
with `rules_failed = ["insufficient_history"]` (never scored with padded data).

---

## 2. TrendScore ∈ [0,100]

Sub-scores (each ∈ [0,1]):

| # | Sub-score | Definition | Weight |
|---|---|---|---|
| T1 | above EMA20 | `1 if C > EMA20 else 0` | 0.12 |
| T2 | above SMA50 | `1 if C > SMA50 else 0` | 0.12 |
| T3 | above SMA200 | `1 if C > SMA200 else 0` | 0.16 |
| T4 | MA stacking | `1 if EMA20 > SMA50 > SMA200 else 0.5 if EMA20 > SMA50 else 0` | 0.14 |
| T5 | SMA50 slope | `ramp(slope50; 0, 0.0015)` where `slope50 = (SMA50_t/SMA50_{t-20})^{1/20} - 1` | 0.12 |
| T6 | SMA200 slope | `ramp(slope200; 0, 0.0008)`, same form over 20 bars | 0.10 |
| T7 | higher highs / higher lows | fraction of the last 3 non-overlapping 20-bar windows where both `max H` and `min L` exceed the previous window's | 0.12 |
| T8 | proximity to 52-week high | `ramp_inv(-Dist52W; 3, 30)` — best within 3% of the high, zero at 30% below | 0.12 |

`TrendScore = 100 · Σ w_i · T_i`

## 3. MomentumScore ∈ [0,100]

| # | Sub-score | Definition | Weight |
|---|---|---|---|
| M1 | RSI level | trapezoid: `0` below 40, ramps to `1` at 55, holds to 68, falls back to `0.35` at 80, `0.1` above 85 — deliberately **not** monotone in RSI | 0.18 |
| M2 | RSI direction | `ramp(RSI_t - RSI_{t-5}; -2, +6)` | 0.10 |
| M3 | MACD posture | `1 if MACD > signal and MACD > 0 else 0.5 if MACD > signal else 0` | 0.16 |
| M4 | MACD histogram rising | `ramp(hist_t - hist_{t-3}; 0, 0.5·ATR/ C ·100)` | 0.10 |
| M5 | 1-month return | `ramp(ROC(21); 0, 12)` | 0.14 |
| M6 | 3-month return | `ramp(ROC(63); 0, 25)` | 0.14 |
| M7 | 6-month return | `ramp(ROC(126); 0, 40)` | 0.08 |
| M8 | acceleration | `ramp(ROC(21)/21 - ROC(63)/63; 0, 0.15)` — recent pace faster than the longer pace | 0.10 |

`MomentumScore = 100 · Σ w_i · M_i`

> **Design note (requirement §19):** M1 is capped and then *decays* above RSI 68, so
> an extremely extended stock cannot earn a high momentum score. Momentum alone never
> produces a BUY — see §7.

## 4. VolumeScore ∈ [0,100]

| # | Sub-score | Definition | Weight |
|---|---|---|---|
| V1 | relative volume | `ramp(RelVol; 1.0, 2.5)` | 0.28 |
| V2 | volume acceleration | `ramp(mean(V,5)/mean(V,50); 1.0, 2.0)` | 0.20 |
| V3 | price-volume confirmation | `up_vol / (up_vol + down_vol)` over 20 bars, mapped `ramp(x; 0.45, 0.70)` | 0.22 |
| V4 | OBV slope | `ramp(OBV_t/OBV_{t-20} - 1; 0, 0.10)` when `OBV_{t-20} > 0`, else `0.5` | 0.20 |
| V5 | liquidity adequacy | `ramp(DollarVol50; 10e6, 100e6)` | 0.10 |

## 5. BreakoutScore ∈ [0,100]

Let `HH(n) = max(H over bars 1..n)` (**excluding** the current bar).

| # | Sub-score | Definition | Weight |
|---|---|---|---|
| B1 | 20-day breakout | `1 if C_t > HH(20)` else `ramp(C_t/HH(20); 0.97, 1.0)·0.6` | 0.20 |
| B2 | 50-day breakout | `1 if C_t > HH(50)` else `0` | 0.18 |
| B3 | 52-week-high breakout | `1 if C_t > HH(252)` else `0` | 0.16 |
| B4 | consolidation before break | `ramp_inv(BBW20_{t-1} percentile over 126 bars; 0.2, 0.6)` — a tight base scores high | 0.14 |
| B5 | range expansion | `ramp(TR_t / ATR14_{t-1}; 1.0, 2.0)` | 0.12 |
| B6 | volume confirmation of the break | `ramp(RelVol; 1.2, 2.5)` if any of B1–B3 fired, else `0` | 0.12 |
| B7 | successful retest | `1` if within the last 10 bars price closed above `HH(20)_prior`, pulled back to within `0.5·ATR` of it, and closed back above — else `0` | 0.08 |

`breakout_type` recorded on the alert = the highest-precedence of
`FIFTY_TWO_WEEK_HIGH > FIFTY_DAY > TWENTY_DAY > CONSOLIDATION > RETEST > NONE`.

## 6. RelativeStrengthScore ∈ [0,100]

For horizon `n ∈ {21, 63, 126}`:

```
RS_n = 100 · ( (C_t / C_{t-n}) / (BENCH_t / BENCH_{t-n}) - 1 )
```

computed against `SPY`, and separately against the stock's sector ETF
(`XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLB, XLRE, XLC`; falls back to `SPY`
when the sector is unknown) and `QQQ`.

| # | Sub-score | Definition | Weight |
|---|---|---|---|
| R1 | `RS_21` vs SPY | `ramp(RS_21; 0, 10)` | 0.24 |
| R2 | `RS_63` vs SPY | `ramp(RS_63; 0, 18)` | 0.22 |
| R3 | `RS_126` vs SPY | `ramp(RS_126; 0, 30)` | 0.14 |
| R4 | `RS_63` vs sector ETF | `ramp(RS_63^{sector}; 0, 15)` | 0.20 |
| R5 | RS-line slope | `1 if (C/SPY)_t > (C/SPY)_{t-10} > (C/SPY)_{t-21}` else `0.5` if only the first holds, else `0` | 0.20 |

> Requirement §22 — a stock is favoured only when it beats **both** market and
> sector; R1–R3 and R4 are separate gate inputs, and the BUY gate additionally
> requires `RS_21 > 0` **and** `RS_63^{sector} > 0`.

## 7. FundamentalScore ∈ [0,100]

Computed from whatever the provider supplies. **Any missing input contributes a
neutral `0.5`, and the count of available inputs is recorded** as
`fundamental_coverage`; when coverage `< 0.34` the score is forced to exactly `50.0`
and flagged `fundamental_data_sparse` so it can never pretend to be information.

| Sub-score | Definition | Weight |
|---|---|---|
| revenue growth YoY | `ramp(g; 0, 0.25)` | 0.18 |
| EPS growth YoY | `ramp(g; 0, 0.30)` | 0.18 |
| last earnings surprise | `ramp(surprise%; -2, 10)` | 0.10 |
| operating margin | `ramp(m; 0, 0.25)` | 0.12 |
| free cash flow positive | `1 if FCF > 0 else 0` | 0.10 |
| debt / equity | `ramp_inv(d/e; 0.5, 2.5)` | 0.10 |
| ROE | `ramp(roe; 0.05, 0.25)` | 0.10 |
| valuation (PEG) | `ramp_inv(PEG; 1.0, 3.5)` when `PEG > 0`, else `0.5` | 0.12 |

## 8. RiskScore ∈ [0,100] — higher = better risk quality

| Sub-score | Definition | Weight |
|---|---|---|
| ATR% moderation | trapezoid: `0` at 0.8%, `1` from 1.5% to 4%, falling to `0` at 9% (too quiet is as unhelpful as too wild) | 0.18 |
| realised vol | `ramp_inv(σ_r(20); 0.25, 0.90)` | 0.14 |
| downside vol | `ramp_inv(σ_down(20); 0.20, 0.70)` | 0.12 |
| beta | `ramp_inv(|β - 1|; 0.3, 1.5)` | 0.08 |
| 1-year max drawdown | `ramp_inv(|MDD_252|; 0.20, 0.60)` | 0.12 |
| recent drawdown | `ramp_inv(|drawdown from 20-day high|; 0.03, 0.20)` | 0.10 |
| gap risk | `ramp_inv(mean(|overnight gap%|, 60); 0.5, 3.0)` | 0.10 |
| liquidity | `ramp(DollarVol50; 10e6, 150e6)` | 0.08 |
| earnings proximity | `0` if earnings within `earnings_blackout_days`, `0.5` if within 2× that, else `1` | 0.08 |

## 9. RegimeScore and the Market Regime Engine

Inputs: `SPY`, `QQQ`, `IWM`, a volatility proxy (`VIX` when available, otherwise
`σ_r(20)` of SPY annualised), and the 11 sector ETFs.

```
breadth      = share of sector ETFs with close > their SMA50          ∈ [0,1]
participation= share of sector ETFs with RS_63 vs SPY > 0             ∈ [0,1]
spy_dd       = 100·(SPY_t / max(SPY high, 252) - 1)                   ≤ 0
vol_level    = VIX (or proxy)
```

RegimeScore (0–100):

```
RegimeScore = 100 · ( 0.16·[SPY > EMA20] + 0.18·[SPY > SMA50] + 0.20·[SPY > SMA200]
                    + 0.14·breadth + 0.12·participation
                    + 0.10·ramp_inv(vol_level; 16, 34)
                    + 0.10·ramp_inv(-spy_dd; 3, 15) )
```

Classification (first match wins):

| Regime | Condition |
|---|---|
| `HIGH_VOLATILITY` | `vol_level ≥ vix_high` (30) **or** `σ_r(20)_SPY ≥ 0.30` |
| `BEAR` | `SPY < SMA200` **and** `SMA200 slope < 0` **and** `spy_dd ≤ -10` |
| `RISK_OFF` | `SPY < SMA50` **and** `breadth < 0.40` |
| `STRONG_BULL` | `SPY > EMA20 > SMA50 > SMA200` **and** `breadth ≥ 0.65` **and** `RegimeScore ≥ 78` |
| `BULL` | `SPY > SMA200` **and** `RegimeScore ≥ 58` |
| `NEUTRAL` | otherwise |

**Regime tightens the BUY gate** (requirement §17). `min_opportunity_score` is
adjusted by a per-regime delta, and some regimes forbid new BUYs entirely:

| Regime | score delta | new BUYs allowed |
|---|---|---|
| `STRONG_BULL` | `-2` | yes |
| `BULL` | `0` | yes |
| `NEUTRAL` | `+4` | yes |
| `RISK_OFF` | `+8` | yes (min RR raised to 2.0) |
| `HIGH_VOLATILITY` | `+10` | yes (min RR raised to 2.2) |
| `BEAR` | — | **no** |

## 10. OpportunityScore ∈ [0,100]

```
OpportunityScore = Σ_k w_k · Score_k
```

Default weights (`StrategyConfig.weights`, sum = 1.0):

| component | weight |
|---|---|
| trend | 0.20 |
| momentum | 0.15 |
| volume | 0.10 |
| breakout | 0.15 |
| relative_strength | 0.15 |
| fundamental | 0.10 |
| regime | 0.10 |
| risk | 0.05 |

Weights are validated to sum to 1.0 ± 1e-6 at load; they are stored per strategy
version and may be re-optimised into a *new* version.

**Category:**

| range | category |
|---|---|
| 90–100 | `EXCEPTIONAL` |
| 85–89 | `STRONG_BUY` |
| 80–84 | `BUY` |
| 70–79 | `WATCH` |
| 55–69 | `NEUTRAL` |
| < 55 | `AVOID` |

**Confidence** ∈ [0,100] is separate from the score and measures *agreement*, not
level:

```
confidence = 100 · ( 0.45·agreement + 0.30·coverage + 0.25·probability_reliability )

agreement              = 1 - clip(stdev(core component scores)/35, 0, 1)
                         over {trend, momentum, volume, breakout, relative_strength}
coverage               = fraction of inputs actually available (fundamentals,
                         bars, quote freshness)
probability_reliability= ramp(probability_sample_size; 30, 300)
```

> **A high OpportunityScore alone never creates a BUY alert** (requirement §25).

---

## 11. Stop, targets, reward/risk

```
swing_low      = min(L over last 10 bars)
stop_atr       = C_t - k_stop · ATR14_t                     (k_stop default 2.0)
stop_swing     = swing_low - 0.25 · ATR14_t

# Structure first: a stop belongs under the swing low, because that is where the trade
# is actually wrong. But a stock that has run far from its base has a swing low too
# distant to risk against, so past the ATR band we fall back to the volatility stop
# rather than accept an oversized loss.
stop_price     = stop_swing  if (stop_swing < stop_atr and
                                 C_t - stop_swing ≤ max_stop_atr_mult · ATR)
                 else stop_atr
stop_price     = max(stop_price, C_t · (1 - max_stop_pct))  # cap risk, default 12%
risk_per_share = C_t - stop_price                           # must be > 0
target1        = C_t + r1 · risk_per_share                  (r1 default 1.5)
target2        = C_t + r2 · risk_per_share                  (r2 default 3.0)
reward_risk    = (target1 - C_t) / risk_per_share  blended with target2:
                 RR = (0.5·(target1 - C_t) + 0.5·(target2 - C_t)) / risk_per_share
```

Stop validity requires `0 < stop_price < C_t`, `0.5·ATR ≤ risk_per_share ≤ 4·ATR`,
and `risk_per_share / C_t ≤ max_stop_pct`.

## 12. Probability engine

Probability is **never** derived from the OpportunityScore (requirement §27).
It is estimated from historical outcomes of comparable setups.

**Labelling (triple barrier).** For a historical setup at bar `t` with entry `C_t`,
stop `S`, target `T1`, and horizon `H = 20` trading days, walk bars `t+1 … t+H`
*forward only*:

- if `L_τ ≤ S` before `H_τ ≥ T1` → label `0` (loss)
- if `H_τ ≥ T1` first → label `1` (win)
- if both are touched inside the same bar → conservatively label `0`
  (intrabar order is unknowable; this biases the estimate **down**, never up)
- if neither is touched by `t+H` → label by sign of `C_{t+H} - C_t`, and record
  `time_exit = True`

**Model.** Logistic regression on standardised features
`[trend, momentum, volume, breakout, relative_strength, fundamental, risk,
regime_score, atr_pct, reward_risk, dist_52w_high, rel_volume]`, fitted with
L2 regularisation, then **calibrated** (Platt/sigmoid on a held-out split; isotonic
when `n ≥ 1000`). Interpretable by design; the coefficient vector is stored with the
strategy version.

**Fallback.** When `n < min_probability_samples` (default 50) for the model, the
engine falls back to a bucketed empirical frequency (OpportunityScore decile ×
regime), and if *that* is also too thin it returns the configured
`prior_win_rate` (default 0.40) with `sample_size = 0` and
`reliability = "PRIOR_ONLY"`. The UI shows the sample size next to every
probability and never displays a probability without it.

**Reported with every estimate:** `probability`, `sample_size`,
`historical_win_rate`, `expected_return_on_win`, `expected_loss_on_loss`,
Wilson 95% confidence interval, and the model tag. Nothing is presented as certainty
(requirement §61.2, §61.3).

## 13. Expected value

In R-multiples (`1R = risk_per_share`):

```
avg_win_R   = historical mean R of winning comparable setups, default (r1+r2)/2 = 2.25
avg_loss_R  = historical mean |R| of losing comparable setups, default 1.0
EV_R        = p · avg_win_R - (1 - p) · avg_loss_R
EV_pct      = EV_R · (risk_per_share / C_t) · 100
```

**Reject if `EV_R ≤ 0`** (requirement §28). Minimum `reward_risk` default `1.5`.

## 14. BUY gate — all thirteen must pass

| # | Rule id | Condition |
|---|---|---|
| 1 | `min_opportunity_score` | `OpportunityScore ≥ min_score + regime_delta` (base 80) |
| 2 | `bullish_trend` | `TrendScore ≥ 60` **and** `C > EMA20` **and** `C > SMA50` **and** `C > SMA200` |
| 3 | `liquidity` | `C ≥ 5`, `market_cap ≥ 500e6`, `DollarVol50 ≥ 10e6`, `mean(V,50) ≥ 500e3` |
| 4 | `spread` | `spread_bps ≤ 25` (skipped with a recorded note when no quote is available) |
| 5 | `positive_expected_value` | `EV_R > 0` |
| 6 | `min_reward_risk` | `RR ≥ 1.5` (raised by regime) |
| 7 | `relative_strength` | `RelativeStrengthScore ≥ 55` **and** `RS_21 > 0` **and** `RS_63^{sector} > 0` |
| 8 | `market_regime` | regime allows new BUYs (not `BEAR`) |
| 9 | `valid_stop` | stop validity per §11 |
| 10 | `multiple_confirmations` | at least 3 of {trend, momentum, volume, breakout, relative_strength} score `≥ 60`, **and** `BreakoutScore ≥ 55` **or** `MomentumScore ≥ 65` |
| 11 | `no_duplicate_alert` | no open alert already exists for this instrument |
| 12 | `earnings_window` | no scheduled earnings within `earnings_blackout_days` (default 5) |
| 13 | `data_integrity` | bars fresh, ≥ 252 bars, no NaN in required indicators, regime classified |

Only when **all thirteen** pass is a BUY alert created. Passed and failed rule ids
are persisted on `stock_scores` and `audit_logs` for every evaluated stock, whether
it passes or not.

## 15. Position sizing

```
risk_capital    = portfolio_equity · risk_pct_per_trade      (default 0.0075 = 0.75%)
risk_per_share  = entry - stop
shares          = floor(risk_capital / risk_per_share)
notional        = shares · entry
```

Then clamped by portfolio rules (§16). `shares = 0` ⇒ no paper position is opened,
but **the alert is still created** — the signal and the portfolio are separate
concerns.

## 16. Portfolio risk limits

| limit | default |
|---|---|
| max risk per trade | 1.0% of equity |
| max total open risk | 6.0% of equity |
| max open positions | 12 |
| max sector exposure | 30% of equity |
| max single position | 12% of equity |
| min cash | 5% of equity |
| max correlated cluster | 4 positions with pairwise 63-day return correlation ≥ 0.80 |

## 17. SELL engine — priority-ordered triggers

Evaluated top-down; the first firing trigger produces the SELL.

| Priority | Trigger | Condition |
|---|---|---|
| 1 | `STOP_LOSS` | `L_t ≤ current_stop` → fill at `min(open, stop)` |
| 2 | `TRAILING_STOP` | trailing active **and** `L_t ≤ trailing_stop` |
| 3 | `TARGET_2` | `H_t ≥ target2` (full exit, or 25% partial if staged exits enabled) |
| 4 | `TARGET_1` | `H_t ≥ target1` → 25% partial + status `TARGET_1_HIT`; activates trailing |
| 5 | `TREND_BREAKDOWN` | `C < SMA50` **and** `C < EMA20` on **two consecutive** closes |
| 6 | `MOMENTUM_DETERIORATION` | `MACD < signal` **and** `RSI14 < 45` **and** `hist_t < hist_{t-3}` |
| 7 | `RS_BREAKDOWN` | `RS_21 < 0` **and** `(C/SPY)_t < (C/SPY)_{t-10}` |
| 8 | `BREAKOUT_FAILURE` | breakout entry **and** `C < breakout_level - 0.5·ATR_entry` within 15 bars of entry |
| 9 | `REGIME_DETERIORATION` | regime became `BEAR` or `HIGH_VOLATILITY` **and** `unrealised return < 0` |
| 10 | `RISK_INCREASE` | `ATR%_t > 2.0 · ATR%_entry` **and** unrealised return `< 1R` |
| 11 | `FUNDAMENTAL_DETERIORATION` | `FundamentalScore` fell ≥ 25 points below entry with coverage ≥ 0.34 |
| 12 | `TIME_EXIT` | `holding_days ≥ 60` **and** unrealised return `< 0.5R` |
| 13 | `VOLATILITY_EXIT` | `σ_r(20)_t > 2.5 · σ_r(20)_entry` **and** unrealised return `< 0` |

**Explicit prohibition (requirement §31):** overbought RSI is *not* a sell trigger.
`RSI > 70` alone never appears in any condition above, and
`test_rsi_overbought_alone_does_not_sell` enforces this in the test suite.

### Trailing stop

Three modes, all supported and configurable; when several are enabled the trailing
stop is the **maximum** of the enabled candidates, and it is **monotonically
non-decreasing** for the life of the trade:

```
chandelier = max(C since entry) - atr_mult · ATR14_t          (atr_mult default 2.5)
percent    = max(C since entry) · (1 - pct_trail)             (pct_trail default 0.08)
ma_stop    = EMA20_t  (or SMA50 for the "slow" variant)

trailing_stop_t = max(trailing_stop_{t-1}, max(enabled candidates))
```

Trailing activates once **either** unrealised gain ≥ `1R` **or** `TARGET_1_HIT`.
Until then only the initial stop applies. `current_stop = max(initial_stop,
trailing_stop)`.

### Staged exits (optional, on by default)

| event | fraction closed | remaining |
|---|---|---|
| `TARGET_1_HIT` | 25% | 75% |
| `TARGET_2_HIT` | 25% | 50% |
| trailing stop / other trigger | 100% of remainder | 0% |

Each partial writes a `sell_alerts` row with `fraction_closed` and an
`alert_events` PARTIAL_EXIT entry. The BUY alert only reaches `CLOSED` when
`remaining_fraction = 0`.

### Final return

```
final_return_pct = Σ_i fraction_i · (exit_price_i / entry_price - 1) · 100
r_multiple       = Σ_i fraction_i · (exit_price_i - entry_price) / initial_risk_per_share
holding_period_days = (last_exit_ts - buy_ts).days
```

## 18. Explainability contract

Every scored stock carries `rules_passed`, `rules_failed`, per-component scores and
their contributions. Every BUY alert carries `buy_reasons` (human-readable, e.g.
`"Relative volume 2.3× the 50-day average"`) and `risk_factors`. Every monitoring
pass records a `HOLD` or `SELL` decision with its reasons into `audit_logs`.
No decision in this system is unexplainable.
