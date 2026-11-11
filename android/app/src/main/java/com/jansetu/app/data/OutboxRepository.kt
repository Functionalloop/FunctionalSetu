package com.jansetu.app.data

import androidx.room.withTransaction
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.OutboxEntity
import com.jansetu.app.data.local.SurveyEntity
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import java.time.Instant
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/** A place fix taken when the survey is saved (never tracked in the background). */
data class Fix(val lat: Double, val lng: Double, val accuracyM: Double?)

@Singleton
class OutboxRepository @Inject constructor(private val local: LocalDb) {

    /**
     * Saves the survey on the phone and queues it for /sync/push in one transaction.
     * The screen shows the change at once; the server sees it at the next sync.
     */
    suspend fun saveSurvey(edit: SurveyEntity, fix: Fix?) {
        val db = local.db
        val now = Instant.now().toString()
        db.withTransaction {
            val before = db.voters().survey(edit.voterId)
            val row = edit.copy(
                version = before?.version ?: 0,
                isSurveyed = true,
                surveyedAt = before?.surveyedAt ?: now,
                lat = fix?.lat ?: before?.lat,
                lng = fix?.lng ?: before?.lng,
                locationAccuracyM = if (fix != null) fix.accuracyM else before?.locationAccuracyM,
                locationCapturedAt = if (fix != null) now else before?.locationCapturedAt,
                updatedAt = now,
                pending = true,
                conflict = before?.conflict ?: false,
            )
            db.voters().saveLocalSurvey(row)

            val data = surveyData(row, fix).toString()
            val outbox = db.outbox()
            // An edit not sent yet is simply replaced (same id). Once sent, a new edit is a new item;
            // the push rebases it on the version the first one gets.
            val unsent = outbox.unsent(row.voterId, OutboxEntity.TYPE_SURVEY)
            if (unsent == null || outbox.replaceData(unsent.id, data, now) == 0) {
                outbox.insert(
                    OutboxEntity(
                        id = UUID.randomUUID().toString(), type = OutboxEntity.TYPE_SURVEY,
                        entityId = row.voterId, baseVersion = row.version, changedAt = now, data = data,
                    ),
                )
            }
        }
    }

    /** The PUT /voters/{id}/survey body without `version` (SurveyIn). `location` only when taken now. */
    fun surveyData(s: SurveyEntity, fix: Fix?): JsonObject = buildJsonObject {
        put("mobile_1", s.mobile1)
        put("mobile_2", s.mobile2)
        put("dob", s.dob)
        put("caste_id", s.casteId)
        put("profession_id", s.professionId)
        put("color_tag_id", s.colorTagId)
        put("has_new_address", s.hasNewAddress)
        put("new_address_mr", s.newAddressMr)
        put("new_address_en", s.newAddressEn)
        put("notes", s.notes)
        put("extra_check_1", s.extraCheck1)
        put("extra_check_2", s.extraCheck2)
        put("extra_info_1", s.extraInfo1)
        put("extra_info_2", s.extraInfo2)
        put("extra_info_3", s.extraInfo3)
        put("extra_info_4", s.extraInfo4)
        put("extra_info_5", s.extraInfo5)
        if (fix != null) putJsonObject("location") {
            put("lat", fix.lat)
            put("lng", fix.lng)
            put("accuracy_m", fix.accuracyM)
        }
    }
}
