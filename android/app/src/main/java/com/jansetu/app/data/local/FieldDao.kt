package com.jansetu.app.data.local

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

/** One house of the walk list: the roll's house number in a booth, with its last visit. */
data class HouseRow(
    /** null = voters without a house number in the roll. */
    val house: String?,
    val voters: Int,
    /** Up to three names in roll order, for the line under the house number. */
    val names: String?,
    @ColumnInfo(name = "last_outcome") val lastOutcome: String?,
    @ColumnInfo(name = "last_visit_at") val lastVisitAt: String?,
    /** The last visit is still waiting in the outbox. */
    @ColumnInfo(name = "last_pending") val lastPending: Boolean?,
)

/** A Kutumb with its number of members on this phone. */
data class FamilyRow(
    val id: String,
    @ColumnInfo(name = "booth_id") val boothId: String,
    val label: String?,
    val pending: Boolean,
    val members: Int,
)

/** For "Add a member": the Kutumb a voter is in now. */
data class MemberOf(
    @ColumnInfo(name = "voter_id") val voterId: String,
    @ColumnInfo(name = "family_id") val familyId: String,
    val label: String?,
)

private const val ROW_COLS = """v.id, v.part_no, v.serial_no, v.epic_no, v.first_name_en, v.middle_name_en, v.last_name_en,
    v.first_name_mr, v.middle_name_mr, v.last_name_mr, v.gender, v.age, v.house_no,
    s.is_surveyed, c.hex AS color_hex, s.pending, 0 AS total"""

/** Kutumbs, their members and visits (7.4). Written by the pull and by FieldRepository. */
@Dao
abstract class FieldDao {
    // ------------------------------------------------------------ Kutumbs
    @Upsert abstract suspend fun upsertFamilies(rows: List<FamilyEntity>)
    @Upsert abstract suspend fun upsertMembers(rows: List<FamilyMemberEntity>)
    @Query("SELECT * FROM families WHERE id = :id") abstract suspend fun family(id: String): FamilyEntity?
    @Query("SELECT * FROM family_members WHERE voter_id = :voterId") abstract suspend fun member(voterId: String): FamilyMemberEntity?
    @Query("DELETE FROM family_members WHERE voter_id IN (:voterIds)") abstract suspend fun deleteMembers(voterIds: List<String>)
    @Query("DELETE FROM families WHERE id IN (:ids)") protected abstract suspend fun deleteFamilyRows(ids: List<String>)
    @Query("DELETE FROM family_members WHERE family_id IN (:ids)") protected abstract suspend fun deleteMembersOf(ids: List<String>)
    @Query("UPDATE families SET label = :label, pending = :pending, updated_at = :updatedAt WHERE id = :id")
    abstract suspend fun setLabel(id: String, label: String?, pending: Boolean, updatedAt: String?)

    @Transaction
    open suspend fun deleteFamilies(ids: List<String>) {
        ids.chunked(500).forEach { deleteMembersOf(it); deleteFamilyRows(it) }
    }

    /** The voter's Kutumb (null = none). */
    @Query("SELECT f.* FROM family_members m JOIN families f ON f.id = m.family_id WHERE m.voter_id = :voterId")
    abstract fun familyOf(voterId: String): Flow<FamilyEntity?>

    /** Members in roll order, as search rows. */
    @Query("""SELECT $ROW_COLS
                FROM family_members m JOIN voters v ON v.id = m.voter_id
                LEFT JOIN surveys s ON s.voter_id = v.id LEFT JOIN color_tags c ON c.id = s.color_tag_id
               WHERE m.family_id = :familyId ORDER BY v.part_no, v.booth_no, v.serial_no, v.id""")
    abstract fun members(familyId: String): Flow<List<VoterRow>>

    /** The booth's Kutumbs by name, for "Add to a Kutumb". */
    @Query("""SELECT f.id, f.booth_id, f.label, f.pending,
                     (SELECT count(*) FROM family_members m WHERE m.family_id = f.id) AS members
                FROM families f WHERE f.booth_id = :boothId ORDER BY lower(coalesce(f.label, '')), f.id""")
    abstract fun boothFamilies(boothId: String): Flow<List<FamilyRow>>

    @Query("""SELECT m.voter_id, m.family_id, f.label FROM family_members m JOIN families f ON f.id = m.family_id
               WHERE m.voter_id IN (:voterIds)""")
    abstract fun memberOf(voterIds: List<String>): Flow<List<MemberOf>>

    // Rows with a change waiting in the outbox: a pull must not undo them before the push.
    @Query("SELECT entity_id FROM outbox WHERE status = 'queued' AND type = 'family' AND entity_id IN (:voterIds)")
    protected abstract suspend fun queuedMemberships(voterIds: List<String>): List<String>
    @Query("SELECT id FROM families WHERE pending = 1 AND id IN (:ids)")
    protected abstract suspend fun pendingFamilies(ids: List<String>): List<String>

    /** Pulled Kutumbs; deleted ones go with their member rows. A Kutumb changed on this phone is kept. */
    @Transaction
    open suspend fun savePulledFamilies(live: List<FamilyEntity>, deletedIds: List<String>) {
        if (deletedIds.isNotEmpty()) deleteFamilies(deletedIds)
        if (live.isEmpty()) return
        val keep = live.map { it.id }.chunked(500).flatMap { pendingFamilies(it) }.toSet()
        upsertFamilies(live.filter { it.id !in keep })
    }

    /** Pulled memberships, voter to Kutumb (null = taken out). A membership changed on this phone is kept. */
    @Transaction
    open suspend fun savePulledMembers(rows: List<Pair<String, String?>>) {
        if (rows.isEmpty()) return
        val keep = rows.map { it.first }.chunked(500).flatMap { queuedMemberships(it) }.toSet()
        val fresh = rows.filter { it.first !in keep }
        fresh.filter { it.second == null }.map { it.first }.chunked(500).forEach { deleteMembers(it) }
        upsertMembers(fresh.mapNotNull { (voter, family) -> family?.let { FamilyMemberEntity(voter, it) } })
    }

    // ------------------------------------------------------------ visits
    @Upsert abstract suspend fun upsertVisits(rows: List<VisitEntity>)
    @Query("SELECT id FROM visits WHERE pending = 1 AND id IN (:ids)")
    protected abstract suspend fun pendingVisits(ids: List<String>): List<String>

    /** Pulled visits; one still waiting in the outbox stays as the phone has it. */
    @Transaction
    open suspend fun savePulledVisits(rows: List<VisitEntity>) {
        if (rows.isEmpty()) return
        val waiting = rows.map { it.id }.chunked(500).flatMap { pendingVisits(it) }.toSet()
        upsertVisits(rows.filter { it.id !in waiting })
    }

    @Query("DELETE FROM visits WHERE id = :id") abstract suspend fun deleteVisit(id: String)

    /**
     * The walk list of one booth: houses by the roll's house number (numbers in number order, then
     * the other house numbers, then voters without one), each with its voter count and last visit.
     */
    @Query("""SELECT v.house_no AS house, count(*) AS voters,
                     (SELECT group_concat(n, ', ') FROM (
                         SELECT trim(coalesce(x.first_name_en, x.first_name_mr, '') || ' ' ||
                                     coalesce(x.last_name_en, x.last_name_mr, '')) AS n
                           FROM voters x WHERE x.booth_id = :boothId AND x.house_no IS v.house_no
                          ORDER BY x.serial_no LIMIT 3)) AS names,
                     (SELECT t.outcome FROM visits t WHERE t.booth_id = :boothId AND t.house_no IS v.house_no
                       ORDER BY t.visited_at DESC LIMIT 1) AS last_outcome,
                     (SELECT t.visited_at FROM visits t WHERE t.booth_id = :boothId AND t.house_no IS v.house_no
                       ORDER BY t.visited_at DESC LIMIT 1) AS last_visit_at,
                     (SELECT t.pending FROM visits t WHERE t.booth_id = :boothId AND t.house_no IS v.house_no
                       ORDER BY t.visited_at DESC LIMIT 1) AS last_pending
                FROM voters v WHERE v.booth_id = :boothId
               GROUP BY v.house_no
               ORDER BY v.house_no IS NULL, CAST(v.house_no AS INTEGER) = 0, CAST(v.house_no AS INTEGER), v.house_no""")
    abstract fun houses(boothId: String): Flow<List<HouseRow>>

    /** The voters of one house in roll order (house null = no house number). */
    @Query("""SELECT $ROW_COLS
                FROM voters v LEFT JOIN surveys s ON s.voter_id = v.id LEFT JOIN color_tags c ON c.id = s.color_tag_id
               WHERE v.booth_id = :boothId AND v.house_no IS :house ORDER BY v.serial_no, v.id""")
    abstract fun houseVoters(boothId: String, house: String?): Flow<List<VoterRow>>

    // ------------------------------------------------------------ areas leaving the phone
    @Query("DELETE FROM families WHERE booth_id NOT IN (:keep)") protected abstract suspend fun deleteFamiliesOutside(keep: List<String>)
    @Query("DELETE FROM visits WHERE booth_id NOT IN (:keep)") protected abstract suspend fun deleteVisitsOutside(keep: List<String>)
    @Query("DELETE FROM family_members WHERE family_id NOT IN (SELECT id FROM families) OR voter_id NOT IN (SELECT id FROM voters)")
    protected abstract suspend fun deleteLooseMembers()

    /** After the area list changed: drop Kutumbs, members and visits of booths no longer on this phone. */
    @Transaction
    open suspend fun dropOutside(keepAreaIds: List<String>) {
        deleteFamiliesOutside(keepAreaIds)
        deleteVisitsOutside(keepAreaIds)
        deleteLooseMembers()
    }
}
