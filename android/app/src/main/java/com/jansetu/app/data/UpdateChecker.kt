package com.jansetu.app.data

import android.content.Context
import com.jansetu.app.BuildConfig
import com.jansetu.app.data.remote.ApiJson
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.AppVersion
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.apiCall
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import javax.inject.Inject
import javax.inject.Singleton

/** What the Update required screen shows. [apkUrl] is null when the server has not told us yet. */
data class UpdateRequired(val minVersionCode: Int, val apkUrl: String?)

/**
 * The app must update when its version is below the higher of the two minimums: the server's
 * (GET /app/version, a release published with --required) and the workspace's
 * (settings.min_app_version_code from the pull).
 */
fun updateRequired(appVersionCode: Int, serverMin: Int, workspaceMin: Int, apkUrl: String?): UpdateRequired? {
    val min = maxOf(serverMin, workspaceMin)
    return if (appVersionCode < min) UpdateRequired(min, apkUrl) else null
}

/** min_app_version_code from the pull settings JSON; 1 (nothing forced) when it is missing. */
fun workspaceMinVersion(settingsJson: String?): Int = settingsJson?.let {
    runCatching { ApiJson.parseToJsonElement(it).jsonObject["min_app_version_code"]?.jsonPrimitive?.intOrNull }.getOrNull()
} ?: 1

/**
 * Update required (7.9). The two minimums are kept in their own prefs file, so the gate holds
 * offline and after a restart. The server's is checked when the app starts and on "Check again".
 */
@Singleton
class UpdateChecker @Inject constructor(@ApplicationContext context: Context, private val api: JansetuApi) {
    private val prefs = context.getSharedPreferences("jansetu_update", Context.MODE_PRIVATE)
    private val _required = MutableStateFlow(compute())
    val required: StateFlow<UpdateRequired?> = _required

    suspend fun check(): ApiResult<AppVersion> {
        val r = apiCall { api.appVersion() }
        when {
            r is ApiResult.Ok -> prefs.edit().putInt(SERVER_MIN, r.value.minVersionCode).putString(APK_URL, r.value.apkUrl).apply()
            r is ApiResult.Err && r.status == 404 -> prefs.edit().remove(SERVER_MIN).remove(APK_URL).apply() // none published
        }
        _required.value = compute()
        return r
    }

    /** Called with the stored pull settings whenever they change. */
    fun noteSettings(settingsJson: String?) {
        if (settingsJson == null) return
        prefs.edit().putInt(WORKSPACE_MIN, workspaceMinVersion(settingsJson)).apply()
        _required.value = compute()
    }

    /** After logout: the next login may be another workspace. */
    fun forgetWorkspace() {
        prefs.edit().remove(WORKSPACE_MIN).apply()
        _required.value = compute()
    }

    private fun compute() = updateRequired(
        BuildConfig.VERSION_CODE, prefs.getInt(SERVER_MIN, 1), prefs.getInt(WORKSPACE_MIN, 1), prefs.getString(APK_URL, null),
    )

    private companion object {
        const val SERVER_MIN = "server_min"
        const val WORKSPACE_MIN = "workspace_min"
        const val APK_URL = "apk_url"
    }
}
