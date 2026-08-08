# IMPLEMENTATION_PLAN.md

22 phases, in dependency order. Each phase lists its deliverable and its
verification step. Phases are not marked done until their verification passes.

---

## Build verification status (read this first)

| Component | Can it be compiled/tested in the dev container? | Status |
|---|---|---|
| Backend (Python/FastAPI) | **Yes** — PyPI is reachable | 219 tests pass, ruff clean, green in CI |
| Android (Kotlin/Gradle) | **No** — `dl.google.com` is blocked by egress policy, and `maven.google.com` redirects to it. AGP, AndroidX, Compose, Room, Hilt and the Android SDK are all unreachable | **Green in CI**: all 19 modules compile, unit tests pass, `app-debug.apk` (19.8 MB) uploaded as an artifact |

`curl https://maven.google.com/com/android/tools/build/gradle/8.7.3/gradle-8.7.3.pom`
returns a 301 to `dl.google.com`, which the proxy answers with **403 (policy
denial)**. This is an organisation egress rule, not a misconfiguration, and it is not
something the build can route around.

Consequence: **the APK is produced by `.github/workflows/android.yml` on GitHub
Actions**, not in this container. The workflow runs unit tests, assembles the debug
APK and uploads it as an artifact. Acceptance criterion §60.1 ("I can install the
APK") is satisfied by downloading that artifact.

CI was therefore the first compiler to see the Android sources, and it took six rounds
to reach green. What it found, in order:

| Round | Finding |
|---|---|
| 1 | `NetworkModule` used OkHttp 3's Java-style accessors; OkHttp 4 deprecates them at ERROR level |
| 2 | `MetricRow` declared `modifier` before `valueColor`, so 25 call sites passed a `Color` to a `Modifier` parameter |
| 3 | `:app` injected `AppPreferences` without declaring `:core:datastore` |
| 4 | `Modifier.padding` used without its import |
| 5 | `AlertsViewModel` combined `selectedTab` alongside its own `flatMapLatest`, so a tab switch briefly paired the new tab with the previous tab's alerts |
| 6 | Green — unit tests pass, APK assembled |

Round 5 is the one worth recording: the failing unit test was reporting a real,
user-visible defect (the CLOSED tab momentarily showing open trades), not a flaw in
itself. The fix moves the tab inside `flatMapLatest` so tab and list always come from a
single emission, making the inconsistent state unrepresentable rather than merely
unlikely.

---

## Phase 1 — System architecture
`ARCHITECTURE.md`, module boundaries, dependency rules, tier split.
✔ Verify: docs written; module graph matches the eventual directory layout.

## Phase 2 — Backend database
17 SQLAlchemy models, session management, Postgres/SQLite duality, bootstrap.
✔ Verify: `create_all()` on SQLite; round-trip insert/select test per table.

## Phase 3 — Market data
`MarketDataProvider` protocol; Polygon, Finnhub, FMP, Twelve Data, Alpha Vantage
adapters; provider registry with failover; a deterministic **synthetic** provider
for tests and offline demos, clearly labelled `SYNTHETIC` end-to-end.
✔ Verify: adapter unit tests against recorded fixtures; registry failover test;
synthetic provider reproducibility test.

## Phase 4 — Stock universe
Fidelity-tradable filters (exchange, security type, price, market cap, dollar
volume, share volume; OTC/penny/leveraged/inverse excluded by default, ETF/ADR
configurable). Every exclusion records a reason.
✔ Verify: `test_universe_filters` covers each rule and each default.

## Phase 5 — Technical indicators
EMA/SMA/RSI/MACD/ATR/OBV/ROC/Bollinger/realised vol/downside vol/beta/drawdown/
relative strength, all as pure functions over `BarWindow`.
✔ Verify: known-value tests against hand-computed fixtures; no-lookahead test.

## Phase 6 — Market regime
Regime engine over SPY/QQQ/IWM/VIX/sector ETFs; `RegimeScore`; classification;
per-regime gate tightening.
✔ Verify: synthetic bull/bear/high-vol series classify correctly; BEAR blocks BUYs.

## Phase 7 — Opportunity scoring
Seven component scores + weighted `OpportunityScore`, category, confidence,
`rules_passed` / `rules_failed`, full component breakdown.
✔ Verify: weights sum to 1; every score bounded [0,100]; monotonicity tests;
sparse-fundamentals path returns exactly 50 and is flagged.

## Phase 8 — BUY engine
Stops/targets, reward/risk, probability model, expected value, the 13-rule gate.
✔ Verify: each rule individually blocks a BUY; high score alone does not fire;
EV ≤ 0 rejected; duplicate guard; earnings blackout.

## Phase 9 — Alert lifecycle
Creation with the immutable entry snapshot, event timeline, status machine,
audit log.
✔ Verify: entry immutability; one open alert per instrument; append-only events.

## Phase 10 — SELL engine
13 priority-ordered triggers, trailing stops (chandelier/percent/MA, monotone),
staged partial exits, final return and R-multiple.
✔ Verify: each trigger fires in isolation; **RSI overbought alone never sells**;
trailing never decreases; fractions sum to 1.0; SELL always references its BUY.

## Phase 11 — Android foundation
Multi-module Gradle (version catalog, convention plugins), Hilt, Retrofit, Room,
DataStore, WorkManager, Material 3 dark theme, navigation scaffold.
✔ Verify: CI `assembleDebug`.

## Phase 12 — Android Scanner
Ranked cards, sorting, filter sheet, search, category badges.

## Phase 13 — Android Alert Center
Tabs ALL/BUY/SELL/ACTIVE/CLOSED, alert cards, unread badge, read/archive,
alert detail with WHY WE BOUGHT, thesis panel, lifecycle stepper, timeline.

## Phase 14 — Android Stock Details
Candlestick chart with BUY/SELL markers, stop/target lines, MA overlays;
volume/RSI/MACD/RS panes; Overview/Technical/Fundamental/Risk/Signal History.

## Phase 15 — Android Positions
Paper portfolio summary and position cards.

## Phase 16 — Android Analytics
Statistics grid, equity curve vs SPY, drawdown, monthly returns, distribution.

## Phase 17 — Android local notifications
Channels, dedupe, deep link `equitysignal://alert/{uid}` → alert detail,
runtime permission on API 33+.
✔ Verify: navigation deep-link test.

## Phase 18 — Backtesting
`BarWindow` look-ahead barrier, next-open fills, stop-first ambiguity rule,
costs/slippage/spread, split handling, cash-constrained portfolio, metrics,
SPY benchmark.
✔ Verify: no-lookahead, split-phantom-stop, stop-first, cash-constraint tests.

## Phase 19 — Walk-forward validation
Rolling/anchored folds, purge + embargo, train/validation/test isolation,
per-fold reporting, `overfit_gap`.
✔ Verify: test-window data never influences fitted statistics.

## Phase 20 — Paper portfolio
Virtual equity, sizing by risk, portfolio limits, correlation cluster cap,
realised/unrealised P&L, snapshots. `PAPER_TRADING = True` by default.
✔ Verify: sizing formula; limits; P&L arithmetic.

## Phase 21 — Testing
Full backend suite: indicators, scoring, EV, stops, targets, sizing, BUY logic,
SELL logic, P&L, duplicate alerts, lifecycle, API, DB, backtesting.
Android: ViewModel, repository, Room, network, navigation, UI tests.
✔ Verify: `pytest` green locally; Gradle `testDebugUnitTest` green in CI.

## Phase 22 — Production hardening
`.env.example`, no secrets in source, API-key auth, rate limiting, structured
logging, health/system-status endpoints, graceful degradation, Docker Compose,
CI workflows.

## Phase 23 — Live-data deployment
Everything between "the code compiles" and "the phone shows real prices":

* **Client-side pacing.** Every vendor sells access by request rate, and a 429 costs a
  request while returning no data — which the scanner correctly treats as a refusal to
  signal. So an unpaced deployment does not merely run slowly, it never alerts. A sliding
  60-second limiter fronts every request, with per-vendor defaults and a
  `MARKET_DATA_RATE_LIMIT_PER_MINUTE` override; 429/5xx/transport errors are retried with
  exponential backoff and honour `Retry-After`, while a rejected key fails immediately
  rather than burning quota.
* **Universe pre-screen.** Exchange and security-type rules are decided from the profile
  before any market-data request, so the ~10k listed symbols cost history calls only for
  the fraction that could ever be eligible. `UNIVERSE_MAX_SYMBOLS` caps the rest.
* **Operator CLI** (`python -m app.cli`): `check`, `init-db`, `universe`, `scan`,
  `monitor`, `bootstrap`. `bootstrap` exists because the scheduler leaves a fresh
  deployment looking broken — it waits for its first interval, and its market-hours guard
  means a Saturday install shows an empty app until Monday.
* **Deployment**: Postgres + API + one-shot bootstrap + optional Caddy TLS in
  `docker-compose.yml`; `scripts/setup.sh` generates secrets and runs the whole sequence;
  `docs/DEPLOYMENT.md` documents it, including the four things only the operator can supply.
* **Android**: a debug-only network security config so a LAN backend is reachable (the
  release build stays HTTPS-only), and a base-URL rewrite that preserves a reverse-proxy
  subpath instead of collapsing it to the host root.

✔ Verify: `test_provider_transport.py` (limiter windows, retry/backoff, pre-screen
equivalence with the full rule set), `test_cli.py` (check reports each misconfiguration,
bootstrap stops at the first failure, no key is ever printed),
`BaseUrlInterceptorTest.kt` (host/port/subpath rewriting, https default, invalid input
left untouched).

---

## Acceptance criteria mapping (requirement §60)

| # | Criterion | Where it is satisfied |
|---|---|---|
| 1 | Install the APK | CI artifact from `.github/workflows/android.yml` |
| 2 | Open the app | `:app` MainActivity + NavHost |
| 3 | Market status | Home banner ← `GET /market/status` |
| 4 | See stocks analysed | Home "stocks scanned" + Scanner |
| 5 | Ranked opportunities | Scanner screen ← `GET /scanner` |
| 6 | Generates BUY alerts | `domain/signals/buy_engine.py` + scanner worker |
| 7 | BUY alerts in-app | Alert Center |
| 8 | Alerts stored | `buy_alerts` + Room cache; never deleted |
| 9 | Alerts update | monitor loop + `SyncWorker` |
| 10–13 | Return, max gain, drawdown, stop/targets | alert tracking fields → Alert Detail |
| 14 | Why the stock was selected | `buy_reasons` → WHY WE BOUGHT panel |
| 15–16 | SELL detection + in-app SELL alerts | `sell_engine.py` → Alert Center SELL tab |
| 17 | SELL links to BUY | `sell_alerts.buy_alert_id` NOT NULL |
| 18 | Closed trades accessible | History screen; append-only tables |
| 19–20 | Notifications + tap opens the alert | `:core:notifications` + deep link |
| 21 | Filter BUY/SELL/ACTIVE/CLOSED | Alert Center tabs |
| 22 | Complete timeline | `alert_events` → `GET /alerts/{id}/timeline` |
| 23 | Stock charts | Stock Detail candlestick + panes |
| 24 | Performance statistics | Analytics screen |
| 25 | Run backtests | Backtesting screen → `POST /backtests` |
| 26 | Compare with SPY | equity curve benchmark |
| 27 | Walk-forward | backtest mode `WALK_FORWARD`, per-fold table |
| 28 | Paper trading | Positions screen; `PAPER_TRADING=True` default |
| 29 | Survives restarts | Postgres + Room persistence; no in-memory alert state |
| 30 | No external notification integrations | none present — see the grep check below |

## Prohibited-integration check

CI runs a guard that fails the build if any of these appear in the source:

```
telegram · discord · slack webhook · smtplib · sendgrid · mailgun ·
twilio · whatsapp · SMTP · nodemailer
```

See `.github/workflows/backend.yml` → `no-external-alert-channels` job.
