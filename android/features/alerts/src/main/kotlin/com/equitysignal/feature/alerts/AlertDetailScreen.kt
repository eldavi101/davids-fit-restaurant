package com.equitysignal.feature.alerts

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.equitysignal.core.common.Formats
import com.equitysignal.core.common.MarketTime
import com.equitysignal.core.designsystem.Chip
import com.equitysignal.core.designsystem.EmptyState
import com.equitysignal.core.designsystem.FinancialCard
import com.equitysignal.core.designsystem.FinancialColors
import com.equitysignal.core.designsystem.LifecycleStepper
import com.equitysignal.core.designsystem.LoadingState
import com.equitysignal.core.designsystem.MetricRow
import com.equitysignal.core.designsystem.NumericTextStyle
import com.equitysignal.core.designsystem.ReturnText
import com.equitysignal.core.designsystem.SectionLabel
import com.equitysignal.core.designsystem.StatusChip
import com.equitysignal.core.designsystem.returnColor
import com.equitysignal.core.model.Alert
import com.equitysignal.core.model.AlertEvent

/**
 * Alert detail (requirement 12).
 *
 * Answers, in order: what is this, how is it doing, **why did we buy it**, is the thesis
 * still intact, where are the exits, and what has happened since.
 */
@Composable
fun AlertDetailScreen(
    alertUid: String,
    onStockClick: (String) -> Unit,
    onBack: () -> Unit,
    viewModel: AlertDetailViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    when (val current = state) {
        AlertDetailUiState.Loading -> LoadingState(label = "Loading alert")
        is AlertDetailUiState.Missing -> EmptyState(
            title = "Alert not available",
            subtitle = "It has not synchronised to this device yet. Pull to refresh on the " +
                "Alerts screen once you are online.",
        )
        is AlertDetailUiState.Ready -> LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item { HeaderSection(current.alert, onStockClick) }
            item { LifecycleSection(current.alert) }
            item { PriceSection(current.alert) }
            item { WhyWeBoughtSection(current.alert) }
            item { ThesisSection(current.alert) }
            item { LevelsSection(current.alert) }
            item { ProbabilitySection(current.alert) }
            if (current.alert.sell != null) item { ExitSection(current.alert) }
            item { SectionLabel("Timeline", Modifier.padding(top = 8.dp)) }
            items(current.timeline, key = { "${it.tsUtc}-${it.type}" }) { TimelineRow(it) }
            item {
                TextButton(onClick = onBack, modifier = Modifier.fillMaxWidth()) {
                    Text("Back to alerts")
                }
            }
        }
    }
}

@Composable
private fun HeaderSection(alert: Alert, onStockClick: (String) -> Unit) {
    FinancialCard {
        Column {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Text(
                        alert.ticker,
                        style = MaterialTheme.typography.headlineMedium,
                        color = FinancialColors.OnSurface,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        alert.companyName.orEmpty(),
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                }
                StatusChip(alert.status)
            }
            Spacer(Modifier.height(8.dp))
            Row {
                alert.sector?.let { Chip(it, FinancialColors.Neutral); Spacer(Modifier.width(6.dp)) }
                alert.marketRegime?.let { Chip(it.replace('_', ' '), FinancialColors.Accent) }
            }
            Spacer(Modifier.height(8.dp))
            Text(
                "Signalled ${MarketTime.stamp(alert.buyTsUtc)} · ${alert.strategyVersion}",
                style = MaterialTheme.typography.labelSmall,
                color = FinancialColors.OnSurfaceMuted,
            )
            Spacer(Modifier.height(8.dp))
            Button(onClick = { onStockClick(alert.ticker) }, modifier = Modifier.fillMaxWidth()) {
                Text("View chart and analysis")
            }
        }
    }
}

@Composable
private fun LifecycleSection(alert: Alert) {
    FinancialCard {
        Column {
            SectionLabel("Lifecycle")
            Spacer(Modifier.height(10.dp))
            LifecycleStepper(alert.status)
        }
    }
}

@Composable
private fun PriceSection(alert: Alert) {
    FinancialCard {
        Column {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column {
                    SectionLabel("Entry")
                    Text(
                        Formats.money(alert.buyPrice),
                        style = MaterialTheme.typography.headlineSmall.merge(NumericTextStyle),
                        color = FinancialColors.OnSurface,
                    )
                }
                Column {
                    SectionLabel(if (alert.isClosed) "Exit" else "Current")
                    Text(
                        Formats.money(alert.sell?.sellPrice ?: alert.currentPrice),
                        style = MaterialTheme.typography.headlineSmall.merge(NumericTextStyle),
                        color = FinancialColors.OnSurface,
                    )
                }
                Column(horizontalAlignment = Alignment.End) {
                    SectionLabel(if (alert.isClosed) "Final return" else "Return")
                    ReturnText(alert.displayReturnPct, style = MaterialTheme.typography.headlineSmall)
                }
            }
            Spacer(Modifier.height(12.dp))
            MetricRow("Maximum gain", Formats.percent(alert.maxGainPct), returnColor(alert.maxGainPct))
            MetricRow(
                "Maximum drawdown",
                Formats.percent(alert.maxDrawdownPct),
                returnColor(alert.maxDrawdownPct),
            )
            MetricRow("Opportunity score", "${Formats.score(alert.opportunityScore)}/100")
            MetricRow("Confidence", "${Formats.score(alert.confidence)}/100")
            if (alert.remainingFraction < 1.0 && !alert.isClosed) {
                MetricRow("Position remaining", "${(alert.remainingFraction * 100).toInt()}%")
            }
        }
    }
}

/** Requirement 60.14: exactly why this stock was selected. */
@Composable
private fun WhyWeBoughtSection(alert: Alert) {
    FinancialCard {
        Column {
            SectionLabel("Why we bought")
            Spacer(Modifier.height(8.dp))
            if (alert.buyReasons.isEmpty()) {
                Text(
                    "No reasons recorded for this alert.",
                    style = MaterialTheme.typography.bodySmall,
                    color = FinancialColors.OnSurfaceMuted,
                )
            } else {
                alert.buyReasons.forEach { reason ->
                    Row(Modifier.padding(vertical = 3.dp)) {
                        Text("✓ ", color = FinancialColors.Gain)
                        Text(
                            reason,
                            style = MaterialTheme.typography.bodyMedium,
                            color = FinancialColors.OnSurface,
                        )
                    }
                }
            }

            if (alert.riskFactors.isNotEmpty()) {
                Spacer(Modifier.height(12.dp))
                SectionLabel("Risk factors")
                Spacer(Modifier.height(6.dp))
                alert.riskFactors.forEach { risk ->
                    Row(Modifier.padding(vertical = 3.dp)) {
                        Text("⚠ ", color = FinancialColors.Watch)
                        Text(
                            risk,
                            style = MaterialTheme.typography.bodyMedium,
                            color = FinancialColors.OnSurfaceMuted,
                        )
                    }
                }
            }

            Spacer(Modifier.height(12.dp))
            SectionLabel("Component scores at entry")
            Spacer(Modifier.height(4.dp))
            alert.componentScores.asPairs().forEach { (name, value) ->
                MetricRow(name, Formats.score(value))
            }
        }
    }
}

@Composable
private fun ThesisSection(alert: Alert) {
    val healthy = alert.thesisValid
    FinancialCard {
        Column {
            SectionLabel("Current thesis")
            Spacer(Modifier.height(6.dp))
            Text(
                if (healthy) "Bullish thesis remains valid." else "Warning — thesis under review.",
                style = MaterialTheme.typography.titleMedium,
                color = if (healthy) FinancialColors.Gain else FinancialColors.Watch,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(6.dp))
            alert.thesisNotes.forEach { note ->
                Row(Modifier.padding(vertical = 2.dp)) {
                    Text(if (healthy) "✓ " else "• ", color = if (healthy) FinancialColors.Gain else FinancialColors.Watch)
                    Text(note, style = MaterialTheme.typography.bodyMedium, color = FinancialColors.OnSurface)
                }
            }
        }
    }
}

@Composable
private fun LevelsSection(alert: Alert) {
    FinancialCard {
        Column {
            SectionLabel("Stop and targets")
            Spacer(Modifier.height(8.dp))
            MetricRow("Stop loss", Formats.money(alert.stopPrice), FinancialColors.Loss)
            alert.trailingStopPrice?.let {
                MetricRow("Trailing stop", Formats.money(it), FinancialColors.Trailing)
            }
            MetricRow("Stop in force", Formats.money(alert.currentStopPrice ?: alert.stopPrice))
            MetricRow("Target 1", Formats.money(alert.target1Price), FinancialColors.Gain)
            MetricRow("Target 2", Formats.money(alert.target2Price), FinancialColors.Gain)
            MetricRow("Reward / risk", Formats.ratio(alert.rewardRisk))
            alert.breakoutType?.takeIf { it != "NONE" }?.let {
                MetricRow("Breakout", it.replace('_', ' ').lowercase())
            }
        }
    }
}

/**
 * Probability is always shown with its sample size (requirement 27). A number without its
 * evidence would invite exactly the false confidence the spec forbids.
 */
@Composable
private fun ProbabilitySection(alert: Alert) {
    FinancialCard {
        Column {
            SectionLabel("Statistical estimate")
            Spacer(Modifier.height(8.dp))
            MetricRow(
                "P(target before stop)",
                Formats.probability(alert.probability, alert.probabilitySampleSize),
            )
            MetricRow("Expected value", "${Formats.ratio(alert.expectedValue)}R")
            Spacer(Modifier.height(6.dp))
            Text(
                if ((alert.probabilitySampleSize ?: 0) == 0) {
                    "No comparable historical setups were available, so this is a configured " +
                        "prior rather than an estimate from data. It is not a forecast."
                } else {
                    "Estimated from ${alert.probabilitySampleSize} comparable historical setups. " +
                        "Past behaviour of similar setups, not a prediction."
                },
                style = MaterialTheme.typography.bodySmall,
                color = FinancialColors.OnSurfaceMuted,
            )
        }
    }
}

@Composable
private fun ExitSection(alert: Alert) {
    val sell = alert.sell ?: return
    FinancialCard {
        Column {
            SectionLabel("Exit")
            Spacer(Modifier.height(8.dp))
            MetricRow("Sold", MarketTime.stamp(sell.sellTsUtc))
            MetricRow("Exit price", Formats.money(sell.sellPrice))
            MetricRow("Final return", Formats.percent(sell.finalReturnPct), returnColor(sell.finalReturnPct))
            MetricRow("R multiple", Formats.ratio(sell.rMultiple))
            MetricRow("Holding period", "${sell.holdingPeriodDays} day(s)")
            MetricRow("Exit reason", sell.exitReason.replace('_', ' ').lowercase())
            sell.exitReasonDetail?.let {
                Spacer(Modifier.height(6.dp))
                Text(it, style = MaterialTheme.typography.bodySmall, color = FinancialColors.OnSurfaceMuted)
            }
        }
    }
}

@Composable
private fun TimelineRow(event: AlertEvent) {
    FinancialCard {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
            Column(Modifier.width(96.dp)) {
                Text(
                    MarketTime.shortDate(event.tsUtc),
                    style = MaterialTheme.typography.labelSmall,
                    color = FinancialColors.OnSurfaceMuted,
                )
                Text(
                    MarketTime.time(event.tsUtc),
                    style = MaterialTheme.typography.labelSmall,
                    color = FinancialColors.OnSurfaceMuted,
                )
            }
            Column(Modifier.weight(1f)) {
                Text(
                    event.title,
                    style = MaterialTheme.typography.bodyMedium,
                    color = FinancialColors.OnSurface,
                    fontWeight = FontWeight.SemiBold,
                )
                event.detail?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall, color = FinancialColors.OnSurfaceMuted)
                }
            }
            event.price?.let {
                Text(
                    Formats.money(it),
                    style = MaterialTheme.typography.bodyMedium.merge(NumericTextStyle),
                    color = FinancialColors.OnSurface,
                )
            }
        }
    }
}
