package com.jansetu.app.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
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
    @SerialName("is_important") val isImportant: Boolean = false,
    @SerialName("position_id") val positionId: String? = null,
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
    @SerialName("is_default") val isDefault: Boolean = false,
    @SerialName("sort_order") val sortOrder: Int = 0,
    @SerialName("is_active") val isActive: Boolean = true,
)

@Serializable
data class CustomFieldLabelDto(
    @SerialName("field_key") val fieldKey: String,
    @SerialName("label_mr") val labelMr: String? = null,
    @SerialName("label_en") val labelEn: String? = null,
    @SerialName("is_enabled") val isEnabled: Boolean = false,
)

@Serializable
data class SyncLists(
    val castes: List<NamedListEntry> = emptyList(),
    val professions: List<NamedListEntry> = emptyList(),
    @SerialName("color_tags") val colorTags: List<ColorTagDto> = emptyList(),
    @SerialName("custom_field_labels") val customFieldLabels: List<CustomFieldLabelDto> = emptyList(),
    val positions: List<NamedListEntry> = emptyList(),
    @SerialName("influencer_types") val influencerTypes: List<NamedListEntry> = emptyList(),
)

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
)

@Serializable data class PushResponse(val results: List<PushResult>)

@Serializable
data class ErrorBody(
    val code: String,
    val message: String,
    val current: JsonObject? = null,
)

@Serializable data class ErrorResponse(val error: ErrorBody)
