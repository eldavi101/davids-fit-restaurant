package com.equitysignal.feature.alerts

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.equitysignal.core.model.Alert
import com.equitysignal.core.model.AlertEvent
import com.equitysignal.domain.MarkAlertReadUseCase
import com.equitysignal.domain.ObserveAlertTimelineUseCase
import com.equitysignal.domain.ObserveAlertUseCase
import com.equitysignal.domain.RefreshAlertsUseCase
import com.equitysignal.domain.RefreshTimelineUseCase
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

sealed interface AlertDetailUiState {
    data object Loading : AlertDetailUiState
    data object Missing : AlertDetailUiState
    data class Ready(val alert: Alert, val timeline: List<AlertEvent>) : AlertDetailUiState
}

@HiltViewModel
class AlertDetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    observeAlert: ObserveAlertUseCase,
    observeTimeline: ObserveAlertTimelineUseCase,
    private val markRead: MarkAlertReadUseCase,
    private val refreshTimeline: RefreshTimelineUseCase,
    private val refreshAlerts: RefreshAlertsUseCase,
) : ViewModel() {

    private val alertUid: String = checkNotNull(savedStateHandle["alertUid"]) {
        "alertUid is required to open an alert"
    }

    val uiState: StateFlow<AlertDetailUiState> =
        combine(observeAlert(alertUid), observeTimeline(alertUid)) { alert, timeline ->
            if (alert == null) AlertDetailUiState.Missing
            else AlertDetailUiState.Ready(alert, timeline)
        }.stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = AlertDetailUiState.Loading,
        )

    init {
        // Opening the detail screen is what marks an alert read. Nothing deletes it
        // (requirement 5) — read is a separate, local flag.
        viewModelScope.launch { markRead(alertUid) }
        viewModelScope.launch {
            refreshTimeline(alertUid)
            // A cold deep link from a notification may land before the alert has synced.
            if (uiState.value is AlertDetailUiState.Missing) {
                refreshAlerts()
                refreshTimeline(alertUid)
            }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            refreshAlerts()
            refreshTimeline(alertUid)
        }
    }
}
