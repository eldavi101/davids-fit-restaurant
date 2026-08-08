# ANDROID_ARCHITECTURE.md

**Stack:** Kotlin 2.0 · Jetpack Compose (BOM) · Material 3 · Hilt · Room ·
Retrofit/OkHttp · Kotlinx Serialization · Coroutines/Flow · WorkManager ·
DataStore · Navigation Compose · Vico (charts)

`minSdk 26` · `targetSdk 35` · `compileSdk 35` · JVM target 17

---

## 1. Module graph

```
                         :app
                          │
   ┌──────────────────────┼───────────────────────────────┐
   │        :features:dashboard  scanner  alerts  positions│
   │                stockdetails  history  analytics       │
   │                  backtesting  settings                │
   └──────────────────────┬───────────────────────────────┘
                          ▼
                       :domain          (pure Kotlin, no Android deps)
                          ▲
                          │
                       :data            (repository impls, sync, workers)
                          │
   ┌──────────┬───────────┼───────────┬─────────────┬──────────────┐
:core:network :core:database :core:datastore :core:model :core:common
                          │
              :core:designsystem   :core:notifications   :core:testing
```

Rules enforced by dependency declaration:

- `:domain` is a **pure Kotlin library** — it cannot reference Android, Room or
  Retrofit types. It owns models, repository *interfaces* and use cases.
- `:features:*` depend on `:domain`, `:core:designsystem`, `:core:common`,
  `:core:model`. They never depend on `:data`, `:core:network` or `:core:database`.
- `:app` is the only module that knows every feature; it wires Hilt and navigation.
- No feature depends on another feature. Cross-feature navigation goes through
  route constants in `:core:common`.

## 2. Layer responsibilities

### Presentation (`:features:*`)

Compose screens + `ViewModel`s. One `UiState` data class per screen, exposed as
`StateFlow<UiState>` via `stateIn(viewModelScope, WhileSubscribed(5_000), Initial)`.
Screens are stateless composables driven by that state plus an event lambda;
`@Preview`-able without Hilt.

```kotlin
sealed interface AlertsUiState {
    data object Loading : AlertsUiState
    data class Ready(
        val tab: AlertTab,
        val alerts: List<AlertUi>,
        val unreadCount: Int,
        val lastUpdated: Instant?,
        val isStale: Boolean,
        val isRefreshing: Boolean,
    ) : AlertsUiState
    data class Error(val message: String, val cached: List<AlertUi>) : AlertsUiState
}
```

Note `Error` still carries cached data — an offline screen shows the last good data,
labelled, rather than an empty error page.

### Domain (`:domain`)

Models (`Alert`, `AlertStatus`, `AlertEvent`, `ScannerResult`, `Position`,
`MarketRegime`, `Analytics`, `BacktestRun`, `StockDetail`, `StrategySettings`),
repository interfaces, and use cases:

`ObserveAlertsUseCase`, `ObserveUnreadAlertCountUseCase`, `MarkAlertReadUseCase`,
`ArchiveAlertUseCase`, `ObserveScannerUseCase`, `RefreshScannerUseCase`,
`ObserveDashboardUseCase`, `ObserveAlertTimelineUseCase`, `ObservePositionsUseCase`,
`ObserveAnalyticsUseCase`, `RunBacktestUseCase`, `ObserveSettingsUseCase`,
`UpdateSettingsUseCase`, `SyncNowUseCase`.

### Data (`:data`)

Repository implementations following **offline-first single source of truth**:

```
Room (SSOT) ──Flow──► UseCase ──► ViewModel ──► Compose
   ▲
   └── SyncManager ◄── Retrofit ◄── backend
```

The UI **never** waits on the network. It observes Room; sync writes into Room;
Compose recomposes. `NetworkBoundResource`-style helper:

```kotlin
fun <Db, Net> networkBoundResource(
    query: () -> Flow<Db>,
    fetch: suspend () -> Net,
    saveFetchResult: suspend (Net) -> Unit,
    shouldFetch: (Db) -> Boolean = { true },
): Flow<Resource<Db>>
```

## 3. Persistence & freshness

Every cached entity carries `fetchedAtUtc`. `FreshnessPolicy` maps an age to a
label used everywhere in the UI:

| age | label | price display |
|---|---|---|
| < 60 s | `LIVE` | plain |
| 60 s – 15 min | `DELAYED` | plain + timestamp |
| > 15 min or offline | `CACHED` | dimmed, `CACHED` chip, timestamp |

A cached price is **never** rendered as if live (requirement §46). Every screen has a
`LAST UPDATED <time ET>` line in its top bar.

`alert_read_status` is a separate Room table keyed by `alertUid`; refreshing
`cached_alerts` uses `@Insert(onConflict = REPLACE)` on the alert table only, so read
and archived flags survive every sync.

## 4. Sync

| trigger | work |
|---|---|
| app foreground / screen resume | `SyncNowUseCase` → immediate `GET /sync?since=` |
| `SyncWorker` (WorkManager, periodic 15 min, `NetworkType.CONNECTED`) | delta sync |
| `AlertMonitorWorker` (periodic 15 min, market hours only) | alert deltas + notifications |
| manual pull-to-refresh | forced full refresh |
| `BootReceiver` / `MyPackageReplaced` | re-enqueue periodic work |

Backoff: exponential, 30 s → 5 min, `KEEP` policy on unique periodic work so
re-enqueueing is idempotent. All workers are `@HiltWorker` with a
`HiltWorkerFactory` installed via `Configuration.Provider` on the `Application`.

The backend keeps analysing regardless of the app's state; the app is a reader
(requirement §44).

## 5. Notifications

Channels (created on first launch, `NotificationChannelGroup` "Signals"):

| channel id | name | importance |
|---|---|---|
| `buy_signals` | BUY signals | `HIGH` |
| `sell_signals` | SELL signals | `HIGH` |
| `position_updates` | Position updates | `DEFAULT` |
| `system` | Sync & system | `LOW` |

A notification is posted only when sync ingests an alert whose `alertUid` is new to
`cached_alerts` — so a notification can never exist without its alert. Dedupe is by
`alertUid` hash used as the notification id, and a `notified` flag in Room, so a
re-sync cannot double-post.

```
🚨 BUY SIGNAL · NVDA
Entry $184.32 · Score 91/100 · R/R 2.25
Tap to view analysis.
```

```
🔔 SELL SIGNAL · NVDA
Entry $184.32 → Exit $198.70 · +7.80%
Trailing stop triggered.
```

Deep link: `equitysignal://alert/{alertUid}` declared as an
`<intent-filter>` on `MainActivity` (`android:launchMode="singleTask"`), routed by
`NavHost` to `alert_detail/{alertUid}`. `POST_NOTIFICATIONS` is requested at runtime
on API 33+ with a rationale; denial degrades gracefully — the Alert Center still
works, since it is the primary mechanism and notifications are only a convenience.

## 6. Navigation

Bottom bar (5 destinations, requirement §7):

| route | label | icon |
|---|---|---|
| `home` | HOME | dashboard |
| `scanner` | SCANNER | radar |
| `alerts` | ALERTS | notifications (with badge) |
| `positions` | POSITIONS | account balance |
| `analytics` | ANALYTICS | insights |

Reachable from within: `alert_detail/{alertUid}`, `stock_detail/{ticker}`,
`history`, `backtesting`, `backtest_detail/{runUid}`, `strategy_lab`, `settings`,
`system_status`.

The alerts tab badge shows the unread count from
`ObserveUnreadAlertCountUseCase` — a Room `Flow`, so it updates without navigation.

## 7. Screens

| Screen | Content |
|---|---|
| **Home** | market status + regime banner; stat grid (stocks scanned, strong opportunities, BUY/SELL alerts today, active alerts, open paper positions, strategy return, win rate, profit factor, current drawdown); TOP OPPORTUNITIES list; recent alerts |
| **Scanner** | ranked cards with all component scores, entry/stop/target, R/R, category badge; sort, filter sheet (score, sector, market cap, price, rel volume, risk, signal type, regime), search |
| **Alerts** | tabs ALL / BUY / SELL / ACTIVE / CLOSED; financial cards with entry, current, return, max gain, max drawdown, stop, target, score, status chip; swipe to archive; unread dot |
| **Alert Detail** | header with status lifecycle stepper; price block; metrics grid; **WHY WE BOUGHT** checklist; **CURRENT THESIS** panel (valid / warning); stop & target ladder; timeline; link to Stock Detail; SELL block when closed |
| **Positions** | paper portfolio summary (equity, cash, open risk, exposure) + position cards with shares, cost basis, unrealised P&L, stop distance |
| **Stock Detail** | candlestick chart with BUY/SELL markers, stop and target lines, EMA20/EMA50/SMA200 overlays; volume, RSI, MACD, RS panes; tabs Overview / Technical / Fundamental / Risk / Signal History |
| **History** | closed trades with filters (date, ticker, sector, strategy version, return, score) and outcome segments |
| **Analytics** | full statistics grid; equity curve vs SPY; drawdown chart; monthly returns heat strip; win/loss distribution |
| **Backtesting** | configure and launch a run; run list with status; detail with metrics, per-fold walk-forward table (train/validation/test), equity curve, trade blotter |
| **Strategy Lab** | weight sliders and gate thresholds with live category preview; saving creates a new strategy version |
| **Settings** | backend URL + API key, universe filters, scoring weights, gate thresholds, sell engine, risk/portfolio limits, sync cadence, notification toggles, theme |
| **System Status** | provider health, last scan/monitor, degraded flags, error counts, DB state |

## 8. Design language

Dark-first institutional theme (requirement §54).

```kotlin
// core/designsystem — semantic financial colors, not raw palette references
val Gain      = Color(0xFF17C964)   // positive returns
val Loss      = Color(0xFFF31260)   // negative returns
val Neutral   = Color(0xFF8B93A7)
val Surface   = Color(0xFF0E1117)   // page
val SurfaceEl = Color(0xFF161B24)   // cards
val Accent    = Color(0xFF3B82F6)
```

Status colours are semantic and consistent everywhere:
`EXCEPTIONAL` violet · `STRONG_BUY` / `BUY` green · `WATCH` amber ·
`NEUTRAL` grey · `AVOID` / `STOPPED` red · `ACTIVE` blue · `CLOSED` slate.

Numerics use tabular figures (`FontFeatureSetting("tnum")`) so columns align.
Returns always carry an explicit sign and a colour. Shared components:
`ScoreBadge`, `StatusChip`, `ReturnText`, `StatTile`, `AlertCard`, `ScannerRow`,
`LifecycleStepper`, `MetricGrid`, `SparklineChart`, `CandlestickChart`,
`EquityCurveChart`, `FreshnessLabel`, `EmptyState`, `ErrorState`.

Accessibility: content descriptions on every icon-only control, ≥ 4.5:1 contrast for
text, minimum 48 dp touch targets, and return values also carry a ▲/▼ glyph so
red/green is never the only signal.

## 9. Testing

| layer | tool | coverage |
|---|---|---|
| ViewModels | JUnit + Turbine + `MainDispatcherRule` | state transitions, tab filtering, error→cached fallback |
| Repositories | fake DAO + `MockWebServer` | mapping, delta sync, read-status preservation |
| Room | `Room.inMemoryDatabaseBuilder` (Robolectric) | DAO queries, unread count, upsert not clobbering read state |
| Network | `MockWebServer` | DTO deserialisation, auth header, error mapping |
| Navigation | `TestNavHostController` | deep link `equitysignal://alert/{uid}` resolves to alert detail |
| UI | `createAndroidComposeRule` | Alert Center tabs, badge, empty/error states |

## 10. Build verification status

The development container for this repository blocks `dl.google.com` at the egress
policy layer, and `maven.google.com` redirects there — so AGP, AndroidX, Compose,
Room, Hilt and the Android SDK itself cannot be downloaded, and **no Gradle Android
build can run inside it**.

The Android sources here are therefore *written but not compiled locally*.
`.github/workflows/android.yml` runs `./gradlew :app:assembleDebug` and
`./gradlew testDebugUnitTest` on GitHub Actions, where the SDK is installed and the
network is open, and uploads `app-debug.apk` as a build artifact. That workflow is
the authoritative compile check for this module.

**Status: green.** All 19 modules compile, the unit tests pass, and the workflow
publishes `equity-signal-debug-apk` (19.8 MB). See `IMPLEMENTATION_PLAN.md` for the
six rounds of findings it took to get there.
