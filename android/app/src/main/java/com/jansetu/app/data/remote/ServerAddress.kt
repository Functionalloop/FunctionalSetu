package com.jansetu.app.data.remote

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.Response

/**
 * Server address typed on the Login screen of the DEBUG build (plan 6.6, laptop fallback):
 * "192.168.137.1:8000" becomes "http://192.168.137.1:8000/api/v1/". The release build always
 * uses BuildConfig.API_URL. Returns null when the text is not a usable address.
 */
object ServerAddress {
    fun normalize(input: String): HttpUrl? {
        val raw = input.trim()
        val scheme = listOf("http://", "https://").firstOrNull { raw.startsWith(it, ignoreCase = true) }
        val rest = (if (scheme != null) raw.substring(scheme.length) else raw).trimEnd('/')
        if (rest.isEmpty() || rest.startsWith("/") || ":/" in rest) return null
        var t = (scheme?.lowercase() ?: "http://") + rest
        if (!t.endsWith("/api/v1")) t = t.removeSuffix("/api") + "/api/v1"
        val url = "$t/".toHttpUrlOrNull() ?: return null
        if (url.host.isBlank() || url.encodedPath != "/api/v1/") return null
        return url
    }

    /** Short form for the screen: "192.168.137.1:8000" or "myjansetu.com". */
    fun label(url: HttpUrl): String =
        if (url.port == HttpUrl.defaultPort(url.scheme)) url.host else "${url.host}:${url.port}"
}

/** Sends every call to [current] (scheme, host, port) instead of the address the client was built with. */
class ServerAddressInterceptor(private val current: () -> HttpUrl?) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val target = current() ?: return chain.proceed(chain.request())
        val req = chain.request()
        val url = req.url.newBuilder().scheme(target.scheme).host(target.host).port(target.port).build()
        return chain.proceed(req.newBuilder().url(url).build())
    }
}
