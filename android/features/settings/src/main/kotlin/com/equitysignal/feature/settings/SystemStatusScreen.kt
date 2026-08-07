package com.equitysignal.feature.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
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
import com.equitysignal.core.common.MarketTime
import com.equitysignal.core.designsystem.Chip
import com.equitysignal.core.designsystem.ErrorBanner
import com.equitysignal.core.designsystem.FinancialCard
import com.equitysignal.core.designsystem.FinancialColors
import com.equitysignal.core.designsystem.LoadingState
import com.equitysignal.core.designsystem.MetricRow
import com.equitysignal.core.designsystem.SectionLabel
import com.equitysignal.core.model.SystemStatus
import com.equitysignal.domain.MarketRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SystemStatusUiState(
    val status: SystemStatus? = null,
    val isLoading: Boolean = true,
    val error: String? = null,
)

@HiltViewModel
class SystemStatusViewModel @Inject constructor(
    private val marketRepository: MarketRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SystemStatusUiState())
    val uiState: StateFlow<SystemStatusUiState> = _uiState.asStateFlow()

    init { refresh() }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            marketRepository.systemStatus()
                .onSuccess { status -> _uiState.update { it.copy(status = status, isLoading = false) } }
                .onFailure { error -> _uiState.update { it.copy(isLoading = false, error = error.message) } }
        }
    }
}

/** System status: whether the machinery behind the alerts is actually healthy. */
@Composable
fun SystemStatusScreen(viewModel: SystemStatusViewModel = hiltViewModel()) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    if (state.isLoading && state.status == null) {
        LoadingState(label = "Checking backend")
        return
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        state.error?.let { item { ErrorBanner(it) } }
        val status = state.status ?: return@LazyColumn

        item {
            FinancialCard {
                Column {
                    SectionLabel("Backend")
                    Spacer(Modifier.height(8.dp))
                    MetricRow(
                        "Database",
                        if (status.databaseOk) "reachable" else "unavailable",
                        if (status.databaseOk) FinancialColors.Gain else FinancialColors.Loss,
                    )
                    MetricRow("Active provider", status.activeProvider ?: "—")
                    MetricRow("Strategy", status.strategyVersion ?: "—")
                    MetricRow("Scheduler", if (status.schedulerEnabled) "running" else "off")
                    MetricRow("Last scan", status.lastScanUtc?.let { MarketTime.stamp(it) } ?: "never")
                    MetricRow("Last regime", status.lastRegime ?: "—")
                    Spacer(Modifier.height(8.dp))
                    Chip("PAPER TRADING", FinancialColors.Accent, filled = true)
                }
            }
        }

        item {
            FinancialCard {
                Column {
                    SectionLabel("Data providers")
                    Spacer(Modifier.height(8.dp))
                    status.providers.forEach { provider ->
                        MetricRow(
                            provider.name,
                            if (provider.ok) "ok" else provider.detail,
                            if (provider.ok) FinancialColors.Gain else FinancialColors.Loss,
                        )
                    }
                }
            }
        }

        item {
            FinancialCard {
                Column {
                    SectionLabel("Coverage")
                    Spacer(Modifier.height(8.dp))
                    MetricRow("Instruments tracked", status.instruments.toString())
                    MetricRow("Eligible universe", status.eligibleInstruments.toString())
                    MetricRow("Open alerts", status.openAlerts.toString())
                    MetricRow("Total alerts", status.totalAlerts.toString())
                    MetricRow("Total SELL alerts", status.totalSells.toString())
                    MetricRow(
                        "Recorded data failures",
                        status.auditErrors.toString(),
                        if (status.auditErrors > 0) FinancialColors.Watch else FinancialColors.OnSurface,
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "A data failure means the scanner refused to create a signal because " +
                            "its inputs were incomplete or stale — that is the intended behaviour.",
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                }
            }
        }
    }
}
