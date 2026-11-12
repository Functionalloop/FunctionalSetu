package com.jansetu.app.data

import android.annotation.SuppressLint
import android.content.Context
import android.provider.Settings
import com.jansetu.app.data.local.KeystoreCipher
import com.jansetu.app.data.remote.ApiJson
import com.jansetu.app.data.remote.TokenStore
import com.jansetu.app.data.remote.UserSummary
import com.jansetu.app.data.remote.WorkspaceSummary
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.Serializable
import javax.inject.Inject
import javax.inject.Singleton

/** Who is logged in on this phone and how far setup has got. Kept outside the database (it survives a wipe check). */
@Serializable
data class Session(
    val user: UserSummary,
    val workspace: WorkspaceSummary,
    val deviceStatus: String?,
    val mustChangePassword: Boolean,
    /** Set when the first download has finished; until then the app shows the download screen. */
    val firstSyncDone: Boolean = false,
) {
    val isBoothAgent: Boolean get() = user.role == "booth_agent"
    val canSurvey: Boolean get() = user.role != "booth_agent"
}

/** Tokens encrypted with a Keystore key; the session (no secrets) as plain JSON in private prefs. */
@Singleton
class SessionStore @Inject constructor(@ApplicationContext private val context: Context) : TokenStore {
    private val prefs = context.getSharedPreferences("jansetu_session", Context.MODE_PRIVATE)
    private val cipher = KeystoreCipher("jansetu_tokens")

    @Volatile private var access: String? = read(ACCESS)
    @Volatile private var refresh: String? = read(REFRESH)

    private val _session = MutableStateFlow(
        prefs.getString(SESSION, null)?.let { runCatching { ApiJson.decodeFromString<Session>(it) }.getOrNull() },
    )
    val session: StateFlow<Session?> = _session

    override val accessToken: String? get() = access
    override val refreshToken: String? get() = refresh

    @Synchronized
    override fun saveTokens(access: String, refresh: String) {
        this.access = access
        this.refresh = refresh
        prefs.edit().putString(ACCESS, cipher.encrypt(access.toByteArray()))
            .putString(REFRESH, cipher.encrypt(refresh.toByteArray())).commit()
    }

    @Synchronized
    override fun clearTokens() {
        access = null
        refresh = null
        prefs.edit().remove(ACCESS).remove(REFRESH).commit()
    }

    fun saveSession(s: Session) {
        _session.value = s
        prefs.edit().putString(SESSION, ApiJson.encodeToString(Session.serializer(), s)).commit()
    }

    fun update(change: (Session) -> Session) {
        _session.value?.let { saveSession(change(it)) }
    }


    /**
     * Ends the session on this phone: forgets tokens and session, keeps the last workspace code and
     * user ID, and stores [notice] for the Login screen. The session is cleared last, because
     * clearing it shows Login at once and Login reads the notice when it appears.
     */
    @Synchronized
    fun signOut(notice: String?) {
        val last = lastLogin
        clearTokens()
        prefs.edit().clear().commit()
        cipher.deleteKey()
        lastLogin = last
        this.notice = notice
        _session.value = null
    }

    /** Last workspace code and user ID typed, to fill the Login form next time. */
    var lastLogin: Pair<String, String>?
        get() = prefs.getString(LAST_WS, null)?.let { it to (prefs.getString(LAST_USER, null) ?: "") }
        set(v) { prefs.edit().putString(LAST_WS, v?.first).putString(LAST_USER, v?.second).commit() }

    /** One message for the Login screen (why the user was sent back to it). Read once. */
    var notice: String?
        get() = prefs.getString(NOTICE, null)
        set(v) { prefs.edit().putString(NOTICE, v).commit() }

    /** Stays the same across reinstalls (per signing key), so a reinstalled phone is not a new device. */
    @SuppressLint("HardwareIds")
    fun deviceUid(): String = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) ?: "unknown"

    private fun read(key: String): String? =
        prefs.getString(key, null)?.let { runCatching { String(cipher.decrypt(it)) }.getOrNull() }

    private companion object {
        const val ACCESS = "access"
        const val REFRESH = "refresh"
        const val SESSION = "session"
        const val LAST_WS = "last_ws"
        const val LAST_USER = "last_user"
        const val NOTICE = "notice"
    }
}
