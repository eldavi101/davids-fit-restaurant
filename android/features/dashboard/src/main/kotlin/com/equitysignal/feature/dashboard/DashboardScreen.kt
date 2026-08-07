package com.equitysignal.feature.dashboard

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.equitysignal.core.common.Formats
import com.equitysignal.core.common.FreshnessPolicy
import com.equitysignal.core.common.MarketTime
import com.equitysignal.core.designsystem.CategoryChip
import com.equitysignal.core.designsystem.Chip
import com.equitysignal.core.designsystem.ErrorBanner
import com.equitysignal.core.designsystem.FinancialCard
import com.equitysignal.core.designsystem.FinancialColors
import com.equitysignal.core.designsystem.FreshnessLabel
import com.equitysignal.core.designsystem.NumericTextStyle
import com.equitysignal.core.designsystem.ReturnText
import com.equitysignal.core.designsystem.SectionLabel
import com.equitysignal.core.designsystem.StatTile
import com.equitysignal.core.designsystem.SyntheticDataBanner
import com.equitysignal.core.designsystem.returnColor
import com.equitysignal.core.model.DashboardSummary
import com.equitysignal.core.model.MarketSessionState
import com.equitysignal.core.model.ScannerResult
import com.equitysignal.domain.ObserveDashboardUseCase
import com.equitysignal.domain.RefreshPortfolioUseCase
import com.equitysignal.domain.SyncNowUseCase
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class DashboardUiState(
    val summary: DashboardSummary? = null,
    val isRefreshing: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class DashboardViewModel @Inject constructor(
    observeDashboard: ObserveDashboardUseCase,
    private val syncNow: SyncNowUseCase,
    private val refreshPortfolio: RefreshPortfolioUseCase,
) : ViewModel() {

    private val refreshing = MutableStateFlow(false)
    private val error = MutableStateFlow<String?>(null)

    val uiState: StateFlow<DashboardUiState> =
        combine(observeDashboard(), refreshing, error) { summary, isRefreshing, message ->
            DashboardUiState(summary, isRefreshing, message)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), DashboardUiState())

    init { refresh() }

    fun refresh() {
        if (refreshing.value) return
        viewModelScope.launch {
            refreshing.value = true
            error.value = null
            when (val outcome = syncNow()) {
                is com.equitysignal.domain.SyncOutcome.Failure -> error.value = outcome.message
                com.equitysignal.domain.SyncOutcome.NotConfigured ->
                    error.value = "Add your backend URL and API key in Settings to begin."
                else -> refreshPortfolio()
            }
            refreshing.value = false
        }
    }
}

/** Home (requirement 8): market state, system activity, strategy performance, best ideas. */
@Composable
fun DashboardScreen(
    onOpportunityClick: (String) -> Unit,
    onAlertClick: (String) -> Unit,
    viewModel: DashboardViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val summary = state.summary

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (state.error != null) item { ErrorBanner(state.error!!) }

        // Requirement 61.1: generated data is announced, never passed off as a live feed.
        if (summary?.marketStatus?.syntheticData == true) item { SyntheticDataBanner() }

        item { MarketBanner(summary) }
        item { StatGrid(summary) }
        item { PerformanceCard(summary) }

        item { SectionLabel("Top opportunities", Modifier.padding(top = 4.dp)) }
        val opportunities = summary?.topOpportunities.orEmpty()
        if (opportunities.isEmpty()) {
            item {
                FinancialCard {
                    Text(
                        "No ranked opportunities cached yet. Pull down after the next scan.",
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                }
            }
        } else {
            items(opportunities, key = { it.ticker }) { row ->
                OpportunityRow(row) { onOpportunityClick(row.ticker) }
            }
        }

        item {
            FreshnessLabel(
                freshness = FreshnessPolicy.classify(summary?.lastUpdatedUtc),
                fetchedAtUtc = summary?.lastUpdatedUtc,
                modifier = Modifier.padding(top = 8.dp),
            )
        }
    }
}

@Composable
private fun MarketBanner(summary: DashboardSummary?) {
    val status = summary?.marketStatus
    val regime = summary?.regime
    FinancialCard {
        Column {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    SectionLabel("Market")
                    Text(
                        status?.session?.name ?: "UNKNOWN",
                        style = MaterialTheme.typography.headlineSmall,
                        color = when (status?.session) {
                            MarketSessionState.OPEN -> FinancialColors.Gain
                            MarketSessionState.PRE, MarketSessionState.POST -> FinancialColors.Watch
                            else -> FinancialColors.Neutral
                        },
                        fontWeight = FontWeight.Bold,
                    )
                }
                Column(horizontalAlignment = Alignment.End) {
                    SectionLabel("Regime")
                    Text(
                        regime?.regime?.name?.replace('_', ' ') ?: "—",
                        style = MaterialTheme.typography.titleMedium,
                        color = FinancialColors.OnSurface,
                        fontWeight = FontWeight.SemiBold,
                    )
                    if (regime?.allowsNewBuys == false) {
                        Chip("NEW BUYS BLOCKED", FinancialColors.Loss, filled = true)
                    }
                }
            }
            if (status?.degraded == true) {
                Spacer(Modifier.height(8.dp))
                Text(
                    "⚠ ${status.degradedReasons.firstOrNull() ?: "Backend reports degraded data"}",
                    style = MaterialTheme.typography.bodySmall,
                    color = FinancialColors.Watch,
                )
            }
            status?.nextCloseUtc?.let {
                Spacer(Modifier.height(6.dp))
                Text(
                    "Next close ${MarketTime.stamp(it)}",
                    style = MaterialTheme.typography.labelSmall,
                    color = FinancialColors.OnSurfaceMuted,
                )
            }
        }
    }
}

@Composable
private fun StatGrid(summary: DashboardSummary?) {
    val tiles = listOf(
        "Stocks scanned" to (summary?.stocksScanned?.toString() ?: "—"),
        "Strong ideas" to (summary?.strongOpportunities?.toString() ?: "—"),
        "BUY alerts today" to (summary?.buyAlertsToday?.toString() ?: "—"),
        "SELL alerts today" to (summary?.sellAlertsToday?.toString() ?: "—"),
        "Active alerts" to (summary?.activeAlerts?.toString() ?: "—"),
        "Open positions" to (summary?.openPositions?.toString() ?: "—"),
    )
    LazyVerticalGrid(
        columns = GridCells.Fixed(3),
        modifier = Modifier.fillMaxWidth().height(180.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        userScrollEnabled = false,
    ) {
        items(tiles) { (label, value) -> StatTile(label, value) }
    }
}

@Composable
private fun PerformanceCard(summary: DashboardSummary?) {
    FinancialCard {
        Column {
            SectionLabel("Strategy performance")
            Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column {
                    SectionLabel("Avg return")
                    ReturnText(summary?.strategyReturnPct)
                }
                Column {
                    SectionLabel("Win rate")
                    Text(
                        summary?.winRate?.let { Formats.percent(it * 100, 1, signed = false) } ?: "—",
                        style = MaterialTheme.typography.titleMedium.merge(NumericTextStyle),
                        color = FinancialColors.OnSurface,
                    )
                }
                Column {
                    SectionLabel("Profit factor")
                    Text(
                        Formats.ratio(summary?.profitFactor),
                        style = MaterialTheme.typography.titleMedium.merge(NumericTextStyle),
                        color = FinancialColors.OnSurface,
                    )
                }
                Column(horizontalAlignment = Alignment.End) {
                    SectionLabel("Drawdown")
                    Text(
                        Formats.percent(summary?.currentDrawdownPct),
                        style = MaterialTheme.typography.titleMedium.merge(NumericTextStyle),
                        color = returnColor(summary?.currentDrawdownPct),
                    )
                }
            }
        }
    }
}

@Composable
private fun OpportunityRow(result: ScannerResult, onClick: () -> Unit) {
    FinancialCard(modifier = Modifier.clickable(onClick = onClick)) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    result.ticker,
                    style = MaterialTheme.typography.titleMedium,
                    color = FinancialColors.OnSurface,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    result.companyName.orEmpty(),
                    style = MaterialTheme.typography.bodySmall,
                    color = FinancialColors.OnSurfaceMuted,
                    maxLines = 1,
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    "Score ${Formats.score(result.opportunityScore)}",
                    style = MaterialTheme.typography.bodyMedium.merge(NumericTextStyle),
                    color = FinancialColors.OnSurface,
                )
                Spacer(Modifier.height(4.dp))
                CategoryChip(result.category)
            }
        }
    }
}
