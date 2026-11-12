package com.jansetu.app.data.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SyncScheduler @Inject constructor(@ApplicationContext private val context: Context) {
    private val wm get() = WorkManager.getInstance(context)
    private val online = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    /** Every 15 minutes while there is a network (the shortest period Android allows). */
    fun startPeriodic() {
        wm.enqueueUniquePeriodicWork(
            PERIODIC, ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
                .setConstraints(online)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.MINUTES)
                .build(),
        )
    }

    /** "Sync now", and after each survey save. Waits for a network if there is none. */
    fun syncNow() {
        wm.enqueueUniqueWork(
            NOW, ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<SyncWorker>()
                .setConstraints(online)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build(),
        )
    }

    /** First download; carries on after the app is closed, and resumes from the last saved page. */
    fun firstDownload() {
        wm.enqueueUniqueWork(
            FIRST, ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<PullWorker>()
                .setConstraints(online)
                .setBackoffCriteria(BackoffPolicy.LINEAR, 15, TimeUnit.SECONDS)
                .build(),
        )
    }

    fun firstDownloadInfo(): Flow<WorkInfo?> = wm.getWorkInfosForUniqueWorkFlow(FIRST).map { it.firstOrNull() }
    fun syncNowInfo(): Flow<WorkInfo?> = wm.getWorkInfosForUniqueWorkFlow(NOW).map { it.firstOrNull() }

    fun cancel() {
        wm.cancelUniqueWork(PERIODIC)
        wm.cancelUniqueWork(NOW)
        wm.cancelUniqueWork(FIRST)
    }

    companion object {
        const val PERIODIC = "sync_periodic"
        const val NOW = "sync_now"
        const val FIRST = "first_download"
    }
}
