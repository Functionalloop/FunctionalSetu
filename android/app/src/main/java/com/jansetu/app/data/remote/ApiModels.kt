package com.jansetu.app.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

// Shapes from docs/openapi.json. Only the fields the app uses; unknown fields are ignored,
// so the server can add fields without breaking old phones.

@Serializable
data class DeviceInfo(
    @SerialName("device_uid") val deviceUid: String,
    val model: String? = null,
    @SerialName("os_version") val osVersion: String? = null,
    @SerialName("app_version_code") val appVersionCode: Int? = null,
)

@Serializable
data class LoginRequest(
    @SerialName("workspace_code") val workspaceCode: String,
    val username: String,
    val password: String,
    val device: DeviceInfo?,
)

@Serializable data class RefreshRequest(@SerialName("refresh_token") val refreshToken: String)

@Serializable
data class ChangePasswordRequest(
    @SerialName("current_password") val currentPassword: String,
    @SerialName("new_password") val newPassword: String,
)

@Serializable
data class UserSummary(
    val id: String,
    val username: String,
    @SerialName("full_name_en") val fullNameEn: String,
    @SerialName("full_name_mr") val fullNameMr: String? = null,
    val role: String,
)

@Serializable
data class WorkspaceSummary(
    val id: String,
    val code: String,
    @SerialName("name_en") val nameEn: String,
    @SerialName("name_mr") val nameMr: String? = null,
)

@Serializable data class DeviceSummary(val id: String, val status: String)

@Serializable
data class AuthTokens(
    @SerialName("access_token") val accessToken: String,
    @SerialName("refresh_token") val refreshToken: String,
    @SerialName("expires_in") val expiresIn: Int,
    @SerialName("must_change_password") val mustChangePassword: Boolean,
    val user: UserSummary,
    val workspace: WorkspaceSummary,
    val device: DeviceSummary? = null,
)

@Serializable
data class DeviceDetail(
    val id: String,
    val status: String,
    @SerialName("wipe_required") val wipeRequired: Boolean = false,
)

@Serializable
data class AppVersion(
    @SerialName("latest_version_code") val latestVersionCode: Int,
    @SerialName("latest_version_name") val latestVersionName: String,
    @SerialName("min_version_code") val minVersionCode: Int,
    @SerialName("apk_url") val apkUrl: String,
)

@Serializable
data class SyncArea(
    val id: String,
    @SerialName("parent_id") val parentId: String? = null,
    val level: String,
    val code: String,
    val number: Int? = null,
    @SerialName("name_mr") val nameMr: String,
    @SerialName("name_en") val nameEn: String? = null,
    @SerialName("address_mr") val addressMr: String? = null,
    @SerialName("address_en") val addressEn: String? = null,
    @SerialName("ac_no") val acNo: Int? = null,
    @SerialName("sort_order") val sortOrder: Int = 0,
)

@Serializable
data class SyncVoter(
    val id: String,
    @SerialName("local_body_id") val localBodyId: String,
    @SerialName("ward_id") val wardId: String,
    @SerialName("booth_id") val boothId: String,
    @SerialName("section_id") val sectionId: String? = null,
    @SerialName("part_no") val partNo: Int,
    @SerialName("booth_no") val boothNo: Int? = null,
    @SerialName("serial_no") val serialNo: Int,
    @SerialName("epic_no") val epicNo: String? = null,
    @SerialName("first_name_mr") val firstNameMr: String? = null,
    @SerialName("middle_name_mr") val middleNameMr: String? = null,
    @SerialName("last_name_mr") val lastNameMr: String? = null,
    @SerialName("first_name_en") val firstNameEn: String? = null,
    @SerialName("middle_name_en") val middleNameEn: String? = null,
    @SerialName("last_name_en") val lastNameEn: String? = null,
    @SerialName("relation_type") val relationType: String? = null,
    @SerialName("relative_name_mr") val relativeNameMr: String? = null,
    @SerialName("relative_name_en") val relativeNameEn: String? = null,
    val gender: String,
    val age: Int? = null,
    @SerialName("age_as_of") val ageAsOf: String? = null,
    @SerialName("house_no") val houseNo: String? = null,
    @SerialName("address_mr") val addressMr: String? = null,
    @SerialName("address_en") val addressEn: String? = null,
    @SerialName("list_type") val listType: String = "main",
    @SerialName("roll_status") val rollStatus: String = "active",
    @SerialName("deletion_reason") val deletionReason: String? = null,
    @SerialName("is_repeated_in_roll") val isRepeatedInRoll: Boolean = false,
    @SerialName("deleted_at") val deletedAt: String? = null,
)

@Serializable
data class SurveyDto(
    @SerialName("voter_id") val voterId: String,
    @SerialName("mobile_1") val mobile1: String? = null,
    @SerialName("mobile_2") val mobile2: String? = null,
    val dob: String? = null,
    @SerialName("caste_id") val casteId: String? = null,
    @SerialName("profession_id") val professionId: String? = null,
    @SerialName("color_tag_id") val colorTagId: String? = null,
    @SerialName("has_new_address") val hasNewAddress: Boolean = false,
    @SerialName("new_address_mr") val newAddressMr: String? = null,
    @SerialName("new_address_en") val newAddressEn: String? = null,
    val notes: String? = null,
    @SerialName("extra_check_1") val extraCheck1: Boolean? = null,
    @SerialName("extra_check_2") val extraCheck2: Boolean? = null,
    @SerialName("extra_info_1") val extraInfo1: String? = null,
    @SerialName("extra_info_2") val extraInfo2: String? = null,
    @SerialName("extra_info_3") val extraInfo3: String? = null,
    @SerialName("extra_info_4") val extraInfo4: String? = null,
    @SerialName("extra_info_5") val extraInfo5: String? = null,
    @SerialName("is_influencer") val isInfluencer: Boolean = false,
    @SerialName("influencer_type_id") val influencerTypeId: String? = null,
    @SerialName("in_self_help_group") val inSelfHelpGroup: Boolean = false,
    @SerialName("self_help_group_name") val selfHelpGroupName: String? = null,
    @SerialName("ration_card") val rationCard: String? = null,
    val version: Int,
    @SerialName("is_surveyed") val isSurveyed: Boolean = false,
    @SerialName("surveyed_at") val surveyedAt: String? = null,
    val lat: Double? = null,
    val lng: Double? = null,
    @SerialName("location_accuracy_m") val locationAccuracyM: Double? = null,
    @SerialName("location_captured_at") val locationCapturedAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)

@Serializable
data class NamedListEntry(
    val id: String,
    @SerialName("name_mr") val nameMr: String,
    @SerialName("name_en") val nameEn: String? = null,
    // Kept so an admin's edit (9.7: the server replaces the whole entry) does not clear it.
    @SerialName("name_hi") val nameHi: String? = null,
    @SerialName("sort_order") val sortOrder: Int = 0,
    @SerialName("is_active") val isActive: Boolean = true,
)

@Serializable
data class ColorTagDto(
    val id: String,
    val code: String,
    val hex: String,
    @SerialName("label_mr") val labelMr: String,
    @SerialName("label_en") val labelEn: String,
    @SerialName("label_hi") val labelHi: String? = null,
    @SerialName("is_default") val isDefault: Boolean = false,
    @SerialName("sort_order") val sortOrder: Int = 0,
    @SerialName("is_active") val isActive: Boolean = true,
)

@Serializable
data class CustomFieldLabelDto(
    @SerialName("field_key") val fieldKey: String,
    @SerialName("label_mr") val labelMr: String? = null,
    @SerialName("label_en") val labelEn: String? = null,
    @SerialName("label_hi") val labelHi: String? = null,
    @SerialName("is_enabled") val isEnabled: Boolean = false,
)

@Serializable
data class SyncLists(
    val castes: List<NamedListEntry> = emptyList(),
    val professions: List<NamedListEntry> = emptyList(),
    @SerialName("color_tags") val colorTags: List<ColorTagDto> = emptyList(),
    @SerialName("custom_field_labels") val customFieldLabels: List<CustomFieldLabelDto> = emptyList(),
    @SerialName("influencer_types") val influencerTypes: List<NamedListEntry> = emptyList(),
)

/** A Kutumb as the pull sends it (SyncFamily) and as the push result returns it. */
@Serializable
data class SyncFamily(
    val id: String,
    @SerialName("ward_id") val wardId: String? = null,
    @SerialName("booth_id") val boothId: String? = null,
    val label: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("deleted_at") val deletedAt: String? = null,
)

/** A voter's Kutumb; familyId null = taken out. */
@Serializable
data class SyncFamilyMember(
    @SerialName("voter_id") val voterId: String,
    @SerialName("family_id") val familyId: String? = null,
)

@Serializable
data class VisitDto(
    val id: String,
    @SerialName("voter_id") val voterId: String? = null,
    @SerialName("booth_id") val boothId: String,
    @SerialName("house_no") val houseNo: String? = null,
    val outcome: String,
    @SerialName("visited_at") val visitedAt: String,
    @SerialName("revisit_at") val revisitAt: String? = null,
    val note: String? = null,
    @SerialName("visited_by") val visitedBy: String,
)

/** Eligible but Not Registered (NewVoter), as the pull sends it and the push returns it. */
@Serializable
data class NewVoterDto(
    val id: String,
    @SerialName("full_name_en") val fullNameEn: String? = null,
    @SerialName("full_name_mr") val fullNameMr: String? = null,
    @SerialName("relative_name") val relativeName: String? = null,
    val dob: String? = null,
    val gender: String? = null,
    val mobile: String? = null,
    val address: String? = null,
    @SerialName("ward_id") val wardId: String,
    @SerialName("booth_id") val boothId: String? = null,
    @SerialName("family_id") val familyId: String? = null,
    @SerialName("form6_status") val form6Status: String = "not_applied",
    val notes: String? = null,
    val version: Int,
    @SerialName("matched_voter_id") val matchedVoterId: String? = null,
    @SerialName("created_by") val createdBy: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String? = null,
)

/** GET /voters/{id}/history (7.6, Information Updation). */
@Serializable
data class HistoryChange(
    val old: JsonElement? = null,
    val new: JsonElement? = null,
    @SerialName("old_label") val oldLabel: String? = null,
    @SerialName("new_label") val newLabel: String? = null,
)

@Serializable
data class HistoryEntry(
    val at: String,
    val kind: String,
    val action: String,
    val by: UserSummary? = null,
    val changes: Map<String, HistoryChange> = emptyMap(),
)

@Serializable
data class HistoryPage(val items: List<HistoryEntry>, @SerialName("next_cursor") val nextCursor: String? = null)

/** PATCH /families/{id}: rename a Kutumb (online only; there is no push type for it). */
@Serializable data class FamilyPatch(val label: String)

@Serializable
data class SyncPage(
    /** Text, never a number: xid8 is 64-bit. */
    val watermark: String,
    @SerialName("next_cursor") val nextCursor: String? = null,
    val settings: JsonObject? = null,
    val lists: SyncLists? = null,
    val wipe: Boolean = false,
    val areas: List<SyncArea> = emptyList(),
    @SerialName("area_ids") val areaIds: List<String>? = null,
    @SerialName("total_voters") val totalVoters: Int? = null,
    @SerialName("total_surveys") val totalSurveys: Int? = null,
    val voters: List<SyncVoter> = emptyList(),
    val surveys: List<SurveyDto> = emptyList(),
    @SerialName("gone_voter_ids") val goneVoterIds: List<String> = emptyList(),
    val families: List<SyncFamily> = emptyList(),
    @SerialName("family_members") val familyMembers: List<SyncFamilyMember> = emptyList(),
    val visits: List<VisitDto> = emptyList(),
    @SerialName("new_voters") val newVoters: List<NewVoterDto> = emptyList(),
    @SerialName("part_notes") val partNotes: List<PartNoteDto> = emptyList(),
    /** 8.1: voted marks; polling-day roles only (a surveyor gets none). Replace by voter_id. */
    val turnout: List<TurnoutMarkDto> = emptyList(),
)

/** A voter's voted mark (8.1); is_voted false = undone. */
@Serializable
data class TurnoutMarkDto(
    @SerialName("voter_id") val voterId: String,
    @SerialName("is_voted") val isVoted: Boolean,
    @SerialName("marked_by") val markedBy: String,
    @SerialName("marked_at") val markedAt: String,
    val source: String,
)

/** 7.11: a part's shared note; version 0 = none yet. */
@Serializable
data class PartNoteDto(
    @SerialName("booth_id") val boothId: String,
    val note: String,
    val version: Int,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("updated_by") val updatedBy: String? = null,
)

@Serializable
data class PushItem(
    val id: String,
    val type: String,
    @SerialName("entity_id") val entityId: String,
    @SerialName("base_version") val baseVersion: Int,
    @SerialName("changed_at") val changedAt: String? = null,
    val data: JsonObject,
)

@Serializable data class PushRequest(val items: List<PushItem>)

@Serializable data class PushError(val code: String, val message: String)

@Serializable
data class PushResult(
    val id: String,
    val status: String,
    val duplicate: Boolean = false,
    val error: PushError? = null,
    val survey: SurveyDto? = null,
    @SerialName("conflict_fields") val conflictFields: List<String> = emptyList(),
    val family: SyncFamily? = null,
    val visit: VisitDto? = null,
    @SerialName("new_voter") val newVoter: NewVoterDto? = null,
    @SerialName("part_note") val partNote: PartNoteDto? = null,
    /** voted / unvoted: the marks of the item's voters as the server holds them now. */
    val turnout: List<TurnoutMarkDto> = emptyList(),
)

@Serializable data class PushResponse(val results: List<PushResult>)

@Serializable
data class ErrorBody(
    val code: String,
    val message: String,
    val current: JsonObject? = null,
)

@Serializable data class ErrorResponse(val error: ErrorBody)

// --- Phones, as an admin sees them (GET /devices, approve, block) ---

@Serializable
data class AdminDevice(
    val id: String,
    val status: String,
    val model: String? = null,
    @SerialName("os_version") val osVersion: String? = null,
    @SerialName("app_version_code") val appVersionCode: Int? = null,
    @SerialName("requested_at") val requestedAt: String,
    @SerialName("decided_at") val decidedAt: String? = null,
    @SerialName("user_id") val userId: String,
    @SerialName("blocked_reason") val blockedReason: String? = null,
    // Only in the list (GET /devices), not in the approve / block answer.
    val username: String? = null,
    @SerialName("full_name_en") val fullNameEn: String? = null,
    val role: String? = null,
    @SerialName("last_seen_at") val lastSeenAt: String? = null,
)

@Serializable
data class DevicePage(val items: List<AdminDevice>, @SerialName("next_cursor") val nextCursor: String? = null)

@Serializable data class BlockDeviceRequest(val reason: String? = null)

// --- More menu (7.9) ---

@Serializable
data class Terms(
    val version: Int,
    @SerialName("body_mr") val bodyMr: String,
    @SerialName("body_en") val bodyEn: String,
    @SerialName("published_at") val publishedAt: String,
)

@Serializable data class TermsAccept(val version: Int)

/** GET /me: only what the app reads. */
@Serializable data class MeUserTerms(@SerialName("terms_version") val termsVersion: Int? = null)
@Serializable data class Me(val user: MeUserTerms)

@Serializable
data class Announcement(
    val id: String,
    val body: String,
    @SerialName("audience_geo_id") val audienceGeoId: String? = null,
    @SerialName("created_by") val createdBy: UserSummary,
    @SerialName("created_at") val createdAt: String,
    @SerialName("expires_at") val expiresAt: String? = null,
    @SerialName("is_read") val isRead: Boolean,
)

@Serializable
data class AnnouncementPage(
    val items: List<Announcement>,
    @SerialName("next_cursor") val nextCursor: String? = null,
)

@Serializable
data class ProblemReportIn(
    val body: String,
    @SerialName("app_version_code") val appVersionCode: Int?,
    @SerialName("phone_model") val phoneModel: String?,
)

// --- Conflict review (7.10) ---

@Serializable
data class Conflict(
    val id: String,
    @SerialName("entity_type") val entityType: String,
    @SerialName("entity_id") val entityId: String,
    @SerialName("field_name") val fieldName: String,
    @SerialName("client_value") val clientValue: JsonElement? = null,
    @SerialName("server_value") val serverValue: JsonElement? = null,
    @SerialName("client_user") val clientUser: UserSummary,
    @SerialName("client_changed_at") val clientChangedAt: String? = null,
    @SerialName("created_at") val createdAt: String,
    val status: String,
)

@Serializable
data class ConflictPage(
    val items: List<Conflict>,
    @SerialName("next_cursor") val nextCursor: String? = null,
)

/** keep: "kept_client" (the phone's value is written) or "kept_server". */
@Serializable data class ConflictResolution(val keep: String)

// --- Users & devices, Booths & karyakartas (9.6) ---

/** A user as an admin sees it (GET /users, /users/{id}). */
@Serializable
data class AdminUser(
    val id: String,
    val username: String,
    @SerialName("full_name_en") val fullNameEn: String,
    @SerialName("full_name_mr") val fullNameMr: String? = null,
    val role: String,
    val mobile: String? = null,
    @SerialName("local_body_id") val localBodyId: String? = null,
    @SerialName("is_active") val isActive: Boolean = true,
    @SerialName("must_change_password") val mustChangePassword: Boolean = false,
    @SerialName("last_login_at") val lastLoginAt: String? = null,
    @SerialName("locked_until") val lockedUntil: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("device_count") val deviceCount: Int = 0,
    @SerialName("pending_device") val pendingDevice: Boolean = false,
    /** Assigned wards and booths (server 9.6); an older server leaves it out. */
    @SerialName("area_ids") val areaIds: List<String> = emptyList(),
)

@Serializable
data class UserPage(val items: List<AdminUser>, @SerialName("next_cursor") val nextCursor: String? = null)

@Serializable
data class NewUser(
    val username: String,
    @SerialName("full_name_en") val fullNameEn: String,
    @SerialName("full_name_mr") val fullNameMr: String? = null,
    val mobile: String? = null,
    val role: String,
    @SerialName("local_body_id") val localBodyId: String? = null,
)

/** Shown once: after create and after reset password. */
@Serializable
data class TemporaryPassword(val user: AdminUser, @SerialName("temporary_password") val temporaryPassword: String)

@Serializable data class AssignmentsIn(@SerialName("area_ids") val areaIds: List<String>)

@Serializable
data class AssignedArea(
    val id: String,
    @SerialName("parent_id") val parentId: String? = null,
    val level: String,
    val code: String,
    val number: Int? = null,
    @SerialName("name_mr") val nameMr: String,
    @SerialName("name_en") val nameEn: String? = null,
)

@Serializable data class AssignmentsOut(val areas: List<AssignedArea>)

// --- Constituencies, Election & candidate, Lists & labels (9.7) ---

@Serializable
data class Constituency(
    val id: String,
    val code: String,
    val number: Int? = null,
    @SerialName("name_mr") val nameMr: String,
    @SerialName("name_en") val nameEn: String? = null,
    @SerialName("ac_no") val acNo: Int? = null,
    @SerialName("is_active") val isActive: Boolean = true,
    @SerialName("voter_count") val voterCount: Int = 0,
    @SerialName("user_count") val userCount: Int = 0,
)

@Serializable
data class ConstituencyIn(
    val code: String,
    @SerialName("name_mr") val nameMr: String,
    @SerialName("name_en") val nameEn: String? = null,
    @SerialName("ac_no") val acNo: Int? = null,
)

/** Caste, profession or influencer type to add or save (PATCH replaces the whole entry). */
@Serializable
data class NamedEntryIn(
    @SerialName("name_mr") val nameMr: String,
    @SerialName("name_en") val nameEn: String? = null,
    @SerialName("name_hi") val nameHi: String? = null,
    @SerialName("sort_order") val sortOrder: Int = 0,
    @SerialName("is_active") val isActive: Boolean = true,
)

@Serializable
data class ColorTagIn(
    val code: String,
    val hex: String,
    @SerialName("label_mr") val labelMr: String,
    @SerialName("label_en") val labelEn: String,
    @SerialName("label_hi") val labelHi: String? = null,
    @SerialName("is_default") val isDefault: Boolean = false,
    @SerialName("sort_order") val sortOrder: Int = 0,
    @SerialName("is_active") val isActive: Boolean = true,
)

@Serializable
data class CustomFieldLabelIn(
    @SerialName("label_mr") val labelMr: String? = null,
    @SerialName("label_en") val labelEn: String? = null,
    @SerialName("label_hi") val labelHi: String? = null,
    @SerialName("is_enabled") val isEnabled: Boolean,
)

@Serializable
data class MessageTemplateDto(
    val kind: String,
    @SerialName("body_mr") val bodyMr: String? = null,
    @SerialName("body_en") val bodyEn: String? = null,
    @SerialName("body_hi") val bodyHi: String? = null,
)

@Serializable
data class MessageTemplateIn(
    @SerialName("body_mr") val bodyMr: String? = null,
    @SerialName("body_en") val bodyEn: String? = null,
    @SerialName("body_hi") val bodyHi: String? = null,
)

// --- Activity log, Worker activity, Worker locations (9.8) ---

@Serializable
data class AuditEntry(
    val id: Long,
    @SerialName("occurred_at") val occurredAt: String,
    val actor: UserSummary? = null,
    @SerialName("device_id") val deviceId: String? = null,
    val action: String,
    @SerialName("entity_type") val entityType: String,
    @SerialName("entity_id") val entityId: String? = null,
    @SerialName("old_values") val oldValues: JsonObject? = null,
    @SerialName("new_values") val newValues: JsonObject? = null,
)

@Serializable
data class AuditPage(val items: List<AuditEntry>, @SerialName("next_cursor") val nextCursor: String? = null)

@Serializable
data class WorkerDay(
    val user: UserSummary,
    val day: String,
    val surveys: Int = 0,
    val visits: Int = 0,
    @SerialName("mobiles_collected") val mobilesCollected: Int = 0,
    @SerialName("new_voters") val newVoters: Int = 0,
    @SerialName("voted_marks") val votedMarks: Int = 0,
)

@Serializable
data class WorkerActivity(
    @SerialName("date_from") val dateFrom: String,
    @SerialName("date_to") val dateTo: String,
    val rows: List<WorkerDay> = emptyList(),
)

@Serializable
data class WorkerLocation(
    val user: UserSummary,
    val kind: String,
    @SerialName("voter_id") val voterId: String? = null,
    val lat: Double,
    val lng: Double,
    @SerialName("accuracy_m") val accuracyM: Double? = null,
    val at: String,
)

@Serializable
data class WorkerLocationPage(val items: List<WorkerLocation>, @SerialName("next_cursor") val nextCursor: String? = null)

@Serializable
data class StoredFile(
    val id: String,
    val kind: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long,
)

// --- Data quality, mobile number sheets, Matching Engine, roll corrections (10.6; API of 10.2-10.5) ---

@Serializable
data class DataQualitySummary(
    val voters: Int = 0,
    @SerialName("no_mobile") val noMobile: Int = 0,
    @SerialName("no_dob") val noDob: Int = 0,
    @SerialName("possible_duplicates") val possibleDuplicates: Int = 0,
    @SerialName("repeated_in_roll") val repeatedInRoll: Int = 0,
    val shifted: Int = 0,
    @SerialName("doubtful_dead") val doubtfulDead: Int = 0,
)

@Serializable
data class DuplicatePair(
    val id: String,
    @SerialName("voter_a") val voterA: SyncVoter,
    @SerialName("voter_b") val voterB: SyncVoter,
    val source: String,
    val similarity: Double? = null,
    val status: String,
)

@Serializable
data class DuplicatePairPage(val items: List<DuplicatePair>, @SerialName("next_cursor") val nextCursor: String? = null)

/** keep_voter_id (super admin only) hides the other voter; left out (null) it only records the decision. */
@Serializable
data class PairResolution(
    @SerialName("same_person") val samePerson: Boolean,
    @SerialName("keep_voter_id") val keepVoterId: String? = null,
)

@Serializable
data class MobileImportRow(
    val id: Long,
    @SerialName("row_no") val rowNo: Int,
    val name: String? = null,
    val mobile: String,
    @SerialName("address_text") val addressText: String? = null,
    val status: String,
    @SerialName("matched_voter_id") val matchedVoterId: String? = null,
    @SerialName("candidate_voter_ids") val candidateVoterIds: List<String> = emptyList(),
)

@Serializable
data class MobileImport(
    val id: String,
    val status: String,
    @SerialName("matched_count") val matchedCount: Int = 0,
    @SerialName("review_count") val reviewCount: Int = 0,
    @SerialName("not_found_count") val notFoundCount: Int = 0,
    val error: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("finished_at") val finishedAt: String? = null,
    val rows: List<MobileImportRow> = emptyList(),
)

@Serializable
data class MobileImportPage(val items: List<MobileImport>, @SerialName("next_cursor") val nextCursor: String? = null)

@Serializable
data class RollImport(
    val id: String,
    @SerialName("local_body_id") val localBodyId: String,
    @SerialName("list_type") val listType: String,
    val title: String,
    @SerialName("published_on") val publishedOn: String? = null,
    val status: String,
    val counts: Map<String, Int> = emptyMap(),
    val error: String? = null,
    @SerialName("imported_by") val importedBy: UserSummary? = null,
    @SerialName("applied_at") val appliedAt: String? = null,
    @SerialName("created_at") val createdAt: String,
)

@Serializable
data class RollImportPage(val items: List<RollImport>, @SerialName("next_cursor") val nextCursor: String? = null)

@Serializable
data class RollImportRow(
    val id: Long,
    @SerialName("row_no") val rowNo: Int,
    @SerialName("part_no") val partNo: Int? = null,
    @SerialName("serial_no") val serialNo: Int? = null,
    @SerialName("epic_no") val epicNo: String? = null,
    @SerialName("first_name_en") val firstNameEn: String? = null,
    @SerialName("last_name_en") val lastNameEn: String? = null,
    @SerialName("first_name_mr") val firstNameMr: String? = null,
    @SerialName("last_name_mr") val lastNameMr: String? = null,
    val gender: String? = null,
    val age: Int? = null,
    @SerialName("house_no") val houseNo: String? = null,
    @SerialName("match_status") val matchStatus: String? = null,
    @SerialName("matched_voter_id") val matchedVoterId: String? = null,
    val similarity: Double? = null,
    @SerialName("match_notes") val matchNotes: String? = null,
    @SerialName("review_status") val reviewStatus: String,
)

@Serializable
data class RollImportRowPage(val items: List<RollImportRow>, @SerialName("next_cursor") val nextCursor: String? = null)

@Serializable
data class RowResolution(val accept: Boolean, @SerialName("voter_id") val voterId: String? = null)

/** PATCH /voters/{id}/roll: only the changed keys in `fields` (a JSON null clears one). */
@Serializable
data class RollPatch(val fields: JsonObject, val reason: String, val reference: String? = null)

@Serializable
data class RemoveRestore(val reason: String, val reference: String? = null)

/** The parts of VoterDetail the correction screens read back. */
@Serializable
data class RollVoter(val id: String, @SerialName("deleted_at") val deletedAt: String? = null)

@Serializable
data class VoterListItem(
    val id: String,
    @SerialName("part_no") val partNo: Int,
    @SerialName("serial_no") val serialNo: Int,
    @SerialName("epic_no") val epicNo: String? = null,
    @SerialName("full_name_en") val fullNameEn: String? = null,
    @SerialName("full_name_mr") val fullNameMr: String? = null,
    val gender: String,
    val age: Int? = null,
    @SerialName("house_no") val houseNo: String? = null,
)

@Serializable
data class VoterListPage(val items: List<VoterListItem>, @SerialName("next_cursor") val nextCursor: String? = null)

// --- Reports and exports (11.3; server 11.1, 11.2) ---------------------------------------------------

/** One Village Panchayat (ward) or part (booth) of a report; `parentId` = a booth's ward (null on wards). */
@Serializable
data class AreaCount(
    @SerialName("area_id") val areaId: String,
    val name: String,
    val level: String,
    val total: Int,
    /** Surveyed (survey progress) or voted (turnout). */
    val done: Int,
    val percent: Double,
    @SerialName("parent_id") val parentId: String? = null,
)

@Serializable
data class SurveyProgress(val total: Int, val surveyed: Int, val percent: Double, @SerialName("by_area") val byArea: List<AreaCount> = emptyList())

/** `colorTagId` null = no colour tag. Only counts above zero are sent. */
@Serializable
data class ColorTagCount(@SerialName("color_tag_id") val colorTagId: String? = null, val count: Int)

@Serializable
data class ColorTagReport(
    val total: Int,
    @SerialName("by_tag") val byTag: List<ColorTagCount> = emptyList(),
    /** area id -> counts */
    @SerialName("by_area") val byArea: Map<String, List<ColorTagCount>> = emptyMap(),
)

@Serializable
data class AgeBand(val band: String, val male: Int, val female: Int, val other: Int)

@Serializable
data class Demographics(
    val total: Int, val male: Int, val female: Int, val other: Int,
    @SerialName("age_bands") val ageBands: List<AgeBand> = emptyList(),
)

/** `hour` is the Indian hour (0-23). */
@Serializable
data class TurnoutHour(val hour: Int, val voted: Int, val cumulative: Int)

@Serializable
data class TurnoutReport(
    val total: Int, val voted: Int, val percent: Double,
    @SerialName("by_area") val byArea: List<AreaCount> = emptyList(),
    @SerialName("by_hour") val byHour: List<TurnoutHour> = emptyList(),
)

/**
 * POST /exports. kind = voter_list, mobile_list, report or turnout; format = xlsx or pdf; language = mr, en or hi.
 * `filter` takes the GET /voters keys (voter kinds) or ward_id (+ booth_id for demographics); empty `columns` =
 * the server's default columns.
 */
@Serializable
data class ExportIn(
    val kind: String,
    val format: String,
    val language: String = "mr",
    val filter: JsonObject = JsonObject(emptyMap()),
    val columns: List<String> = emptyList(),
    val options: JsonObject = JsonObject(emptyMap()),
)

/** status = queued, running, done or failed (`error` is a plain message for the user). */
@Serializable
data class ExportJob(
    val id: String,
    val kind: String,
    val format: String,
    val status: String,
    @SerialName("row_count") val rowCount: Int? = null,
    @SerialName("page_count") val pageCount: Int? = null,
    val error: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("finished_at") val finishedAt: String? = null,
)
