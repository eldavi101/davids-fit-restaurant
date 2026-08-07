package com.equitysignal.core.database

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey
import androidx.room.TypeConverter

/**
 * Room cache entities.
 *
 * Room is a cache with provenance, not a source of truth: every table carries
 * `fetchedAtUtc` so the UI can label data live / delayed / cached and never present a
 * stale price as a live one (requirement 46).
 *
 * `AlertReadStatusEntity` is deliberately a *separate* table from `CachedAlertEntity`.
 * Sync replaces alert rows wholesale; keeping read and archived flags in their own table
 * means a refresh can never silently mark a user's alerts unread again.
 */

@Entity(tableName = "cached_alerts", indices = [Index("status"), Index("ticker")])
data class CachedAlertEntity(
    @PrimaryKey val alertUid: String,
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
    // Flattened SELL fields — a closed alert is one card, not two.
    val sellUid: String?,
    val sellTsUtc: Long?,
    val sellPrice: Double?,
    val sellReason: String?,
    val sellReasonDetail: String?,
    val sellRMultiple: Double?,
    val fetchedAtUtc: Long,
)

@Entity(
    tableName = "cached_alert_events",
    primaryKeys = ["alertUid", "tsUtc", "eventType"],
    indices = [Index("alertUid")],
)
data class CachedAlertEventEntity(
    val alertUid: String,
    val tsUtc: Long,
    val eventType: String,
    val price: Double?,
    val title: String,
    val detail: String?,
)

/** Local-only UI state. Never overwritten by sync, never deleted. */
@Entity(tableName = "alert_read_status")
data class AlertReadStatusEntity(
    @PrimaryKey val alertUid: String,
    val isRead: Boolean = false,
    val isArchived: Boolean = false,
    val readAtUtc: Long? = null,
    /** Set once a local notification has been posted, so a re-sync cannot double-notify. */
    val notified: Boolean = false,
)

@Entity(tableName = "cached_scanner_results")
data class CachedScannerEntity(
    @PrimaryKey val ticker: String,
    val rank: Int,
    val companyName: String?,
    val price: Double?,
    val opportunityScore: Double,
    val confidence: Double,
    val category: String,
    val trendScore: Double,
    val momentumScore: Double,
    val volumeScore: Double,
    val breakoutScore: Double,
    val relativeStrengthScore: Double,
    val fundamentalScore: Double,
    val riskScore: Double,
    val regimeScore: Double,
    val relVolume: Double?,
    val rs21: Double?,
    val atrPct: Double?,
    val suggestedEntry: Double?,
    val stopPrice: Double?,
    val target1Price: Double?,
    val target2Price: Double?,
    val rewardRisk: Double?,
    val probability: Double?,
    val probabilitySampleSize: Int?,
    val expectedValue: Double?,
    val signalReady: Boolean,
    val rulesFailed: List<String>,
    val sector: String?,
    val marketCap: Double?,
    val marketRegime: String?,
    val fetchedAtUtc: Long,
)

@Entity(tableName = "cached_positions")
data class CachedPositionEntity(
    @PrimaryKey val id: Long,
    val alertId: Long?,
    val ticker: String,
    val openedTsUtc: Long,
    val entryPrice: Double,
    val currentPrice: Double,
    val shares: Double,
    val costBasis: Double,
    val marketValue: Double,
    val unrealizedPnl: Double,
    val realizedPnl: Double,
    val returnPct: Double,
    val stopPrice: Double?,
    val target1Price: Double?,
    val target2Price: Double?,
    val riskAmount: Double?,
    val riskPctOfEquity: Double?,
    val sector: String?,
    val status: String,
    val fetchedAtUtc: Long,
)

@Entity(tableName = "cached_stocks")
data class CachedStockEntity(
    @PrimaryKey val ticker: String,
    val companyName: String?,
    val exchange: String?,
    val sector: String?,
    val industry: String?,
    val marketCap: Double?,
    val lastPrice: Double?,
    val eligible: Boolean,
    val ineligibleReason: String?,
    val fetchedAtUtc: Long,
)

/**
 * Singleton rows for payloads the UI treats as one object.
 * `key` is a fixed constant so an upsert always replaces the single row.
 */
@Entity(tableName = "cached_snapshots")
data class CachedSnapshotEntity(
    @PrimaryKey val key: String,
    val json: String,
    val fetchedAtUtc: Long,
) {
    companion object {
        const val MARKET_STATUS = "market_status"
        const val REGIME = "regime"
        const val ANALYTICS = "analytics"
        const val PORTFOLIO = "portfolio"
        const val SYNC_CURSOR = "sync_cursor"
    }
}

@Entity(tableName = "user_settings")
data class UserSettingEntity(
    @PrimaryKey val key: String,
    val value: String,
    val updatedAtUtc: Long,
)

/** Room stores string lists as a delimited blob; the delimiter cannot occur in the data. */
class Converters {
    @TypeConverter
    fun fromStringList(value: List<String>?): String = value?.joinToString(DELIMITER).orEmpty()

    @TypeConverter
    fun toStringList(value: String?): List<String> =
        if (value.isNullOrEmpty()) emptyList() else value.split(DELIMITER)

    private companion object {
        // A control character, so a reason string containing commas or pipes survives.
        const val DELIMITER = ""
    }
}
