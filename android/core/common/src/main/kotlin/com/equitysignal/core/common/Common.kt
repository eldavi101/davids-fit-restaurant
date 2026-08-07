package com.equitysignal.core.common

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import javax.inject.Qualifier
import kotlin.math.abs
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers

/** A loaded value, a failure, or work in progress — with cached data preserved on failure. */
sealed interface Resource<out T> {
    data class Loading<T>(val cached: T? = null) : Resource<T>
    data class Success<T>(val data: T) : Resource<T>

    /**
     * A failure that still carries whatever was cached.
     *
     * This shape is deliberate: an offline screen shows the last good data, labelled as
     * cached, rather than an empty error page (requirement 46).
     */
    data class Error<T>(val message: String, val cached: T? = null, val cause: Throwable? = null) :
        Resource<T>
}

@Qualifier @Retention(AnnotationRetention.BINARY) annotation class IoDispatcher
@Qualifier @Retention(AnnotationRetention.BINARY) annotation class DefaultDispatcher

interface AppDispatchers {
    val io: CoroutineDispatcher
    val default: CoroutineDispatcher
    val main: CoroutineDispatcher
}

object RealDispatchers : AppDispatchers {
    override val io: CoroutineDispatcher = Dispatchers.IO
    override val default: CoroutineDispatcher = Dispatchers.Default
    override val main: CoroutineDispatcher = Dispatchers.Main
}

/**
 * Time formatting.
 *
 * Everything inside the app is epoch-millis UTC; every user-facing string is rendered in
 * America/New_York, because that is the market's clock and a trader reading "10:32" needs
 * it to mean 10:32 in New York regardless of where they are (requirement 61.18).
 */
object MarketTime {
    val ZONE: ZoneId = ZoneId.of("America/New_York")

    private val timeFormat = DateTimeFormatter.ofPattern("h:mm a", Locale.US)
    private val dateFormat = DateTimeFormatter.ofPattern("MMM d, yyyy", Locale.US)
    private val shortDateFormat = DateTimeFormatter.ofPattern("MMM d", Locale.US)
    private val dateTimeFormat = DateTimeFormatter.ofPattern("MMM d, h:mm a", Locale.US)

    fun time(epochMillis: Long): String = format(epochMillis, timeFormat)
    fun date(epochMillis: Long): String = format(epochMillis, dateFormat)
    fun shortDate(epochMillis: Long): String = format(epochMillis, shortDateFormat)
    fun dateTime(epochMillis: Long): String = format(epochMillis, dateTimeFormat)

    /** "Aug 7, 10:32 AM ET" — the label used wherever a timestamp is shown outright. */
    fun stamp(epochMillis: Long): String = "${dateTime(epochMillis)} ET"

    private fun format(epochMillis: Long, formatter: DateTimeFormatter): String =
        formatter.format(Instant.ofEpochMilli(epochMillis).atZone(ZONE))

    fun relative(epochMillis: Long, now: Long = System.currentTimeMillis()): String {
        val seconds = (now - epochMillis) / 1000
        return when {
            seconds < 0 -> "just now"
            seconds < 60 -> "${seconds}s ago"
            seconds < 3_600 -> "${seconds / 60}m ago"
            seconds < 86_400 -> "${seconds / 3_600}h ago"
            seconds < 604_800 -> "${seconds / 86_400}d ago"
            else -> shortDate(epochMillis)
        }
    }

    fun isToday(epochMillis: Long, now: Long = System.currentTimeMillis()): Boolean =
        Instant.ofEpochMilli(epochMillis).atZone(ZONE).toLocalDate() ==
            Instant.ofEpochMilli(now).atZone(ZONE).toLocalDate()

    /** Parse an ISO-8601 UTC timestamp from the API. Returns null rather than throwing. */
    fun parseIso(value: String?): Long? =
        value?.let { runCatching { Instant.parse(it).toEpochMilli() }.getOrNull() }
}

/**
 * How stale cached data is allowed to look before the UI stops implying it is live.
 * See docs/ANDROID_ARCHITECTURE.md §3.
 */
object FreshnessPolicy {
    const val LIVE_WINDOW_MS = 60_000L
    const val DELAYED_WINDOW_MS = 15 * 60_000L

    fun classify(
        fetchedAtUtc: Long?,
        online: Boolean = true,
        now: Long = System.currentTimeMillis(),
    ): com.equitysignal.core.model.Freshness {
        if (fetchedAtUtc == null || !online) return com.equitysignal.core.model.Freshness.CACHED
        val age = now - fetchedAtUtc
        return when {
            age <= LIVE_WINDOW_MS -> com.equitysignal.core.model.Freshness.LIVE
            age <= DELAYED_WINDOW_MS -> com.equitysignal.core.model.Freshness.DELAYED
            else -> com.equitysignal.core.model.Freshness.CACHED
        }
    }
}

/** Number formatting for a financial UI: explicit signs, sane magnitudes, no surprises. */
object Formats {
    fun money(value: Double?, decimals: Int = 2): String =
        value?.let { "$" + String.format(Locale.US, "%,.${decimals}f", it) } ?: "—"

    fun signedMoney(value: Double?): String {
        if (value == null) return "—"
        val sign = if (value >= 0) "+" else "-"
        return sign + "$" + String.format(Locale.US, "%,.2f", abs(value))
    }

    /** Returns always carry an explicit sign, so a gain is never mistaken for a loss. */
    fun percent(value: Double?, decimals: Int = 2, signed: Boolean = true): String {
        if (value == null) return "—"
        val sign = if (signed && value >= 0) "+" else ""
        return sign + String.format(Locale.US, "%.${decimals}f", value) + "%"
    }

    fun ratio(value: Double?, decimals: Int = 2): String =
        value?.let { String.format(Locale.US, "%.${decimals}f", it) } ?: "—"

    fun score(value: Double?): String =
        value?.let { String.format(Locale.US, "%.0f", it) } ?: "—"

    fun probability(value: Double?, sampleSize: Int?): String {
        if (value == null) return "—"
        val percent = String.format(Locale.US, "%.0f%%", value * 100)
        // The sample size travels with every probability. A 62% drawn from 11 observations
        // is not a 62% probability, and the UI must not let it look like one.
        return when {
            sampleSize == null -> percent
            sampleSize == 0 -> "$percent (prior only)"
            else -> "$percent (n=$sampleSize)"
        }
    }

    fun compactNumber(value: Double?): String {
        if (value == null) return "—"
        val abs = abs(value)
        return when {
            abs >= 1e12 -> String.format(Locale.US, "%.2fT", value / 1e12)
            abs >= 1e9 -> String.format(Locale.US, "%.2fB", value / 1e9)
            abs >= 1e6 -> String.format(Locale.US, "%.1fM", value / 1e6)
            abs >= 1e3 -> String.format(Locale.US, "%.1fK", value / 1e3)
            else -> String.format(Locale.US, "%.0f", value)
        }
    }

    fun shares(value: Double?): String =
        value?.let { String.format(Locale.US, "%,.0f", it) } ?: "—"

    fun multiple(value: Double?): String =
        value?.let { String.format(Locale.US, "%.2f×", it) } ?: "—"
}

/** Navigation routes. Shared here so features can link to each other without depending on each other. */
object Routes {
    const val HOME = "home"
    const val SCANNER = "scanner"
    const val ALERTS = "alerts"
    const val POSITIONS = "positions"
    const val ANALYTICS = "analytics"

    const val HISTORY = "history"
    const val BACKTESTING = "backtesting"
    const val STRATEGY_LAB = "strategy_lab"
    const val SETTINGS = "settings"
    const val SYSTEM_STATUS = "system_status"

    const val ALERT_DETAIL = "alert_detail/{alertUid}"
    const val STOCK_DETAIL = "stock_detail/{ticker}"
    const val BACKTEST_DETAIL = "backtest_detail/{runUid}"

    fun alertDetail(alertUid: String) = "alert_detail/$alertUid"
    fun stockDetail(ticker: String) = "stock_detail/$ticker"
    fun backtestDetail(runUid: String) = "backtest_detail/$runUid"

    /** Deep link target for a local notification. Always points at a stored alert. */
    const val DEEP_LINK_SCHEME = "equitysignal"
    const val ALERT_DEEP_LINK = "$DEEP_LINK_SCHEME://alert/{alertUid}"

    fun alertDeepLink(alertUid: String) = "$DEEP_LINK_SCHEME://alert/$alertUid"
}
