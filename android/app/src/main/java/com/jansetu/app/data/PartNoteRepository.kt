package com.jansetu.app.data

import androidx.room.withTransaction
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.OutboxEntity
import com.jansetu.app.data.local.PartNoteEntity
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.time.Instant
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

const val PART_NOTE_MAX = 2000

/**
 * Part notes (7.11): a save is the local row plus a `part_note` outbox item in one transaction, on top
 * of the version the phone has (0 = none yet). An item not sent yet takes the new text instead of a
 * second item; an item already on its way is followed by a new one, rebased when the first comes back.
 */
@Singleton
class PartNoteRepository @Inject constructor(private val local: LocalDb) {
    private val db get() = local.db

    suspend fun save(boothId: String, text: String, userId: String) {
        val note = text.trim().take(PART_NOTE_MAX)
        val now = Instant.now().toString()
        db.withTransaction {
            val before = db.partNotes().get(boothId)
            val row = PartNoteEntity(
                boothId, note, before?.version ?: 0, now, userId, pending = true, conflict = before?.conflict ?: false,
            )
            db.partNotes().upsert(listOf(row))
            val data = buildJsonObject { put("note", note) }.toString()
            val outbox = db.outbox()
            val unsent = outbox.unsent(boothId, OutboxEntity.TYPE_PART_NOTE)
            if (unsent == null || outbox.replaceData(unsent.id, data, now) == 0) {
                outbox.insert(OutboxEntity(UUID.randomUUID().toString(), OutboxEntity.TYPE_PART_NOTE, boothId, row.version, now, data))
            }
        }
    }
}
