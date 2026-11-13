package com.jansetu.app.data.sync

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.jansetu.app.data.SessionStore
import com.jansetu.app.data.UpdateChecker
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.sync.withLock

/** Push the outbox, then a delta pull (5.11). Runs every 15 minutes and on "Sync now". */
@HiltWorker
class SyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val sync: SyncRepository,
    private val store: SessionStore,
    private val wipe: WipeHandler,
    private val updates: UpdateChecker,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val session = store.session.value ?: return Result.failure()
        if (!session.firstSyncDone || session.deviceStatus == "pending") return Result.success()
        if (updates.required.value != null) return Result.success() // too old: send nothing until updated (7.9)
        val outcome = sync.lock.withLock { sync.syncNow() }
        return when (outcome) {
            SyncOutcome.Done -> Result.success()
            SyncOutcome.Wipe -> {
                wipe.wipe(WipeHandler.BLOCKED)
                Result.failure()
            }
            is SyncOutcome.Failed ->
                if (outcome.offline && runAttemptCount < 5) Result.retry()
                else Result.failure(workDataOf(PullWorker.ERROR to outcome.message))
        }
    }
}
