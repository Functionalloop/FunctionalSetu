package com.jansetu.app.data.local

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

// Rows mirror the /sync/pull payload (docs/openapi.json: SyncArea, SyncVoter, Survey, SyncLists).
// IDs are the server's UUIDs as strings. Dates are ISO 8601 strings, as sent.

@Entity(tableName = "areas", indices = [Index("parent_id"), Index("level")])
data class AreaEntity(
    @PrimaryKey val id: String,
    @ColumnInfo(name = "parent_id") val parentId: String?,
    val level: String,
    val code: String,
    val number: Int?,
    @ColumnInfo(name = "name_mr") val nameMr: String,
    @ColumnInfo(name = "name_en") val nameEn: String?,
    @ColumnInfo(name = "address_mr") val addressMr: String?,
    @ColumnInfo(name = "address_en") val addressEn: String?,
    @ColumnInfo(name = "ac_no") val acNo: Int?,
    @ColumnInfo(name = "sort_order") val sortOrder: Int,
)

@Entity(
    tableName = "voters",
    indices = [
        Index("ward_id"), Index("booth_id"), Index("serial_no"),
        Index(value = ["part_no", "booth_no", "serial_no"]),
        // Walk list (7.4): the houses of one booth.
        Index(value = ["booth_id", "house_no"]),
    ],
)
data class VoterEntity(
    @PrimaryKey val id: String,
    @ColumnInfo(name = "local_body_id") val localBodyId: String,
    @ColumnInfo(name = "ward_id") val wardId: String,
    @ColumnInfo(name = "booth_id") val boothId: String,
    @ColumnInfo(name = "section_id") val sectionId: String?,
    @ColumnInfo(name = "part_no") val partNo: Int,
    @ColumnInfo(name = "booth_no") val boothNo: Int?,
    @ColumnInfo(name = "serial_no") val serialNo: Int,
    @ColumnInfo(name = "epic_no") val epicNo: String?,
    @ColumnInfo(name = "first_name_mr") val firstNameMr: String?,
    @ColumnInfo(name = "middle_name_mr") val middleNameMr: String?,
    @ColumnInfo(name = "last_name_mr") val lastNameMr: String?,
    @ColumnInfo(name = "first_name_en") val firstNameEn: String?,
    @ColumnInfo(name = "middle_name_en") val middleNameEn: String?,
    @ColumnInfo(name = "last_name_en") val lastNameEn: String?,
    @ColumnInfo(name = "relation_type") val relationType: String?,
    @ColumnInfo(name = "relative_name_mr") val relativeNameMr: String?,
    @ColumnInfo(name = "relative_name_en") val relativeNameEn: String?,
    val gender: String,
    val age: Int?,
    @ColumnInfo(name = "age_as_of") val ageAsOf: String?,
    @ColumnInfo(name = "house_no") val houseNo: String?,
    @ColumnInfo(name = "address_mr") val addressMr: String?,
    @ColumnInfo(name = "address_en") val addressEn: String?,
    @ColumnInfo(name = "list_type") val listType: String,
    @ColumnInfo(name = "roll_status") val rollStatus: String,
    @ColumnInfo(name = "deletion_reason") val deletionReason: String?,
    @ColumnInfo(name = "is_repeated_in_roll") val isRepeatedInRoll: Boolean,
)

/**
 * The phone's copy of a voter's survey. [version] is the last version the server confirmed
 * (0 = none yet); a local save keeps it and sets [pending] until the push result arrives.
 */
@Entity(tableName = "surveys", indices = [Index("color_tag_id"), Index("is_surveyed"), Index("is_influencer")])
data class SurveyEntity(
    @PrimaryKey @ColumnInfo(name = "voter_id") val voterId: String,
    @ColumnInfo(name = "mobile_1") val mobile1: String? = null,
    @ColumnInfo(name = "mobile_2") val mobile2: String? = null,
    val dob: String? = null,
    @ColumnInfo(name = "caste_id") val casteId: String? = null,
    @ColumnInfo(name = "profession_id") val professionId: String? = null,
    @ColumnInfo(name = "color_tag_id") val colorTagId: String? = null,
    @ColumnInfo(name = "has_new_address") val hasNewAddress: Boolean = false,
    @ColumnInfo(name = "new_address_mr") val newAddressMr: String? = null,
    @ColumnInfo(name = "new_address_en") val newAddressEn: String? = null,
    val notes: String? = null,
    @ColumnInfo(name = "extra_check_1") val extraCheck1: Boolean? = null,
    @ColumnInfo(name = "extra_check_2") val extraCheck2: Boolean? = null,
    @ColumnInfo(name = "extra_info_1") val extraInfo1: String? = null,
    @ColumnInfo(name = "extra_info_2") val extraInfo2: String? = null,
    @ColumnInfo(name = "extra_info_3") val extraInfo3: String? = null,
    @ColumnInfo(name = "extra_info_4") val extraInfo4: String? = null,
    @ColumnInfo(name = "extra_info_5") val extraInfo5: String? = null,
    // Client changes of 12 Nov (SRS 1.1); no Important voter field or position since 7.13 (database version 3)
    @ColumnInfo(name = "is_influencer") val isInfluencer: Boolean = false,
    @ColumnInfo(name = "influencer_type_id") val influencerTypeId: String? = null,
    @ColumnInfo(name = "in_self_help_group") val inSelfHelpGroup: Boolean = false,
    @ColumnInfo(name = "self_help_group_name") val selfHelpGroupName: String? = null,
    /** AAY, PHH or NPHH; null = not asked. */
    @ColumnInfo(name = "ration_card") val rationCard: String? = null,
    val version: Int = 0,
    @ColumnInfo(name = "is_surveyed") val isSurveyed: Boolean = false,
    @ColumnInfo(name = "surveyed_at") val surveyedAt: String? = null,
    val lat: Double? = null,
    val lng: Double? = null,
    @ColumnInfo(name = "location_accuracy_m") val locationAccuracyM: Double? = null,
    @ColumnInfo(name = "location_captured_at") val locationCapturedAt: String? = null,
    @ColumnInfo(name = "updated_at") val updatedAt: String? = null,
    /** A local change is waiting in the outbox; a pull must not overwrite it. */
    val pending: Boolean = false,
    /** The server refused the last push as a version conflict; shown on the Sync screen. */
    val conflict: Boolean = false,
)

/** Simple lists: kind = "caste" | "profession" | "influencer_type". */
@Entity(tableName = "list_entries", indices = [Index("kind")])
data class ListEntryEntity(
    @PrimaryKey val id: String,
    val kind: String,
    @ColumnInfo(name = "name_mr") val nameMr: String,
    @ColumnInfo(name = "name_en") val nameEn: String?,
    @ColumnInfo(name = "sort_order") val sortOrder: Int,
    @ColumnInfo(name = "is_active") val isActive: Boolean,
)

@Entity(tableName = "color_tags")
data class ColorTagEntity(
    @PrimaryKey val id: String,
    val code: String,
    val hex: String,
    @ColumnInfo(name = "label_mr") val labelMr: String,
    @ColumnInfo(name = "label_en") val labelEn: String,
    @ColumnInfo(name = "is_default") val isDefault: Boolean,
    @ColumnInfo(name = "sort_order") val sortOrder: Int,
    @ColumnInfo(name = "is_active") val isActive: Boolean,
)

@Entity(tableName = "custom_field_labels")
data class CustomFieldLabelEntity(
    @PrimaryKey @ColumnInfo(name = "field_key") val fieldKey: String,
    @ColumnInfo(name = "label_mr") val labelMr: String?,
    @ColumnInfo(name = "label_en") val labelEn: String?,
    @ColumnInfo(name = "is_enabled") val isEnabled: Boolean,
)

/**
 * One offline change waiting for POST /sync/push. [id] is made once on the phone and sent
 * unchanged on every retry, so the server never applies it twice.
 * status: "queued" (to send), "conflict" (server copy differs), "rejected" (server refused).
 */
@Entity(tableName = "outbox", indices = [Index("status"), Index("entity_id")])
data class OutboxEntity(
    @PrimaryKey val id: String,
    val type: String,
    @ColumnInfo(name = "entity_id") val entityId: String,
    @ColumnInfo(name = "base_version") val baseVersion: Int,
    @ColumnInfo(name = "changed_at") val changedAt: String,
    /** JSON of the push item's `data`. */
    val data: String,
    val status: String = STATUS_QUEUED,
    val attempts: Int = 0,
    @ColumnInfo(name = "error_code") val errorCode: String? = null,
    @ColumnInfo(name = "error_message") val errorMessage: String? = null,
    @ColumnInfo(name = "conflict_fields") val conflictFields: String? = null,
    /** On a conflict: the server's survey JSON, to show next to the phone's copy. */
    @ColumnInfo(name = "server_copy") val serverCopy: String? = null,
    /** Order of saves on this phone; items are pushed in this order. */
    val seq: Long = System.currentTimeMillis(),
) {
    companion object {
        const val STATUS_QUEUED = "queued"
        const val STATUS_CONFLICT = "conflict"
        const val STATUS_REJECTED = "rejected"
        const val TYPE_SURVEY = "survey"
        /** A new Kutumb; entity_id = the Kutumb's id. Always sent before the `family` items that use it. */
        const val TYPE_FAMILY_NEW = "family_new"
        /** A voter put in a Kutumb or taken out; entity_id = the voter. */
        const val TYPE_FAMILY = "family"
        /** A visit; entity_id = the voter, data.id = the visit's id. */
        const val TYPE_VISIT = "visit"
        /** Eligible but Not Registered, made on the phone; entity_id = its id, base_version 0. */
        const val TYPE_NEW_VOTER = "new_voter"
        /** An edit of one; entity_id = its id, base_version = the version the phone last had. */
        const val TYPE_NEW_VOTER_UPDATE = "new_voter_update"
        /** A slip shared (7.7); entity_id = the voter, data = {id, channel, at}. Nothing kept locally. */
        const val TYPE_SLIP_EVENT = "slip_event"
    }
}

/** Small key-value store for sync progress (watermark, pull cursor, settings JSON, user JSON). */
@Entity(tableName = "sync_state")
data class SyncStateEntity(
    @PrimaryKey val key: String,
    val value: String?,
)

/**
 * A Kutumb (7.4): made by hand by a surveyor, a name and its members, in one booth.
 * [pending] = made or renamed on this phone and not confirmed by the server yet.
 */
@Entity(tableName = "families", indices = [Index("booth_id")])
data class FamilyEntity(
    @PrimaryKey val id: String,
    @ColumnInfo(name = "ward_id") val wardId: String?,
    @ColumnInfo(name = "booth_id") val boothId: String,
    val label: String?,
    @ColumnInfo(name = "updated_at") val updatedAt: String?,
    val pending: Boolean = false,
)

/** A voter's Kutumb. Only voters in a Kutumb have a row; taking a voter out deletes it. */
@Entity(tableName = "family_members", indices = [Index("family_id")])
data class FamilyMemberEntity(
    @PrimaryKey @ColumnInfo(name = "voter_id") val voterId: String,
    @ColumnInfo(name = "family_id") val familyId: String,
)

/**
 * A door-to-door visit (7.3 on the server). booth_id and house_no are the voter's, so the walk
 * list finds the last visit of a house. outcome: met, not_home, revisit, shifted.
 */
@Entity(tableName = "visits", indices = [Index(value = ["booth_id", "house_no"]), Index("voter_id")])
data class VisitEntity(
    @PrimaryKey val id: String,
    @ColumnInfo(name = "voter_id") val voterId: String?,
    @ColumnInfo(name = "booth_id") val boothId: String,
    @ColumnInfo(name = "house_no") val houseNo: String?,
    val outcome: String,
    @ColumnInfo(name = "visited_at") val visitedAt: String,
    @ColumnInfo(name = "revisit_at") val revisitAt: String? = null,
    val note: String? = null,
    @ColumnInfo(name = "visited_by") val visitedBy: String,
    /** Made on this phone, not sent yet. */
    val pending: Boolean = false,
)

/**
 * Eligible but Not Registered (7.5): a person who can vote but is not on the roll. Belongs to a part
 * (booth_id) or, with no part, its Village Panchayat (ward_id). [version] is the last version the server
 * confirmed (1 for a record not confirmed yet: the server gives 1 on create); [pending] / [conflict] as
 * on surveys. form6_status: not_applied, applied, approved, rejected.
 */
@Entity(tableName = "new_voters", indices = [Index("booth_id"), Index("ward_id"), Index("created_at")])
data class NewVoterEntity(
    @PrimaryKey val id: String,
    @ColumnInfo(name = "full_name_en") val fullNameEn: String? = null,
    @ColumnInfo(name = "full_name_mr") val fullNameMr: String? = null,
    @ColumnInfo(name = "relative_name") val relativeName: String? = null,
    /** yyyy-MM-dd */
    val dob: String? = null,
    /** M, F or O */
    val gender: String? = null,
    val mobile: String? = null,
    val address: String? = null,
    @ColumnInfo(name = "ward_id") val wardId: String,
    @ColumnInfo(name = "booth_id") val boothId: String? = null,
    @ColumnInfo(name = "family_id") val familyId: String? = null,
    @ColumnInfo(name = "form6_status") val form6Status: String = "not_applied",
    val notes: String? = null,
    val version: Int = 1,
    @ColumnInfo(name = "matched_voter_id") val matchedVoterId: String? = null,
    @ColumnInfo(name = "created_by") val createdBy: String? = null,
    @ColumnInfo(name = "created_at") val createdAt: String,
    @ColumnInfo(name = "updated_at") val updatedAt: String? = null,
    val pending: Boolean = false,
    val conflict: Boolean = false,
)
