package com.equitysignal.core.database

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

/**
 * An alert joined with its local read/archived state.
 *
 * Room composes this from the two tables at read time, which is what keeps sync (writing
 * alerts) and the user's read state (written locally) from ever clobbering each other.
 */
data class AlertWithReadStatus(
    val alertUid: String,
    val id: Long,
    val ticker: String,
    val companyName: String?,
    val status: String,
    val strategyVersion: String,
    val buyTsUtc: Long,
    val buyPrice: Double,
    val opportunityScore: Double,
    val confidence: Double,
    val probability: Double?,
    val probabilitySampleSize: Int?,
    val expectedValue: Double?,
    val rewardRisk: Double?,
    val marketRegime: String?,
    val sector: String?,
    val industry: String?,
    val breakoutType: String?,
    val stopPrice: Double,
    val currentStopPrice: Double?,
    val trailingStopPrice: Double?,
    val target1Price: Double,
    val target2Price: Double,
    val currentPrice: Double?,
    val currentReturnPct: Double,
    val maxGainPct: Double,
    val maxDrawdownPct: Double,
    val remainingFraction: Double,
    val thesisValid: Boolean,
    val thesisNotes: List<String>,
    val buyReasons: List<String>,
    val riskFactors: List<String>,
    val trendScore: Double,
    val momentumScore: Double,
    val volumeScore: Double,
    val breakoutScore: Double,
    val relativeStrengthScore: Double,
    val fundamentalScore: Double,
    val riskScore: Double,
    val closedTsUtc: Long?,
    val finalReturnPct: Double?,
    val holdingPeriodDays: Int?,
    val sellUid: String?,
    val sellTsUtc: Long?,
    val sellPrice: Double?,
    val sellReason: String?,
    val sellReasonDetail: String?,
    val sellRMultiple: Double?,
    val fetchedAtUtc: Long,
    val isRead: Boolean?,
    val isArchived: Boolean?,
)

private const val ALERT_SELECT = """
    SELECT a.*, r.isRead AS isRead, r.isArchived AS isArchived
    FROM cached_alerts a
    LEFT JOIN alert_read_status r ON r.alertUid = a.alertUid
"""

private const val OPEN_STATUSES =
    "('WATCHING','BUY_SIGNAL','ACTIVE','TARGET_1_HIT','TARGET_2_HIT','TRAILING')"

@Dao
interface AlertDao {

    @Query("$ALERT_SELECT ORDER BY a.buyTsUtc DESC")
    fun observeAll(): Flow<List<AlertWithReadStatus>>

    @Query("$ALERT_SELECT WHERE a.status IN $OPEN_STATUSES ORDER BY a.buyTsUtc DESC")
    fun observeActive(): Flow<List<AlertWithReadStatus>>

    @Query("$ALERT_SELECT WHERE a.status NOT IN $OPEN_STATUSES ORDER BY a.closedTsUtc DESC")
    fun observeClosed(): Flow<List<AlertWithReadStatus>>

    @Query("$ALERT_SELECT WHERE a.sellUid IS NOT NULL ORDER BY a.sellTsUtc DESC")
    fun observeWithSells(): Flow<List<AlertWithReadStatus>>

    @Query("$ALERT_SELECT WHERE a.alertUid = :alertUid LIMIT 1")
    fun observeOne(alertUid: String): Flow<AlertWithReadStatus?>

    @Query("$ALERT_SELECT WHERE a.alertUid = :alertUid LIMIT 1")
    suspend fun getOne(alertUid: String): AlertWithReadStatus?

    @Query("$ALERT_SELECT WHERE a.ticker = :ticker ORDER BY a.buyTsUtc DESC")
    fun observeForTicker(ticker: String): Flow<List<AlertWithReadStatus>>

    /** Badge count: unread and not archived. Drives `Alerts 🔔 3` in the bottom bar. */
    @Query(
        """
        SELECT COUNT(*) FROM cached_alerts a
        LEFT JOIN alert_read_status r ON r.alertUid = a.alertUid
        WHERE COALESCE(r.isRead, 0) = 0 AND COALESCE(r.isArchived, 0) = 0
        """
    )
    fun observeUnreadCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM cached_alerts WHERE status IN $OPEN_STATUSES")
    fun observeActiveCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM cached_alerts WHERE buyTsUtc >= :sinceUtc")
    fun observeBuyCountSince(sinceUtc: Long): Flow<Int>

    @Query("SELECT COUNT(*) FROM cached_alerts WHERE sellTsUtc IS NOT NULL AND sellTsUtc >= :sinceUtc")
    fun observeSellCountSince(sinceUtc: Long): Flow<Int>

    @Query("SELECT alertUid FROM cached_alerts")
    suspend fun knownUids(): List<String>

    /**
     * Sync writes alerts here. `REPLACE` touches only this table, so read and archived
     * state in `alert_read_status` survives untouched.
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(alerts: List<CachedAlertEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertEvents(events: List<CachedAlertEventEntity>)

    @Query("SELECT * FROM cached_alert_events WHERE alertUid = :alertUid ORDER BY tsUtc ASC")
    fun observeTimeline(alertUid: String): Flow<List<CachedAlertEventEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun setReadStatus(status: AlertReadStatusEntity)

    @Query("SELECT * FROM alert_read_status WHERE alertUid = :alertUid LIMIT 1")
    suspend fun readStatus(alertUid: String): AlertReadStatusEntity?

    @Query("SELECT alertUid FROM alert_read_status WHERE notified = 1")
    suspend fun notifiedUids(): List<String>

    @Transaction
    suspend fun markRead(alertUid: String, now: Long) {
        val existing = readStatus(alertUid)
        setReadStatus(
            (existing ?: AlertReadStatusEntity(alertUid)).copy(isRead = true, readAtUtc = now)
        )
    }

    @Transaction
    suspend fun markArchived(alertUid: String, archived: Boolean) {
        val existing = readStatus(alertUid)
        setReadStatus((existing ?: AlertReadStatusEntity(alertUid)).copy(isArchived = archived))
    }

    @Transaction
    suspend fun markNotified(alertUid: String) {
        val existing = readStatus(alertUid)
        setReadStatus((existing ?: AlertReadStatusEntity(alertUid)).copy(notified = true))
    }

    // NOTE: there is deliberately no delete method. Alerts are permanent (requirement 5).
}

@Dao
interface ScannerDao {
    @Query("SELECT * FROM cached_scanner_results ORDER BY opportunityScore DESC")
    fun observeAll(): Flow<List<CachedScannerEntity>>

    @Query("SELECT * FROM cached_scanner_results ORDER BY opportunityScore DESC LIMIT :limit")
    fun observeTop(limit: Int): Flow<List<CachedScannerEntity>>

    @Query("SELECT COUNT(*) FROM cached_scanner_results")
    fun observeCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM cached_scanner_results WHERE opportunityScore >= :threshold")
    fun observeStrongCount(threshold: Double): Flow<Int>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(rows: List<CachedScannerEntity>)

    /**
     * A scanner refresh is a full replacement: a stock that no longer scores must not
     * linger in the list. Wrapped in a transaction so the UI never observes an empty feed.
     */
    @Query("DELETE FROM cached_scanner_results")
    suspend fun clear()

    @Transaction
    suspend fun replaceAll(rows: List<CachedScannerEntity>) {
        clear()
        upsert(rows)
    }
}

@Dao
interface PositionDao {
    @Query("SELECT * FROM cached_positions WHERE status = 'OPEN' ORDER BY openedTsUtc DESC")
    fun observeOpen(): Flow<List<CachedPositionEntity>>

    @Query("SELECT * FROM cached_positions ORDER BY openedTsUtc DESC")
    fun observeAll(): Flow<List<CachedPositionEntity>>

    @Query("SELECT COUNT(*) FROM cached_positions WHERE status = 'OPEN'")
    fun observeOpenCount(): Flow<Int>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(rows: List<CachedPositionEntity>)

    @Query("DELETE FROM cached_positions")
    suspend fun clear()

    @Transaction
    suspend fun replaceAll(rows: List<CachedPositionEntity>) {
        clear()
        upsert(rows)
    }
}

@Dao
interface StockDao {
    @Query("SELECT * FROM cached_stocks WHERE ticker = :ticker LIMIT 1")
    fun observeOne(ticker: String): Flow<CachedStockEntity?>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(stocks: List<CachedStockEntity>)
}

@Dao
interface SnapshotDao {
    @Query("SELECT * FROM cached_snapshots WHERE `key` = :key LIMIT 1")
    fun observe(key: String): Flow<CachedSnapshotEntity?>

    @Query("SELECT * FROM cached_snapshots WHERE `key` = :key LIMIT 1")
    suspend fun get(key: String): CachedSnapshotEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(snapshot: CachedSnapshotEntity)
}

@Dao
interface UserSettingDao {
    @Query("SELECT * FROM user_settings")
    fun observeAll(): Flow<List<UserSettingEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(setting: UserSettingEntity)
}
