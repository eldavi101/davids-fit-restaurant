# Equity Signal Tracker

An Android stock research and signal-tracking system. It continuously scans U.S. equities
tradable through Fidelity, scores them, raises a **BUY alert** only when thirteen
independent conditions agree, tracks every alert permanently, and closes it with an
explicit **SELL alert** that references its parent BUY.

Open the app and you see, immediately: which stocks the system currently considers
high-quality buys, when each was detected and at what price, how it has performed since,
whether the thesis still holds, and exactly when and why the system decided to sell.

> **Paper trading only.** No broker is contacted and no order is ever routed. The system's
> job is to scan, analyse, alert, track, and measure.

---

## What is in this repository

| Path | Contents |
|---|---|
| `docs/` | The eight design documents. Every score, gate and exit rule is defined mathematically there and implemented to match. |
| `backend/` | Python 3.11+ / FastAPI / SQLAlchemy. Market data, indicators, regime, scoring, BUY and SELL engines, alert lifecycle, backtesting, paper portfolio, 30 REST endpoints. |
| `android/` | Kotlin / Jetpack Compose / Material 3, 19 Gradle modules across `:app`, `:core:*`, `:domain`, `:data`, `:features:*`. |
| `.github/workflows/` | Backend lint + tests, Android build + APK artifact, and the prohibited-integration guard. |

The repository also contains the original **David's Fit Restaurant** website
(`index.html`, `css/`, `js/`), which is untouched by this work.

---

## Getting the APK

The development container used to build this project blocks `dl.google.com` at the egress
policy layer, and `maven.google.com` redirects there — so the Android SDK, AGP, AndroidX,
Compose, Room and Hilt are unreachable and no Gradle Android build can run inside it.

**The APK is therefore produced by CI.** Push the branch (or run the workflow manually) and
download the `equity-signal-debug-apk` artifact from the **Android** workflow run. To build
locally on a machine with the Android SDK:

```bash
cd android
./gradlew :app:assembleDebug          # → app/build/outputs/apk/debug/app-debug.apk
./gradlew testDebugUnitTest
```

## Running the backend

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env                  # then fill it in — never commit .env
.venv/bin/pytest                      # 198 tests
.venv/bin/uvicorn app.main:app --reload
```

Or with Docker: `docker compose up` (Postgres + API).

Set `MARKET_DATA_PROVIDER` to one of `polygon`, `finnhub`, `fmp`, `twelvedata`,
`alphavantage` and supply that vendor's key. Leaving it as `synthetic` runs the whole
pipeline on generated data so you can exercise the app before you have credentials —
and every screen says so in a banner, because generated prices are never presented as a
market feed.

In the Android app, open **Settings** and enter your backend URL and the API key from
`API_KEYS`. That key is the only credential the app stores; vendor keys stay on the server.

---

## How a signal works

```
universe → bar ingest → market regime → seven component scores → OpportunityScore
   → BUY gate (13 rules, all must pass) → probability + expected value
   → BUY ALERT (immutable entry snapshot, permanent)
   → monitor: price, return, max gain, max drawdown, thesis re-validation
   → SELL gate (13 priority-ordered triggers) → SELL ALERT (references its BUY)
   → CLOSED, final return computed, kept forever
```

A few decisions worth knowing about, all documented in `docs/STRATEGY_SPEC.md`:

- **A high score alone never fires a signal.** Score is one of thirteen rules, and a
  separate rule requires several independent components to agree.
- **Probability is never derived from the score.** It comes from triple-barrier labelling
  of historical setups and a calibrated logistic model, and every estimate is displayed
  with its sample size. Thin evidence is labelled as a prior, not dressed up as a forecast.
- **Overbought RSI is not a sell trigger.** RSI appears in the SELL engine only *below* 45,
  alongside a MACD cross and a falling histogram. A test enforces this.
- **The backtester runs the same code as the live scanner** — the same `score_stock`,
  `evaluate_buy` and `evaluate_sell` functions — so the two cannot drift apart.
- **Stale or incomplete data blocks a new BUY** and the refusal is written to the audit log.
- **Nothing is ever deleted.** Alerts, events, SELLs and audit entries are append-only, and
  there is no DELETE route in the API.

## What is deliberately absent

No Telegram, Discord, Slack, email, SMS, WhatsApp or any other external notification
channel. The in-app Alert Center is the alert mechanism; Android local notifications are
pointers to alerts already stored on the device. This is enforced by a test that greps the
whole repository and by a CI job that fails the build, not just by documentation.

There is also no automatic Fidelity order execution, and Fidelity is never scraped.
