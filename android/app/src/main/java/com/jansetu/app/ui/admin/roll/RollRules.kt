package com.jansetu.app.ui.admin.roll

import com.jansetu.app.data.local.VoterEntity
import com.jansetu.app.data.remote.RollImport
import com.jansetu.app.data.remote.RollImportRow
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/** Matching Engine and Correct roll record (10.6): wording and checks. Pure: JVM-tested. */
object RollRules {
    // --- reasons (server enum RollEditReason) ---
    val EDIT_REASONS = listOf(
        "typing_mistake" to "Typing mistake in the roll",
        "supplementary_list" to "Supplementary list",
        "booth_changed" to "Part / booth changed",
        "shifted" to "Shifted",
        "other" to "Other",
    )
    val REMOVE_REASONS = listOf(
        "duplicate" to "Listed twice",
        "dead" to "Dead (confirmed)",
        "shifted" to "Shifted away",
        "deleted_in_new_roll" to "Deleted in the new roll",
        "other" to "Other",
    )
    val RESTORE_REASONS = listOf("typing_mistake" to "Removed by mistake", "supplementary_list" to "Back in a supplementary list",
        "other" to "Other")

    fun reasonLabel(code: String): String =
        (EDIT_REASONS + REMOVE_REASONS + RESTORE_REASONS).firstOrNull { it.first == code }?.second ?: code.replace('_', ' ')

    val LIST_TYPES = listOf("main" to "Main roll", "supplementary" to "Supplementary list", "draft" to "Draft roll")
    fun listTypeLabel(code: String) = LIST_TYPES.firstOrNull { it.first == code }?.second ?: code

    // --- Correct roll record ---

    /** The roll fields the phone lets a super admin correct (English only: the roll has no Marathi names). */
    data class RollForm(
        val firstName: String = "",
        val middleName: String = "",
        val lastName: String = "",
        val relationType: String? = null,
        val relativeName: String = "",
        val gender: String = "M",
        val age: String = "",
        val houseNo: String = "",
        val epicNo: String = "",
        val serialNo: String = "",
    )

    fun formOf(v: VoterEntity) = RollForm(
        firstName = v.firstNameEn.orEmpty(), middleName = v.middleNameEn.orEmpty(), lastName = v.lastNameEn.orEmpty(),
        relationType = v.relationType, relativeName = v.relativeNameEn.orEmpty(), gender = v.gender,
        age = v.age?.toString().orEmpty(), houseNo = v.houseNo.orEmpty(), epicNo = v.epicNo.orEmpty(),
        serialNo = v.serialNo.toString(),
    )

    private val EPIC = Regex("^[A-Z0-9/]{6,20}$")

    sealed interface Check {
        data class Ok(val fields: JsonObject) : Check
        data class Problem(val message: String) : Check
    }

    /** The changed keys for PATCH /voters/{id}/roll (empty text = null, which clears it), or what is wrong. */
    fun changes(old: RollForm, new: RollForm, hasMarathiName: Boolean): Check {
        val n = new.copy(
            firstName = new.firstName.trim(), middleName = new.middleName.trim(), lastName = new.lastName.trim(),
            relativeName = new.relativeName.trim(), age = new.age.trim(), houseNo = new.houseNo.trim(),
            epicNo = new.epicNo.trim().uppercase(), serialNo = new.serialNo.trim(),
        )
        if (n.firstName.isEmpty() && n.lastName.isEmpty() && !hasMarathiName) return Check.Problem("Give the voter a name.")
        val serial = n.serialNo.toIntOrNull()
        if (serial == null || serial <= 0) return Check.Problem("The serial number must be a whole number above 0.")
        val age = if (n.age.isEmpty()) null else n.age.toIntOrNull()
        if (n.age.isNotEmpty() && (age == null || age !in 18..125)) return Check.Problem("Age must be from 18 to 125, or empty.")
        if (n.epicNo.isNotEmpty() && !EPIC.matches(n.epicNo)) return Check.Problem("EPIC: 6 to 20 capital letters, digits or /.")
        if (n.gender !in setOf("M", "F", "O")) return Check.Problem("Choose the gender.")

        fun text(s: String) = if (s.isEmpty()) JsonNull else JsonPrimitive(s)
        val fields = buildJsonObject {
            if (n.firstName != old.firstName) put("first_name_en", text(n.firstName))
            if (n.middleName != old.middleName) put("middle_name_en", text(n.middleName))
            if (n.lastName != old.lastName) put("last_name_en", text(n.lastName))
            if (n.relationType != old.relationType) put("relation_type", n.relationType?.let { JsonPrimitive(it) } ?: JsonNull)
            if (n.relativeName != old.relativeName) put("relative_name_en", text(n.relativeName))
            if (n.gender != old.gender) put("gender", JsonPrimitive(n.gender))
            if (n.age != old.age) put("age", age?.let { JsonPrimitive(it) } ?: JsonNull)
            if (n.houseNo != old.houseNo) put("house_no", text(n.houseNo))
            if (n.epicNo != old.epicNo) put("epic_no", text(n.epicNo))
            if (n.serialNo != old.serialNo) put("serial_no", JsonPrimitive(serial))
        }
        return if (fields.isEmpty()) Check.Problem("Nothing has changed.") else Check.Ok(fields)
    }

    fun reference(s: String): String? = s.trim().take(200).ifEmpty { null }

    // --- Matching Engine ---

    fun isWorking(r: RollImport) = r.status == "uploaded" || r.status == "parsing"
    fun isOpen(r: RollImport) = r.status in setOf("uploaded", "parsing", "review")
    fun toReview(r: RollImport) = r.counts["to_review"] ?: 0
    fun canApply(r: RollImport) = r.status == "review" && toReview(r) == 0

    fun statusLine(r: RollImport): String = when (r.status) {
        "uploaded" -> "Waiting to start…"
        "parsing" -> "Reading and comparing the roll…"
        "review" -> if (toReview(r) > 0) "Compared · ${toReview(r)} need a decision" else "Compared · ready to apply"
        "applied" -> "Applied"
        "failed" -> "Failed: ${r.error ?: "the file could not be read."}"
        "discarded" -> "Discarded"
        else -> r.status
    }

    /** Count lines for the import page: the comparison, then (after apply) what apply did. */
    fun countLines(r: RollImport): List<Pair<String, Int>> {
        val c = r.counts
        val compare = listOf(
            "rows" to "Rows in the file", "matched" to "Matched", "uncertain" to "Not sure", "possible_duplicate" to "Listed twice",
            "new" to "New voters", "absent_from_current_roll" to "Not in this file", "unreadable" to "Could not be read",
            "reviewed" to "Decided by hand",
        )
        val applied = listOf(
            "updated" to "Voters updated", "unchanged" to "Unchanged", "added" to "Voters added", "marked_absent" to "Marked not in current roll",
            "deleted_in_roll" to "Deleted in the roll", "skipped" to "Rows skipped", "new_pairs" to "New possible duplicates",
        )
        return (compare + if (r.status == "applied") applied else emptyList()).mapNotNull { (k, label) -> c[k]?.let { label to it } }
    }

    fun matchLabel(status: String?): String = when (status) {
        "matched" -> "Matched"
        "uncertain" -> "Not sure"
        "possible_duplicate" -> "Listed twice in the file"
        "new" -> "New voter"
        "absent_from_current_roll" -> "Not in this file"
        null -> "Could not be read"
        else -> status
    }

    fun rowName(r: RollImportRow): String =
        listOfNotNull(r.firstNameEn, r.lastNameEn).joinToString(" ").ifBlank { listOfNotNull(r.firstNameMr, r.lastNameMr).joinToString(" ") }
            .ifBlank { "(no name)" }

    fun rowLine(r: RollImportRow): String = listOfNotNull(
        "Row ${r.rowNo}",
        r.partNo?.let { "Part $it" },
        r.serialNo?.let { "Serial $it" },
        r.age?.toString(),
        r.gender?.let { when (it) { "M" -> "Male"; "F" -> "Female"; else -> "Other" } },
        r.houseNo?.let { "House $it" },
        r.epicNo?.let { "EPIC $it" },
    ).joinToString(" · ")

    /** Buttons for a row waiting for a decision: accept label (null = none) and reject label (null = none). */
    data class Actions(val accept: String?, val reject: String?)

    fun actions(r: RollImportRow): Actions = when {
        r.reviewStatus != "pending" -> Actions(null, null)
        r.matchStatus == null -> Actions(null, "Skip this row")
        r.matchStatus == "absent_from_current_roll" || r.matchStatus == "new" -> Actions(null, null)
        r.matchedVoterId == null -> Actions(null, "Add as a new voter")
        r.matchStatus == "possible_duplicate" -> Actions("Same voter, skip the row", "A different person: add")
        else -> Actions("Same voter", "Add as a new voter")
    }

    fun reviewLabel(r: RollImportRow): String? = when (r.reviewStatus) {
        "accepted" -> if (r.matchStatus == "possible_duplicate") "Decided: skip" else "Decided: same voter"
        "rejected" -> if (r.matchStatus == null) "Decided: skip" else "Decided: add as new"
        else -> null
    }

    fun mimeFor(name: String): String =
        if (name.lowercase().endsWith(".xlsx")) "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" else "text/csv"
}
