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
import com.equitysignal.core.model.SystemStatus
import kotlinx.coroutines.flow.Flow

/**
 * Repository contracts.
 *
 * Everything the UI observes is a `Flow` fed from the local cache, and every refresh is a
 * separate suspending call that writes into that cache. The screen therefore renders
 * immediately from what it already has and updates when the network answers — it never
 * waits on a request, which is what makes the app usable offline (requirement 46).
 */

sealed interface SyncOutcome {
    data class Success(val newAlerts: Int, val newSells: Int, val syncedAtUtc: Long) : SyncOutcome
    data class Failure(val message: String, val cause: Throwable? = null) : SyncOutcome
    data object NotConfigured : SyncOutcome
}

interface AlertRepository {
    fun observeAll(): Flow<List<Alert>>
    fun observeActive(): Flow<List<Alert>>
    fun observeClosed(): Flow<List<Alert>>
    fun observeSells(): Flow<List<Alert>>
    fun observeAlert(alertUid: String): Flow<Alert?>
    fun observeTimeline(alertUid: String): Flow<List<AlertEvent>>
    fun observeUnreadCount(): Flow<Int>
    fun observeForTicker(ticker: String): Flow<List<Alert>>

    suspend fun refresh(): Result<Unit>
    suspend fun refreshTimeline(alertUid: String): Result<Unit>
    suspend fun markRead(alertUid: String)
    suspend fun setArchived(alertUid: String, archived: Boolean)
}

interface ScannerRepository {
    fun observeResults(): Flow<List<ScannerResult>>
    fun observeTop(limit: Int): Flow<List<ScannerResult>>
    suspend fun refresh(filter: ScannerFilter = ScannerFilter()): Result<Unit>
}

data class ScannerFilter(
    val minScore: Double? = null,
    val sector: String? = null,
    val category: String? = null,
    val minPrice: Double? = null,
    val maxPrice: Double? = null,
    val minMarketCap: Double? = null,
    val minRelVolume: Double? = null,
    val minRiskScore: Double? = null,
    val signalReadyOnly: Boolean = false,
    val regime: String? = null,
    val search: String? = null,
    val sort: String = "score",
    val ascending: Boolean = false,
)

interface MarketRepository {
    fun observeStatus(): Flow<MarketStatus?>
    fun observeRegime(): Flow<MarketRegime?>
    suspend fun refresh(): Result<Unit>
    suspend fun systemStatus(): Result<SystemStatus>
    suspend fun triggerScan(): Result<Unit>
}

interface PortfolioRepository {
    fun observePositions(): Flow<List<Position>>
    fun observePortfolio(): Flow<PortfolioState?>
    fun observeAnalytics(): Flow<Analytics?>
    suspend fun refresh(): Result<Unit>
    suspend fun equityCurve(benchmark: String = "SPY"): Result<EquityCurve>
    suspend fun history(outcome: String = "all"): Result<List<Alert>>
}

interface StockRepository {
    fun observeStock(ticker: String): Flow<StockDetail?>
    suspend fun refreshStock(ticker: String): Result<Unit>
    suspend fun chart(ticker: String, limit: Int = 300): Result<StockChart>
    suspend fun analysis(ticker: String): Result<StockAnalysis>
}

interface BacktestRepository {
    suspend fun runs(): Result<List<BacktestRun>>
    suspend fun run(runUid: String): Result<BacktestRun>
    suspend fun start(
        mode: String,
        startDate: String?,
        endDate: String?,
        initialEquity: Double,
        includeSensitivity: Boolean,
    ): Result<String>
}

interface SettingsRepository {
    fun observeConnection(): Flow<ConnectionSettings>
    suspend fun setConnection(baseUrl: String, apiKey: String)
    suspend fun setNotifications(enabled: Boolean, buy: Boolean, sell: Boolean)
    suspend fun setSyncInterval(minutes: Long)
    suspend fun setDarkTheme(dark: Boolean)
    suspend fun strategySettings(): Result<StrategySettings>
    suspend fun updateStrategySetting(key: String, value: String, createVersion: Boolean): Result<StrategySettings>
}

data class ConnectionSettings(
    val baseUrl: String,
    val apiKey: String,
    val notificationsEnabled: Boolean,
    val buyNotifications: Boolean,
    val sellNotifications: Boolean,
    val syncIntervalMinutes: Long,
    val darkTheme: Boolean,
    val lastSyncAtUtc: Long?,
    val isConfigured: Boolean,
)

interface SyncRepository {
    /** One delta round trip. Posts local notifications for alerts that are new to this device. */
    suspend fun sync(): SyncOutcome
    fun observeDashboard(): Flow<DashboardSummary>
}
