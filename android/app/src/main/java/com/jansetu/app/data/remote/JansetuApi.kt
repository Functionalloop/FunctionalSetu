package com.jansetu.app.data.remote

import kotlinx.serialization.json.JsonObject
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okhttp3.ResponseBody
import retrofit2.Call
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query

/** Base URL ends in /api/v1/ (BuildConfig.API_URL). */
interface JansetuApi {
    @POST("auth/login") suspend fun login(@Body body: LoginRequest): AuthTokens
    @POST("auth/logout") suspend fun logout(): Response<Unit>
    @POST("auth/change-password") suspend fun changePassword(@Body body: ChangePasswordRequest): Response<Unit>

    @GET("devices/me") suspend fun myDevice(): DeviceDetail
    @GET("app/version") suspend fun appVersion(): AppVersion

    // Admin and super admin: phones of their own constituency (super admin: all)
    @GET("devices")
    suspend fun devices(
        @Query("status") status: String? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null,
    ): DevicePage
    @POST("devices/{id}/approve") suspend fun approveDevice(@Path("id") id: String): AdminDevice
    @POST("devices/{id}/block") suspend fun blockDevice(@Path("id") id: String, @Body body: BlockDeviceRequest): AdminDevice

    // Users & devices, Booths & karyakartas (9.6): admin and super admin
    @GET("users")
    suspend fun users(
        @Query("q") q: String? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null,
    ): UserPage
    @GET("users/{id}") suspend fun user(@Path("id") id: String): AdminUser
    @POST("users") suspend fun createUser(@Body body: NewUser): TemporaryPassword
    /** Only the keys present are changed (a JSON null clears a field): see UserEdits. */
    @PATCH("users/{id}") suspend fun updateUser(@Path("id") id: String, @Body body: JsonObject): AdminUser
    @POST("users/{id}/reset-password") suspend fun resetPassword(@Path("id") id: String): TemporaryPassword
    @GET("users/{id}/assignments") suspend fun assignments(@Path("id") id: String): AssignmentsOut
    @PUT("users/{id}/assignments") suspend fun setAssignments(@Path("id") id: String, @Body body: AssignmentsIn): AssignmentsOut

    // Constituencies (super admin), Election & candidate, Lists & labels (9.7: admin and super admin)
    @GET("constituencies") suspend fun constituencies(): List<Constituency>
    @POST("constituencies") suspend fun createConstituency(@Body body: ConstituencyIn): Constituency
    /** Only the keys present are changed. */
    @PATCH("constituencies/{id}") suspend fun updateConstituency(@Path("id") id: String, @Body body: JsonObject): Constituency

    /** The whole settings object: the phone edits some keys and sends all of it back (PUT replaces). */
    @GET("settings/election") suspend fun electionSettings(): JsonObject
    @PUT("settings/election") suspend fun saveElectionSettings(@Body body: JsonObject): JsonObject
    @Multipart @POST("files") suspend fun uploadFile(@Part("kind") kind: RequestBody, @Part file: MultipartBody.Part): StoredFile
    @GET("files/{id}") suspend fun file(@Path("id") id: String): ResponseBody

    /** list = castes, professions or influencer-types. */
    @GET("masters/{list}") suspend fun namedList(@Path("list") list: String): List<NamedListEntry>
    @POST("masters/{list}") suspend fun addNamed(@Path("list") list: String, @Body body: NamedEntryIn): NamedListEntry
    @PATCH("masters/{list}/{id}")
    suspend fun saveNamed(@Path("list") list: String, @Path("id") id: String, @Body body: NamedEntryIn): NamedListEntry
    @GET("masters/color-tags") suspend fun colorTags(): List<ColorTagDto>
    @POST("masters/color-tags") suspend fun addColorTag(@Body body: ColorTagIn): ColorTagDto
    @PATCH("masters/color-tags/{id}") suspend fun saveColorTag(@Path("id") id: String, @Body body: ColorTagIn): ColorTagDto
    @GET("masters/custom-fields") suspend fun customFields(): List<CustomFieldLabelDto>
    @PATCH("masters/custom-fields/{key}")
    suspend fun saveCustomField(@Path("key") key: String, @Body body: CustomFieldLabelIn): CustomFieldLabelDto
    @GET("masters/message-templates") suspend fun messageTemplates(): List<MessageTemplateDto>
    @PATCH("masters/message-templates/{kind}")
    suspend fun saveMessageTemplate(@Path("kind") kind: String, @Body body: MessageTemplateIn): MessageTemplateDto

    @GET("sync/pull")
    suspend fun pull(
        @Query("since") since: String? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null,
    ): SyncPage

    @POST("sync/push") suspend fun push(@Body body: PushRequest): PushResponse

    @GET("voters/{id}/history")
    suspend fun history(@Path("id") voterId: String, @Query("cursor") cursor: String? = null, @Query("limit") limit: Int? = null): HistoryPage

    @PATCH("families/{id}") suspend fun renameFamily(@Path("id") id: String, @Body body: FamilyPatch): SyncFamily

    // Conflict review (7.10)
    @GET("sync/conflicts")
    suspend fun conflicts(
        @Query("entity_id") entityId: String? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null,
    ): ConflictPage
    @POST("sync/conflicts/{id}/resolve") suspend fun resolveConflict(@Path("id") id: String, @Body body: ConflictResolution): Conflict

    // More menu (7.9)
    @GET("me") suspend fun me(): Me
    @GET("terms/current") suspend fun terms(): Terms
    @POST("terms/accept") suspend fun acceptTerms(@Body body: TermsAccept): Response<Unit>
    @GET("announcements")
    suspend fun announcements(@Query("cursor") cursor: String? = null, @Query("limit") limit: Int? = null): AnnouncementPage
    @POST("announcements/{id}/read") suspend fun readAnnouncement(@Path("id") id: String): Response<Unit>
    @POST("problem-reports") suspend fun reportProblem(@Body body: ProblemReportIn): Response<Unit>
}

/**
 * Refresh goes through a client without the authenticator, so it can never loop. It is a blocking
 * Call run with execute(): an enqueued call would wait for a free per-host slot while the calls
 * that need the new token hold all of them (deadlock with 5+ parallel calls).
 */
interface RefreshApi {
    @POST("auth/refresh") fun refresh(@Body body: RefreshRequest): Call<AuthTokens>
}
