package com.equitysignal.feature.backtesting

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import com.equitysignal.core.common.MarketTime
import com.equitysignal.core.designsystem.Chip
import com.equitysignal.core.designsystem.EmptyState
import com.equitysignal.core.designsystem.ErrorBanner
import com.equitysignal.core.designsystem.FinancialCard
import com.equitysignal.core.designsystem.FinancialColors
import com.equitysignal.core.designsystem.LoadingState
import com.equitysignal.core.designsystem.MetricRow
import com.equitysignal.core.designsystem.SectionLabel
import com.equitysignal.core.designsystem.returnColor
import com.equitysignal.core.model.BacktestRun
import com.equitysignal.domain.GetBacktestUseCase
import com.equitysignal.domain.ObserveBacktestsUseCase
import com.equitysignal.domain.RunBacktestUseCase
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class BacktestingUiState(
    val runs: List<BacktestRun> = emptyList(),
    val selected: BacktestRun? = null,
    val isLoading: Boolean = true,
    val isStarting: Boolean = false,
    val message: String? = null,
    val error: String? = null,
)

@HiltViewModel
class BacktestingViewModel @Inject constructor(
    private val observeBacktests: ObserveBacktestsUseCase,
    private val getBacktest: GetBacktestUseCase,
    private val runBacktest: RunBacktestUseCase,
) : ViewModel() {

    private val _uiState = MutableStateFlow(BacktestingUiState())
    val uiState: StateFlow<BacktestingUiState> = _uiState.asStateFlow()

    init { refresh() }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            observeBacktests()
                .onSuccess { runs -> _uiState.update { it.copy(runs = runs, isLoading = false) } }
                .onFailure { error -> _uiState.update { it.copy(isLoading = false, error = error.message) } }
        }
    }

    fun start(mode: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isStarting = true, message = null, error = null) }
            runBacktest(mode)
                .onSuccess { runUid ->
                    _uiState.update {
                        it.copy(
                            isStarting = false,
                            message = "Run $runUid queued. Refresh in a moment for results.",
                        )
                    }
                }
                .onFailure { error -> _uiState.update { it.copy(isStarting = false, error = error.message) } }
        }
    }

    fun select(runUid: String) {
        viewModelScope.launch {
            getBacktest(runUid).onSuccess { run -> _uiState.update { it.copy(selected = run) } }
        }
    }

    fun clearSelection() = _uiState.update { it.copy(selected = null) }
}

/** Backtesting and walk-forward validation (requirements 38–40). */
@Composable
fun BacktestingScreen(viewModel: BacktestingViewModel = hiltViewModel()) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    state.selected?.let { run ->
        BacktestDetail(run, onBack = viewModel::clearSelection)
        return
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            FinancialCard {
                Column {
                    SectionLabel("Run a validation")
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "A backtest simulates the same scoring, BUY and SELL code the live " +
                            "scanner uses, with modelled slippage and spread. Results describe " +
                            "the past; they are not a forecast.",
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = { viewModel.start("BACKTEST") },
                            enabled = !state.isStarting,
                        ) { Text("Backtest") }
                        OutlinedButton(
                            onClick = { viewModel.start("WALK_FORWARD") },
                            enabled = !state.isStarting,
                        ) { Text("Walk-forward") }
                        OutlinedButton(
                            onClick = { viewModel.start("OOS") },
                            enabled = !state.isStarting,
                        ) { Text("Out-of-sample") }
                    }
                    state.message?.let {
                        Spacer(Modifier.height(8.dp))
                        Text(it, style = MaterialTheme.typography.bodySmall, color = FinancialColors.Gain)
                    }
                }
            }
        }

        state.error?.let { item { ErrorBanner(it) } }

        item {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                SectionLabel("Runs")
                OutlinedButton(onClick = viewModel::refresh) { Text("Refresh") }
            }
        }

        when {
            state.isLoading -> item { LoadingState(label = "Loading runs") }
            state.runs.isEmpty() -> item { EmptyState("No backtest runs yet") }
            else -> items(state.runs, key = { it.runUid }) { run ->
                RunCard(run) { viewModel.select(run.runUid) }
            }
        }
    }
}

@Composable
private fun RunCard(run: BacktestRun, onClick: () -> Unit) {
    FinancialCard(modifier = Modifier.clickable(onClick = onClick)) {
        Column {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Text(
                        run.mode.replace('_', ' '),
                        style = MaterialTheme.typography.titleMedium,
                        color = FinancialColors.OnSurface,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        MarketTime.dateTime(run.createdAtUtc),
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                }
                Chip(
                    run.status,
                    when (run.status) {
                        "COMPLETE" -> FinancialColors.Gain
                        "FAILED" -> FinancialColors.Loss
                        else -> FinancialColors.Watch
                    },
                    filled = true,
                )
            }
            if (run.status == "COMPLETE") {
                Spacer(Modifier.height(8.dp))
                MetricRow("Trades", run.trades.toString())
                MetricRow(
                    "Win rate",
                    run.winRate?.let { Formats.percent(it * 100, 1, signed = false) } ?: "—",
                )
                MetricRow("Expectancy", "${Formats.ratio(run.expectancyR)}R")
                MetricRow("Total return", Formats.percent(run.totalReturnPct), returnColor(run.totalReturnPct))
                MetricRow("Benchmark", Formats.percent(run.benchmarkReturnPct), returnColor(run.benchmarkReturnPct))
            }
            run.error?.let {
                Spacer(Modifier.height(6.dp))
                Text(it, style = MaterialTheme.typography.bodySmall, color = FinancialColors.Loss)
            }
        }
    }
}

@Composable
private fun BacktestDetail(run: BacktestRun, onBack: () -> Unit) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            OutlinedButton(onClick = onBack, modifier = Modifier.fillMaxWidth()) {
                Text("Back to runs")
            }
        }

        // Bias warnings are surfaced at the top, not buried under the metrics they qualify.
        if (run.biasWarnings.isNotEmpty()) {
            item {
                FinancialCard {
                    Column {
                        SectionLabel("Limitations of this run")
                        Spacer(Modifier.height(6.dp))
                        run.biasWarnings.forEach {
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

        item {
            FinancialCard {
                Column {
                    SectionLabel("${run.mode.replace('_', ' ')} · ${run.strategyVersion}")
                    Spacer(Modifier.height(8.dp))
                    MetricRow("Period", "${run.startDate ?: "—"} → ${run.endDate ?: "—"}")
                    MetricRow("Universe", "${run.universeSize} symbols")
                    MetricRow("Trades", run.trades.toString())
                    MetricRow(
                        "Win rate",
                        run.winRate?.let { Formats.percent(it * 100, 1, signed = false) } ?: "—",
                    )
                    MetricRow("Profit factor", Formats.ratio(run.profitFactor))
                    MetricRow("Expectancy", "${Formats.ratio(run.expectancyR)}R")
                    MetricRow("Sharpe", run.sharpe?.let { Formats.ratio(it) } ?: "insufficient data")
                    MetricRow("Sortino", run.sortino?.let { Formats.ratio(it) } ?: "insufficient data")
                    MetricRow("Max drawdown", Formats.percent(run.maxDrawdownPct), FinancialColors.Loss)
                    MetricRow("Average return", Formats.percent(run.avgReturnPct), returnColor(run.avgReturnPct))
                    MetricRow("Average holding", run.avgHoldingDays?.let { "${Formats.ratio(it, 1)} days" } ?: "—")
                    MetricRow("Strategy total", Formats.percent(run.totalReturnPct), returnColor(run.totalReturnPct))
                    MetricRow("Benchmark total", Formats.percent(run.benchmarkReturnPct), returnColor(run.benchmarkReturnPct))
                }
            }
        }

        // Per-fold train / validation / test, side by side. The test column is the only
        // out-of-sample one and is the number that matters.
        if (run.folds.isNotEmpty()) {
            item { SectionLabel("Walk-forward folds") }
            items(run.folds, key = { it.fold }) { fold ->
                FinancialCard {
                    Column {
                        Text(
                            "Fold ${fold.fold}",
                            style = MaterialTheme.typography.titleSmall,
                            color = FinancialColors.OnSurface,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Spacer(Modifier.height(6.dp))
                        MetricRow("Train window", fold.trainRange)
                        MetricRow("Test window", fold.testRange)
                        MetricRow("Training samples", fold.trainingSamples.toString())
                        MetricRow("Train expectancy", "${Formats.ratio(fold.trainExpectancy)}R")
                        MetricRow("Validation expectancy", "${Formats.ratio(fold.validationExpectancy)}R")
                        MetricRow(
                            "Test expectancy (out-of-sample)",
                            "${Formats.ratio(fold.testExpectancy)}R",
                            returnColor(fold.testExpectancy),
                        )
                        MetricRow("Test trades", fold.testTrades.toString())
                    }
                }
            }
        }
    }
}
