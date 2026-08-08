# ARCHITECTURE.md

**Project:** Equity Signal Tracker — Android stock research & signal-tracking system
**Strategy family:** `momentum_breakout_v1.0.0`
**Mode:** PAPER TRADING (default, and the only mode implemented)

---

## 1. What this system is

A two-tier system that continuously scans U.S. equities reasonably tradable through
Fidelity, scores them, raises **BUY alerts** when many independent conditions agree,
then tracks every alert until an explicit **SELL alert** closes it. Every alert is a
permanent, auditable object.

It is a *research and signal-tracking* product. It does **not** place broker orders.

### Non-goals (explicitly out of scope)

| Not implemented | Reason |
|---|---|
| Telegram / Discord / Slack / Email / SMS / WhatsApp / any external alert channel | Prohibited by requirements. The in-app Alert Center is the alert mechanism. |
| Automatic Fidelity order execution | Signal validation is deliberately separated from brokerage execution. |
| Scraping Fidelity | Universe is derived from licensed market-data providers. |

Android OS-level notifications **are** used, but only as local pointers to alerts that
already exist in the app database.

---

## 2. Tier split

```
┌───────────────────────────────────────────────┐
│  ANDROID APP  (Kotlin / Compose / Room)       │
│  UI, Alert Center, local notifications,       │
│  offline cache, charts, settings              │
└───────────────────┬───────────────────────────┘
                    │ HTTPS REST + API key
┌───────────────────┴───────────────────────────┐
│  BACKEND  (Python 3.11+ / FastAPI / Postgres) │
│  data ingest, indicators, regime, scoring,    │
│  BUY engine, monitor, SELL engine,            │
│  backtests, paper portfolio, audit log        │
└───────────────────┬───────────────────────────┘
                    │ provider adapters
        ┌───────────┴───────────┐
        │ Polygon / Finnhub /   │
        │ FMP / TwelveData /    │
        │ AlphaVantage          │
        └───────────────────────┘
```

**Why a backend at all:** the scanner and the post-signal monitor must keep running
when the phone is asleep or the app is closed. Android alone cannot guarantee that.
The phone is a *view* over authoritative server state, plus an offline cache.

---

## 3. Backend layering

```
backend/app/
  core/          config, logging, clock (UTC internal / America/New_York display), errors
  db/            SQLAlchemy models, session, bootstrap
  data/
    providers/   MarketDataProvider protocol + adapters + registry
    universe.py  Fidelity-tradable universe construction & liquidity filters
    repository.py persistence helpers for bars/instruments
  domain/
    indicators/  pure functions over price series (no I/O, no DB)
    regime/      market regime engine
    scoring/     trend, momentum, volume, breakout, relative strength,
                 fundamental, risk  →  OpportunityScore
    probability/ triple-barrier labelling, logistic model, calibration
    signals/     buy engine, stops/targets, sell engine, trailing stops
    portfolio/   position sizing, portfolio risk limits, paper portfolio
    backtest/    engine, walk-forward, metrics
  services/      scanner, monitor, alert lifecycle, audit, analytics
  api/           FastAPI routers + schemas
  workers/       scheduler loops
```

### Dependency rule

`api → services → domain → (pure)`, and `services → data → providers`.
`domain/` never imports `api/`, `db/` or `data/providers/`. Every quantitative
function is a pure function of explicit inputs, which is what makes them testable
and backtestable with identical code paths in live scanning and in backtests.

**Single-implementation rule:** the backtester calls the *same* `score_stock()`,
`evaluate_buy()` and `evaluate_sell()` functions as the live scanner. There is no
parallel "backtest version" of the strategy — that is the main defence against
live/backtest divergence.

---

## 4. Android layering (Clean Architecture + MVVM)

```
android/
  app/                     Application, MainActivity, NavHost, DI wiring
  core/common              Result, dispatchers, formatters, time
  core/designsystem        Material 3 dark theme, financial components
  core/model               domain models shared across features
  core/network             Retrofit, OkHttp, DTOs, API key interceptor
  core/database            Room entities, DAOs, converters
  core/datastore           DataStore preferences/settings
  core/notifications       channels, builders, deep-link intents
  core/testing             fixtures & fakes
  domain/                  use cases, repository interfaces
  data/                    repository implementations, sync, WorkManager workers
  features/dashboard  scanner  alerts  positions  stockdetails
           history  analytics  backtesting  settings
```

Presentation → Domain → Data. Features never talk to Retrofit or Room directly;
they depend on `domain` repository interfaces implemented in `data`.

### Offline behaviour

Room is a **cache with provenance**, not a source of truth. Every cached table
stores `fetched_at_utc`. Every screen renders a `LAST UPDATED …` line, and when data
is older than the freshness budget the UI marks prices `CACHED` — never presented as
live. See §46 of the requirements and `ANDROID_ARCHITECTURE.md`.

---

## 5. The pipeline

```
universe refresh (daily)
   ↓
bar ingest (intraday cadence + daily close)
   ↓
market regime engine  (SPY/QQQ/IWM/VIX/sector ETFs)
   ↓
per-stock scoring  (7 component scores → OpportunityScore)
   ↓
BUY gate (13 independent conditions, ALL must pass)
   ↓  pass
probability + expected value  →  reject if EV ≤ 0
   ↓
BUY ALERT persisted (immutable entry snapshot) + alert_event + audit_log
   ↓
monitor loop: price, return, max gain, max drawdown, thesis re-validation
   ↓
SELL gate (12 trigger families, priority ordered)
   ↓
SELL ALERT persisted, references buy_alert_id
   ↓
BUY alert → CLOSED, final return computed, kept forever
```

---

## 6. Failure safety

The scanner refuses to create a BUY signal when any of the following holds
(requirement §51). Each refusal is written to `audit_logs` with the failing reason:

- market data unavailable, or provider returned an error
- bars stale beyond `max_bar_age_minutes`
- database unavailable
- indicator inputs incomplete (insufficient history, NaN)
- market status uncertain
- regime engine could not classify

Monitoring of *existing* alerts continues under degraded data (it must, to protect
open positions), but a stale quote never advances a stop or triggers a SELL by
itself — a SELL requires fresh data or a hard stop breach on confirmed prices.

---

## 7. Security

- No API keys in the APK. Market-data credentials live **only** on the backend as
  environment variables (`.env.example` documents them; `.env` is git-ignored).
- The Android app authenticates to the backend with a single `X-API-Key` supplied by
  the user in Settings and stored in DataStore. It never sees provider credentials.
- HTTPS enforced; cleartext traffic disabled except for an explicit debug localhost
  network-security config.

---

## 8. Time handling

Internally everything is timezone-aware **UTC**. Market sessions, earnings windows
and every user-facing timestamp are rendered in **America/New_York**. Conversion
happens once, at the presentation boundary (`core/clock.py` on the backend,
`core/common` formatters on Android).

---

## 9. Strategy versioning

Every BUY alert stores `strategy_version`. Every SELL alert copies the version from
its parent BUY. Weights, thresholds and engine logic are captured in the
`strategy_versions` table with their full parameter JSON. Re-optimising the strategy
creates a *new* version; historical trades are never re-evaluated under new logic
(requirement §48 / §61.12).

---

## 10. Build and run

| Component | Command |
|---|---|
| Backend deps | `cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev]"` |
| Backend tests | `cd backend && .venv/bin/pytest` |
| Backend run | `uvicorn app.main:app --reload` |
| Android debug APK | `cd android && ./gradlew :app:assembleDebug` |
| Android unit tests | `cd android && ./gradlew test` |

> **Build-environment note.** The container this repository was developed in blocks
> `dl.google.com` (and therefore `maven.google.com`, which redirects there) at the
> egress-policy level. The Android SDK, AGP, AndroidX, Compose, Room and Hilt
> artifacts are unreachable, so the APK **cannot** be produced inside that container.
> `.github/workflows/android.yml` builds and uploads the APK on GitHub Actions, where
> the SDK is present; that workflow is green and publishes `equity-signal-debug-apk`.
> The backend has no such restriction and its full test suite runs locally. See `docs/IMPLEMENTATION_PLAN.md` §"Build verification status".
