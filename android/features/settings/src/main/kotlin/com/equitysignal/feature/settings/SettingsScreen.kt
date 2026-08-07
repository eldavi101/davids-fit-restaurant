package com.equitysignal.feature.settings

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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.equitysignal.core.designsystem.Chip
import com.equitysignal.core.designsystem.ErrorBanner
import com.equitysignal.core.designsystem.FinancialCard
import com.equitysignal.core.designsystem.FinancialColors
import com.equitysignal.core.designsystem.SectionLabel
import com.equitysignal.core.model.SettingField
import com.equitysignal.core.model.StrategySettings
import com.equitysignal.domain.ConnectionSettings
import com.equitysignal.domain.GetStrategySettingsUseCase
import com.equitysignal.domain.ObserveConnectionUseCase
import com.equitysignal.domain.UpdateConnectionUseCase
import com.equitysignal.domain.UpdateNotificationPreferencesUseCase
import com.equitysignal.domain.UpdateStrategySettingUseCase
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class SettingsUiState(
    val connection: ConnectionSettings? = null,
    val strategy: StrategySettings? = null,
    val message: String? = null,
    val error: String? = null,
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    observeConnection: ObserveConnectionUseCase,
    private val updateConnection: UpdateConnectionUseCase,
    private val updateNotifications: UpdateNotificationPreferencesUseCase,
    private val getStrategySettings: GetStrategySettingsUseCase,
    private val updateStrategySetting: UpdateStrategySettingUseCase,
) : ViewModel() {

    private val strategy = MutableStateFlow<StrategySettings?>(null)
    private val message = MutableStateFlow<String?>(null)
    private val error = MutableStateFlow<String?>(null)

    val uiState: StateFlow<SettingsUiState> =
        combine(observeConnection(), strategy, message, error) { connection, strategySettings, note, problem ->
            SettingsUiState(connection, strategySettings, note, problem)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), SettingsUiState())

    init { loadStrategy() }

    fun loadStrategy() {
        viewModelScope.launch {
            getStrategySettings()
                .onSuccess { strategy.value = it; error.value = null }
                .onFailure { error.value = it.message }
        }
    }

    fun saveConnection(baseUrl: String, apiKey: String) {
        viewModelScope.launch {
            updateConnection(baseUrl, apiKey)
            message.value = "Connection saved"
            loadStrategy()
        }
    }

    fun setNotifications(enabled: Boolean, buy: Boolean, sell: Boolean) {
        viewModelScope.launch { updateNotifications(enabled, buy, sell) }
    }

    fun updateSetting(field: SettingField, value: String) {
        viewModelScope.launch {
            message.value = null
            error.value = null
            // A versioned parameter changes how stocks are judged, so it can only be
            // published as a new strategy version — never edited in place.
            updateStrategySetting(field.key, value, createVersion = field.versioned)
                .onSuccess {
                    strategy.value = it
                    message.value = if (field.versioned) {
                        "Published as strategy version ${it.strategyVersion}"
                    } else {
                        "${field.key} updated"
                    }
                }
                .onFailure { error.value = it.message }
        }
    }
}

@Composable
fun SettingsScreen(viewModel: SettingsViewModel = hiltViewModel()) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val connection = state.connection

    var baseUrl by remember(connection?.baseUrl) { mutableStateOf(connection?.baseUrl.orEmpty()) }
    var apiKey by remember(connection?.apiKey) { mutableStateOf(connection?.apiKey.orEmpty()) }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        state.error?.let { item { ErrorBanner(it) } }
        state.message?.let {
            item {
                Text(it, style = MaterialTheme.typography.bodySmall, color = FinancialColors.Gain)
            }
        }

        item {
            FinancialCard {
                Column {
                    SectionLabel("Backend connection")
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = baseUrl,
                        onValueChange = { baseUrl = it },
                        label = { Text("Base URL") },
                        placeholder = { Text("https://your-host/api/v1/") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = apiKey,
                        onValueChange = { apiKey = it },
                        label = { Text("API key") },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "This is the only credential the app stores. Market-data provider keys " +
                            "stay on your backend and are never sent to this device.",
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                    Spacer(Modifier.height(10.dp))
                    Button(
                        onClick = { viewModel.saveConnection(baseUrl, apiKey) },
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("Save connection") }
                }
            }
        }

        item {
            FinancialCard {
                Column {
                    SectionLabel("Local notifications")
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "Notifications are posted on this device only, and always link to an " +
                            "alert already stored in the app. Nothing is sent to any external " +
                            "service.",
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                    Spacer(Modifier.height(8.dp))
                    ToggleRow("Enabled", connection?.notificationsEnabled == true) {
                        viewModel.setNotifications(
                            it,
                            connection?.buyNotifications != false,
                            connection?.sellNotifications != false,
                        )
                    }
                    ToggleRow("BUY signals", connection?.buyNotifications == true) {
                        viewModel.setNotifications(
                            connection?.notificationsEnabled != false, it,
                            connection?.sellNotifications != false,
                        )
                    }
                    ToggleRow("SELL signals", connection?.sellNotifications == true) {
                        viewModel.setNotifications(
                            connection?.notificationsEnabled != false,
                            connection?.buyNotifications != false, it,
                        )
                    }
                }
            }
        }

        item {
            FinancialCard {
                Column {
                    SectionLabel("Strategy")
                    Spacer(Modifier.height(6.dp))
                    Text(
                        state.strategy?.strategyVersion ?: "—",
                        style = MaterialTheme.typography.titleMedium,
                        color = FinancialColors.OnSurface,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        state.strategy?.description.orEmpty(),
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                    Spacer(Modifier.height(8.dp))
                    Chip("PAPER TRADING", FinancialColors.Accent, filled = true)
                }
            }
        }

        val fields = state.strategy?.fields.orEmpty()
        if (fields.isNotEmpty()) {
            item { SectionLabel("Strategy parameters") }
            items(fields, key = { "${it.section}.${it.key}" }) { field ->
                SettingFieldRow(field) { viewModel.updateSetting(field, it) }
            }
        }
    }
}

@Composable
private fun ToggleRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = FinancialColors.OnSurface)
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@Composable
private fun SettingFieldRow(field: SettingField, onSave: (String) -> Unit) {
    var value by remember(field.value) { mutableStateOf(field.value) }
    FinancialCard {
        Column {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        field.key.replace('_', ' '),
                        style = MaterialTheme.typography.bodyMedium,
                        color = FinancialColors.OnSurface,
                    )
                    Text(
                        "${field.section} · default ${field.default}",
                        style = MaterialTheme.typography.labelSmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                }
                if (field.versioned) Chip("VERSIONED", FinancialColors.Watch)
            }
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(
                value = value,
                onValueChange = { value = it },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            if (field.versioned) {
                Spacer(Modifier.height(4.dp))
                Text(
                    "Changing this publishes a new strategy version so existing alerts stay " +
                        "comparable with the logic that produced them.",
                    style = MaterialTheme.typography.labelSmall,
                    color = FinancialColors.OnSurfaceMuted,
                )
            }
            Spacer(Modifier.height(6.dp))
            Button(
                onClick = { onSave(value) },
                enabled = value != field.value,
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (field.versioned) "Publish new version" else "Save") }
        }
    }
}
