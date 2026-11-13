package com.jansetu.app.data.local

import androidx.room.ColumnInfo
import androidx.room.Embedded
import androidx.room.Entity
import androidx.room.Fts4
import androidx.room.FtsOptions
import androidx.room.PrimaryKey

/**
 * Search index, filled by the app (not a content table): one row per voter, and its rowid is the
 * voter's rowid, so a search joins on integers and never reads the index's text back.
 * The "simple" tokenizer lowercases ASCII and keeps every non-ASCII character inside a word, so
 * Devanagari words are never split at vowel signs (unicode61 may treat combining marks as breaks).
 * Prefix indexes make 2-3 letter searches fast while typing (a 1-letter index made loading 3x slower).
 */
@Fts4(tokenizer = FtsOptions.TOKENIZER_SIMPLE, prefix = [2, 3])
@Entity(tableName = "voter_fts")
data class VoterFts(
    @PrimaryKey @ColumnInfo(name = "rowid") val rowid: Long,
    val body: String,
)

/** A voter with SQLite's rowid (stable across upserts: Room's upsert updates in place). */
data class VoterWithRowid(
    @Embedded val voter: VoterEntity,
    @ColumnInfo(name = "rid") val rid: Long,
)

object VoterSearch {
    /** English name, Marathi name, relative names, EPIC, house number and survey mobiles. */
    fun body(v: VoterEntity, s: SurveyEntity?): String = listOfNotNull(
        v.firstNameEn, v.middleNameEn, v.lastNameEn,
        v.firstNameMr, v.middleNameMr, v.lastNameMr,
        v.relativeNameEn, v.relativeNameMr,
        v.epicNo, v.houseNo,
        s?.mobile1, s?.mobile2,
    ).joinToString(" ").lowercase()

    /**
     * Turns what the user typed into an FTS MATCH expression: every word must match as a prefix.
     * Characters that FTS treats as syntax are dropped. Returns null when nothing is left to match.
     */
    fun matchQuery(input: String): String? {
        val words = input.lowercase()
            .split(Regex("[\\s\\p{Punct}]+"))
            .map { w -> w.filter { it.isLetterOrDigit() || it.code >= 0x80 } }
            .filter { it.isNotEmpty() }
            .take(5)
        // One letter matches half the roll; text search starts at 2 characters.
        if (words.isEmpty() || words.sumOf { it.length } < 2) return null
        return words.joinToString(" ") { "$it*" }
    }

    /** "123" also finds serial number 123 (exact), as the server's search does. */
    fun serialNumber(input: String): Int? = input.trim().takeIf { it.length in 1..6 && it.all(Char::isDigit) }?.toInt()
}
