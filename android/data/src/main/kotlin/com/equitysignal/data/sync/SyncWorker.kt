package com.equitysignal.data.sync

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.equitysignal.domain.SyncOutcome
import com.equitysignal.domain.SyncRepository
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Background synchronisation (requirement 44).
 *
 * The backend keeps scanning and monitoring whether or not the app is running; this worker
 * simply pulls the results in. It is therefore safe for it to be delayed or skipped — no
 * signal is lost, only its arrival on the phone is late.
 */
@HiltWorker
class SyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val syncRepository: SyncRepository,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result = when (val outcome = syncRepository.sync()) {
        is SyncOutcome.Success -> Result.success()
        // Nothing to retry against until the user configures a backend.
        SyncOutcome.NotConfigured -> Result.success()
        is SyncOutcome.Failure ->
            if (runAttemptCount < MAX_ATTEMPTS) Result.retry() else Result.failure()
    }

    companion object {
        const val UNIQUE_NAME = "equity_signal_sync"
        const val MAX_ATTEMPTS = 4
    }
}

@Singleton
class SyncScheduler @Inject constructor(
    private val workManager: WorkManager,
) {
    /**
     * Enqueues the periodic sync. `KEEP` makes re-enqueueing idempotent, so calling this on
     * every app start (and after boot) cannot stack duplicate work.
     */
    fun schedule(intervalMinutes: Long) {
        val request = PeriodicWorkRequestBuilder<SyncWorker>(
            intervalMinutes.coerceAtLeast(15L), TimeUnit.MINUTES,
        )
            .setConstraints(
                Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .addTag(SyncWorker.UNIQUE_NAME)
            .build()

        workManager.enqueueUniquePeriodicWork(
            SyncWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
    }

    /** Called when the user changes the sync cadence in Settings. */
    fun reschedule(intervalMinutes: Long) {
        val request = PeriodicWorkRequestBuilder<SyncWorker>(
            intervalMinutes.coerceAtLeast(15L), TimeUnit.MINUTES,
        )
            .setConstraints(
                Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .addTag(SyncWorker.UNIQUE_NAME)
            .build()

        workManager.enqueueUniquePeriodicWork(
            SyncWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.UPDATE,
            request,
        )
    }

    fun cancel() {
        workManager.cancelUniqueWork(SyncWorker.UNIQUE_NAME)
    }
}
