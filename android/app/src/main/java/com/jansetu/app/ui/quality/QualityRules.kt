package com.jansetu.app.ui.quality

import com.jansetu.app.data.remote.DataQualitySummary
import com.jansetu.app.data.remote.MobileImport
import com.jansetu.app.data.remote.SyncVoter
import com.jansetu.app.ui.common.genderLabel

/** Wording and checks of the Data quality, Repeated voters and Mobile numbers screens (10.6). Pure: JVM-tested. */
object QualityRules {
    /** One line of the Data quality summary; `source` set = it opens the pair list ("" = every source). */
    data class Line(val label: String, val count: Int, val source: String? = null)

    const val ROLL_FLAG = "roll_flag"

    fun lines(s: DataQualitySummary): List<Line> = listOf(
        Line("Missing mobile numbers", s.noMobile),
        Line("Missing birth dates", s.noDob),
        Line("Possible duplicates", s.possibleDuplicates, source = ""),
        Line("Repeated in the roll", s.repeatedInRoll, source = ROLL_FLAG),
        Line("Shifted address", s.shifted),
        Line("Doubtful “dead” marks", s.doubtfulDead),
    )

    /** "12% of 872" style note under a count, or null when there are no voters. */
    fun share(count: Int, of: Int): String? = if (of <= 0) null else "${count * 100 / of}% of ${"%,d".format(of)} voters"

    fun pairTitle(source: String?): String = if (source == ROLL_FLAG) "Repeated in the roll" else "Possible duplicates"

    fun sourceLabel(source: String): String = when (source) {
        ROLL_FLAG -> "Marked repeated in the roll"
        "fuzzy_match" -> "Same name, relative and gender; age close"
        "roll_update" -> "Found by the Matching Engine"
        else -> source
    }

    fun statusLabel(status: String): String = when (status) {
        "unchecked" -> "Not checked yet"
        "same_person" -> "Same person"
        "different_people" -> "Different people"
        else -> status
    }

    private fun join(vararg parts: String?) = parts.filterNot { it.isNullOrBlank() }.joinToString(" ")

    fun name(v: SyncVoter): String =
        join(v.firstNameEn, v.middleNameEn, v.lastNameEn).ifBlank { join(v.firstNameMr, v.middleNameMr, v.lastNameMr) }.ifBlank { "(no name)" }

    /** "Part 12 · Serial 340 · 46 · Female · House 88 · EPIC ABC1234567" (what tells two records apart). */
    fun voterLine(v: SyncVoter): String = listOfNotNull(
        "Part ${v.partNo} · Serial ${v.serialNo}",
        v.age?.toString(),
        genderLabel(v.gender),
        v.houseNo?.let { "House $it" },
        v.epicNo?.let { "EPIC $it" },
    ).joinToString(" · ")

    fun relativeLine(v: SyncVoter): String? = (v.relativeNameEn ?: v.relativeNameMr)?.let { r ->
        when (v.relationType) {
            "father" -> "Father: $r"; "mother" -> "Mother: $r"; "husband" -> "Husband: $r"; "wife" -> "Wife: $r"
            else -> "Relative: $r"
        }
    }

    // --- mobile number sheets ------------------------------------------------------------------------

    const val MAX_SHEET_BYTES = 20 * 1024 * 1024

    fun isWorking(m: MobileImport) = m.status == "queued" || m.status == "running"

    fun sheetLine(m: MobileImport): String = when (m.status) {
        "queued" -> "Waiting to start…"
        "running" -> "Matching the numbers…"
        "failed" -> "Failed: ${m.error ?: "the sheet could not be read."}"
        else -> "${m.matchedCount} matched · ${m.reviewCount} to review · ${m.notFoundCount} not found"
    }

    fun rowLabel(status: String): String = when (status) {
        "matched" -> "Number saved"
        "needs_review" -> "Needs review"
        "not_found" -> "No voter found"
        "skipped" -> "Skipped"
        else -> status
    }

    fun rowOpen(status: String) = status == "needs_review" || status == "not_found"

    /** Message when the picked file cannot be a sheet (the server checks the content again). */
    fun sheetProblem(name: String?, size: Long?): String? {
        val n = name?.lowercase().orEmpty()
        return when {
            !(n.endsWith(".csv") || n.endsWith(".xlsx")) -> "Choose a CSV or Excel (.xlsx) file."
            size != null && size > MAX_SHEET_BYTES -> "The file is larger than 20 MB."
            size == 0L -> "The file is empty."
            else -> null
        }
    }

    fun mimeFor(name: String): String =
        if (name.lowercase().endsWith(".xlsx")) "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" else "text/csv"
}
