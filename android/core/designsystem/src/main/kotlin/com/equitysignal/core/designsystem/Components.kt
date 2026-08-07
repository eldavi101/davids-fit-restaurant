package com.equitysignal.core.designsystem

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.ArrowDropUp
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.equitysignal.core.common.Formats
import com.equitysignal.core.common.MarketTime
import com.equitysignal.core.model.AlertStatus
import com.equitysignal.core.model.Freshness
import com.equitysignal.core.model.ScoreCategory

/**
 * Shared financial components.
 *
 * Two rules run through all of them:
 *  - colour is never the only carrier of meaning (returns also carry a sign and a ▲/▼
 *    glyph, chips carry text), so the UI stays readable for colour-blind users;
 *  - numbers use tabular figures so columns align.
 */

fun categoryColor(category: ScoreCategory): Color = when (category) {
    ScoreCategory.EXCEPTIONAL -> FinancialColors.Exceptional
    ScoreCategory.STRONG_BUY -> FinancialColors.StrongBuy
    ScoreCategory.BUY -> FinancialColors.Buy
    ScoreCategory.WATCH -> FinancialColors.Watch
    ScoreCategory.NEUTRAL -> FinancialColors.NeutralChip
    ScoreCategory.AVOID -> FinancialColors.Avoid
    ScoreCategory.UNKNOWN -> FinancialColors.Neutral
}

fun statusColor(status: AlertStatus): Color = when (status) {
    AlertStatus.BUY_SIGNAL -> FinancialColors.StrongBuy
    AlertStatus.ACTIVE -> FinancialColors.Active
    AlertStatus.TARGET_1_HIT, AlertStatus.TARGET_2_HIT -> FinancialColors.Gain
    AlertStatus.TRAILING -> FinancialColors.Trailing
    AlertStatus.STOPPED -> FinancialColors.Stopped
    AlertStatus.SELL_SIGNAL -> FinancialColors.Watch
    AlertStatus.CLOSED -> FinancialColors.Closed
    AlertStatus.INVALIDATED -> FinancialColors.Neutral
    AlertStatus.WATCHING -> FinancialColors.Watch
    AlertStatus.UNKNOWN -> FinancialColors.Neutral
}

fun returnColor(value: Double?): Color = when {
    value == null -> FinancialColors.Neutral
    value > 0 -> FinancialColors.Gain
    value < 0 -> FinancialColors.Loss
    else -> FinancialColors.Neutral
}

@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text.uppercase(),
        style = MaterialTheme.typography.labelSmall,
        color = FinancialColors.OnSurfaceMuted,
        modifier = modifier,
    )
}

/** A return figure: sign, colour and an arrow glyph, so colour is never the only signal. */
@Composable
fun ReturnText(
    value: Double?,
    modifier: Modifier = Modifier,
    style: androidx.compose.ui.text.TextStyle = MaterialTheme.typography.titleMedium,
    showArrow: Boolean = true,
) {
    val color = returnColor(value)
    Row(modifier = modifier, verticalAlignment = Alignment.CenterVertically) {
        if (showArrow && value != null && value != 0.0) {
            Icon(
                imageVector = if (value > 0) Icons.Filled.ArrowDropUp else Icons.Filled.ArrowDropDown,
                contentDescription = if (value > 0) "up" else "down",
                tint = color,
                modifier = Modifier.size(18.dp),
            )
        }
        Text(
            text = Formats.percent(value),
            style = style.merge(NumericTextStyle),
            color = color,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
fun Chip(
    text: String,
    color: Color,
    modifier: Modifier = Modifier,
    filled: Boolean = false,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(6.dp))
            .then(
                if (filled) Modifier.background(color.copy(alpha = 0.18f))
                else Modifier.border(1.dp, color.copy(alpha = 0.55f), RoundedCornerShape(6.dp))
            )
            .padding(horizontal = 8.dp, vertical = 3.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
fun StatusChip(status: AlertStatus, modifier: Modifier = Modifier) {
    Chip(
        text = status.name.replace('_', ' '),
        color = statusColor(status),
        modifier = modifier,
        filled = true,
    )
}

@Composable
fun CategoryChip(category: ScoreCategory, modifier: Modifier = Modifier) {
    Chip(
        text = category.name.replace('_', ' '),
        color = categoryColor(category),
        modifier = modifier,
        filled = true,
    )
}

/** Score out of 100 with a proportional bar; the denominator is always visible. */
@Composable
fun ScoreBadge(score: Double, modifier: Modifier = Modifier, label: String = "Score") {
    val color = when {
        score >= 90 -> FinancialColors.Exceptional
        score >= 85 -> FinancialColors.StrongBuy
        score >= 80 -> FinancialColors.Buy
        score >= 70 -> FinancialColors.Watch
        else -> FinancialColors.NeutralChip
    }
    Column(modifier = modifier.semantics { contentDescription = "$label ${score.toInt()} out of 100" }) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                text = Formats.score(score),
                style = MaterialTheme.typography.headlineSmall.merge(NumericTextStyle),
                color = color,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = "/100",
                style = MaterialTheme.typography.bodySmall,
                color = FinancialColors.OnSurfaceMuted,
                modifier = Modifier.padding(bottom = 2.dp),
            )
        }
        Spacer(Modifier.height(4.dp))
        LinearProgressIndicator(
            progress = { (score / 100.0).toFloat().coerceIn(0f, 1f) },
            modifier = Modifier.fillMaxWidth().height(3.dp).clip(RoundedCornerShape(2.dp)),
            color = color,
            trackColor = FinancialColors.Outline,
        )
    }
}

@Composable
fun StatTile(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    valueColor: Color = FinancialColors.OnSurface,
    caption: String? = null,
) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = FinancialColors.SurfaceElevated),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(Modifier.padding(12.dp)) {
            SectionLabel(label)
            Spacer(Modifier.height(6.dp))
            Text(
                text = value,
                style = MaterialTheme.typography.titleLarge.merge(NumericTextStyle),
                color = valueColor,
            )
            if (caption != null) {
                Text(
                    text = caption,
                    style = MaterialTheme.typography.bodySmall,
                    color = FinancialColors.OnSurfaceMuted,
                )
            }
        }
    }
}

@Composable
fun MetricRow(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    valueColor: Color = FinancialColors.OnSurface,
) {
    Row(
        modifier = modifier.fillMaxWidth().padding(vertical = 5.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = FinancialColors.OnSurfaceMuted)
        Text(
            value,
            style = MaterialTheme.typography.bodyMedium.merge(NumericTextStyle),
            color = valueColor,
            fontWeight = FontWeight.Medium,
        )
    }
}

/**
 * The freshness line every screen carries.
 *
 * Requirement 46: a cached price is never presented as a live one. When data is stale or
 * the device is offline, this says so in words, not only in colour.
 */
@Composable
fun FreshnessLabel(
    freshness: Freshness,
    fetchedAtUtc: Long?,
    modifier: Modifier = Modifier,
) {
    val (text, color) = when (freshness) {
        Freshness.LIVE -> "LIVE" to FinancialColors.Gain
        Freshness.DELAYED -> "DELAYED" to FinancialColors.Watch
        Freshness.CACHED -> "CACHED" to FinancialColors.Neutral
    }
    Row(modifier = modifier, verticalAlignment = Alignment.CenterVertically) {
        if (freshness == Freshness.CACHED) {
            Icon(
                Icons.Filled.CloudOff,
                contentDescription = "showing cached data",
                tint = color,
                modifier = Modifier.size(14.dp),
            )
            Spacer(Modifier.width(4.dp))
        }
        Text(
            text = if (fetchedAtUtc != null) "$text · updated ${MarketTime.relative(fetchedAtUtc)}"
            else "$text · never updated",
            style = MaterialTheme.typography.labelSmall,
            color = color,
        )
    }
}

@Composable
fun LoadingState(modifier: Modifier = Modifier, label: String = "Loading") {
    Box(modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator(color = FinancialColors.Accent)
            Spacer(Modifier.height(12.dp))
            Text(label, style = MaterialTheme.typography.bodySmall, color = FinancialColors.OnSurfaceMuted)
        }
    }
}

@Composable
fun EmptyState(title: String, subtitle: String? = null, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxWidth().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(title, style = MaterialTheme.typography.titleMedium, color = FinancialColors.OnSurface)
        if (subtitle != null) {
            Spacer(Modifier.height(6.dp))
            Text(
                subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = FinancialColors.OnSurfaceMuted,
            )
        }
    }
}

/** An error banner that still lets cached content render beneath it. */
@Composable
fun ErrorBanner(message: String, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
        colors = CardDefaults.cardColors(containerColor = FinancialColors.Loss.copy(alpha = 0.12f)),
        shape = RoundedCornerShape(10.dp),
    ) {
        Text(
            text = message,
            style = MaterialTheme.typography.bodySmall,
            color = FinancialColors.Loss,
            modifier = Modifier.padding(10.dp),
        )
    }
}

/** Prominent banner shown whenever the backend is serving generated data. */
@Composable
fun SyntheticDataBanner(modifier: Modifier = Modifier) {
    Card(
        modifier = modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
        colors = CardDefaults.cardColors(containerColor = FinancialColors.Watch.copy(alpha = 0.14f)),
        shape = RoundedCornerShape(10.dp),
    ) {
        Column(Modifier.padding(10.dp)) {
            Text(
                "SYNTHETIC DATA",
                style = MaterialTheme.typography.labelSmall,
                color = FinancialColors.Watch,
                fontWeight = FontWeight.Bold,
            )
            Text(
                "The backend is running on generated prices, not a live market feed. " +
                    "Nothing on screen is real market data.",
                style = MaterialTheme.typography.bodySmall,
                color = FinancialColors.OnSurface,
            )
        }
    }
}

@Composable
fun FinancialCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = FinancialColors.Surface),
        shape = RoundedCornerShape(14.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, FinancialColors.Outline),
    ) {
        Box(Modifier.padding(14.dp)) { content() }
    }
}

/** The alert lifecycle stepper (requirement 11). */
@Composable
fun LifecycleStepper(current: AlertStatus, modifier: Modifier = Modifier) {
    val path = listOf(
        AlertStatus.BUY_SIGNAL,
        AlertStatus.ACTIVE,
        AlertStatus.TARGET_1_HIT,
        AlertStatus.TRAILING,
        AlertStatus.SELL_SIGNAL,
        AlertStatus.CLOSED,
    )
    // A stopped or invalidated alert leaves the happy path; show where it left instead of
    // pretending it progressed.
    val reachedIndex = when (current) {
        AlertStatus.STOPPED, AlertStatus.INVALIDATED -> path.indexOf(AlertStatus.ACTIVE)
        AlertStatus.TARGET_2_HIT -> path.indexOf(AlertStatus.TARGET_1_HIT)
        else -> path.indexOf(current).takeIf { it >= 0 } ?: 0
    }

    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        path.forEachIndexed { index, step ->
            val reached = index <= reachedIndex
            val color = if (reached) statusColor(current) else FinancialColors.Outline
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier.weight(1f),
            ) {
                Box(
                    Modifier.size(10.dp).clip(RoundedCornerShape(5.dp)).background(color)
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    text = step.name.replace('_', ' ').replace(" SIGNAL", ""),
                    style = MaterialTheme.typography.labelSmall,
                    color = if (reached) FinancialColors.OnSurface else FinancialColors.OnSurfaceMuted,
                )
            }
            if (index < path.lastIndex) {
                Box(
                    Modifier
                        .weight(0.3f)
                        .height(1.dp)
                        .background(if (index < reachedIndex) statusColor(current) else FinancialColors.Outline)
                )
            }
        }
    }
}
