package com.equitysignal.data

import com.equitysignal.core.common.IoDispatcher
import com.equitysignal.core.common.MarketTime
import com.equitysignal.core.database.AlertDao
import com.equitysignal.core.database.CachedSnapshotEntity
import com.equitysignal.core.database.PositionDao
import com.equitysignal.core.database.ScannerDao
import com.equitysignal.core.database.SnapshotDao
import com.equitysignal.core.datastore.AppPreferences
import com.equitysignal.core.model.AlertStatus
import com.equitysignal.core.model.DashboardSummary
import com.equitysignal.core.notifications.AlertNotifier
import com.equitysignal.core.network.EquitySignalApi
import com.equitysignal.core.network.toModel
import com.equitysignal.domain.MarketRepository
import com.equitysignal.domain.PortfolioRepository
import com.equitysignal.domain.SyncOutcome
import com.equitysignal.domain.SyncRepository
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json

/**
 * Delta synchronisation and the dashboard aggregate.
 *
 * One `GET /sync?since=` round trip fetches everything the app caches, which keeps the
 * background worker cheap. Notifications are posted here — and only here — for alerts the
 * device has not seen before, so a notification can never exist without its stored alert
 * (ALERT_LIFECYCLE.md §7).
 */
@Singleton
class SyncRepositoryImpl @Inject constructor(
    private val api: EquitySignalApi,
    private val alertDao: AlertDao,
    private val scannerDao: ScannerDao,
    private val positionDao: PositionDao,
    private val snapshotDao: SnapshotDao,
    private val preferences: AppPreferences,
    private val notifier: AlertNotifier,
    private val json: Json,
    @IoDispatcher private val dispatcher: CoroutineDispatcher,
) : SyncRepository {

    override suspend fun sync(): SyncOutcome = withContext(dispatcher) {
        val settings = preferences.current()
        if (!settings.isConfigured) return@withContext SyncOutcome.NotConfigured

        try {
            val now = System.currentTimeMillis()
            val response = api.sync(since = settings.lastSyncCursor)

            // Which alerts are new to *this device*? Compute before writing, because after
            // the upsert every uid looks familiar.
            val knownUids = alertDao.knownUids().toSet()
            val alreadyNotified = alertDao.notifiedUids().toSet()

            val alerts = response.alerts.map { it.toModel(now) }
            alertDao.upsert(alerts.map { it.toEntity() })

            response.scanner.takeIf { it.isNotEmpty() }?.let { rows ->
                scannerDao.replaceAll(rows.map { it.toModel(now).toEntity() })
            }
            response.positions.let { rows ->
                positionDao.replaceAll(rows.map { it.toModel().toEntity(now) })
            }

            response.marketStatus?.let {
                snapshotDao.put(
                    CachedSnapshotEntity(
                        CachedSnapshotEntity.MARKET_STATUS,
                        json.encodeToString(
                            com.equitysignal.core.network.dto.MarketStatusDto.serializer(), it
                        ),
                        now,
                    )
                )
            }
            response.regime?.let {
                snapshotDao.put(
                    CachedSnapshotEntity(
                        CachedSnapshotEntity.REGIME,
                        json.encodeToString(
                            com.equitysignal.core.network.dto.MarketRegimeDto.serializer(), it
                        ),
                        now,
                    )
                )
            }
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
            response.analytics?.let {
                snapshotDao.put(
                    CachedSnapshotEntity(
                        CachedSnapshotEntity.ANALYTICS,
                        json.encodeToString(
                            com.equitysignal.core.network.dto.AnalyticsDto.serializer(), it
                        ),
                        now,
                    )
                )
            }

            var newBuys = 0
            var newSells = 0
            if (settings.notificationsEnabled) {
                notifier.ensureChannels()
                for (alert in alerts) {
                    val isNewToDevice = alert.alertUid !in knownUids
                    val notifiedAlready = alert.alertUid in alreadyNotified

                    if (isNewToDevice && !notifiedAlready && settings.buyNotifications &&
                        alert.status != AlertStatus.CLOSED
                    ) {
                        notifier.notifyBuy(alert)
                        alertDao.markNotified(alert.alertUid)
                        newBuys++
                    }

                    // A SELL is notified once, when the alert first appears closed here.
                    val sell = alert.sell
                    if (sell != null && settings.sellNotifications) {
                        val sellKey = alert.alertUid + ":sell"
                        if (sellKey !in alreadyNotified) {
                            notifier.notifySell(alert)
                            alertDao.markNotified(sellKey)
                            newSells++
                        }
                    }
                }
            }

            preferences.setSyncCursor(response.nextSince, now)
            SyncOutcome.Success(newAlerts = newBuys, newSells = newSells, syncedAtUtc = now)
        } catch (error: Throwable) {
            SyncOutcome.Failure(error.message ?: "Sync failed", error)
        }
    }

    override fun observeDashboard(): Flow<DashboardSummary> {
        val startOfDay = startOfMarketDayUtc()
        return combine(
            snapshotDao.observe(CachedSnapshotEntity.MARKET_STATUS),
            snapshotDao.observe(CachedSnapshotEntity.REGIME),
            snapshotDao.observe(CachedSnapshotEntity.ANALYTICS),
            scannerDao.observeTop(5),
            alertDao.observeAll(),
        ) { statusRow, regimeRow, analyticsRow, topRows, alertRows ->
            val status = statusRow?.let {
                runCatching {
                    json.decodeFromString(
                        com.equitysignal.core.network.dto.MarketStatusDto.serializer(), it.json
                    ).toModel(it.fetchedAtUtc)
                }.getOrNull()
            }
            val regime = regimeRow?.let {
                runCatching {
                    json.decodeFromString(
                        com.equitysignal.core.network.dto.MarketRegimeDto.serializer(), it.json
                    ).toModel()
                }.getOrNull()
            }
            val analytics = analyticsRow?.let {
                runCatching {
                    json.decodeFromString(
                        com.equitysignal.core.network.dto.AnalyticsDto.serializer(), it.json
                    ).toModel(it.fetchedAtUtc)
                }.getOrNull()
            }

            val alerts = alertRows.map { it.toModel() }
            val top = topRows.map { it.toModel() }

            DashboardSummary(
                marketStatus = status,
                regime = regime,
                stocksScanned = top.size.coerceAtLeast(0),
                strongOpportunities = top.count { it.opportunityScore >= 80.0 },
                buyAlertsToday = alerts.count { it.buyTsUtc >= startOfDay },
                sellAlertsToday = alerts.count { (it.sell?.sellTsUtc ?: 0L) >= startOfDay },
                activeAlerts = alerts.count { it.isOpen },
                openPositions = analytics?.portfolio?.openPositions ?: 0,
                strategyReturnPct = analytics?.avgReturnPct,
                winRate = analytics?.winRate,
                profitFactor = analytics?.profitFactor,
                currentDrawdownPct = analytics?.portfolio?.drawdownPct ?: analytics?.maxDrawdownPct,
                topOpportunities = top,
                recentAlerts = alerts.take(5),
                lastUpdatedUtc = listOfNotNull(
                    status?.fetchedAtUtc,
                    analytics?.fetchedAtUtc,
                    alerts.maxOfOrNull { it.fetchedAtUtc },
                ).maxOrNull(),
            )
        }
    }

    /** "Today" means the current market day in New York, not the device's local day. */
    private fun startOfMarketDayUtc(): Long =
        LocalDate.now(MarketTime.ZONE)
            .atStartOfDay(MarketTime.ZONE)
            .toInstant()
            .toEpochMilli()
}
