package com.jansetu.app.data

import android.os.Build
import com.jansetu.app.BuildConfig
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.ChangePasswordRequest
import com.jansetu.app.data.remote.DeviceInfo
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.LoginRequest
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.apiCallNoBody
import com.jansetu.app.data.sync.WipeHandler
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SessionRepository @Inject constructor(
    private val api: JansetuApi,
    private val store: SessionStore,
    private val local: LocalDb,
    private val wipeHandler: WipeHandler,
) {
    val session = store.session

    /** The password typed at login, in memory only, so Set password does not ask for it again. */
    @Volatile var loginPassword: String? = null
        private set

    suspend fun login(workspace: String, username: String, password: String): ApiResult<Unit> = withContext(Dispatchers.IO) {
        val device = DeviceInfo(
            deviceUid = store.deviceUid(),
            model = "${Build.MANUFACTURER} ${Build.MODEL}".take(100),
            osVersion = "Android ${Build.VERSION.RELEASE}",
            appVersionCode = BuildConfig.VERSION_CODE,
        )
        when (val r = apiCall { api.login(LoginRequest(workspace.trim(), username.trim(), password, device)) }) {
            is ApiResult.Ok -> {
                val t = r.value
                // Data left by another user or workspace must never be shown to this one.
                val previousOwner = local.owner()
                if (previousOwner != null && previousOwner != t.user.id) local.wipe()
                local.setOwner(t.user.id)
                store.saveTokens(t.accessToken, t.refreshToken)
                store.lastLogin = workspace.trim() to username.trim()
                store.notice = null
                loginPassword = if (t.mustChangePassword) password else null
                store.saveSession(
                    Session(
                        user = t.user, workspace = t.workspace, deviceStatus = t.device?.status,
                        mustChangePassword = t.mustChangePassword,
                        firstSyncDone = previousOwner == t.user.id && local.firstSyncDone(),
                    ),
                )
                ApiResult.Ok(Unit)
            }
            is ApiResult.Err -> r
            is ApiResult.Offline -> r
        }
    }

    suspend fun changePassword(current: String, new: String): ApiResult<Unit> = withContext(Dispatchers.IO) {
        val r = apiCallNoBody { api.changePassword(ChangePasswordRequest(current, new)) }
        if (r is ApiResult.Ok) {
            loginPassword = null
            store.update { it.copy(mustChangePassword = false) }
        }
        r
    }

    /** Asks the server whether an admin has approved this phone yet. */
    suspend fun refreshDeviceStatus(): ApiResult<String> = withContext(Dispatchers.IO) {
        when (val r = apiCall { api.myDevice() }) {
            is ApiResult.Ok -> {
                store.update { it.copy(deviceStatus = r.value.status) }
                ApiResult.Ok(r.value.status)
            }
            is ApiResult.Err -> r
            is ApiResult.Offline -> r
        }
    }

    fun markFirstSyncDone() {
        local.setFirstSyncDone()
        store.update { it.copy(firstSyncDone = true) }
    }

    /**
     * Ends the session on the server (best effort) and deletes everything on the phone:
     * the next user of this phone must not see this user's voters. Unsent changes are lost,
     * so the UI warns first when the outbox is not empty.
     */
    suspend fun logout() = withContext(Dispatchers.IO) {
        if (store.accessToken != null) apiCallNoBody { api.logout() }
        endLocally()
    }

    fun endLocally() = wipeHandler.wipe(notice = null)
}
