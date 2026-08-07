package com.equitysignal.feature.stockdetails

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.equitysignal.core.model.Alert
import com.equitysignal.core.model.StockAnalysis
import com.equitysignal.core.model.StockChart
import com.equitysignal.core.model.StockDetail
import com.equitysignal.domain.GetStockAnalysisUseCase
import com.equitysignal.domain.GetStockChartUseCase
import com.equitysignal.domain.ObserveAlertsForTickerUseCase
import com.equitysignal.domain.ObserveStockUseCase
import com.equitysignal.domain.RefreshStockUseCase
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class StockDetailUiState(
    val ticker: String = "",
    val detail: StockDetail? = null,
    val chart: StockChart? = null,
    val analysis: StockAnalysis? = null,
    val signals: List<Alert> = emptyList(),
    val isLoading: Boolean = true,
    val error: String? = null,
)

@HiltViewModel
class StockDetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    observeStock: ObserveStockUseCase,
    observeAlertsForTicker: ObserveAlertsForTickerUseCase,
    private val getChart: GetStockChartUseCase,
    private val getAnalysis: GetStockAnalysisUseCase,
    private val refreshStock: RefreshStockUseCase,
) : ViewModel() {

    private val ticker: String = checkNotNull(savedStateHandle["ticker"]) { "ticker is required" }

    private val chart = MutableStateFlow<StockChart?>(null)
    private val analysis = MutableStateFlow<StockAnalysis?>(null)
    private val loading = MutableStateFlow(true)
    private val error = MutableStateFlow<String?>(null)

    val uiState: StateFlow<StockDetailUiState> = combine(
        observeStock(ticker),
        observeAlertsForTicker(ticker),
        chart,
        analysis,
        combine(loading, error) { isLoading, message -> isLoading to message },
    ) { detail, signals, chartData, analysisData, (isLoading, message) ->
        StockDetailUiState(
            ticker = ticker,
            detail = detail,
            chart = chartData,
            analysis = analysisData,
            signals = signals,
            isLoading = isLoading,
            error = message,
        )
    }.stateIn(
        viewModelScope,
        SharingStarted.WhileSubscribed(5_000),
        StockDetailUiState(ticker = ticker),
    )

    init { load() }

    fun load() {
        viewModelScope.launch {
            loading.value = true
            error.value = null
            refreshStock(ticker).onFailure { error.value = it.message }
            getChart(ticker).onSuccess { chart.value = it }.onFailure { error.value = it.message }
            getAnalysis(ticker).onSuccess { analysis.value = it }
            loading.value = false
        }
    }
}
