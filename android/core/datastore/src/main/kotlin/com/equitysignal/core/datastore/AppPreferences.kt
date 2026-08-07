package com.equitysignal.core.datastore

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "equity_signal_prefs")

data class AppSettings(
    val baseUrl: String,
    val apiKey: String,
    val notificationsEnabled: Boolean,
    val buyNotifications: Boolean,
    val sellNotifications: Boolean,
    val syncIntervalMinutes: Long,
    val darkTheme: Boolean,
    val lastSyncCursor: String?,
    val lastSyncAtUtc: Long?,
) {
    val isConfigured: Boolean get() = baseUrl.isNotBlank() && apiKey.isNotBlank()
}

/**
 * User preferences.
 *
 * The API key stored here is the *only* credential the app holds. Market-data vendor keys
 * never leave the backend (requirement 52), so this value grants access to the user's own
 * server and nothing else.
 */
@Singleton
class AppPreferences @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private object Keys {
        val BASE_URL = stringPreferencesKey("base_url")
        val API_KEY = stringPreferencesKey("api_key")
        val NOTIFICATIONS = booleanPreferencesKey("notifications_enabled")
        val BUY_NOTIFICATIONS = booleanPreferencesKey("buy_notifications")
        val SELL_NOTIFICATIONS = booleanPreferencesKey("sell_notifications")
        val SYNC_INTERVAL = longPreferencesKey("sync_interval_minutes")
        val DARK_THEME = booleanPreferencesKey("dark_theme")
        val SYNC_CURSOR = stringPreferencesKey("sync_cursor")
        val LAST_SYNC = longPreferencesKey("last_sync_at")
    }

    companion object {
        const val DEFAULT_BASE_URL = "http://10.0.2.2:8000/api/v1/"
        const val DEFAULT_SYNC_INTERVAL_MINUTES = 15L
    }

    val settings: Flow<AppSettings> = context.dataStore.data.map { prefs ->
        AppSettings(
            baseUrl = prefs[Keys.BASE_URL] ?: DEFAULT_BASE_URL,
            apiKey = prefs[Keys.API_KEY].orEmpty(),
            notificationsEnabled = prefs[Keys.NOTIFICATIONS] ?: true,
            buyNotifications = prefs[Keys.BUY_NOTIFICATIONS] ?: true,
            sellNotifications = prefs[Keys.SELL_NOTIFICATIONS] ?: true,
            syncIntervalMinutes = prefs[Keys.SYNC_INTERVAL] ?: DEFAULT_SYNC_INTERVAL_MINUTES,
            darkTheme = prefs[Keys.DARK_THEME] ?: true,
            lastSyncCursor = prefs[Keys.SYNC_CURSOR],
            lastSyncAtUtc = prefs[Keys.LAST_SYNC],
        )
    }

    suspend fun current(): AppSettings = settings.first()

    suspend fun setConnection(baseUrl: String, apiKey: String) {
        context.dataStore.edit {
            it[Keys.BASE_URL] = baseUrl.trim()
            it[Keys.API_KEY] = apiKey.trim()
        }
    }

    suspend fun setNotifications(enabled: Boolean, buy: Boolean, sell: Boolean) {
        context.dataStore.edit {
            it[Keys.NOTIFICATIONS] = enabled
            it[Keys.BUY_NOTIFICATIONS] = buy
            it[Keys.SELL_NOTIFICATIONS] = sell
        }
    }

    suspend fun setSyncInterval(minutes: Long) {
        context.dataStore.edit { it[Keys.SYNC_INTERVAL] = minutes.coerceAtLeast(15L) }
    }

    suspend fun setDarkTheme(dark: Boolean) {
        context.dataStore.edit { it[Keys.DARK_THEME] = dark }
    }

    /** Advances the delta-sync cursor after a successful sync. */
    suspend fun setSyncCursor(cursor: String?, syncedAtUtc: Long) {
        context.dataStore.edit {
            if (cursor != null) it[Keys.SYNC_CURSOR] = cursor
            it[Keys.LAST_SYNC] = syncedAtUtc
        }
    }
}

@Module
@InstallIn(SingletonComponent::class)
object DataStoreModule {
    @Provides
    @Singleton
    fun providePreferences(@ApplicationContext context: Context): AppPreferences =
        AppPreferences(context)
}
