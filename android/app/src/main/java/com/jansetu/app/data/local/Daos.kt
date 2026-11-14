package com.jansetu.app.data.local

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import androidx.room.RawQuery
import androidx.room.Transaction
import androidx.room.Upsert
import androidx.sqlite.db.SupportSQLiteQuery
import kotlinx.coroutines.flow.Flow

@Dao
abstract class VoterDao {
    @Upsert protected abstract suspend fun upsertVoterRows(rows: List<VoterEntity>)
    @Upsert protected abstract suspend fun upsertSurveyRows(rows: List<SurveyEntity>)
    @Insert protected abstract suspend fun insertFts(rows: List<VoterFts>)

    @Query("DELETE FROM voters WHERE id IN (:ids)") protected abstract suspend fun deleteVoterRows(ids: List<String>)
    @Query("DELETE FROM surveys WHERE voter_id IN (:ids)") protected abstract suspend fun deleteSurveyRows(ids: List<String>)
    @Query("DELETE FROM family_members WHERE voter_id IN (:ids)") protected abstract suspend fun deleteMemberRows(ids: List<String>)
    // FTS4 finds a row only by "rowid = ?"; "rowid IN (...)" would scan the whole index each time.
    @Query("DELETE FROM voter_fts WHERE rowid = :rowid") protected abstract suspend fun deleteFtsRow(rowid: Long)
    @Query("SELECT rowid FROM voters WHERE id IN (:ids)") protected abstract suspend fun rowids(ids: List<String>): List<Long>
    protected open suspend fun deleteFts(ids: List<String>) = rowids(ids).forEach { deleteFtsRow(it) }
    @Query("SELECT *, rowid AS rid FROM voters WHERE id IN (:ids)")
    protected abstract suspend fun votersWithRowid(ids: List<String>): List<VoterWithRowid>


    @Query("SELECT * FROM voters WHERE id IN (:ids)") abstract suspend fun voters(ids: List<String>): List<VoterEntity>
    @Query("SELECT * FROM surveys WHERE voter_id IN (:ids)") abstract suspend fun surveys(ids: List<String>): List<SurveyEntity>
    @Query("SELECT voter_id FROM surveys WHERE voter_id IN (:ids) AND (pending = 1 OR conflict = 1)")
    protected abstract suspend fun pendingIds(ids: List<String>): List<String>

    @Query("SELECT * FROM voters WHERE id = :id") abstract suspend fun voter(id: String): VoterEntity?
    @Query("SELECT * FROM voters WHERE id = :id") abstract fun voterFlow(id: String): Flow<VoterEntity?>
    @Query("SELECT * FROM surveys WHERE voter_id = :id") abstract suspend fun survey(id: String): SurveyEntity?

    /** 7.8 Birthdays: voters whose survey date of birth falls on one of these 'MM-DD' days. */
    @Query(
        """SELECT v.id, v.part_no, v.serial_no, v.first_name_en, v.middle_name_en, v.last_name_en,
                  v.first_name_mr, v.middle_name_mr, v.last_name_mr, s.dob, s.mobile_1
             FROM voters v JOIN surveys s ON s.voter_id = v.id
            WHERE s.dob IS NOT NULL AND substr(s.dob, 6, 5) IN (:days)
            ORDER BY v.part_no, v.serial_no""",
    )
    abstract suspend fun birthdays(days: List<String>): List<BirthdayRow>
    @Query("SELECT * FROM surveys WHERE voter_id = :id") abstract fun surveyFlow(id: String): Flow<SurveyEntity?>

    @RawQuery(observedEntities = [VoterEntity::class, SurveyEntity::class, ColorTagEntity::class])
    abstract fun rows(query: SupportSQLiteQuery): Flow<List<VoterRow>>

    @RawQuery(observedEntities = [VoterEntity::class, SurveyEntity::class])
    abstract fun countFlow(query: SupportSQLiteQuery): Flow<Int>

    @RawQuery abstract suspend fun rowsNow(query: SupportSQLiteQuery): List<VoterRow>
    @RawQuery abstract suspend fun countNow(query: SupportSQLiteQuery): Int

    @Query("SELECT count(*) FROM voters") abstract fun voterCount(): Flow<Int>
    @Query("SELECT count(*) FROM voters") abstract suspend fun voterCountNow(): Int
    @Query("SELECT count(*) FROM surveys WHERE is_surveyed = 1") abstract fun surveyedCount(): Flow<Int>
    @Query("SELECT count(*) FROM surveys WHERE mobile_1 IS NOT NULL") abstract fun withMobileCount(): Flow<Int>

    /** Saves one page of pulled voters. Removed ones (deletedIds) go, with their surveys. */
    @Transaction
    open suspend fun savePulledVoters(rows: List<VoterEntity>, deletedIds: List<String>) {
        if (deletedIds.isNotEmpty()) removeVoters(deletedIds)
        if (rows.isEmpty()) return
        upsertVoterRows(rows)
        reindex(rows.map { it.id })
    }

    /** Saves pulled surveys, except where a local change is waiting to be pushed or is in conflict. */
    @Transaction
    open suspend fun savePulledSurveys(rows: List<SurveyEntity>) {
        if (rows.isEmpty()) return
        val keep = pendingIds(rows.map { it.voterId }).toSet()
        val fresh = rows.filter { it.voterId !in keep }
        upsertSurveyRows(fresh)
        reindex(fresh.map { it.voterId })
    }

    /** A survey saved on this phone. */
    @Transaction
    open suspend fun saveLocalSurvey(row: SurveyEntity) {
        upsertSurveyRows(listOf(row))
        reindex(listOf(row.voterId))
    }

    @Upsert abstract suspend fun upsertSurvey(row: SurveyEntity)

    @Transaction
    open suspend fun removeVoters(ids: List<String>) {
        ids.chunked(500).forEach {
            deleteFts(it); deleteSurveyRows(it); deleteMemberRows(it); deleteVoterRows(it)
        }
    }

    /** Voters whose booth is no longer one of this phone's areas (area_ids holds every area in scope). */
    @Query("SELECT id FROM voters WHERE booth_id NOT IN (:keep)")
    abstract suspend fun votersOutside(keep: List<String>): List<String>

    /** Rebuilds the search row of these voters (names, EPIC, house, mobiles). */
    protected open suspend fun reindex(ids: List<String>) {
        ids.chunked(500).forEach { chunk ->
            val surveys = surveys(chunk).associateBy { it.voterId }
            val rows = votersWithRowid(chunk)
            rows.forEach { deleteFtsRow(it.rid) }
            insertFts(rows.map { VoterFts(it.rid, VoterSearch.body(it.voter, surveys[it.voter.id])) })
        }
    }
}

@Dao
interface AreaDao {
    @Upsert suspend fun upsert(rows: List<AreaEntity>)
    @Query("DELETE FROM areas WHERE id NOT IN (:keep)") suspend fun deleteOthers(keep: List<String>)
    @Query("SELECT id FROM areas") suspend fun ids(): List<String>
    @Query("SELECT * FROM areas WHERE level = :level ORDER BY sort_order, number, name_en") fun byLevel(level: String): Flow<List<AreaEntity>>
    @Query("SELECT * FROM areas WHERE parent_id = :parent ORDER BY sort_order, number, name_en") fun children(parent: String): Flow<List<AreaEntity>>
    @Query("SELECT * FROM areas WHERE id = :id") suspend fun area(id: String): AreaEntity?
    @Query("SELECT * FROM areas WHERE id IN (:ids)") suspend fun areas(ids: List<String>): List<AreaEntity>
    @Query("SELECT * FROM areas ORDER BY sort_order, number, name_en") suspend fun all(): List<AreaEntity>
}

@Dao
interface ListDao {
    @Upsert suspend fun upsertEntries(rows: List<ListEntryEntity>)
    @Upsert suspend fun upsertColorTags(rows: List<ColorTagEntity>)
    @Upsert suspend fun upsertLabels(rows: List<CustomFieldLabelEntity>)
    @Query("SELECT * FROM list_entries WHERE kind = :kind ORDER BY sort_order, name_en") fun entries(kind: String): Flow<List<ListEntryEntity>>
    @Query("SELECT * FROM color_tags ORDER BY sort_order") fun colorTags(): Flow<List<ColorTagEntity>>
    @Query("SELECT * FROM custom_field_labels") fun labels(): Flow<List<CustomFieldLabelEntity>>
}

@Dao
interface OutboxDao {
    @Insert suspend fun insert(item: OutboxEntity)
    @Query("SELECT * FROM outbox WHERE status = 'queued' ORDER BY seq LIMIT :limit") suspend fun queued(limit: Int): List<OutboxEntity>
    @Query("SELECT * FROM outbox WHERE id = :id") suspend fun item(id: String): OutboxEntity?
    @Query("SELECT * FROM outbox WHERE status != 'queued' ORDER BY seq DESC") fun problems(): Flow<List<OutboxEntity>>
    @Query("SELECT count(*) FROM outbox WHERE status = 'queued'") fun queuedCount(): Flow<Int>
    @Query("SELECT count(*) FROM outbox WHERE status = 'queued' AND type IN (:types)")
    fun queuedCountOf(types: List<String>): Flow<Int>
    /** Polling day (8.2): queued voted / unvoted items that name this voter (ids in data are quoted UUIDs). */
    @Query("""SELECT count(*) FROM outbox WHERE status = 'queued' AND
              ((type = 'unvoted' AND entity_id = :voterId) OR (type = 'voted' AND data LIKE '%"' || :voterId || '"%'))""")
    suspend fun turnoutQueuedFor(voterId: String): Int
    @Query("""SELECT * FROM outbox WHERE status = 'queued' AND attempts = 0 AND type = 'voted'
              AND data LIKE '%"' || :voterId || '"%' ORDER BY seq""")
    suspend fun unsentMarksOf(voterId: String): List<OutboxEntity>
    @Query("SELECT count(*) FROM outbox WHERE status = 'queued' AND entity_id = :entityId AND type = :type")
    suspend fun queuedFor(entityId: String, type: String): Int
    @Query("DELETE FROM outbox WHERE id = :id") suspend fun delete(id: String)
    @Query("UPDATE outbox SET attempts = attempts + 1 WHERE id IN (:ids)") suspend fun countAttempt(ids: List<String>)
    @Query("""UPDATE outbox SET status = :status, error_code = :code, error_message = :message,
              conflict_fields = :fields, server_copy = :serverCopy WHERE id = :id""")
    suspend fun mark(id: String, status: String, code: String?, message: String?, fields: String?, serverCopy: String?)
    @Query("UPDATE outbox SET base_version = :version WHERE status = 'queued' AND entity_id = :entityId AND type = :type")
    suspend fun rebase(entityId: String, type: String, version: Int)
    @Query("SELECT * FROM outbox WHERE status = 'queued' AND entity_id = :entityId AND type = :type AND attempts = 0 ORDER BY seq DESC LIMIT 1")
    suspend fun unsent(entityId: String, type: String): OutboxEntity?
    @Query("UPDATE outbox SET data = :data, changed_at = :changedAt WHERE id = :id AND attempts = 0")
    suspend fun replaceData(id: String, data: String, changedAt: String): Int
}

@Dao
interface SyncStateDao {
    @Upsert suspend fun put(row: SyncStateEntity)
    @Query("SELECT value FROM sync_state WHERE key = :key") suspend fun get(key: String): String?
    @Query("SELECT value FROM sync_state WHERE key = :key") fun flow(key: String): Flow<String?>
    @Query("DELETE FROM sync_state WHERE key = :key") suspend fun delete(key: String)
}

data class BirthdayRow(
    val id: String,
    @ColumnInfo(name = "part_no") val partNo: Int,
    @ColumnInfo(name = "serial_no") val serialNo: Int,
    @ColumnInfo(name = "first_name_en") val firstNameEn: String?,
    @ColumnInfo(name = "middle_name_en") val middleNameEn: String?,
    @ColumnInfo(name = "last_name_en") val lastNameEn: String?,
    @ColumnInfo(name = "first_name_mr") val firstNameMr: String?,
    @ColumnInfo(name = "middle_name_mr") val middleNameMr: String?,
    @ColumnInfo(name = "last_name_mr") val lastNameMr: String?,
    val dob: String,
    @ColumnInfo(name = "mobile_1") val mobile1: String?,
)
