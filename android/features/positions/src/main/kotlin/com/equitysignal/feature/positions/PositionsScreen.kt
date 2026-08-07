package com.equitysignal.feature.positions

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
import com.equitysignal.core.designsystem.Chip
import com.equitysignal.core.designsystem.EmptyState
import com.equitysignal.core.designsystem.ErrorBanner
import com.equitysignal.core.designsystem.FinancialCard
import com.equitysignal.core.designsystem.FinancialColors
import com.equitysignal.core.designsystem.MetricRow
import com.equitysignal.core.designsystem.NumericTextStyle
import com.equitysignal.core.designsystem.ReturnText
import com.equitysignal.core.designsystem.SectionLabel
import com.equitysignal.core.designsystem.returnColor
import com.equitysignal.core.model.PortfolioState
import com.equitysignal.core.model.Position
import com.equitysignal.domain.ObservePortfolioUseCase
import com.equitysignal.domain.ObservePositionsUseCase
import com.equitysignal.domain.RefreshPortfolioUseCase
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class PositionsUiState(
    val positions: List<Position> = emptyList(),
    val portfolio: PortfolioState? = null,
    val isRefreshing: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class PositionsViewModel @Inject constructor(
    observePositions: ObservePositionsUseCase,
    observePortfolio: ObservePortfolioUseCase,
    private val refreshPortfolio: RefreshPortfolioUseCase,
) : ViewModel() {

    private val refreshing = MutableStateFlow(false)
    private val error = MutableStateFlow<String?>(null)

    val uiState: StateFlow<PositionsUiState> =
        combine(observePositions(), observePortfolio(), refreshing, error) { positions, portfolio, busy, message ->
            PositionsUiState(positions, portfolio, busy, message)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), PositionsUiState())

    init { refresh() }

    fun refresh() {
        if (refreshing.value) return
        viewModelScope.launch {
            refreshing.value = true
            error.value = null
            refreshPortfolio().onFailure { error.value = it.message ?: "Could not refresh positions" }
            refreshing.value = false
        }
    }
}

/**
 * The paper portfolio (requirement 41).
 *
 * These are hypothetical positions sized by risk. No broker is contacted and no order is
 * ever routed; the portfolio exists so signal quality is measured against a realistic
 * capital constraint rather than assumed to be free.
 */
@Composable
fun PositionsScreen(viewModel: PositionsViewModel = hiltViewModel()) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        state.error?.let { item { ErrorBanner(it) } }
        item { PortfolioCard(state.portfolio) }

        if (state.positions.isEmpty()) {
            item {
                EmptyState(
                    title = "No open paper positions",
                    subtitle = "A position opens when a BUY alert fires and the risk budget allows it.",
                )
            }
        } else {
            item { SectionLabel("Open positions") }
            items(state.positions, key = { it.id }) { PositionCard(it) }
        }
    }
}

@Composable
private fun PortfolioCard(portfolio: PortfolioState?) {
    FinancialCard {
        Column {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                SectionLabel("Paper portfolio")
                Chip("PAPER TRADING", FinancialColors.Accent, filled = true)
            }
            Spacer(Modifier.height(10.dp))
            Text(
                Formats.money(portfolio?.equity),
                style = MaterialTheme.typography.headlineMedium.merge(NumericTextStyle),
                color = FinancialColors.OnSurface,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(10.dp))
            MetricRow("Cash", Formats.money(portfolio?.cash))
            MetricRow("Positions value", Formats.money(portfolio?.positionsValue))
            MetricRow(
                "Unrealised P&L",
                Formats.signedMoney(portfolio?.unrealizedPnl),
                returnColor(portfolio?.unrealizedPnl),
            )
            MetricRow(
                "Realised P&L",
                Formats.signedMoney(portfolio?.realizedPnl),
                returnColor(portfolio?.realizedPnl),
            )
            MetricRow(
                "Open risk",
                "${Formats.money(portfolio?.openRisk)} (${Formats.percent((portfolio?.openRiskPct ?: 0.0) * 100, 2, signed = false)})",
            )
            MetricRow("Drawdown", Formats.percent(portfolio?.drawdownPct), returnColor(portfolio?.drawdownPct))
        }
    }
}

@Composable
private fun PositionCard(position: Position) {
    FinancialCard {
        Column {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column {
                    Text(
                        position.ticker,
                        style = MaterialTheme.typography.titleMedium,
                        color = FinancialColors.OnSurface,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "${Formats.shares(position.shares)} shares @ ${Formats.money(position.entryPrice)}",
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                }
                Column(horizontalAlignment = Alignment.End) {
                    ReturnText(position.returnPct)
                    Text(
                        Formats.signedMoney(position.unrealizedPnl),
                        style = MaterialTheme.typography.bodySmall.merge(NumericTextStyle),
                        color = returnColor(position.unrealizedPnl),
                    )
                }
            }
            Spacer(Modifier.height(8.dp))
            MetricRow("Market value", Formats.money(position.marketValue))
            MetricRow("Cost basis", Formats.money(position.costBasis))
            MetricRow("Stop", Formats.money(position.stopPrice), FinancialColors.Loss)
            MetricRow("Target", Formats.money(position.target1Price), FinancialColors.Gain)
            position.riskPctOfEquity?.let {
                MetricRow("Risk of equity", Formats.percent(it * 100, 2, signed = false))
            }
        }
    }
}
