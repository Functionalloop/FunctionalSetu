package com.jansetu.app.data.remote

import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import okhttp3.Authenticator
import okhttp3.Interceptor
import okhttp3.Request
import okhttp3.Response
import okhttp3.Route

interface TokenStore {
    val accessToken: String?
    val refreshToken: String?
    fun saveTokens(access: String, refresh: String)
    fun clearTokens()
}

/** Things any API call can find out that end the session; the app reacts in one place (MainActivity). */
sealed interface SessionEvent {
    /** Refresh token no longer works (expired, logged out elsewhere, account disabled). */
    data class LoggedOut(val message: String) : SessionEvent

    /** 403 device_blocked: delete the local database and go to Login (context/sync.md). */
    data object Blocked : SessionEvent
}

/** Buffered until the app reads it (an event raised by a background sync is not lost); never replayed. */
class SessionEvents {
    private val channel = Channel<SessionEvent>(capacity = 16, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val events: Flow<SessionEvent> = channel.receiveAsFlow()
    fun send(e: SessionEvent) { channel.trySend(e) }
}

private fun Response.errorCode(): String? =
    runCatching { ApiJson.decodeFromString<ErrorResponse>(peekBody(8192).string()).error.code }.getOrNull()

private fun Request.withToken(token: String): Request =
    newBuilder().header("Authorization", "Bearer $token").build()

/** Adds the access token to every call except login/refresh (which carry no token). */
class AuthInterceptor(private val tokens: TokenStore, private val events: SessionEvents) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val token = tokens.accessToken
        val request = chain.request().let { if (token != null && it.header("Authorization") == null) it.withToken(token) else it }
        val response = chain.proceed(request)
        if (response.code == 403 && response.errorCode() == "device_blocked") events.send(SessionEvent.Blocked)
        return response
    }
}

/**
 * On 401 token_expired: refresh once and repeat the call. Synchronized, so ten calls failing
 * together cause one refresh; the others see the new token and just retry.
 */
class TokenAuthenticator(
    private val tokens: TokenStore,
    private val refreshApi: RefreshApi,
    private val events: SessionEvents,
) : Authenticator {
    override fun authenticate(route: Route?, response: Response): Request? {
        val sent = response.request.header("Authorization")?.removePrefix("Bearer ") ?: return null
        if (response.priorResponse != null) return null // this call was already retried once
        if (response.errorCode() != "token_expired") return null

        synchronized(this) {
            val current = tokens.accessToken
            if (current != null && current != sent) return response.request.withToken(current)
            val refresh = tokens.refreshToken ?: return null

            return when (val r = refreshNow(refresh)) {
                is ApiResult.Ok -> {
                    tokens.saveTokens(r.value.accessToken, r.value.refreshToken)
                    response.request.withToken(r.value.accessToken)
                }
                is ApiResult.Err -> {
                    if (r.code == "device_blocked") {
                        events.send(SessionEvent.Blocked)
                    } else if (r.status == 401 || r.status == 403) {
                        tokens.clearTokens()
                        events.send(SessionEvent.LoggedOut(r.message))
                    }
                    null
                }
                is ApiResult.Offline -> null
            }
        }
    }

    private fun refreshNow(refresh: String): ApiResult<AuthTokens> = try {
        val r = refreshApi.refresh(RefreshRequest(refresh)).execute()
        val body = r.body()
        if (r.isSuccessful && body != null) ApiResult.Ok(body) else parseError(r.code(), r.errorBody()?.string())
    } catch (e: java.io.IOException) {
        ApiResult.Offline(e)
    }
}
