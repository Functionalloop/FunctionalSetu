package com.jansetu.app.data.remote

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import java.util.concurrent.TimeUnit

/** Builds the clients without Hilt, so tests can point them at a fake server. */
object ApiFactory {
    /** [server] (debug build): the address typed on the Login screen; every call goes there instead of [baseUrl]. */
    fun create(
        baseUrl: String, tokens: TokenStore, events: SessionEvents, debug: Boolean = false,
        server: (() -> HttpUrl?)? = null,
    ): JansetuApi {
        val converter = ApiJson.asConverterFactory("application/json".toMediaType())
        val base = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS) // a first-download page can be large on 2G/3G
            .writeTimeout(60, TimeUnit.SECONDS)
            .apply { if (server != null) addInterceptor(ServerAddressInterceptor(server)) }
            .apply {
                // Headers only: bodies hold voter data and must not reach the log.
                if (debug) addInterceptor(HttpLoggingInterceptor().setLevel(HttpLoggingInterceptor.Level.BASIC))
            }
            .build()

        val refreshApi = Retrofit.Builder().baseUrl(baseUrl).client(base)
            .addConverterFactory(converter).build().create(RefreshApi::class.java)

        val client = base.newBuilder()
            .addInterceptor(AuthInterceptor(tokens, events))
            .authenticator(TokenAuthenticator(tokens, refreshApi, events))
            .build()

        return Retrofit.Builder().baseUrl(baseUrl).client(client)
            .addConverterFactory(converter).build().create(JansetuApi::class.java)
    }
}
