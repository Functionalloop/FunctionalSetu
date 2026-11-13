package com.jansetu.app.data.local

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Entity
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

/**
 * 7.11: the one shared note of a part (its booth). [version] 0 = the server has no note yet;
 * [pending] = changed here and not confirmed; [conflict] = the server refused it as stale (Sync screen).
 */
@Entity(tableName = "part_notes")
data class PartNoteEntity(
    @PrimaryKey @ColumnInfo(name = "booth_id") val boothId: String,
    val note: String,
    val version: Int,
    @ColumnInfo(name = "updated_at") val updatedAt: String? = null,
    @ColumnInfo(name = "updated_by") val updatedBy: String? = null,
    val pending: Boolean = false,
    val conflict: Boolean = false,
)

@Dao
abstract class PartNoteDao {
    @Upsert abstract suspend fun upsert(rows: List<PartNoteEntity>)
    @Query("SELECT * FROM part_notes WHERE booth_id = :boothId") abstract suspend fun get(boothId: String): PartNoteEntity?
    @Query("SELECT * FROM part_notes WHERE booth_id = :boothId") abstract fun flow(boothId: String): Flow<PartNoteEntity?>

    @Query("SELECT booth_id FROM part_notes WHERE (pending = 1 OR conflict = 1) AND booth_id IN (:ids)")
    protected abstract suspend fun changedHere(ids: List<String>): List<String>

    /** Pulled notes, except those changed on this phone and not confirmed yet. */
    @Transaction
    open suspend fun savePulled(rows: List<PartNoteEntity>) {
        if (rows.isEmpty()) return
        val keep = changedHere(rows.map { it.boothId }).toSet()
        upsert(rows.filter { it.boothId !in keep })
    }

    /** After the area list changed: drop notes of parts that left the phone. */
    @Query("DELETE FROM part_notes WHERE booth_id NOT IN (:keep)")
    abstract suspend fun dropOutside(keep: List<String>)
}
