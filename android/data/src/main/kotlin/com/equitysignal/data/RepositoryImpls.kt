package com.equitysignal.data

import com.equitysignal.core.common.IoDispatcher
import com.equitysignal.core.database.AlertDao
import com.equitysignal.core.database.CachedSnapshotEntity
import com.equitysignal.core.database.PositionDao
import com.equitysignal.core.database.ScannerDao
import com.equitysignal.core.database.SnapshotDao
import com.equitysignal.core.database.StockDao
import com.equitysignal.core.datastore.AppPreferences
import com.equitysignal.core.model.Alert
import com.equitysignal.core.model.AlertEvent
import com.equitysignal.core.model.Analytics
import com.equitysignal.core.model.BacktestRun
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
import com.equitysignal.core.network.EquitySignalApi
import com.equitysignal.core.network.dto.BacktestRequestDto
import com.equitysignal.core.network.dto.SettingsUpdateDto
import com.equitysignal.core.network.toModel
import com.equitysignal.domain.AlertRepository
import com.equitysignal.domain.BacktestRepository
import com.equitysignal.domain.ConnectionSettings
import com.equitysignal.domain.MarketRepository
import com.equitysignal.domain.PortfolioRepository
import com.equitysignal.domain.ScannerFilter
import com.equitysignal.domain.ScannerRepository
import com.equitysignal.domain.SettingsRepository
import com.equitysignal.domain.StockRepository
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json

/**
 * Repository implementations.
 *
 * The pattern throughout: **observe from Room, refresh into Room**. A screen subscribes to
 * the cache and gets whatever is already there instantly; refreshes write to the same
 * cache and the UI recomposes. No screen ever awaits a network call to render, which is
 * what makes the app work with no connection at all.
 *
 * Failures return `Result.failure` rather than throwing, so a ViewModel can surface the
 * message beside the cached content instead of replacing it with an error page.
 */

private suspend fun <T> apiCall(
    dispatcher: CoroutineDispatcher,
    block: suspend () -> T,
): Result<T> = withContext(dispatcher) {
    runCatching { block() }.recoverCatching { error ->
        throw when (error) {
            is java.net.UnknownHostException ->
                IllegalStateException("Cannot reach the backend. Check the URL in Settings.", error)
            is java.net.SocketTimeoutException ->
                IllegalStateException("The backend did not respond in time.", error)
            is retrofit2.HttpException -> when (error.code()) {
                401 -> IllegalStateException("API key rejected. Check it in Settings.", error)
                404 -> IllegalStateException("Not found on the backend.", error)
                429 -> IllegalStateException("Rate limited. Try again shortly.", error)
                else -> IllegalStateException("Backend error ${error.code()}.", error)
            }
            else -> error
        }
    }
}

@Singleton
class AlertRepositoryImpl @Inject constructor(
    private val api: EquitySignalApi,
    private val alertDao: AlertDao,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : AlertRepository {

    override fun observeAll(): Flow<List<Alert>> =
        alertDao.observeAll().map { rows -> rows.map { it.toModel() }.filterNot { it.isArchived } }

    override fun observeActive(): Flow<List<Alert>> =
        alertDao.observeActive().map { rows -> rows.map { it.toModel() } }

    override fun observeClosed(): Flow<List<Alert>> =
        alertDao.observeClosed().map { rows -> rows.map { it.toModel() } }

    override fun observeSells(): Flow<List<Alert>> =
        alertDao.observeWithSells().map { rows -> rows.map { it.toModel() } }

    override fun observeAlert(alertUid: String): Flow<Alert?> =
        alertDao.observeOne(alertUid).map { it?.toModel() }

    override fun observeTimeline(alertUid: String): Flow<List<AlertEvent>> =
        alertDao.observeTimeline(alertUid).map { rows -> rows.map { it.toModel() } }

    override fun observeUnreadCount(): Flow<Int> = alertDao.observeUnreadCount()

    override fun observeForTicker(ticker: String): Flow<List<Alert>> =
        alertDao.observeForTicker(ticker).map { rows -> rows.map { it.toModel() } }

    override suspend fun refresh(): Result<Unit> = apiCall(dispatcher) {
        val now = System.currentTimeMillis()
        val alerts = api.alerts(limit = 500).alerts.map { it.toModel(now) }
        alertDao.upsert(alerts.map { it.toEntity() })
    }

    override suspend fun refreshTimeline(alertUid: String): Result<Unit> = apiCall(dispatcher) {
        val timeline = api.timeline(alertUid)
        alertDao.upsertEvents(
            timeline.events.map { it.toModel(alertUid).toEntity() }
        )
    }

    override suspend fun markRead(alertUid: String) = withContext(dispatcher) {
        alertDao.markRead(alertUid, System.currentTimeMillis())
    }

    override suspend fun setArchived(alertUid: String, archived: Boolean) = withContext(dispatcher) {
        alertDao.markArchived(alertUid, archived)
    }
}

@Singleton
class ScannerRepositoryImpl @Inject constructor(
    private val api: EquitySignalApi,
    private val scannerDao: ScannerDao,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : ScannerRepository {

    override fun observeResults(): Flow<List<ScannerResult>> =
        scannerDao.observeAll().map { rows -> rows.map { it.toModel() } }

    override fun observeTop(limit: Int): Flow<List<ScannerResult>> =
        scannerDao.observeTop(limit).map { rows -> rows.map { it.toModel() } }

    override suspend fun refresh(filter: ScannerFilter): Result<Unit> = apiCall(dispatcher) {
        val now = System.currentTimeMillis()
        val response = api.scanner(
            minScore = filter.minScore,
            sector = filter.sector,
            category = filter.category,
            minMarketCap = filter.minMarketCap,
            minPrice = filter.minPrice,
            maxPrice = filter.maxPrice,
            minRelVolume = filter.minRelVolume,
            minRiskScore = filter.minRiskScore,
            signalReady = if (filter.signalReadyOnly) true else null,
            regime = filter.regime,
            search = filter.search?.takeIf { it.isNotBlank() },
            sort = filter.sort,
            order = if (filter.ascending) "asc" else "desc",
            limit = 150,
        )
        // A full replacement: a stock that no longer scores must leave the list.
        scannerDao.replaceAll(response.results.map { it.toModel(now).toEntity() })
    }
}

@Singleton
class MarketRepositoryImpl @Inject constructor(
    private val api: EquitySignalApi,
    private val snapshotDao: SnapshotDao,
    private val json: Json,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : MarketRepository {

    override fun observeStatus(): Flow<MarketStatus?> =
        snapshotDao.observe(CachedSnapshotEntity.MARKET_STATUS).map { row ->
            row?.let {
                runCatching {
                    json.decodeFromString(
                        com.equitysignal.core.network.dto.MarketStatusDto.serializer(), it.json
                    ).toModel(it.fetchedAtUtc)
                }.getOrNull()
            }
        }

    override fun observeRegime(): Flow<MarketRegime?> =
        snapshotDao.observe(CachedSnapshotEntity.REGIME).map { row ->
            row?.let {
                runCatching {
                    json.decodeFromString(
                        com.equitysignal.core.network.dto.MarketRegimeDto.serializer(), it.json
                    ).toModel()
                }.getOrNull()
            }
        }

    override suspend fun refresh(): Result<Unit> = apiCall(dispatcher) {
        val now = System.currentTimeMillis()
        val status = api.marketStatus()
        snapshotDao.put(
            CachedSnapshotEntity(
                CachedSnapshotEntity.MARKET_STATUS,
                json.encodeToString(
                    com.equitysignal.core.network.dto.MarketStatusDto.serializer(), status
                ),
                now,
            )
        )
        val regime = api.marketRegime()
        snapshotDao.put(
            CachedSnapshotEntity(
                CachedSnapshotEntity.REGIME,
                json.encodeToString(
                    com.equitysignal.core.network.dto.MarketRegimeDto.serializer(), regime
                ),
                now,
            )
        )
    }

    override suspend fun systemStatus(): Result<SystemStatus> =
        apiCall(dispatcher) { api.systemStatus().toModel() }

    override suspend fun triggerScan(): Result<Unit> = apiCall(dispatcher) { api.triggerScan(); Unit }
}

@Singleton
class PortfolioRepositoryImpl @Inject constructor(
    private val api: EquitySignalApi,
    private val positionDao: PositionDao,
    private val snapshotDao: SnapshotDao,
    private val json: Json,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : PortfolioRepository {

    override fun observePositions(): Flow<List<Position>> =
        positionDao.observeOpen().map { rows -> rows.map { it.toModel() } }

    override fun observePortfolio(): Flow<PortfolioState?> =
        snapshotDao.observe(CachedSnapshotEntity.PORTFOLIO).map { row ->
            row?.let {
                runCatching {
                    json.decodeFromString(
                        com.equitysignal.core.network.dto.PortfolioDto.serializer(), it.json
                    ).toModel()
                }.getOrNull()
            }
        }

    override fun observeAnalytics(): Flow<Analytics?> =
        snapshotDao.observe(CachedSnapshotEntity.ANALYTICS).map { row ->
            row?.let {
                runCatching {
                    json.decodeFromString(
                        com.equitysignal.core.network.dto.AnalyticsDto.serializer(), it.json
                    ).toModel(it.fetchedAtUtc)
                }.getOrNull()
            }
        }

    override suspend fun refresh(): Result<Unit> = apiCall(dispatcher) {
        val now = System.currentTimeMillis()
        val response = api.positions()
        positionDao.replaceAll(response.positions.map { it.toModel().toEntity(now) })
        response.portfolio?.let {
            snapshotDao.put(
                CachedSnapshotEntity(
                    CachedSnapshotEntity.PORTFOLIO,
                    json.encodeToString(
                        com.equitysignal.core.network.dto.PortfolioDto.serializer(), it
                    ),
                    now,
                )
            )
        }
        val analytics = api.analytics()
        snapshotDao.put(
            CachedSnapshotEntity(
                CachedSnapshotEntity.ANALYTICS,
                json.encodeToString(
                    com.equitysignal.core.network.dto.AnalyticsDto.serializer(), analytics
                ),
                now,
            )
        )
    }

    override suspend fun equityCurve(benchmark: String): Result<EquityCurve> =
        apiCall(dispatcher) { api.equityCurve(benchmark).toModel() }

    override suspend fun history(outcome: String): Result<List<Alert>> = apiCall(dispatcher) {
        val now = System.currentTimeMillis()
        api.history(outcome = outcome, limit = 500).alerts.map { it.toModel(now) }
    }
}

@Singleton
class StockRepositoryImpl @Inject constructor(
    private val api: EquitySignalApi,
    private val stockDao: StockDao,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : StockRepository {

    override fun observeStock(ticker: String): Flow<StockDetail?> =
        stockDao.observeOne(ticker).map { it?.toModel() }

    override suspend fun refreshStock(ticker: String): Result<Unit> = apiCall(dispatcher) {
        val detail = api.stock(ticker).toModel()
        stockDao.upsert(listOf(detail.toEntity()))
    }

    override suspend fun chart(ticker: String, limit: Int): Result<StockChart> =
        apiCall(dispatcher) { api.stockBars(ticker, limit).toModel() }

    override suspend fun analysis(ticker: String): Result<StockAnalysis> =
        apiCall(dispatcher) { api.stockAnalysis(ticker).toModel() }
}

@Singleton
class BacktestRepositoryImpl @Inject constructor(
    private val api: EquitySignalApi,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : BacktestRepository {

    override suspend fun runs(): Result<List<BacktestRun>> =
        apiCall(dispatcher) { api.backtests().runs.map { it.toModel() } }

    override suspend fun run(runUid: String): Result<BacktestRun> =
        apiCall(dispatcher) { api.backtest(runUid).toModel() }

    override suspend fun start(
        mode: String,
        startDate: String?,
        endDate: String?,
        initialEquity: Double,
        includeSensitivity: Boolean,
    ): Result<String> = apiCall(dispatcher) {
        api.startBacktest(
            BacktestRequestDto(
                mode = mode,
                startDate = startDate,
                endDate = endDate,
                initialEquity = initialEquity,
                includeSensitivity = includeSensitivity,
            )
        ).runUid
    }
}

@Singleton
class SettingsRepositoryImpl @Inject constructor(
    private val api: EquitySignalApi,
    private val preferences: AppPreferences,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : SettingsRepository {

    override fun observeConnection(): Flow<ConnectionSettings> =
        preferences.settings.map {
            ConnectionSettings(
                baseUrl = it.baseUrl,
                apiKey = it.apiKey,
                notificationsEnabled = it.notificationsEnabled,
                buyNotifications = it.buyNotifications,
                sellNotifications = it.sellNotifications,
                syncIntervalMinutes = it.syncIntervalMinutes,
                darkTheme = it.darkTheme,
                lastSyncAtUtc = it.lastSyncAtUtc,
                isConfigured = it.isConfigured,
            )
        }

    override suspend fun setConnection(baseUrl: String, apiKey: String) =
        preferences.setConnection(baseUrl, apiKey)

    override suspend fun setNotifications(enabled: Boolean, buy: Boolean, sell: Boolean) =
        preferences.setNotifications(enabled, buy, sell)

    override suspend fun setSyncInterval(minutes: Long) = preferences.setSyncInterval(minutes)

    override suspend fun setDarkTheme(dark: Boolean) = preferences.setDarkTheme(dark)

    override suspend fun strategySettings(): Result<StrategySettings> =
        apiCall(dispatcher) { api.settings().toModel() }

    override suspend fun updateStrategySetting(
        key: String,
        value: String,
        createVersion: Boolean,
    ): Result<StrategySettings> = apiCall(dispatcher) {
        // Values arrive from a text field; send the narrowest JSON type that fits so the
        // backend's validation sees a number as a number.
        val element = value.toDoubleOrNull()?.let {
            kotlinx.serialization.json.JsonPrimitive(it)
        } ?: value.toBooleanStrictOrNull()?.let {
            kotlinx.serialization.json.JsonPrimitive(it)
        } ?: kotlinx.serialization.json.JsonPrimitive(value)

        api.updateSettings(
            SettingsUpdateDto(updates = mapOf(key to element), createVersion = createVersion)
        ).toModel()
    }
}
