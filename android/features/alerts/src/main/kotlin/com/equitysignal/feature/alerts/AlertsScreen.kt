package com.equitysignal.feature.alerts

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.equitysignal.core.common.Formats
import com.equitysignal.core.common.FreshnessPolicy
import com.equitysignal.core.common.MarketTime
import com.equitysignal.core.designsystem.CategoryChip
import com.equitysignal.core.designsystem.EmptyState
import com.equitysignal.core.designsystem.ErrorBanner
import com.equitysignal.core.designsystem.FinancialCard
import com.equitysignal.core.designsystem.FinancialColors
import com.equitysignal.core.designsystem.FreshnessLabel
import com.equitysignal.core.designsystem.LoadingState
import com.equitysignal.core.designsystem.NumericTextStyle
import com.equitysignal.core.designsystem.ReturnText
import com.equitysignal.core.designsystem.SectionLabel
import com.equitysignal.core.designsystem.StatusChip
import com.equitysignal.core.designsystem.returnColor
import com.equitysignal.core.model.Alert
import com.equitysignal.domain.AlertsTab

/**
 * The Alert Center (requirement 10).
 *
 * Every alert the system has ever produced lives here, permanently. Tabs filter it;
 * nothing removes it. A closed trade keeps its card and simply changes shape — entry and
 * exit, final return, holding period, exit reason (requirement 55).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AlertsScreen(
    onAlertClick: (String) -> Unit,
    viewModel: AlertsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    when (val current = state) {
        AlertsUiState.Loading -> LoadingState(label = "Loading alerts")
        is AlertsUiState.Ready -> Column(Modifier.fillMaxSize()) {
            ScrollableTabRow(
                selectedTabIndex = AlertsTab.entries.indexOf(current.tab),
                containerColor = FinancialColors.Background,
                edgePadding = 12.dp,
            ) {
                AlertsTab.entries.forEach { tab ->
                    Tab(
                        selected = tab == current.tab,
                        onClick = { viewModel.selectTab(tab) },
                        text = {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(tab.name)
                                if (tab == AlertsTab.ALL && current.unreadCount > 0) {
                                    Spacer(Modifier.width(6.dp))
                                    UnreadBadge(current.unreadCount)
                                }
                            }
                        },
                    )
                }
            }

            if (current.error != null) ErrorBanner(current.error)

            if (current.alerts.isEmpty()) {
                EmptyState(
                    title = when (current.tab) {
                        AlertsTab.CLOSED -> "No closed trades yet"
                        AlertsTab.ACTIVE -> "No active alerts"
                        AlertsTab.SELL -> "No SELL alerts yet"
                        else -> "No alerts yet"
                    },
                    subtitle = "The scanner raises a BUY alert only when all thirteen " +
                        "conditions agree, so quiet periods are expected.",
                )
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item {
                        FreshnessLabel(
                            freshness = FreshnessPolicy.classify(current.lastUpdatedUtc),
                            fetchedAtUtc = current.lastUpdatedUtc,
                            modifier = Modifier.padding(bottom = 4.dp),
                        )
                    }
                    items(current.alerts, key = { it.alertUid }) { alert ->
                        AlertCard(alert = alert, onClick = { onAlertClick(alert.alertUid) })
                    }
                }
            }
        }
    }
}

@Composable
private fun UnreadBadge(count: Int) {
    Box(
        Modifier
            .size(18.dp)
            .clip(CircleShape)
            .background(FinancialColors.Loss),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = if (count > 99) "99+" else count.toString(),
            style = MaterialTheme.typography.labelSmall,
            color = androidx.compose.ui.graphics.Color.White,
            fontWeight = FontWeight.Bold,
        )
    }
}

/**
 * One alert, in either of its two shapes.
 *
 * Open: entry, current, return, max gain, stop, target, score.
 * Closed: entry, exit, final return, holding period, exit reason.
 * Same card, same object — it transitions rather than disappearing.
 */
@Composable
fun AlertCard(alert: Alert, onClick: () -> Unit, modifier: Modifier = Modifier) {
    FinancialCard(modifier = modifier.clickable(onClick = onClick)) {
        Column {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        if (!alert.isRead) {
                            Box(
                                Modifier.size(7.dp).clip(CircleShape)
                                    .background(FinancialColors.Accent)
                            )
                            Spacer(Modifier.width(6.dp))
                        }
                        Text(
                            alert.ticker,
                            style = MaterialTheme.typography.titleLarge,
                            color = FinancialColors.OnSurface,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                    Text(
                        alert.companyName.orEmpty(),
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                        maxLines = 1,
                    )
                }
                Column(horizontalAlignment = Alignment.End) {
                    StatusChip(alert.status)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        MarketTime.shortDate(alert.buyTsUtc),
                        style = MaterialTheme.typography.labelSmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                }
            }

            Spacer(Modifier.height(12.dp))

            if (alert.isClosed) ClosedBody(alert) else OpenBody(alert)
        }
    }
}

@Composable
private fun OpenBody(alert: Alert) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        PriceCell("Entry", Formats.money(alert.buyPrice))
        PriceCell("Current", Formats.money(alert.currentPrice))
        Column(horizontalAlignment = Alignment.End) {
            SectionLabel("Return")
            ReturnText(alert.currentReturnPct)
        }
    }
    Spacer(Modifier.height(10.dp))
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        PriceCell("Max gain", Formats.percent(alert.maxGainPct), returnColor(alert.maxGainPct))
        PriceCell("Drawdown", Formats.percent(alert.maxDrawdownPct), returnColor(alert.maxDrawdownPct))
        PriceCell("Stop", Formats.money(alert.currentStopPrice ?: alert.stopPrice))
        PriceCell("Target", Formats.money(alert.target1Price))
        Column(horizontalAlignment = Alignment.End) {
            SectionLabel("Score")
            Text(
                "${Formats.score(alert.opportunityScore)}/100",
                style = MaterialTheme.typography.bodyMedium.merge(NumericTextStyle),
                color = FinancialColors.OnSurface,
                fontWeight = FontWeight.SemiBold,
            )
        }
    }
    if (!alert.thesisValid) {
        Spacer(Modifier.height(8.dp))
        Text(
            "⚠ ${alert.thesisNotes.firstOrNull() ?: "Thesis under review"}",
            style = MaterialTheme.typography.bodySmall,
            color = FinancialColors.Watch,
        )
    }
}

@Composable
private fun ClosedBody(alert: Alert) {
    val sell = alert.sell
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        PriceCell("Entry", Formats.money(alert.buyPrice))
        PriceCell("Exit", Formats.money(sell?.sellPrice))
        Column(horizontalAlignment = Alignment.End) {
            SectionLabel("Final return")
            ReturnText(alert.finalReturnPct)
        }
    }
    Spacer(Modifier.height(10.dp))
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        PriceCell("Holding", "${alert.holdingPeriodDays ?: 0} day(s)")
        PriceCell("Max gain", Formats.percent(alert.maxGainPct), returnColor(alert.maxGainPct))
        PriceCell("R multiple", Formats.ratio(sell?.rMultiple))
    }
    if (sell != null) {
        Spacer(Modifier.height(8.dp))
        Text(
            "Exit reason: ${sell.exitReason.replace('_', ' ').lowercase()}",
            style = MaterialTheme.typography.bodySmall,
            color = FinancialColors.OnSurfaceMuted,
        )
    }
}

@Composable
private fun PriceCell(
    label: String,
    value: String,
    color: androidx.compose.ui.graphics.Color = FinancialColors.OnSurface,
) {
    Column {
        SectionLabel(label)
        Text(
            value,
            style = MaterialTheme.typography.bodyMedium.merge(NumericTextStyle),
            color = color,
            fontWeight = FontWeight.SemiBold,
        )
    }
}
