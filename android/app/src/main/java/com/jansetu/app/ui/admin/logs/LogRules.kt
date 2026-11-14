package com.jansetu.app.ui.admin.logs

import com.jansetu.app.data.remote.AuditEntry
import com.jansetu.app.data.remote.UserSummary
import com.jansetu.app.data.remote.WorkerDay
import com.jansetu.app.ui.voter.fieldLabel
import com.jansetu.app.ui.voter.valueText
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import java.time.LocalDate
import java.time.ZoneId
import java.util.Locale

/**
 * The wording and sums of Activity log, Worker activity and Worker locations (9.8), kept free of Android so
 * they are tested on the JVM (AdminLogsTest). Field labels come from Information Updation (HistoryTab.kt).
 */
object LogRules {
    val IST: ZoneId = ZoneId.of("Asia/Kolkata")

    /** The server's limit for one Worker activity / locations request (MAX_DAYS). */
    const val MAX_DAYS = 92

    fun today(): LocalDate = LocalDate.now(IST)

    /** Quick ranges: label -> (from, to), Indian dates. */
    fun presets(today: LocalDate): List<Pair<String, Pair<LocalDate, LocalDate>>> = listOf(
        "Today" to (today to today),
        "Yesterday" to (today.minusDays(1) to today.minusDays(1)),
        "7 days" to (today.minusDays(6) to today),
        "30 days" to (today.minusDays(29) to today),
    )

    fun checkRange(from: LocalDate, to: LocalDate): String? = when {
        to.isBefore(from) -> "The end date is before the start date."
        from.plusDays(MAX_DAYS.toLong()) <= to -> "At most $MAX_DAYS days at a time."
        else -> null
    }

    /** What an Activity log filter chip asks the server for (entity_type), with its words. */
    val KINDS: List<Pair<String, String?>> = listOf(
        "All" to null, "Surveys" to "voter_surveys", "Voted" to "voter_turnout", "Kutumb" to "family_members",
        "Users" to "users", "Phones" to "devices", "Areas given" to "user_area_assignments",
    )

    private val ENTITY = mapOf(
        "voter_surveys" to "Survey", "voter_turnout" to "Voted mark", "family_members" to "Kutumb member",
        "families" to "Kutumb", "voters" to "Roll entry", "new_voters" to "Eligible but Not Registered",
        "part_notes" to "Part note", "users" to "User", "devices" to "Phone", "user_area_assignments" to "Area given",
        "geo_units" to "Area", "castes" to "Caste", "professions" to "Profession", "influencer_types" to "Influencer type",
        "color_tags" to "Colour tag", "custom_field_labels" to "Survey field", "message_templates" to "Message text",
        "tenant_settings" to "Election settings", "announcements" to "Announcement", "visits" to "Visit",
        "slip_events" to "Voter slip", "terms_acceptances" to "Terms accepted",
    )

    /** Records whose entity_id is a voter's id, so the voter can be named from this phone's own data. */
    val VOTER_ENTITIES = setOf("voter_surveys", "voter_turnout", "family_members", "voters")

    /** Bookkeeping columns not worth a line. */
    private val SKIP = setOf(
        "id", "tenant_id", "created_at", "updated_at", "sync_xid", "version", "created_by", "updated_by",
        "client_mutation_id", "voter_id", "user_id", "last_seen_at", "search_text", "location_captured_at",
        "location_accuracy_m", "device_id", "marked_by_device_id", "last_device_id", "fts",
    )

    /** "Survey saved", "Phone approved", "User added", ... */
    fun title(e: AuditEntry): String {
        val what = ENTITY[e.entityType] ?: e.entityType.replace('_', ' ').replaceFirstChar { it.uppercase(Locale.ENGLISH) }
        if (e.entityType == "devices" && e.action == "update") {
            val status = e.newValues?.text("status")
            if (status != null && status != e.oldValues?.text("status")) return when (status) {
                "approved" -> "Phone approved"
                "blocked" -> "Phone blocked"
                "wiped" -> "Phone wiped"
                else -> "Phone: $status"
            }
        }
        if (e.entityType == "users" && e.action == "update") {
            val on = e.newValues?.get("is_active").bool()
            if (on != null && on != e.oldValues?.get("is_active").bool()) return if (on) "User switched on" else "User switched off"
            if (e.newValues?.text("password_changed_at") != e.oldValues?.text("password_changed_at")) return "Password set"
        }
        if (e.entityType == "voter_turnout") return if (e.newValues?.get("is_voted").bool() == false) "Voted mark undone" else "Marked voted"
        if (e.action == "update" && e.oldValues?.text("deleted_at") == null && e.newValues?.text("deleted_at") != null) return "$what removed"
        return when (e.action) {
            "insert" -> if (e.entityType == "voter_surveys") "Survey saved (first time)" else "$what added"
            "delete" -> "$what removed"
            else -> if (e.entityType == "voter_surveys") "Survey saved" else "$what changed"
        }
    }

    /** Who or what the change is about, from the row itself (a voter is named by the screen from local data). */
    fun subject(e: AuditEntry): String? {
        val v = e.newValues ?: e.oldValues ?: return null
        return when (e.entityType) {
            "users" -> listOfNotNull(v.text("full_name_en"), v.text("username")).joinToString(" · ").ifEmpty { null }
            "devices" -> v.text("model")
            "color_tags" -> v.text("label_en") ?: v.text("label_mr")
            "custom_field_labels" -> v.text("label_en") ?: v.text("label_mr") ?: v.text("field_key")
            "message_templates" -> v.text("kind")
            "tenant_settings" -> v.text("election_name_en") ?: v.text("election_name_mr")
            "announcements" -> v.text("body")?.take(60)
            else -> v.text("name_en") ?: v.text("name_mr") ?: v.text("label")
        }
    }

    /**
     * "Field: old -> new" lines: for a change the fields that differ, for an insert the fields with a value
     * (not empty, not false), for a delete the old fields with a value. `labels` names ids (users, areas, lists).
     */
    fun changeLines(e: AuditEntry, labels: Map<String, String> = emptyMap(), max: Int = 12): List<String> {
        val old = e.oldValues.orEmpty()
        val new = e.newValues.orEmpty()
        val keys = when (e.action) {
            "update" -> (new.keys + old.keys).filter { it !in SKIP && new[it].norm() != old[it].norm() }
            "insert" -> new.keys.filter { it !in SKIP && new[it].hasValue() }
            else -> old.keys.filter { it !in SKIP && old[it].hasValue() }
        }.distinct()
        var location = false
        val lines = mutableListOf<String>()
        for (k in keys) {
            if (k == "lat" || k == "lng") { location = true; continue }
            val o = show(k, old[k], labels)
            val n = show(k, new[k], labels)
            lines += when (e.action) {
                "update" -> "${fieldLabel(k)}: $o → $n"
                "insert" -> "${fieldLabel(k)}: $n"
                else -> "${fieldLabel(k)}: $o"
            }
        }
        if (location) lines += "Location saved"
        return if (lines.size > max) lines.take(max) + "and ${lines.size - max} more" else lines
    }

    private fun show(key: String, v: JsonElement?, labels: Map<String, String>): String {
        val s = (v as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull
        if (s != null && key.endsWith("_id")) return labels[s] ?: "(set)"
        return valueText(key, v, null)
    }

    // --- Worker activity -------------------------------------------------------------------------------

    data class Totals(
        val user: UserSummary?, val surveys: Int, val visits: Int, val mobiles: Int, val newVoters: Int, val voted: Int,
        val days: List<WorkerDay>,
    )

    /** One line per worker (most surveys first), and the team's total (user = null). */
    fun totals(rows: List<WorkerDay>): Pair<List<Totals>, Totals> {
        fun sum(user: UserSummary?, r: List<WorkerDay>) = Totals(
            user, r.sumOf { it.surveys }, r.sumOf { it.visits }, r.sumOf { it.mobilesCollected }, r.sumOf { it.newVoters },
            r.sumOf { it.votedMarks }, r.sortedByDescending { it.day },
        )
        val each = rows.groupBy { it.user.id }.values.map { sum(it.first().user, it) }
            .sortedWith(compareByDescending<Totals> { it.surveys + it.visits + it.voted }.thenBy { it.user?.fullNameEn?.lowercase() })
        return each to sum(null, rows)
    }

    fun countsLine(surveys: Int, visits: Int, mobiles: Int, newVoters: Int, voted: Int): String = listOf(
        "$surveys surveyed", "$visits visits", "$mobiles mobiles", "$newVoters not registered", "$voted voted",
    ).joinToString(" · ")

    // --- Worker locations ------------------------------------------------------------------------------

    /** For the phone's own map app (an Intent, no map service of ours). */
    fun geoUri(lat: Double, lng: Double, label: String): String =
        "geo:%.6f,%.6f?q=%.6f,%.6f(%s)".format(Locale.ROOT, lat, lng, lat, lng, java.net.URLEncoder.encode(label, "UTF-8"))

    fun placeLine(lat: Double, lng: Double, accuracy: Double?): String =
        "%.5f, %.5f".format(Locale.ROOT, lat, lng) + (accuracy?.let { " · ±%.0f m".format(Locale.ROOT, it) } ?: "")

    // --- JSON helpers ----------------------------------------------------------------------------------

    private fun kotlinx.serialization.json.JsonObject.text(key: String): String? =
        (this[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull?.ifBlank { null }

    private fun JsonElement?.bool(): Boolean? = (this as? JsonPrimitive)?.takeIf { it !is JsonNull }?.booleanOrNull

    private fun JsonElement?.norm(): JsonElement = this ?: JsonNull

    private fun JsonElement?.hasValue(): Boolean = when (val p = this) {
        null, is JsonNull -> false
        is JsonPrimitive -> p.contentOrNull.let { !it.isNullOrEmpty() && !(it == "false" && !p.isString) }
        else -> p.toString() !in setOf("[]", "{}")
    }
}
