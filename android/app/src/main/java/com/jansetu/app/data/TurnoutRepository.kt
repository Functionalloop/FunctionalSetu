package com.jansetu.app.data

import androidx.room.withTransaction
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.OutboxEntity
import com.jansetu.app.data.local.TurnoutEntity
import com.jansetu.app.data.remote.ApiJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.time.Instant
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Polling day (8.2). A mark or an undo is saved on the phone and queued for /sync/push in one transaction,
 * so it shows at once and works offline (push types `voted` and `unvoted`, context/sync.md).
 * A mark item carries its own id (entity_id) and the voter ids; the server never marks twice for one id.
 */
@Singleton
class TurnoutRepository @Inject constructor(private val local: LocalDb) {
    private val db get() = local.db

    /**
     * Marks these voters as voted. Voters already voted on the phone are left as they are.
     * source: single, bulk_typed or booth_list. Returns how many were marked now.
     */
    suspend fun markVoted(voterIds: List<String>, source: String, userId: String): Int {
        val now = Instant.now().toString()
        return db.withTransaction {
            val voted = db.turnout().get(voterIds.distinct()).filter { it.isVoted }.map { it.voterId }.toSet()
            val todo = voterIds.distinct().filter { it !in voted }
            if (todo.isEmpty()) return@withTransaction 0
            db.turnout().upsert(todo.map { TurnoutEntity(it, true, userId, now, source, pending = true) })
            queue(OutboxEntity.TYPE_VOTED, UUID.randomUUID().toString(), markData(todo, source, now), now)
            todo.size
        }
    }

    /**
     * Undoes the voter's mark. A mark that never left the phone is simply taken back (out of its queued
     * item); otherwise an `unvoted` item goes up.
     */
    suspend fun undo(voterId: String, userId: String) {
        val now = Instant.now().toString()
        db.withTransaction {
            val row = db.turnout().get(voterId)
            if (row == null || !row.isVoted) return@withTransaction
            val unsent = if (row.pending) db.outbox().unsentMarksOf(voterId).firstOrNull() else null
            if (unsent != null && takeOut(unsent, voterId, now)) {
                // The server never had this mark. An earlier undo still on its way keeps the row "undone".
                if (db.outbox().turnoutQueuedFor(voterId) > 0) {
                    db.turnout().upsert(listOf(row.copy(isVoted = false, pending = true)))
                } else {
                    db.turnout().delete(listOf(voterId))
                }
                return@withTransaction
            }
            db.turnout().upsert(listOf(row.copy(isVoted = false, markedBy = row.markedBy ?: userId, pending = true)))
            queue(OutboxEntity.TYPE_UNVOTED, voterId, "{}", now)
        }
    }

    /** Removes the voter from a mark item not sent yet (the whole item when it was the only one). */
    private suspend fun takeOut(item: OutboxEntity, voterId: String, now: String): Boolean {
        val data = ApiJson.parseToJsonElement(item.data).jsonObject
        val ids = data["voter_ids"]?.jsonArray?.map { it.jsonPrimitive.content } ?: return false
        if (voterId !in ids) return false
        val rest = ids - voterId
        if (rest.isEmpty()) {
            db.outbox().delete(item.id)
            return true
        }
        val source = data["source"]?.jsonPrimitive?.content ?: "single"
        val at = data["marked_at"]?.jsonPrimitive?.content ?: now
        return db.outbox().replaceData(item.id, markData(rest, source, at), item.changedAt) > 0
    }

    private fun markData(ids: List<String>, source: String, at: String) = buildJsonObject {
        put("voter_ids", JsonArray(ids.map { JsonPrimitive(it) }))
        put("source", source)
        put("marked_at", at)
    }.toString()

    private suspend fun queue(type: String, entityId: String, data: String, now: String) {
        db.outbox().insert(
            OutboxEntity(UUID.randomUUID().toString(), type, entityId, 0, now, data, seq = nextSeq()),
        )
    }

    // A mark and its undo in the same millisecond must keep their order.
    private var lastSeq = 0L
    @Synchronized private fun nextSeq(): Long {
        lastSeq = maxOf(System.currentTimeMillis(), lastSeq + 1)
        return lastSeq
    }
}
