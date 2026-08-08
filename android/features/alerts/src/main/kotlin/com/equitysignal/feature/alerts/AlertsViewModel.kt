package com.equitysignal.feature.alerts

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.equitysignal.core.model.Alert
import com.equitysignal.domain.AlertsTab
import com.equitysignal.domain.ArchiveAlertUseCase
import com.equitysignal.domain.ObserveAlertsUseCase
import com.equitysignal.domain.ObserveUnreadAlertCountUseCase
import com.equitysignal.domain.RefreshAlertsUseCase
import com.equitysignal.domain.SyncNowUseCase
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

sealed interface AlertsUiState {
    data object Loading : AlertsUiState

    data class Ready(
        val tab: AlertsTab,
        val alerts: List<Alert>,
        val unreadCount: Int,
        val lastUpdatedUtc: Long?,
        val isRefreshing: Boolean,
        val error: String?,
    ) : AlertsUiState
}

@HiltViewModel
class AlertsViewModel @Inject constructor(
    private val observeAlerts: ObserveAlertsUseCase,
    private val observeUnreadCount: ObserveUnreadAlertCountUseCase,
    private val refreshAlerts: RefreshAlertsUseCase,
    private val archiveAlert: ArchiveAlertUseCase,
    private val syncNow: SyncNowUseCase,
) : ViewModel() {

    private val selectedTab = MutableStateFlow(AlertsTab.ALL)
    private val refreshing = MutableStateFlow(false)
    private val error = MutableStateFlow<String?>(null)

    /**
     * The tab is captured *inside* `flatMapLatest`, not combined alongside it.
     *
     * Feeding `selectedTab` into the combine as its own source made the tab and the list
     * two independent inputs, so a tab switch produced a transient state pairing the new
     * tab with the previous tab's alerts — the CLOSED tab briefly showing open trades.
     * Deriving both from one emission makes that state unrepresentable.
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    val uiState: StateFlow<AlertsUiState> =
        selectedTab.flatMapLatest { tab ->
            combine(
                observeAlerts(tab),
                observeUnreadCount(),
                refreshing,
                error,
            ) { alerts, unread, isRefreshing, errorMessage ->
                AlertsUiState.Ready(
                    tab = tab,
                    alerts = alerts,
                    unreadCount = unread,
                    lastUpdatedUtc = alerts.maxOfOrNull { it.fetchedAtUtc },
                    isRefreshing = isRefreshing,
                    // The error sits *beside* the cached list, never in place of it: an
                    // alert the user already has must stay readable when the network is
                    // down.
                    error = errorMessage,
                )
            }
        }.stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = AlertsUiState.Loading,
        )

    init {
        refresh()
    }

    fun selectTab(tab: AlertsTab) {
        selectedTab.value = tab
    }

    fun refresh() {
        if (refreshing.value) return
        viewModelScope.launch {
            refreshing.value = true
            error.value = null
            // Sync first (it also posts notifications for anything new), then reconcile
            // the alert list itself.
            syncNow()
            refreshAlerts().onFailure { error.value = it.message ?: "Could not refresh alerts" }
            refreshing.value = false
        }
    }

    fun archive(alertUid: String, archived: Boolean) {
        viewModelScope.launch { archiveAlert(alertUid, archived) }
    }

    fun dismissError() {
        error.value = null
    }
}
