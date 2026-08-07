# BACKTESTING_SPEC.md

The backtester exists to answer one question honestly: *would this strategy have
produced these alerts, at these prices, with money that actually had to be there?*
Everything below is designed to make the answer pessimistic rather than flattering.

---

## 1. The single-implementation rule

The backtest calls the **same** functions as the live scanner:

```
domain.scoring.score_stock()      domain.signals.evaluate_buy()
domain.signals.evaluate_sell()    domain.signals.compute_stop_targets()
domain.portfolio.position_size()
```

There is no separate "backtest strategy". If the two ever diverge, the backtest is
worthless — so the code makes divergence impossible by construction.

## 2. Bias controls

### 2.1 Look-ahead bias

A `BarWindow` object is the only way the engine can see data. It exposes bars
`0 … t` and physically cannot return bar `t+1`:

```python
class BarWindow:
    def __init__(self, bars, t): self._bars, self._t = bars, t
    def series(self, field): return self._bars[field][: self._t + 1]   # inclusive
```

Every indicator takes a `BarWindow`. Attempting to index past `t` raises.
`test_no_lookahead_in_indicators` re-computes every indicator at bar `t` from a
truncated array and asserts identical values — if any indicator peeked, the values
would differ.

### 2.2 Execution timing

Signals are computed **on the close of bar `t`** and executed **at the open of bar
`t+1`**. There is no same-bar entry at the signal price, ever. Exits follow the same
rule except for stops, which are evaluated intrabar (see §3).

### 2.3 Data leakage

- The probability model is fitted **only** on labels whose entire 20-bar outcome
  window ends before the first bar of the evaluation period. Setups whose outcome
  window would overlap the test period are dropped (purging), plus a 5-bar embargo.
- Feature standardisation (mean/std) is fitted on training data only and applied
  to test data — never re-fitted on the combined set.
- `test_probability_model_purge_and_embargo` asserts no training label's outcome
  window overlaps the test window.

### 2.4 Survivorship bias

`instruments` rows are never deleted. Delisted tickers keep `delisted = true` and
their `last_seen_utc`. The backtest universe at date `d` is
`{i : i.first_seen_utc ≤ d ≤ coalesce(i.delisted_at, ∞)}` — i.e. the universe *as it
was*, including companies that later failed. When the configured provider cannot
supply delisted history, the run is flagged:

```json
"bias_warnings": ["survivorship: provider supplied only currently-listed symbols;
                   results are optimistic by an unquantified amount"]
```

The system states the limitation instead of hiding it. It never silently reports a
survivorship-contaminated result as clean.

### 2.5 Corporate actions

All bars are split- and dividend-adjusted at ingest, with `raw_close`, `split_factor`
and `dividend` retained. A split detected *inside* an open backtest position adjusts
`shares`, `entry_price`, `stop`, `targets` and `highest_price_since_entry` by the
split factor in the same bar, so no phantom gap-down stop fires.
`test_split_does_not_trigger_phantom_stop` covers this.

## 3. Fill model

| event | fill price |
|---|---|
| entry | `open_{t+1} · (1 + slippage_bps/1e4) + half_spread` |
| target exit (limit) | `target` exactly, only if `high_t ≥ target`; no better fill |
| stop exit (intrabar) | `min(open_t, stop) · (1 - slippage_bps/1e4) - half_spread` — a gap-down fills at the **open**, not at the stop |
| signal exit (market) | `open_{t+1} · (1 - slippage_bps/1e4) - half_spread` |

Defaults: `slippage_bps = 5`, `spread_bps = 4` (half-spread each side),
`commission_per_trade = 0.0` (Fidelity equity commissions are zero; the field exists
and is applied when non-zero).

**Ambiguity rule:** if a bar's range contains *both* the stop and the target, the
engine takes the **stop**. Intrabar sequence is unknowable, and assuming the
favourable one is how backtests lie.

**Liquidity cap:** an entry may not exceed `max_participation` (default 1%) of the
bar's dollar volume; excess size is not filled.

## 4. Portfolio simulation

Cash-constrained and sequential. Each bar:

1. mark open positions to `close_t`, update trailing stops
2. evaluate exits (priority order from `STRATEGY_SPEC.md` §17)
3. evaluate new BUY candidates from bar `t`'s close, rank by OpportunityScore
4. size with `position_size()`, apply portfolio limits (§16 of the strategy spec),
   fill at `open_{t+1}` in rank order **until cash or risk budget runs out**
5. snapshot equity

A signal that cannot be funded is recorded as `skipped_insufficient_capital` — it
does not silently become a free trade.

## 5. Metrics

```
return_i        = (exit_i / entry_i - 1)
R_i             = (exit_i - entry_i) / initial_risk_per_share_i
win_rate        = |{i : return_i > 0}| / N
profit_factor   = Σ max(pnl_i,0) / |Σ min(pnl_i,0)|      (∞ → reported as null)
expectancy_R    = mean(R_i)
avg_return      = mean(return_i)        median_return = median(return_i)
avg_winner      = mean(return_i | >0)   avg_loser     = mean(return_i | ≤0)
target_hit_rate = |{exit_reason ∈ {TARGET_1, TARGET_2}}| / N
stop_rate       = |{exit_reason ∈ {STOP_LOSS, TRAILING_STOP}}| / N
avg_holding     = mean(holding_days)
```

On the daily equity curve `E_t`, with `r_t = E_t/E_{t-1} - 1`:

```
sharpe    = (mean(r) - rf_daily) / std(r) · √252
sortino   = (mean(r) - rf_daily) / std(min(r,0)) · √252
max_dd    = min over t of (E_t / max_{s≤t} E_s - 1)
CAGR      = (E_T / E_0)^(252/T) - 1
```

`rf_daily` defaults to 0 and is configurable. Sharpe/Sortino are reported with the
number of observations; fewer than 60 daily observations ⇒ reported as `null` with
`"insufficient_observations"` rather than a meaningless number.

Benchmark: buy-and-hold `SPY` over the identical window with the same starting
equity, so the comparison is like-for-like.

## 6. Walk-forward validation

Rolling (default) or anchored windows:

```
fold 1: train 2018-01-01 → 2021-12-31   test 2022-01-01 → 2022-12-31
fold 2: train 2019-01-01 → 2022-12-31   test 2023-01-01 → 2023-12-31
fold 3: train 2020-01-01 → 2023-12-31   test 2024-01-01 → 2024-12-31
…continuing while data remains
```

Per fold:

1. Fit the probability model on the **training** window only.
2. Optimise the tunable parameter set on training data, selecting on a
   **validation** slice = the final 20% of the training window (never the test
   window).
3. Freeze parameters. Run the test window once. Record.

Reported: per-fold train / validation / test metrics side by side, plus the
aggregate of **test folds only** — that aggregate is the headline number, because it
is the only out-of-sample one. A large train-vs-test gap is surfaced as
`overfit_gap = train_expectancy - test_expectancy` rather than buried.

**Hard rule:** test-window data never touches fitting or selection
(`test_walk_forward_never_fits_on_test` asserts the fitted feature statistics for
fold `k` are unchanged when the test window's rows are perturbed).

## 7. Out-of-sample split

Independent of walk-forward, the dataset is split chronologically:

| sample | share | use |
|---|---|---|
| `TRAIN` | first 60% | fitting and parameter search |
| `VALIDATION` | next 20% | model/parameter selection |
| `TEST` | final 20% | touched **once**, at the end |

Results are reported separately for the three samples, never merged into one
headline figure.

## 8. Robustness

Every backtest run also reports:

- **Parameter sensitivity:** metrics at ±20% on `min_opportunity_score`,
  `stop_atr_mult`, `target_r1`, `trail_atr_mult`. A strategy whose edge evaporates
  under a 20% parameter nudge is overfit, and the report says so.
- **Regime breakdown:** metrics per market regime.
- **Trade-count adequacy:** fewer than 30 test trades ⇒ every metric carries
  `"low_sample"` and the run is not treated as evidence.

## 9. What the system will not claim

Backtest output is labelled as a historical simulation with modelled costs. The API
and the app never describe any result as expected, projected or guaranteed future
performance (requirement §61.3). Probabilities always ship with their sample size
and confidence interval.
