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
import retrofit2.http.Streaming

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

    // Activity log, Worker activity, Worker locations (9.8): admin and super admin; dates are Indian dates
    @GET("audit-log")
    suspend fun auditLog(
        @Query("entity_type") entityType: String? = null,
        @Query("actor_user_id") actorUserId: String? = null,
        @Query("date_from") dateFrom: String? = null,
        @Query("date_to") dateTo: String? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null,
    ): AuditPage
    @GET("reports/worker-activity")
    suspend fun workerActivity(
        @Query("date_from") dateFrom: String,
        @Query("date_to") dateTo: String,
        @Query("user_id") userId: String? = null,
    ): WorkerActivity
    @GET("worker-locations")
    suspend fun workerLocations(
        @Query("date_from") dateFrom: String,
        @Query("date_to") dateTo: String,
        @Query("user_id") userId: String? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null,
    ): WorkerLocationPage

    // Data quality (10.5): supervisor and above, the caller's area
    @GET("data-quality/summary") suspend fun dataQuality(@Query("ward_id") wardId: String? = null): DataQualitySummary
    @GET("data-quality/duplicates")
    suspend fun duplicates(
        @Query("unchecked_only") uncheckedOnly: Boolean,
        @Query("source") source: String? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null,
    ): DuplicatePairPage
    @POST("data-quality/duplicates/{id}/resolve")
    suspend fun resolvePair(@Path("id") id: String, @Body body: PairResolution): DuplicatePair

    // Mobile number sheets (10.5): admin and super admin
    @GET("mobile-imports")
    suspend fun mobileImports(@Query("cursor") cursor: String? = null, @Query("limit") limit: Int? = null): MobileImportPage
    @Multipart @POST("mobile-imports") suspend fun startMobileImport(@Part file: MultipartBody.Part): MobileImport
    @GET("mobile-imports/{id}") suspend fun mobileImport(@Path("id") id: String): MobileImport
    /** body = {"voter_id": "<id>" or null}; null skips the row (the key must be sent). */
    @POST("mobile-imports/{id}/rows/{row}/resolve")
    suspend fun resolveMobileRow(@Path("id") id: String, @Path("row") rowId: Long, @Body body: JsonObject): MobileImport

    // Matching Engine (10.2, 10.3): admin reads; upload, review, apply and discard are super admin only
    @GET("rolls/imports")
    suspend fun rollImports(@Query("cursor") cursor: String? = null, @Query("limit") limit: Int? = null): RollImportPage
    @Multipart @POST("rolls/imports")
    suspend fun startRollImport(
        @Part file: MultipartBody.Part,
        @Part("local_body_id") localBodyId: RequestBody,
        @Part("list_type") listType: RequestBody,
        @Part("title") title: RequestBody,
        @Part("published_on") publishedOn: RequestBody?, // null part = left out
    ): RollImport
    @GET("rolls/imports/{id}") suspend fun rollImport(@Path("id") id: String): RollImport
    @GET("rolls/imports/{id}/rows")
    suspend fun rollImportRows(
        @Path("id") id: String,
        @Query("pending_only") pendingOnly: Boolean? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null,
    ): RollImportRowPage
    @POST("rolls/imports/{id}/rows/{row}/resolve")
    suspend fun resolveRollRow(@Path("id") id: String, @Path("row") rowId: Long, @Body body: RowResolution): RollImportRow
    @POST("rolls/imports/{id}/apply") suspend fun applyRollImport(@Path("id") id: String): RollImport
    @POST("rolls/imports/{id}/discard") suspend fun discardRollImport(@Path("id") id: String): RollImport

    // Correct roll record (10.4): super admin; removed voters are listed for admins
    @PATCH("voters/{id}/roll") suspend fun correctVoter(@Path("id") id: String, @Body body: RollPatch): RollVoter
    @POST("voters/{id}/remove") suspend fun removeVoter(@Path("id") id: String, @Body body: RemoveRestore): RollVoter
    @POST("voters/{id}/restore") suspend fun restoreVoter(@Path("id") id: String, @Body body: RemoveRestore): RollVoter
    @GET("voters")
    suspend fun removedVoters(
        @Query("removed") removed: Boolean = true,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null,
    ): VoterListPage

    // Reports & charts, Print or export a list (11.3): supervisor and above, the caller's area
    @GET("reports/survey-progress") suspend fun surveyProgress(@Query("ward_id") wardId: String? = null): SurveyProgress
    @GET("reports/colour-tags") suspend fun colourTagReport(@Query("ward_id") wardId: String? = null): ColorTagReport
    @GET("reports/demographics")
    suspend fun demographics(@Query("ward_id") wardId: String? = null, @Query("booth_id") boothId: String? = null): Demographics
    @GET("reports/turnout") suspend fun turnoutReport(@Query("ward_id") wardId: String? = null): TurnoutReport
    /** Answers 202 at once; poll exportJob until done or failed. */
    @POST("exports") suspend fun startExport(@Body body: ExportIn): ExportJob
    @GET("exports/{id}") suspend fun exportJob(@Path("id") id: String): ExportJob
    /** 409 export_not_ready before done. The file name is in Content-Disposition. */
    @Streaming @GET("exports/{id}/download") suspend fun downloadExport(@Path("id") id: String): Response<ResponseBody>

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
