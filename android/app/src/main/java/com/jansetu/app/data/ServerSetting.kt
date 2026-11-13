package com.jansetu.app.data

import android.content.Context
import com.jansetu.app.BuildConfig
import com.jansetu.app.data.remote.ServerAddress
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Which server the app talks to. Debug build only: an address typed on the Login screen (laptop
 * fallback, plan 6.6), kept in its own prefs file so logging out does not forget it. The release
 * build ignores it and always uses BuildConfig.API_URL.
 */
@Singleton
class ServerSetting @Inject constructor(@ApplicationContext context: Context) {
    private val prefs = context.getSharedPreferences("jansetu_server", Context.MODE_PRIVATE)
    val default: HttpUrl = BuildConfig.API_URL.toHttpUrl()
    val canChange: Boolean = BuildConfig.DEBUG

    private val _current = MutableStateFlow(read())
    val current: StateFlow<HttpUrl> = _current

    /** Saves the typed address; false if it is not an address. Only on the Login screen (no session yet). */
    fun set(input: String): Boolean {
        if (!canChange) return false
        val url = ServerAddress.normalize(input) ?: return false
        prefs.edit().putString(KEY, url.toString()).commit()
        _current.value = url
        return true
    }

    fun reset() {
        prefs.edit().remove(KEY).commit()
        _current.value = default
    }

    private fun read(): HttpUrl =
        if (!canChange) default else prefs.getString(KEY, null)?.let(ServerAddress::normalize) ?: default

    private companion object { const val KEY = "server" }
}
