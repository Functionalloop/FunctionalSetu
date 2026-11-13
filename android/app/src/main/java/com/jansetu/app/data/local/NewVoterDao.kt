package com.jansetu.app.data.local

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

/** Eligible but Not Registered (7.5). Written by the pull and by NewVoterRepository. */
@Dao
abstract class NewVoterDao {
    @Upsert abstract suspend fun upsert(rows: List<NewVoterEntity>)
    @Query("SELECT * FROM new_voters WHERE id = :id") abstract suspend fun get(id: String): NewVoterEntity?
    @Query("SELECT * FROM new_voters WHERE id = :id") abstract fun flow(id: String): Flow<NewVoterEntity?>
    @Query("DELETE FROM new_voters WHERE id = :id") abstract suspend fun delete(id: String)

    /** Newest first; status null = all. */
    @Query("""SELECT * FROM new_voters WHERE (:status IS NULL OR form6_status = :status)
              ORDER BY created_at DESC, id DESC""")
    abstract fun list(status: String?): Flow<List<NewVoterEntity>>

    @Query("SELECT id FROM new_voters WHERE (pending = 1 OR conflict = 1) AND id IN (:ids)")
    protected abstract suspend fun changedHere(ids: List<String>): List<String>

    /** Pulled records, except those changed on this phone and not confirmed yet. */
    @Transaction
    open suspend fun savePulled(rows: List<NewVoterEntity>) {
        if (rows.isEmpty()) return
        val keep = rows.map { it.id }.chunked(500).flatMap { changedHere(it) }.toSet()
        upsert(rows.filter { it.id !in keep })
    }

    /** After the area list changed: drop records whose part (or Village Panchayat) left the phone. */
    @Query("DELETE FROM new_voters WHERE coalesce(booth_id, ward_id) NOT IN (:keep)")
    abstract suspend fun dropOutside(keep: List<String>)
}
