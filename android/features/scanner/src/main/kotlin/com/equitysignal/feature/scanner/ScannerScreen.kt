package com.equitysignal.feature.scanner

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
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import com.equitysignal.core.designsystem.CategoryChip
import com.equitysignal.core.designsystem.Chip
import com.equitysignal.core.designsystem.EmptyState
import com.equitysignal.core.designsystem.ErrorBanner
import com.equitysignal.core.designsystem.FinancialCard
import com.equitysignal.core.designsystem.FinancialColors
import com.equitysignal.core.designsystem.FreshnessLabel
import com.equitysignal.core.designsystem.NumericTextStyle
import com.equitysignal.core.designsystem.SectionLabel
import com.equitysignal.core.model.ScannerResult
import com.equitysignal.domain.ObserveScannerUseCase
import com.equitysignal.domain.RefreshScannerUseCase
import com.equitysignal.domain.ScannerFilter
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class ScannerUiState(
    val results: List<ScannerResult> = emptyList(),
    val filter: ScannerFilter = ScannerFilter(),
    val isRefreshing: Boolean = false,
    val error: String? = null,
    val lastUpdatedUtc: Long? = null,
)

@HiltViewModel
class ScannerViewModel @Inject constructor(
    observeScanner: ObserveScannerUseCase,
    private val refreshScanner: RefreshScannerUseCase,
) : ViewModel() {

    private val filter = MutableStateFlow(ScannerFilter())
    private val refreshing = MutableStateFlow(false)
    private val error = MutableStateFlow<String?>(null)

    val uiState: StateFlow<ScannerUiState> =
        combine(observeScanner(), filter, refreshing, error) { results, currentFilter, busy, message ->
            ScannerUiState(
                results = results,
                filter = currentFilter,
                isRefreshing = busy,
                error = message,
                lastUpdatedUtc = results.maxOfOrNull { it.fetchedAtUtc },
            )
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ScannerUiState())

    init { refresh() }

    fun refresh() {
        if (refreshing.value) return
        viewModelScope.launch {
            refreshing.value = true
            error.value = null
            refreshScanner(filter.value).onFailure {
                error.value = it.message ?: "Could not refresh the scanner"
            }
            refreshing.value = false
        }
    }

    fun setSearch(query: String) {
        filter.value = filter.value.copy(search = query)
        refresh()
    }

    fun setMinScore(score: Double?) {
        filter.value = filter.value.copy(minScore = score)
        refresh()
    }

    fun setSignalReadyOnly(only: Boolean) {
        filter.value = filter.value.copy(signalReadyOnly = only)
        refresh()
    }

    fun setSort(sort: String) {
        filter.value = filter.value.copy(sort = sort)
        refresh()
    }
}

/** Scanner (requirement 9): the ranked, filterable opportunity feed. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScannerScreen(
    onStockClick: (String) -> Unit,
    viewModel: ScannerViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(
            value = state.filter.search.orEmpty(),
            onValueChange = viewModel::setSearch,
            label = { Text("Search ticker or sector") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(12.dp),
        )

        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            AssistChip(
                onClick = { viewModel.setSignalReadyOnly(!state.filter.signalReadyOnly) },
                label = { Text(if (state.filter.signalReadyOnly) "Signal-ready ✓" else "Signal-ready") },
            )
            AssistChip(
                onClick = { viewModel.setMinScore(if (state.filter.minScore == null) 70.0 else null) },
                label = { Text(if (state.filter.minScore != null) "Score ≥ 70 ✓" else "Score ≥ 70") },
            )
            AssistChip(
                onClick = { viewModel.setSort(if (state.filter.sort == "score") "rel_volume" else "score") },
                label = { Text("Sort: ${state.filter.sort}") },
            )
        }

        state.error?.let { ErrorBanner(it) }

        if (state.results.isEmpty()) {
            EmptyState(
                title = "Nothing cached yet",
                subtitle = "Run a scan on the backend, then pull to refresh.",
            )
        } else {
            LazyColumn(
                contentPadding = PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item {
                    FreshnessLabel(
                        FreshnessPolicy.classify(state.lastUpdatedUtc), state.lastUpdatedUtc,
                    )
                }
                items(state.results, key = { it.ticker }) { row ->
                    ScannerRow(row) { onStockClick(row.ticker) }
                }
            }
        }
    }
}

@Composable
private fun ScannerRow(result: ScannerResult, onClick: () -> Unit) {
    FinancialCard(modifier = Modifier.clickable(onClick = onClick)) {
        Column {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "#${result.rank}",
                        style = MaterialTheme.typography.labelSmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                    Spacer(Modifier.padding(horizontal = 4.dp))
                    Column {
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
                }
                Column(horizontalAlignment = Alignment.End) {
                    CategoryChip(result.category)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        Formats.money(result.price),
                        style = MaterialTheme.typography.bodyMedium.merge(NumericTextStyle),
                        color = FinancialColors.OnSurface,
                    )
                }
            }

            Spacer(Modifier.height(10.dp))

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                MiniStat("Score", Formats.score(result.opportunityScore))
                MiniStat("Conf.", Formats.score(result.confidence))
                MiniStat("Trend", Formats.score(result.componentScores.trend))
                MiniStat("Mom.", Formats.score(result.componentScores.momentum))
                MiniStat("Break.", Formats.score(result.componentScores.breakout))
                MiniStat("RS", Formats.score(result.componentScores.relativeStrength))
                MiniStat("Risk", Formats.score(result.componentScores.risk))
            }

            Spacer(Modifier.height(10.dp))

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                MiniStat("Entry", Formats.money(result.suggestedEntry))
                MiniStat("Stop", Formats.money(result.stopPrice))
                MiniStat("Target", Formats.money(result.target1Price))
                MiniStat("R/R", Formats.ratio(result.rewardRisk))
                MiniStat("Rel vol", Formats.multiple(result.relVolume))
            }

            // Requirement 49: a stock that did not qualify says which rule stopped it.
            if (!result.signalReady && result.rulesFailed.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Text(
                    "Blocked by: ${result.rulesFailed.take(3).joinToString(", ") { it.replace('_', ' ') }}",
                    style = MaterialTheme.typography.labelSmall,
                    color = FinancialColors.OnSurfaceMuted,
                )
            } else if (result.signalReady) {
                Spacer(Modifier.height(8.dp))
                Chip("ALL 13 RULES PASSED", FinancialColors.Gain, filled = true)
            }
        }
    }
}

@Composable
private fun MiniStat(label: String, value: String) {
    Column {
        SectionLabel(label)
        Text(
            value,
            style = MaterialTheme.typography.bodySmall.merge(NumericTextStyle),
            color = FinancialColors.OnSurface,
            fontWeight = FontWeight.Medium,
        )
    }
}
