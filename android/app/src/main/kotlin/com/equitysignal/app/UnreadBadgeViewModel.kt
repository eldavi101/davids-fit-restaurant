package com.equitysignal.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.equitysignal.domain.ObserveUnreadAlertCountUseCase
import com.equitysignal.domain.SyncNowUseCase
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/**
 * Feeds the bottom-bar badge.
 *
 * The count comes straight from a Room `Flow`, so it updates the moment an alert is read
 * or a sync brings new ones in — no navigation or manual refresh required.
 */
@HiltViewModel
class UnreadBadgeViewModel @Inject constructor(
    observeUnreadCount: ObserveUnreadAlertCountUseCase,
    private val syncNow: SyncNowUseCase,
) : ViewModel() {

    val unreadCount: StateFlow<Int> = observeUnreadCount()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), 0)

    init {
        // Requirement 44: synchronise immediately when the application opens.
        viewModelScope.launch { syncNow() }
    }
}
