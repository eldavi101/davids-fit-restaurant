package com.equitysignal.feature.analytics

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.equitysignal.core.common.Formats
import com.equitysignal.core.common.FreshnessPolicy
import com.equitysignal.core.designsystem.EmptyState
import com.equitysignal.core.designsystem.ErrorBanner
import com.equitysignal.core.designsystem.FinancialCard
import com.equitysignal.core.designsystem.FinancialColors
import com.equitysignal.core.designsystem.FreshnessLabel
import com.equitysignal.core.designsystem.MetricRow
import com.equitysignal.core.designsystem.SectionLabel
import com.equitysignal.core.designsystem.returnColor
import com.equitysignal.core.model.Analytics
import com.equitysignal.core.model.EquityCurve
import com.equitysignal.domain.GetEquityCurveUseCase
import com.equitysignal.domain.ObserveAnalyticsUseCase
import com.equitysignal.domain.RefreshPortfolioUseCase
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class AnalyticsUiState(
    val analytics: Analytics? = null,
    val equityCurve: EquityCurve? = null,
    val isRefreshing: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class AnalyticsViewModel @Inject constructor(
    observeAnalytics: ObserveAnalyticsUseCase,
    private val refreshPortfolio: RefreshPortfolioUseCase,
    private val getEquityCurve: GetEquityCurveUseCase,
) : ViewModel() {

    private val curve = MutableStateFlow<EquityCurve?>(null)
    private val refreshing = MutableStateFlow(false)
    private val error = MutableStateFlow<String?>(null)

    val uiState: StateFlow<AnalyticsUiState> =
        combine(observeAnalytics(), curve, refreshing, error) { analytics, equity, busy, message ->
            AnalyticsUiState(analytics, equity, busy, message)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), AnalyticsUiState())

    init { refresh() }

    fun refresh() {
        if (refreshing.value) return
        viewModelScope.launch {
            refreshing.value = true
            error.value = null
            refreshPortfolio().onFailure { error.value = it.message }
            getEquityCurve().onSuccess { curve.value = it }
            refreshing.value = false
        }
    }
}

/** Analytics (requirements 36–37): what the strategy has actually done. */
@Composable
fun AnalyticsScreen(viewModel: AnalyticsViewModel = hiltViewModel()) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val analytics = state.analytics

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        state.error?.let { item { ErrorBanner(it) } }

        if (analytics == null) {
            item {
                EmptyState(
                    title = "No analytics cached",
                    subtitle = "Statistics appear once trades have closed.",
                )
            }
            return@LazyColumn
        }

        // Small samples are labelled rather than quietly presented as evidence.
        if (analytics.warnings.isNotEmpty()) {
            item {
                FinancialCard {
                    Column {
                        SectionLabel("Read with care")
                        Spacer(Modifier.height(6.dp))
                        analytics.warnings.forEach {
                            Text(
                                "• $it",
                                style = MaterialTheme.typography.bodySmall,
                                color = FinancialColors.Watch,
                            )
                        }
                    }
                }
            }
        }

        item { HeadlineCard(analytics) }
        item { DistributionCard(analytics) }
        item { EquityCurveCard(state.equityCurve) }
        item { BreakdownCard("By market regime", analytics.byRegime) }
        item { BreakdownCard("By exit reason", analytics.byExitReason) }
        item {
            FreshnessLabel(
                FreshnessPolicy.classify(analytics.fetchedAtUtc), analytics.fetchedAtUtc,
            )
        }
    }
}

@Composable
private fun HeadlineCard(analytics: Analytics) {
    FinancialCard {
        Column {
            SectionLabel("Performance")
            Spacer(Modifier.height(8.dp))
            MetricRow("Total BUY signals", analytics.totalBuySignals.toString())
            MetricRow("Open alerts", analytics.openAlerts.toString())
            MetricRow("Closed trades", analytics.closedTrades.toString())
            MetricRow("Winners / losers", "${analytics.winners} / ${analytics.losers}")
            MetricRow(
                "Win rate",
                analytics.winRate?.let { Formats.percent(it * 100, 1, signed = false) } ?: "—",
            )
            MetricRow("Average return", Formats.percent(analytics.avgReturnPct), returnColor(analytics.avgReturnPct))
            MetricRow("Median return", Formats.percent(analytics.medianReturnPct), returnColor(analytics.medianReturnPct))
            MetricRow("Average winner", Formats.percent(analytics.avgWinnerPct), FinancialColors.Gain)
            MetricRow("Average loser", Formats.percent(analytics.avgLoserPct), FinancialColors.Loss)
            analytics.bestTrade?.let {
                MetricRow("Best trade", "${it.ticker} ${Formats.percent(it.returnPct)}", FinancialColors.Gain)
            }
            analytics.worstTrade?.let {
                MetricRow("Worst trade", "${it.ticker} ${Formats.percent(it.returnPct)}", FinancialColors.Loss)
            }
            MetricRow("Profit factor", Formats.ratio(analytics.profitFactor))
            MetricRow("Expectancy", "${Formats.ratio(analytics.expectancyR)}R")
            MetricRow("Maximum drawdown", Formats.percent(analytics.maxDrawdownPct), FinancialColors.Loss)
            // Null means "not enough observations to state honestly", not "zero".
            MetricRow("Sharpe", analytics.sharpe?.let { Formats.ratio(it) } ?: "insufficient data")
            MetricRow("Sortino", analytics.sortino?.let { Formats.ratio(it) } ?: "insufficient data")
            MetricRow("Average holding", analytics.avgHoldingDays?.let { "${Formats.ratio(it, 1)} days" } ?: "—")
            MetricRow(
                "Target hit rate",
                analytics.targetHitRate?.let { Formats.percent(it * 100, 1, signed = false) } ?: "—",
            )
            MetricRow(
                "Stop rate",
                analytics.stopRate?.let { Formats.percent(it * 100, 1, signed = false) } ?: "—",
            )
        }
    }
}

@Composable
private fun DistributionCard(analytics: Analytics) {
    if (analytics.returnDistribution.isEmpty()) return
    val maxCount = analytics.returnDistribution.maxOf { it.count }.coerceAtLeast(1)
    FinancialCard {
        Column {
            SectionLabel("Return distribution")
            Spacer(Modifier.height(8.dp))
            analytics.returnDistribution.forEach { bucket ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    Text(
                        "${bucket.bucket}%",
                        style = MaterialTheme.typography.labelSmall,
                        color = FinancialColors.OnSurfaceMuted,
                        modifier = Modifier.width(76.dp),
                    )
                    androidx.compose.material3.LinearProgressIndicator(
                        progress = { bucket.count.toFloat() / maxCount },
                        modifier = Modifier.weight(1f).height(8.dp),
                        color = if (bucket.lower >= 0) FinancialColors.Gain else FinancialColors.Loss,
                        trackColor = FinancialColors.Outline,
                    )
                    Text(
                        " ${bucket.count}",
                        style = MaterialTheme.typography.labelSmall,
                        color = FinancialColors.OnSurface,
                    )
                }
                Spacer(Modifier.height(4.dp))
            }
        }
    }
}

/**
 * Strategy equity versus SPY (requirement 60.26), rendered as a sparkline pair so the
 * comparison is like-for-like on the same starting capital.
 */
@Composable
private fun EquityCurveCard(curve: EquityCurve?) {
    FinancialCard {
        Column {
            SectionLabel("Equity curve vs ${curve?.benchmark ?: "SPY"}")
            Spacer(Modifier.height(8.dp))
            if (curve == null || curve.points.size < 2) {
                Text(
                    "Not enough portfolio snapshots yet to draw a curve.",
                    style = MaterialTheme.typography.bodySmall,
                    color = FinancialColors.OnSurfaceMuted,
                )
                return@Column
            }
            SparklineComparison(
                strategy = curve.points.map { it.equity },
                benchmark = curve.points.mapNotNull { it.benchmark },
                modifier = Modifier.fillMaxWidth().height(140.dp),
            )
            Spacer(Modifier.height(8.dp))
            val first = curve.points.first()
            val last = curve.points.last()
            val strategyReturn = if (first.equity > 0) (last.equity / first.equity - 1) * 100 else 0.0
            MetricRow("Strategy", Formats.percent(strategyReturn), returnColor(strategyReturn))
            if (first.benchmark != null && last.benchmark != null && first.benchmark!! > 0) {
                val benchReturn = (last.benchmark!! / first.benchmark!! - 1) * 100
                MetricRow("Benchmark", Formats.percent(benchReturn), returnColor(benchReturn))
            }
            if (curve.monthlyReturns.isNotEmpty()) {
                Spacer(Modifier.height(10.dp))
                SectionLabel("Monthly returns")
                Spacer(Modifier.height(4.dp))
                curve.monthlyReturns.takeLast(12).forEach {
                    MetricRow(it.month, Formats.percent(it.returnPct), returnColor(it.returnPct))
                }
            }
        }
    }
}

@Composable
private fun BreakdownCard(title: String, stats: Map<String, com.equitysignal.core.model.GroupStat>) {
    if (stats.isEmpty()) return
    FinancialCard {
        Column {
            SectionLabel(title)
            Spacer(Modifier.height(8.dp))
            stats.forEach { (name, stat) ->
                MetricRow(
                    name.replace('_', ' '),
                    "${stat.trades} trades · ${Formats.percent(stat.winRate * 100, 0, signed = false)} win · " +
                        Formats.percent(stat.avgReturnPct),
                    returnColor(stat.avgReturnPct),
                )
            }
        }
    }
}
