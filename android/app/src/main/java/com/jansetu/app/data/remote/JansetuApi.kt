package com.jansetu.app.data.remote

import retrofit2.Call
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Query

/** Base URL ends in /api/v1/ (BuildConfig.API_URL). */
interface JansetuApi {
    @POST("auth/login") suspend fun login(@Body body: LoginRequest): AuthTokens
    @POST("auth/logout") suspend fun logout(): Response<Unit>
    @POST("auth/change-password") suspend fun changePassword(@Body body: ChangePasswordRequest): Response<Unit>

    @GET("devices/me") suspend fun myDevice(): DeviceDetail
    @GET("app/version") suspend fun appVersion(): AppVersion

    @GET("sync/pull")
    suspend fun pull(
        @Query("since") since: String? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null,
    ): SyncPage

    @POST("sync/push") suspend fun push(@Body body: PushRequest): PushResponse
}

/**
 * Refresh goes through a client without the authenticator, so it can never loop. It is a blocking
 * Call run with execute(): an enqueued call would wait for a free per-host slot while the calls
 * that need the new token hold all of them (deadlock with 5+ parallel calls).
 */
interface RefreshApi {
    @POST("auth/refresh") fun refresh(@Body body: RefreshRequest): Call<AuthTokens>
}
