package com.equitysignal.core.notifications

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationChannelGroup
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.equitysignal.core.common.Formats
import com.equitysignal.core.common.Routes
import com.equitysignal.core.model.Alert
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Local Android notifications (requirement 6).
 *
 * These are **pointers**, never the alert itself. A notification is only ever posted for
 * an alert that is already stored in the app's database, and tapping it deep-links to that
 * exact alert. Nothing is sent anywhere: no email, no messaging service, no webhook. If
 * the user denies the notification permission the app is fully functional — the Alert
 * Center is the primary mechanism and this is a convenience on top of it.
 */
object NotificationChannels {
    const val GROUP_SIGNALS = "signals"
    const val BUY = "buy_signals"
    const val SELL = "sell_signals"
    const val POSITION = "position_updates"
    const val SYSTEM = "system"
}

@Singleton
class AlertNotifier @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val manager = NotificationManagerCompat.from(context)

    fun ensureChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        manager.createNotificationChannelGroup(
            NotificationChannelGroup(NotificationChannels.GROUP_SIGNALS, "Signals")
        )

        val channels = listOf(
            channel(NotificationChannels.BUY, "BUY signals", NotificationManager.IMPORTANCE_HIGH,
                "A new BUY alert was created and saved in the app."),
            channel(NotificationChannels.SELL, "SELL signals", NotificationManager.IMPORTANCE_HIGH,
                "A tracked position produced a SELL alert."),
            channel(NotificationChannels.POSITION, "Position updates",
                NotificationManager.IMPORTANCE_DEFAULT,
                "Targets reached, trailing stop moves and thesis warnings."),
            channel(NotificationChannels.SYSTEM, "Sync and system",
                NotificationManager.IMPORTANCE_LOW, "Background synchronisation status."),
        )
        channels.forEach { manager.createNotificationChannel(it) }
    }

    private fun channel(id: String, name: String, importance: Int, description: String) =
        NotificationChannel(id, name, importance).apply {
            this.description = description
            group = NotificationChannels.GROUP_SIGNALS
        }

    fun canPost(): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
                PackageManager.PERMISSION_GRANTED
        } else {
            manager.areNotificationsEnabled()
        }

    /**
     * 🚨 BUY SIGNAL · NVDA
     * Entry $184.32 · Score 91/100 · R/R 2.25
     */
    fun notifyBuy(alert: Alert) {
        post(
            channelId = NotificationChannels.BUY,
            id = notificationId(alert.alertUid),
            title = "🚨 BUY SIGNAL · ${alert.ticker}",
            text = buildString {
                append("Entry ${Formats.money(alert.buyPrice)}")
                append(" · Score ${Formats.score(alert.opportunityScore)}/100")
                alert.rewardRisk?.let { append(" · R/R ${Formats.ratio(it)}") }
            },
            big = buildString {
                append("Entry ${Formats.money(alert.buyPrice)}  ")
                append("Stop ${Formats.money(alert.stopPrice)}  ")
                append("Target ${Formats.money(alert.target1Price)}\n")
                alert.buyReasons.take(3).forEach { append("✓ $it\n") }
                append("\nTap to view the full analysis.")
            },
            alertUid = alert.alertUid,
        )
    }

    /**
     * 🔔 SELL SIGNAL · NVDA
     * Entry $184.32 → Exit $198.70 · +7.80%
     */
    fun notifySell(alert: Alert) {
        val sell = alert.sell ?: return
        post(
            channelId = NotificationChannels.SELL,
            id = notificationId(alert.alertUid + ":sell"),
            title = "🔔 SELL SIGNAL · ${alert.ticker}",
            text = "Entry ${Formats.money(sell.entryPrice)} → Exit ${Formats.money(sell.sellPrice)}" +
                " · ${Formats.percent(sell.finalReturnPct)}",
            big = buildString {
                append("Entry ${Formats.money(sell.entryPrice)}\n")
                append("Exit ${Formats.money(sell.sellPrice)}\n")
                append("Return ${Formats.percent(sell.finalReturnPct)} over ")
                append("${sell.holdingPeriodDays} day(s)\n\n")
                append("Reason: ${sell.exitReasonDetail ?: sell.exitReason.replace('_', ' ')}")
            },
            alertUid = alert.alertUid,
        )
    }

    private fun post(
        channelId: String,
        id: Int,
        title: String,
        text: String,
        big: String,
        alertUid: String,
    ) {
        if (!canPost()) return

        // The deep link is the whole point: tapping opens this exact alert, not a list.
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(Routes.alertDeepLink(alertUid))).apply {
            `package` = context.packageName
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            context,
            id,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(big))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .build()

        runCatching { manager.notify(id, notification) }
    }

    /** Stable per-alert id so a re-sync updates rather than stacks duplicates. */
    private fun notificationId(key: String): Int = key.hashCode() and 0x7FFFFFFF
}
