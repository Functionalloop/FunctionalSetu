package com.jansetu.app.data.local

import androidx.room.ColumnInfo
import androidx.sqlite.db.SimpleSQLiteQuery
import androidx.sqlite.db.SupportSQLiteQuery

/** Search text plus the filters of the Filters screen (5.8). Every field is optional. */
data class VoterFilter(
    val q: String = "",
    val wardId: String? = null,
    val boothId: String? = null,
    val ageMin: Int? = null,
    val ageMax: Int? = null,
    val gender: String? = null,
    val colorTagId: String? = null,
    /** true = surveyed, false = not surveyed, null = both. */
    val surveyed: Boolean? = null,
    /** true = important voters only (client, 12 Nov); null = everyone. */
    val important: Boolean? = null,
) {
    val activeFilterCount: Int
        get() = listOf(wardId, boothId, ageMin ?: ageMax, gender, colorTagId, surveyed, important).count { it != null }
}

/** One line of a result list. */
data class VoterRow(
    val id: String,
    @ColumnInfo(name = "part_no") val partNo: Int,
    @ColumnInfo(name = "serial_no") val serialNo: Int,
    @ColumnInfo(name = "epic_no") val epicNo: String?,
    @ColumnInfo(name = "first_name_en") val firstNameEn: String?,
    @ColumnInfo(name = "middle_name_en") val middleNameEn: String?,
    @ColumnInfo(name = "last_name_en") val lastNameEn: String?,
    @ColumnInfo(name = "first_name_mr") val firstNameMr: String?,
    @ColumnInfo(name = "middle_name_mr") val middleNameMr: String?,
    @ColumnInfo(name = "last_name_mr") val lastNameMr: String?,
    val gender: String,
    val age: Int?,
    @ColumnInfo(name = "house_no") val houseNo: String?,
    @ColumnInfo(name = "is_surveyed") val isSurveyed: Boolean?,
    @ColumnInfo(name = "color_hex") val colorHex: String?,
    val pending: Boolean?,
    /** Number of matches of the whole search (same for every row), so one query gives list and count. */
    val total: Int,
)

object VoterQuery {
    private const val FROM = """
        FROM voters v
        LEFT JOIN surveys s ON s.voter_id = v.id
    """

    fun list(f: VoterFilter, limit: Int, offset: Int = 0): SupportSQLiteQuery {
        val (where, args) = where(f)
        return SimpleSQLiteQuery(
            """
            SELECT v.id, v.part_no, v.serial_no, v.epic_no,
                   v.first_name_en, v.middle_name_en, v.last_name_en,
                   v.first_name_mr, v.middle_name_mr, v.last_name_mr,
                   v.gender, v.age, v.house_no,
                   s.is_surveyed, c.hex AS color_hex, s.pending, count(*) OVER () AS total
            $FROM
            LEFT JOIN color_tags c ON c.id = s.color_tag_id
            WHERE $where
            ORDER BY v.part_no, v.booth_no, v.serial_no, v.id
            LIMIT $limit OFFSET $offset
            """.trimIndent(),
            args.toTypedArray(),
        )
    }

    fun count(f: VoterFilter): SupportSQLiteQuery {
        val (where, args) = where(f)
        return SimpleSQLiteQuery("SELECT count(*) $FROM WHERE $where", args.toTypedArray())
    }

    private fun where(f: VoterFilter): Pair<String, List<Any>> {
        val w = mutableListOf<String>()
        val a = mutableListOf<Any>()
        val match = VoterSearch.matchQuery(f.q)
        val serial = VoterSearch.serialNumber(f.q)
        if (match == null && serial != null) {
            w += "v.serial_no = ?"; a += serial
        } else if (match != null) {
            if (serial != null) {
                w += "v.rowid IN (SELECT rowid FROM voter_fts WHERE voter_fts MATCH ? UNION SELECT rowid FROM voters WHERE serial_no = ?)"
                a += match; a += serial
            } else {
                w += "v.rowid IN (SELECT rowid FROM voter_fts WHERE voter_fts MATCH ?)"
                a += match
            }
        }
        f.wardId?.let { w += "v.ward_id = ?"; a += it }
        f.boothId?.let { w += "v.booth_id = ?"; a += it }
        f.ageMin?.let { w += "v.age >= ?"; a += it }
        f.ageMax?.let { w += "v.age <= ?"; a += it }
        f.gender?.let { w += "v.gender = ?"; a += it }
        f.colorTagId?.let { w += "s.color_tag_id = ?"; a += it }
        f.surveyed?.let { w += if (it) "coalesce(s.is_surveyed, 0) = 1" else "coalesce(s.is_surveyed, 0) = 0" }
        f.important?.let { w += if (it) "coalesce(s.is_important, 0) = 1" else "coalesce(s.is_important, 0) = 0" }
        return (if (w.isEmpty()) "1" else w.joinToString(" AND ")) to a
    }
}
