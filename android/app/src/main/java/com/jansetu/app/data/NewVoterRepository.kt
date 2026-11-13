package com.jansetu.app.data

import androidx.room.withTransaction
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.NewVoterEntity
import com.jansetu.app.data.local.OutboxEntity
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.time.Instant
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Eligible but Not Registered (7.5): a save is the local row plus an outbox item in one transaction.
 * A record not sent yet keeps one `new_voter` item (its data replaced by each edit). After that, edits
 * are `new_voter_update` items carrying the version the phone last had; the push rebases the next one
 * on the version the server returns, as for surveys.
 */
@Singleton
class NewVoterRepository @Inject constructor(private val local: LocalDb) {
    private val db get() = local.db

    /** Saves a new record (edit.id empty) or an edit. Returns the record's id. */
    suspend fun save(edit: NewVoterEntity, userId: String): String {
        val now = Instant.now().toString()
        return db.withTransaction {
            val before = edit.id.takeIf { it.isNotEmpty() }?.let { db.newVoters().get(it) }
            val row = clean(edit).copy(
                id = before?.id ?: UUID.randomUUID().toString(),
                version = before?.version ?: 1,
                matchedVoterId = before?.matchedVoterId,
                createdBy = before?.createdBy ?: userId,
                createdAt = before?.createdAt ?: now,
                updatedAt = now,
                pending = true,
                conflict = before?.conflict ?: false,
            )
            db.newVoters().upsert(listOf(row))

            val outbox = db.outbox()
            val data = newVoterPushData(row)
            val unsentCreate = outbox.unsent(row.id, OutboxEntity.TYPE_NEW_VOTER)
            val waitingCreate = unsentCreate != null ||
                (before != null && outbox.queuedFor(row.id, OutboxEntity.TYPE_NEW_VOTER) > 0)
            when {
                before == null -> queue(OutboxEntity.TYPE_NEW_VOTER, row.id, 0, withId(data, row.id), now)
                // Not sent yet: still a create, with the new values.
                unsentCreate != null && outbox.replaceData(unsentCreate.id, withId(data, row.id), now) > 0 -> Unit
                else -> {
                    // The create is on its way (or done): an edit on top of version 1 or the confirmed one.
                    val unsent = outbox.unsent(row.id, OutboxEntity.TYPE_NEW_VOTER_UPDATE)
                    if (unsent == null || outbox.replaceData(unsent.id, data.toString(), now) == 0) {
                        queue(OutboxEntity.TYPE_NEW_VOTER_UPDATE, row.id, if (waitingCreate) 1 else row.version,
                            data.toString(), now)
                    }
                }
            }
            row.id
        }
    }

    private suspend fun queue(type: String, id: String, base: Int, data: String, now: String) =
        db.outbox().insert(OutboxEntity(UUID.randomUUID().toString(), type, id, base, now, data))

    /** The create body: the fields plus the record's own id. */
    private fun withId(data: JsonObject, id: String) = JsonObject(data + ("id" to JsonPrimitive(id))).toString()
}

private fun String?.blankToNull() = this?.trim()?.ifEmpty { null }

/** Trims the text fields (the server does the same); empty = no value. */
fun clean(r: NewVoterEntity) = r.copy(
    fullNameEn = r.fullNameEn.blankToNull(), fullNameMr = r.fullNameMr.blankToNull(),
    relativeName = r.relativeName.blankToNull(), address = r.address.blankToNull(),
    notes = r.notes.blankToNull(), mobile = r.mobile.blankToNull(),
)

/** The POST / PATCH /new-voters body without `id` and `version` (NewVoterFields): every field, always. */
fun newVoterPushData(r: NewVoterEntity): JsonObject = buildJsonObject {
    put("full_name_en", r.fullNameEn)
    put("full_name_mr", r.fullNameMr)
    put("relative_name", r.relativeName)
    put("dob", r.dob)
    put("gender", r.gender)
    put("mobile", r.mobile)
    put("address", r.address)
    put("ward_id", r.wardId)
    put("booth_id", r.boothId)
    put("family_id", r.familyId)
    put("form6_status", r.form6Status)
    put("notes", r.notes)
}
