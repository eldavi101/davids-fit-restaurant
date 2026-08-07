package com.equitysignal.feature.history

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
import androidx.compose.material3.FilterChip
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
import com.equitysignal.core.common.MarketTime
import com.equitysignal.core.designsystem.EmptyState
import com.equitysignal.core.designsystem.ErrorBanner
import com.equitysignal.core.designsystem.FinancialCard
import com.equitysignal.core.designsystem.FinancialColors
import com.equitysignal.core.designsystem.LoadingState
import com.equitysignal.core.designsystem.NumericTextStyle
import com.equitysignal.core.designsystem.ReturnText
import com.equitysignal.core.designsystem.SectionLabel
import com.equitysignal.core.model.Alert
import com.equitysignal.domain.GetHistoryUseCase
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class HistoryUiState(
    val trades: List<Alert> = emptyList(),
    val outcome: String = "all",
    val tickerFilter: String = "",
    val isLoading: Boolean = true,
    val error: String? = null,
) {
    /** Client-side ticker narrowing keeps typing responsive without a round trip. */
    val visible: List<Alert>
        get() = if (tickerFilter.isBlank()) trades
        else trades.filter { it.ticker.contains(tickerFilter, ignoreCase = true) }
}

@HiltViewModel
class HistoryViewModel @Inject constructor(
    private val getHistory: GetHistoryUseCase,
) : ViewModel() {

    private val _uiState = MutableStateFlow(HistoryUiState())
    val uiState: StateFlow<HistoryUiState> = _uiState.asStateFlow()

    init { load("all") }

    fun load(outcome: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, outcome = outcome, error = null) }
            getHistory(outcome)
                .onSuccess { trades -> _uiState.update { it.copy(trades = trades, isLoading = false) } }
                .onFailure { error ->
                    _uiState.update { it.copy(isLoading = false, error = error.message) }
                }
        }
    }

    fun setTickerFilter(value: String) = _uiState.update { it.copy(tickerFilter = value) }
}

/** History (requirement 35). Closed trades are never removed — only filtered. */
@Composable
fun HistoryScreen(
    onTradeClick: (String) -> Unit,
    viewModel: HistoryViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(
            value = state.tickerFilter,
            onValueChange = viewModel::setTickerFilter,
            label = { Text("Filter by ticker") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(12.dp),
        )

        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            listOf("all", "winner", "loser", "stopped", "target").forEach { outcome ->
                FilterChip(
                    selected = state.outcome == outcome,
                    onClick = { viewModel.load(outcome) },
                    label = { Text(outcome.replaceFirstChar { it.uppercase() }) },
                )
            }
        }

        state.error?.let { ErrorBanner(it) }

        when {
            state.isLoading -> LoadingState(label = "Loading history")
            state.visible.isEmpty() -> EmptyState(
                title = "No closed trades match",
                subtitle = "Every closed trade is kept permanently; adjust the filters above.",
            )
            else -> LazyColumn(
                contentPadding = PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(state.visible, key = { it.alertUid }) { trade ->
                    HistoryRow(trade) { onTradeClick(trade.alertUid) }
                }
            }
        }
    }
}

@Composable
private fun HistoryRow(trade: Alert, onClick: () -> Unit) {
    FinancialCard(modifier = Modifier.clickable(onClick = onClick)) {
        Column {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Text(
                        trade.ticker,
                        style = MaterialTheme.typography.titleMedium,
                        color = FinancialColors.OnSurface,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "${MarketTime.shortDate(trade.buyTsUtc)} → " +
                            (trade.closedTsUtc?.let { MarketTime.shortDate(it) } ?: "open"),
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                }
                ReturnText(trade.finalReturnPct ?: trade.currentReturnPct)
            }
            Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Cell("Entry", Formats.money(trade.buyPrice))
                Cell("Exit", Formats.money(trade.sell?.sellPrice))
                Cell("Held", "${trade.holdingPeriodDays ?: 0}d")
                Cell("Score", Formats.score(trade.opportunityScore))
                Cell("Exit", trade.sell?.exitReason?.replace('_', ' ')?.lowercase() ?: "—")
            }
        }
    }
}

@Composable
private fun Cell(label: String, value: String) {
    Column {
        SectionLabel(label)
        Text(
            value,
            style = MaterialTheme.typography.bodySmall.merge(NumericTextStyle),
            color = FinancialColors.OnSurface,
        )
    }
}
