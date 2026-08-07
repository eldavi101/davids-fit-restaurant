# ALERT_LIFECYCLE.md

The alert is the central object of this system. It is created once, updated
continuously, closed explicitly, and **kept forever**.

---

## 1. States

```
                    ┌─────────────┐
                    │  WATCHING   │  score ≥ watch threshold, BUY gate not passed
                    └──────┬──────┘
                           │ all 13 BUY rules pass
                    ┌──────▼──────┐
                    │ BUY_SIGNAL  │  alert row created, entry snapshot frozen
                    └──────┬──────┘
                           │ first monitor pass
                    ┌──────▼──────┐
              ┌─────┤   ACTIVE    ├─────┐
              │     └──────┬──────┘     │
              │            │            │ thesis invalid, no exit fill
   target1 hit│            │stop hit    ▼
        ┌─────▼──────┐  ┌──▼──────┐  ┌──────────────┐
        │TARGET_1_HIT│  │ STOPPED │  │ INVALIDATED  │
        └─────┬──────┘  └──┬──────┘  └──────┬───────┘
              │            │                │
        ┌─────▼──────┐     │                │
        │TARGET_2_HIT│     │                │
        └─────┬──────┘     │                │
              │            │                │
        ┌─────▼──────┐     │                │
        │  TRAILING  │     │                │
        └─────┬──────┘     │                │
              │            │                │
        ┌─────▼────────────▼────────────────▼─────┐
        │              SELL_SIGNAL                │
        └──────────────────┬──────────────────────┘
                           │ remaining_fraction == 0
                    ┌──────▼──────┐
                    │   CLOSED    │  permanent historical trade
                    └─────────────┘
```

| State | Meaning | Open? |
|---|---|---|
| `WATCHING` | On the radar (score ≥ 70) but the BUY gate did not pass. No entry price. | yes |
| `BUY_SIGNAL` | Alert just created. Entry snapshot immutable from this moment. | yes |
| `ACTIVE` | Being monitored, no milestone yet. | yes |
| `TARGET_1_HIT` | Price touched Target 1; 25% booked if staged exits enabled; trailing activated. | yes |
| `TARGET_2_HIT` | Price touched Target 2; a further 25% booked. | yes |
| `TRAILING` | Remainder is being managed by the trailing stop only. | yes |
| `STOPPED` | Exited on the initial stop. Terminal path → `CLOSED`. | closing |
| `SELL_SIGNAL` | A SELL alert has been produced; the exit is recorded. | closing |
| `INVALIDATED` | Thesis broke before any fill logic applied (e.g. data integrity loss, delisting). | closing |
| `CLOSED` | `remaining_fraction == 0`, final return computed. **Never leaves the database.** | no |

"Open" statuses for the duplicate guard: `WATCHING, BUY_SIGNAL, ACTIVE,
TARGET_1_HIT, TARGET_2_HIT, TRAILING`.

## 2. Creation

Triggered only by the BUY gate passing (`STRATEGY_SPEC.md` §14). On creation, in one
transaction:

1. `buy_alerts` row inserted with the **immutable entry snapshot** (every field in
   `DATABASE_SCHEMA.md` §7 "entry snapshot"). These columns are never written again
   — enforced by `AlertLifecycle.update_tracking()` which only touches the tracking
   column set, and asserted by `test_entry_snapshot_is_immutable`.
2. `alert_events` row: `BUY_SIGNAL`, with price and the full reason list.
3. `audit_logs` row: `decision=BUY`, all inputs, indicators, scores, rules.
4. If paper trading is on and sizing yields `shares ≥ 1`: a `positions` row.
5. The alert is marked `notify_pending=True` so the Android sync marks it as a
   candidate for a local notification exactly once.

## 3. Monitoring

Every monitor pass (default every 5 minutes during market hours, once after the
close) for each open alert:

```
current_price          ← latest trade/close
current_return_pct     ← 100·(current/entry - 1)
highest_price_since_buy← max(prev, high of the bar)
max_gain_pct           ← 100·(highest/entry - 1)
lowest_price_since_buy ← min(prev, low of the bar)
max_drawdown_pct       ← 100·(lowest/entry - 1)          # ≤ 0
trailing_stop          ← monotone update per STRATEGY_SPEC §17
thesis_valid           ← re-evaluate trend/momentum/RS/regime vs entry
```

Milestone events are appended (each at most once per alert):
`+2%`, `+5%`, `+10%`, `+20%` profit milestones; `-3%`, `-5%` drawdown milestones;
`TARGET_1_HIT`; `TARGET_2_HIT`; `TRAILING_STOP_UPDATED` (only when it actually
moves, and rate-limited to once per bar); `THESIS_WARNING`; `REGIME_CHANGE`.

Then the SELL gate runs.

## 4. Closing

When the SELL gate fires:

1. `sell_alerts` row inserted with **`buy_alert_id` NOT NULL** — a SELL can never be
   orphaned (requirement §61.11). It carries entry price, exit price, fraction,
   return, R-multiple, holding period, exit reason + detail, the rules that fired,
   max gain, max drawdown, regime, and the **parent's** `strategy_version`.
2. `alert_events`: `SELL_SIGNAL` (and `PARTIAL_EXIT` when `fraction < 1`).
3. The BUY alert's tracking fields are updated: `remaining_fraction` reduced;
   when it reaches 0 → `status = CLOSED`, `closed_ts_utc`, `final_return_pct`,
   `holding_period_days`, `sell_alert_id` set to the final exit.
4. The paper position is reduced/closed and realised P&L booked.
5. `audit_logs`: `decision=SELL` with reasons.

The BUY alert **does not disappear** and is not modified in its entry group. In the
app it transitions from an "ACTIVE BUY" card to a "CLOSED" card showing entry, exit,
final return, holding period and exit reason (requirement §55).

## 5. Timeline

`alert_events` is append-only and permanently available at
`GET /alerts/{id}/timeline`. Example for a full lifecycle:

```
Aug 7  10:32  BUY SIGNAL              $184.32   Score 91 · RR 2.4 · 7 reasons
Aug 7  14:15  +2% PROFIT              $188.01
Aug 8  11:20  TARGET 1 HIT            $191.00   25% closed · trailing activated
Aug 9  13:41  TRAILING STOP UPDATED   $189.20   chandelier, ATR×2.5
Aug 10 10:05  SELL SIGNAL             $198.70   Trailing stop triggered
Aug 10 10:05  CLOSED                  +7.80%    holding 3 days
```

## 6. Read / unread / archived

Read state is **client-side only** (Room table `alert_read_status`), because it is a
per-device UI concern, and because keeping it out of the server projection means a
sync refresh can never clobber it.

- new alert arrives → unread
- opening the Alert Detail screen → read
- the user may archive an alert (hides it from the default list)
- **alerts are never deleted on read** (requirement §5)

The bottom-nav badge counts unread, non-archived alerts: `Alerts 🔔 3`.

## 7. Local notification binding

A notification is a *pointer*, never the alert itself. When sync ingests an alert
whose `alert_uid` is not yet in `cached_alerts` and whose type is BUY or SELL, the
app posts a local notification on channel `buy_signals` / `sell_signals` with a deep
link:

```
equitysignal://alert/{alert_uid}
```

Tapping it opens `MainActivity` → `NavHost` → `alert_detail/{alert_uid}`, i.e. the
exact alert. If the app was cold-started, the deep link is resolved after sync
completes; if the alert is not yet cached the detail screen fetches it by uid.

No alert content ever leaves the device or the backend through any external channel.

## 8. Invariants (all covered by tests)

1. Every `sell_alerts` row has a non-null `buy_alert_id` pointing at an existing BUY.
2. A BUY alert's entry snapshot never changes after insert.
3. At most one open alert exists per instrument at any time.
4. `max_gain_pct ≥ current_return_pct ≥ max_drawdown_pct` at all times.
5. `trailing_stop` is monotonically non-decreasing within one alert.
6. `CLOSED` requires `remaining_fraction == 0` and a non-null `final_return_pct`.
7. Sum of `fraction_closed` over an alert's SELLs equals exactly 1.0 when closed.
8. No alert row is ever deleted, by any code path.
