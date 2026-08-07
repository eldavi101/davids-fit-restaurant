package com.equitysignal.domain

import com.equitysignal.core.model.Alert
import com.equitysignal.core.model.AlertEvent
import com.equitysignal.core.model.Analytics
import com.equitysignal.core.model.BacktestRun
import com.equitysignal.core.model.DashboardSummary
import com.equitysignal.core.model.EquityCurve
import com.equitysignal.core.model.MarketRegime
import com.equitysignal.core.model.MarketStatus
import com.equitysignal.core.model.PortfolioState
import com.equitysignal.core.model.Position
import com.equitysignal.core.model.ScannerResult
import com.equitysignal.core.model.StockAnalysis
import com.equitysignal.core.model.StockChart
import com.equitysignal.core.model.StockDetail
import com.equitysignal.core.model.StrategySettings
import javax.inject.Inject
import kotlinx.coroutines.flow.Flow

/**
 * Use cases.
 *
 * Thin by design: they exist to give screens a vocabulary in domain terms and to keep
 * ViewModels from depending on repository shapes. Where a use case would add nothing but
 * indirection it simply forwards, and where it earns its place — `AlertsTab` filtering,
 * dashboard assembly — the logic lives here rather than in a ViewModel.
 */

enum class AlertsTab { ALL, BUY, SELL, ACTIVE, CLOSED }

class ObserveAlertsUseCase @Inject constructor(private val repository: AlertRepository) {
    operator fun invoke(tab: AlertsTab): Flow<List<Alert>> = when (tab) {
        // ALL and BUY differ in intent, not in source: every alert in this system starts
        // as a BUY, so the BUY tab is the full ledger ordered by entry.
        AlertsTab.ALL, AlertsTab.BUY -> repository.observeAll()
        AlertsTab.SELL -> repository.observeSells()
        AlertsTab.ACTIVE -> repository.observeActive()
        AlertsTab.CLOSED -> repository.observeClosed()
    }
}

class ObserveAlertUseCase @Inject constructor(private val repository: AlertRepository) {
    operator fun invoke(alertUid: String): Flow<Alert?> = repository.observeAlert(alertUid)
}

class ObserveAlertTimelineUseCase @Inject constructor(private val repository: AlertRepository) {
    operator fun invoke(alertUid: String): Flow<List<AlertEvent>> =
        repository.observeTimeline(alertUid)
}

class ObserveUnreadAlertCountUseCase @Inject constructor(private val repository: AlertRepository) {
    operator fun invoke(): Flow<Int> = repository.observeUnreadCount()
}

class MarkAlertReadUseCase @Inject constructor(private val repository: AlertRepository) {
    suspend operator fun invoke(alertUid: String) = repository.markRead(alertUid)
}

class ArchiveAlertUseCase @Inject constructor(private val repository: AlertRepository) {
    /** Archiving hides an alert from the default list. It never deletes it. */
    suspend operator fun invoke(alertUid: String, archived: Boolean) =
        repository.setArchived(alertUid, archived)
}

class RefreshAlertsUseCase @Inject constructor(private val repository: AlertRepository) {
    suspend operator fun invoke(): Result<Unit> = repository.refresh()
}

class RefreshTimelineUseCase @Inject constructor(private val repository: AlertRepository) {
    suspend operator fun invoke(alertUid: String): Result<Unit> =
        repository.refreshTimeline(alertUid)
}

class ObserveAlertsForTickerUseCase @Inject constructor(private val repository: AlertRepository) {
    operator fun invoke(ticker: String): Flow<List<Alert>> = repository.observeForTicker(ticker)
}

class ObserveScannerUseCase @Inject constructor(private val repository: ScannerRepository) {
    operator fun invoke(): Flow<List<ScannerResult>> = repository.observeResults()
}

class RefreshScannerUseCase @Inject constructor(private val repository: ScannerRepository) {
    suspend operator fun invoke(filter: ScannerFilter): Result<Unit> = repository.refresh(filter)
}

class ObserveMarketStatusUseCase @Inject constructor(private val repository: MarketRepository) {
    operator fun invoke(): Flow<MarketStatus?> = repository.observeStatus()
}

class ObserveMarketRegimeUseCase @Inject constructor(private val repository: MarketRepository) {
    operator fun invoke(): Flow<MarketRegime?> = repository.observeRegime()
}

class ObserveDashboardUseCase @Inject constructor(private val repository: SyncRepository) {
    operator fun invoke(): Flow<DashboardSummary> = repository.observeDashboard()
}

class SyncNowUseCase @Inject constructor(private val repository: SyncRepository) {
    suspend operator fun invoke(): SyncOutcome = repository.sync()
}

class ObservePositionsUseCase @Inject constructor(private val repository: PortfolioRepository) {
    operator fun invoke(): Flow<List<Position>> = repository.observePositions()
}

class ObservePortfolioUseCase @Inject constructor(private val repository: PortfolioRepository) {
    operator fun invoke(): Flow<PortfolioState?> = repository.observePortfolio()
}

class ObserveAnalyticsUseCase @Inject constructor(private val repository: PortfolioRepository) {
    operator fun invoke(): Flow<Analytics?> = repository.observeAnalytics()
}

class RefreshPortfolioUseCase @Inject constructor(private val repository: PortfolioRepository) {
    suspend operator fun invoke(): Result<Unit> = repository.refresh()
}

class GetEquityCurveUseCase @Inject constructor(private val repository: PortfolioRepository) {
    suspend operator fun invoke(benchmark: String = "SPY"): Result<EquityCurve> =
        repository.equityCurve(benchmark)
}

class GetHistoryUseCase @Inject constructor(private val repository: PortfolioRepository) {
    suspend operator fun invoke(outcome: String): Result<List<Alert>> = repository.history(outcome)
}

class ObserveStockUseCase @Inject constructor(private val repository: StockRepository) {
    operator fun invoke(ticker: String): Flow<StockDetail?> = repository.observeStock(ticker)
}

class GetStockChartUseCase @Inject constructor(private val repository: StockRepository) {
    suspend operator fun invoke(ticker: String, limit: Int = 300): Result<StockChart> =
        repository.chart(ticker, limit)
}

class GetStockAnalysisUseCase @Inject constructor(private val repository: StockRepository) {
    suspend operator fun invoke(ticker: String): Result<StockAnalysis> = repository.analysis(ticker)
}

class RefreshStockUseCase @Inject constructor(private val repository: StockRepository) {
    suspend operator fun invoke(ticker: String): Result<Unit> = repository.refreshStock(ticker)
}

class ObserveBacktestsUseCase @Inject constructor(private val repository: BacktestRepository) {
    suspend operator fun invoke(): Result<List<BacktestRun>> = repository.runs()
}

class GetBacktestUseCase @Inject constructor(private val repository: BacktestRepository) {
    suspend operator fun invoke(runUid: String): Result<BacktestRun> = repository.run(runUid)
}

class RunBacktestUseCase @Inject constructor(private val repository: BacktestRepository) {
    suspend operator fun invoke(
        mode: String,
        startDate: String? = null,
        endDate: String? = null,
        initialEquity: Double = 100_000.0,
        includeSensitivity: Boolean = false,
    ): Result<String> = repository.start(mode, startDate, endDate, initialEquity, includeSensitivity)
}

class ObserveConnectionUseCase @Inject constructor(private val repository: SettingsRepository) {
    operator fun invoke(): Flow<ConnectionSettings> = repository.observeConnection()
}

class UpdateConnectionUseCase @Inject constructor(private val repository: SettingsRepository) {
    suspend operator fun invoke(baseUrl: String, apiKey: String) =
        repository.setConnection(baseUrl, apiKey)
}

class UpdateNotificationPreferencesUseCase @Inject constructor(
    private val repository: SettingsRepository,
) {
    suspend operator fun invoke(enabled: Boolean, buy: Boolean, sell: Boolean) =
        repository.setNotifications(enabled, buy, sell)
}

class GetStrategySettingsUseCase @Inject constructor(private val repository: SettingsRepository) {
    suspend operator fun invoke(): Result<StrategySettings> = repository.strategySettings()
}

class UpdateStrategySettingUseCase @Inject constructor(private val repository: SettingsRepository) {
    /**
     * `createVersion` must be true for any parameter that changes how stocks are judged.
     * The backend rejects the change otherwise, so historical alerts stay comparable.
     */
    suspend operator fun invoke(key: String, value: String, createVersion: Boolean) =
        repository.updateStrategySetting(key, value, createVersion)
}
