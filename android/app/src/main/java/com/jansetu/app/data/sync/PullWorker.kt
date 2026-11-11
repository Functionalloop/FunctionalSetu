package com.jansetu.app.data.sync

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.jansetu.app.data.SessionStore
import com.jansetu.app.data.local.LocalDb
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.sync.withLock

/** Errors after which trying again cannot help: the login itself is gone. */
internal val DEAD_LOGIN = setOf("session_ended", "invalid_token", "invalid_refresh_token", "account_disabled", "workspace_suspended")

/**
 * First download (5.6). Each page is saved with its cursor, so if the app or phone is closed the
 * next run resumes from the last saved page. Progress: "done" voters on the phone of "total".
 */
@HiltWorker
class PullWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val sync: SyncRepository,
    private val local: LocalDb,
    private val store: SessionStore,
    private val wipe: WipeHandler,
    private val scheduler: SyncScheduler,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        if (store.session.value == null) return Result.failure()
        val outcome = sync.lock.withLock {
            sync.pull(onProgress = { done, total -> setProgress(workDataOf(DONE to done, TOTAL to (total ?: -1))) })
        }
        return when (outcome) {
            SyncOutcome.Done -> {
                local.setFirstSyncDone()
                store.update { it.copy(firstSyncDone = true) }
                scheduler.startPeriodic()
                Result.success()
            }
            SyncOutcome.Wipe -> {
                wipe.wipe(WipeHandler.BLOCKED)
                Result.failure()
            }
            is SyncOutcome.Failed ->
                if (outcome.code in DEAD_LOGIN) Result.failure(workDataOf(ERROR to outcome.message))
                else Result.retry()
        }
    }

    companion object {
        const val DONE = "done"
        const val TOTAL = "total"
        const val ERROR = "error"
    }
}
