package com.jansetu.app.data

import androidx.room.withTransaction
import com.jansetu.app.data.local.FamilyEntity
import com.jansetu.app.data.local.FamilyMemberEntity
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.OutboxEntity
import com.jansetu.app.data.local.VisitEntity
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.FamilyPatch
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.apiCall
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.time.Instant
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/** Kutumb name rules of the server (KutumbName): 1 to 200 characters after trimming. */
const val KUTUMB_NAME_MAX = 200

/**
 * Kutumb Connect and walk-list visits (7.4). Every change is saved on the phone and queued for
 * /sync/push in one transaction, so it shows at once and goes up at the next sync
 * (push types family_new, family and visit; context/sync.md).
 */
@Singleton
class FieldRepository @Inject constructor(private val local: LocalDb, private val api: JansetuApi) {
    private val db get() = local.db

    /** Makes a Kutumb in the voter's booth and puts these voters in it. Returns the Kutumb's id. */
    suspend fun newKutumb(boothId: String, wardId: String?, label: String, memberIds: List<String>): String {
        val name = label.trim().take(KUTUMB_NAME_MAX)
        require(name.isNotEmpty()) { "A Kutumb needs a name." }
        val id = UUID.randomUUID().toString()
        val now = Instant.now().toString()
        db.withTransaction {
            db.field().upsertFamilies(listOf(FamilyEntity(id, wardId, boothId, name, now, pending = true)))
            val data = buildJsonObject { put("id", id); put("booth_id", boothId); put("label", name) }
            // Queued before the members' items (seq), so the push sends the Kutumb first.
            queue(OutboxEntity.TYPE_FAMILY_NEW, id, data.toString(), now)
            memberIds.forEach { setMembership(it, id, now) }
        }
        return id
    }

    /** Puts the voter in this Kutumb (moving them out of another one). */
    suspend fun putIn(voterId: String, familyId: String) = db.withTransaction {
        setMembership(voterId, familyId, Instant.now().toString())
    }

    /** Takes the voter out of their Kutumb. */
    suspend fun takeOut(voterId: String) = db.withTransaction {
        setMembership(voterId, null, Instant.now().toString())
    }

    private suspend fun setMembership(voterId: String, familyId: String?, now: String) {
        val field = db.field()
        if (familyId == null) field.deleteMembers(listOf(voterId)) else field.upsertMembers(listOf(FamilyMemberEntity(voterId, familyId)))
        val outbox = db.outbox()
        // Only the last membership counts (last change wins on the server). An earlier one not sent
        // yet is dropped, and the new one goes to the end: after any Kutumb it names.
        outbox.unsent(voterId, OutboxEntity.TYPE_FAMILY)?.let { outbox.delete(it.id) }
        val data = buildJsonObject {
            if (familyId == null) put("leave_family", true) else put("family_id", familyId)
        }
        queue(OutboxEntity.TYPE_FAMILY, voterId, data.toString(), now)
    }

    /**
     * Renames a Kutumb. A Kutumb not sent yet is renamed in its queued item; otherwise this needs the
     * internet (PATCH /families/{id}; there is no push type for a rename). Returns an error text or null.
     */
    suspend fun rename(familyId: String, label: String): String? {
        val name = label.trim().take(KUTUMB_NAME_MAX)
        if (name.isEmpty()) return "A Kutumb needs a name."
        val field = db.field()
        val family = field.family(familyId) ?: return "This Kutumb is no longer on this phone."
        if (family.pending) {
            val now = Instant.now().toString()
            val changed = db.withTransaction {
                val item = db.outbox().unsent(familyId, OutboxEntity.TYPE_FAMILY_NEW) ?: return@withTransaction false
                val data = buildJsonObject { put("id", familyId); put("booth_id", family.boothId); put("label", name) }
                if (db.outbox().replaceData(item.id, data.toString(), now) == 0) return@withTransaction false
                field.setLabel(familyId, name, pending = true, updatedAt = now)
                true
            }
            return if (changed) null else "This Kutumb is being sent. Sync, then rename it."
        }
        return when (val r = apiCall { api.renameFamily(familyId, FamilyPatch(name)) }) {
            is ApiResult.Ok -> { field.setLabel(familyId, r.value.label, pending = false, updatedAt = r.value.updatedAt); null }
            is ApiResult.Offline -> "Renaming a Kutumb needs internet. Try again when online."
            is ApiResult.Err -> r.message
        }
    }

    /**
     * Marks a house on the walk list: a visit on one voter of the house (the server copies booth and
     * house from that voter). outcome: met, not_home, revisit, shifted.
     */
    suspend fun markVisit(voterId: String, outcome: String, userId: String) {
        val voter = db.voters().voter(voterId) ?: return
        val id = UUID.randomUUID().toString()
        val now = Instant.now().toString()
        db.withTransaction {
            db.field().upsertVisits(listOf(VisitEntity(id, voterId, voter.boothId, voter.houseNo, outcome, now, visitedBy = userId, pending = true)))
            val data = buildJsonObject { put("id", id); put("outcome", outcome); put("visited_at", now) }
            queue(OutboxEntity.TYPE_VISIT, voterId, data.toString(), now)
        }
    }

    private suspend fun queue(type: String, entityId: String, data: String, now: String) {
        db.outbox().insert(
            OutboxEntity(
                id = UUID.randomUUID().toString(), type = type, entityId = entityId, baseVersion = 0,
                changedAt = now, data = data, seq = nextSeq(),
            ),
        )
    }

    // Items made in the same millisecond must keep their order (a Kutumb before its members).
    private var lastSeq = 0L
    @Synchronized private fun nextSeq(): Long {
        lastSeq = maxOf(System.currentTimeMillis(), lastSeq + 1)
        return lastSeq
    }
}
