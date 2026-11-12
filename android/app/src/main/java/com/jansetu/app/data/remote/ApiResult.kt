package com.jansetu.app.data.remote

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import retrofit2.HttpException
import java.io.IOException
import kotlin.coroutines.cancellation.CancellationException

sealed interface ApiResult<out T> {
    data class Ok<T>(val value: T) : ApiResult<T>

    /** The server answered with an error body: `{"error": {"code", "message"}}`. */
    data class Err(val status: Int, val code: String, val message: String, val current: JsonObject? = null) : ApiResult<Nothing>

    /** No answer: no network, timeout, server down. Safe to retry. */
    data class Offline(val cause: IOException) : ApiResult<Nothing>
}

val ApiJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    encodeDefaults = true
    coerceInputValues = true
}

/** Message for the user. Server messages are already written for people. */
fun ApiResult<*>.userMessage(): String? = when (this) {
    is ApiResult.Ok -> null
    is ApiResult.Err -> message
    is ApiResult.Offline -> "No connection to the server. Check the internet and try again."
}

fun parseError(status: Int, body: String?): ApiResult.Err {
    val parsed = body?.takeIf { it.isNotBlank() }?.let { runCatching { ApiJson.decodeFromString<ErrorResponse>(it) }.getOrNull() }
    return if (parsed != null) {
        ApiResult.Err(status, parsed.error.code, parsed.error.message, parsed.error.current)
    } else {
        ApiResult.Err(status, "http_$status", "The server could not handle the request (error $status). Try again later.")
    }
}

suspend fun <T> apiCall(block: suspend () -> T): ApiResult<T> = try {
    ApiResult.Ok(block())
} catch (e: CancellationException) {
    throw e
} catch (e: HttpException) {
    parseError(e.code(), e.response()?.errorBody()?.string())
} catch (e: IOException) {
    ApiResult.Offline(e)
}

/** For endpoints that answer 204 (Response<Unit>). */
suspend fun apiCallNoBody(block: suspend () -> retrofit2.Response<Unit>): ApiResult<Unit> = try {
    val r = block()
    if (r.isSuccessful) ApiResult.Ok(Unit) else parseError(r.code(), r.errorBody()?.string())
} catch (e: CancellationException) {
    throw e
} catch (e: IOException) {
    ApiResult.Offline(e)
}
