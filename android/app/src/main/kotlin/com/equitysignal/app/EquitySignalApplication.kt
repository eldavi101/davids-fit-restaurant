package com.equitysignal.app

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import com.equitysignal.core.datastore.AppPreferences
import com.equitysignal.core.notifications.AlertNotifier
import com.equitysignal.data.sync.SyncScheduler
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

@HiltAndroidApp
class EquitySignalApplication : Application(), Configuration.Provider {

    @Inject lateinit var workerFactory: HiltWorkerFactory
    @Inject lateinit var syncScheduler: SyncScheduler
    @Inject lateinit var notifier: AlertNotifier
    @Inject lateinit var preferences: AppPreferences

    private val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setWorkerFactory(workerFactory).build()

    override fun onCreate() {
        super.onCreate()
        notifier.ensureChannels()

        // Enqueuing is idempotent (KEEP), so doing this on every start is safe and means
        // background sync survives a reinstall or a force-stop without extra plumbing.
        applicationScope.launch {
            syncScheduler.schedule(preferences.current().syncIntervalMinutes)
        }
    }
}
