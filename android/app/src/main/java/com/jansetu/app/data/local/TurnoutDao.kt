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
 * 8.2: a voter's voted mark (polling day). One row per voter, like the server's voter_turnout.
 * [isVoted] false = the mark was undone. [pending] = changed on this phone and not confirmed yet;
 * a pulled mark never overwrites it.
 */
@Entity(tableName = "turnout")
data class TurnoutEntity(
    @PrimaryKey @ColumnInfo(name = "voter_id") val voterId: String,
    @ColumnInfo(name = "is_voted") val isVoted: Boolean,
    @ColumnInfo(name = "marked_by") val markedBy: String?,
    @ColumnInfo(name = "marked_at") val markedAt: String?,
    /** single, bulk_typed, booth_list or admin */
    val source: String?,
    val pending: Boolean = false,
)

/** One voter of a part on the Mark voted screen. */
data class MarkRow(
    val id: String,
    @ColumnInfo(name = "serial_no") val serialNo: Int,
    @ColumnInfo(name = "first_name_en") val firstNameEn: String?,
    @ColumnInfo(name = "middle_name_en") val middleNameEn: String?,
    @ColumnInfo(name = "last_name_en") val lastNameEn: String?,
    @ColumnInfo(name = "first_name_mr") val firstNameMr: String?,
    @ColumnInfo(name = "middle_name_mr") val middleNameMr: String?,
    @ColumnInfo(name = "last_name_mr") val lastNameMr: String?,
    @ColumnInfo(name = "is_voted") val isVoted: Boolean,
    val pending: Boolean,
)

data class PartTurnout(val voters: Int, val voted: Int)

@Dao
abstract class TurnoutDao {
    @Upsert abstract suspend fun upsert(rows: List<TurnoutEntity>)
    @Query("SELECT * FROM turnout WHERE voter_id = :voterId") abstract suspend fun get(voterId: String): TurnoutEntity?
    @Query("SELECT * FROM turnout WHERE voter_id IN (:ids)") abstract suspend fun get(ids: List<String>): List<TurnoutEntity>
    @Query("DELETE FROM turnout WHERE voter_id IN (:ids)") abstract suspend fun delete(ids: List<String>)

    @Query("SELECT voter_id FROM turnout WHERE pending = 1 AND voter_id IN (:ids)")
    protected abstract suspend fun pendingIds(ids: List<String>): List<String>

    /** Pulled marks, except those changed on this phone and not confirmed yet. */
    @Transaction
    open suspend fun savePulled(rows: List<TurnoutEntity>) {
        if (rows.isEmpty()) return
        val keep = rows.map { it.voterId }.chunked(500).flatMap { pendingIds(it) }.toSet()
        upsert(rows.filter { it.voterId !in keep })
    }

    /** Marks of voters no longer on the phone (their part left, or they were removed). */
    @Query("DELETE FROM turnout WHERE voter_id NOT IN (SELECT id FROM voters)")
    abstract suspend fun dropOrphans()

    /** Voters of a part on the current roll (only they can vote), in serial order, with their mark. */
    @Query(
        """SELECT v.id, v.serial_no, v.first_name_en, v.middle_name_en, v.last_name_en,
                  v.first_name_mr, v.middle_name_mr, v.last_name_mr,
                  coalesce(t.is_voted, 0) AS is_voted, coalesce(t.pending, 0) AS pending
             FROM voters v LEFT JOIN turnout t ON t.voter_id = v.id
            WHERE v.booth_id = :boothId AND v.roll_status = 'active'
            ORDER BY v.serial_no""",
    )
    abstract fun part(boothId: String): Flow<List<MarkRow>>

    @Query(
        """SELECT count(*) AS voters, coalesce(sum(t.is_voted), 0) AS voted
             FROM voters v LEFT JOIN turnout t ON t.voter_id = v.id
            WHERE v.booth_id = :boothId AND v.roll_status = 'active'""",
    )
    abstract fun partCounts(boothId: String): Flow<PartTurnout>

    /** When each voted voter of the part was marked (ISO 8601), for the by-hour bars. */
    @Query(
        """SELECT t.marked_at FROM turnout t JOIN voters v ON v.id = t.voter_id
            WHERE v.booth_id = :boothId AND v.roll_status = 'active' AND t.is_voted = 1 AND t.marked_at IS NOT NULL""",
    )
    abstract fun markTimes(boothId: String): Flow<List<String>>
}
