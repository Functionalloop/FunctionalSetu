package com.jansetu.app.data.sync

import com.jansetu.app.data.SessionStore
import com.jansetu.app.data.local.LocalDb
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Deletes everything this phone holds: background sync, the database file and its key, tokens and
 * the session. The UI watches the session, so it goes to Login by itself (also from a worker).
 * Kept: the last workspace code and user ID (to fill the Login form) and the notice to show there.
 */
@Singleton
class WipeHandler @Inject constructor(
    private val local: LocalDb,
    private val store: SessionStore,
    private val scheduler: SyncScheduler,
) {
    @Synchronized
    fun wipe(notice: String?) {
        scheduler.cancel()
        local.wipe()
        store.signOut(notice)
    }

    companion object {
        const val BLOCKED = "This phone has been blocked by the admin. Its data has been deleted from the phone."
    }
}
