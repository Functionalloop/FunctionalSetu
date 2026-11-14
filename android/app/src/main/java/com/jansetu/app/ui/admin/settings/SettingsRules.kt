package com.jansetu.app.ui.admin.settings

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import java.time.LocalDate
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * The rules of Constituencies, Election & candidate and Lists & labels (9.7), kept free of Android so they are
 * tested on the JVM (AdminSettingsTest). The server checks all of them again (routers/constituencies.py,
 * settings.py, masters.py).
 */
object SettingsRules {
    private val MOBILE = Regex("^[6-9][0-9]{9}$")
    private val TAG_CODE = Regex("^[a-z_]{2,20}$")
    private val HEX = Regex("^#[0-9A-Fa-f]{6}$")

    /** The server's election types (tenant_settings CHECK), with the words shown. */
    val ELECTION_TYPES = linkedMapOf(
        "vidhan_sabha" to "Assembly (Vidhan Sabha)",
        "lok_sabha" to "Lok Sabha",
        "gram_panchayat" to "Village Panchayat",
        "zilla_parishad" to "Zilla Panchayat",
        "nagarpalika" to "Municipal Council",
        "municipal_corporation" to "Municipal Corporation",
        "nagar_panchayat" to "Nagar Panchayat",
        "panchayat_samiti" to "Panchayat Samiti",
        "other" to "Other",
    )

    /** Message texts (GET /masters/message-templates kinds), with the words shown. */
    val TEMPLATE_KINDS = linkedMapOf(
        "birthday" to "Birthday wish",
        "slip_whatsapp" to "Voter slip on WhatsApp",
        "slip_sms" to "Voter slip by SMS",
        "general" to "General message",
    )

    /** Survey fields an admin can name (CustomFieldKey). */
    val CUSTOM_FIELDS = linkedMapOf(
        "extra_check_1" to "Extra tick box 1", "extra_check_2" to "Extra tick box 2",
        "extra_info_1" to "Extra text 1", "extra_info_2" to "Extra text 2", "extra_info_3" to "Extra text 3",
        "extra_info_4" to "Extra text 4", "extra_info_5" to "Extra text 5",
    )

    // --- election settings: the server's JSON, edited key by key ---------------------------------------

    fun text(s: JsonObject, key: String): String = (s[key] as? JsonPrimitive)?.contentOrNull ?: ""
    fun flag(s: JsonObject, key: String): Boolean = (s[key] as? JsonPrimitive)?.booleanOrNull ?: false

    /**
     * The settings to PUT: the server's object with `changes` put in. Text is trimmed; empty = null (cleared).
     * Every key the screen does not show goes back as it came, because PUT replaces the whole set.
     */
    fun withChanges(s: JsonObject, changes: Map<String, Any?>): JsonObject {
        val out = LinkedHashMap<String, JsonElement>(s)
        for ((k, v) in changes) out[k] = when (v) {
            null -> JsonNull
            is Boolean -> JsonPrimitive(v)
            is Number -> JsonPrimitive(v)
            else -> v.toString().trim().ifEmpty { null }?.let(::JsonPrimitive) ?: JsonNull
        }
        return JsonObject(out)
    }

    /** "07:00:00" or "07:00" -> 7:00 am; empty when not set. */
    fun showTime(value: String): String = parseTime(value)?.format(DateTimeFormatter.ofPattern("h:mm a", Locale.ENGLISH))
        ?.lowercase(Locale.ENGLISH) ?: ""

    fun parseTime(value: String): LocalTime? = runCatching { LocalTime.parse(value) }.getOrNull()

    /** As the server takes it: "HH:mm:ss". */
    fun timeValue(hour: Int, minute: Int): String = LocalTime.of(hour, minute).toString().let { if (it.length == 5) "$it:00" else it }

    /** "2027-02-14" -> 14 Feb 2027. */
    fun showDate(value: String): String = runCatching {
        LocalDate.parse(value).format(DateTimeFormatter.ofPattern("d MMM yyyy", Locale.ENGLISH))
    }.getOrDefault("")

    /** The first problem with the Election & candidate form, or null. */
    fun checkElection(start: String, end: String, contact: String): String? {
        val a = parseTime(start)
        val b = parseTime(end)
        return when {
            (a == null) != (b == null) -> "Set both polling times, or neither."
            a != null && b != null && !b.isAfter(a) -> "Polling must end after it starts."
            contact.isNotBlank() && !MOBILE.matches(contact.trim()) -> "Contact number: 10 digits starting with 6, 7, 8 or 9."
            else -> null
        }
    }

    // --- constituencies --------------------------------------------------------------------------------

    fun checkConstituency(code: String, nameMr: String, acNo: String): String? = when {
        code.isBlank() -> "Write the code (for example AC2)."
        code.trim().length > 40 -> "Code: at most 40 characters."
        nameMr.isBlank() -> "Write the name in Marathi."
        acNo.isNotBlank() && (acNo.trim().toIntOrNull() ?: 0) < 1 -> "AC number: a whole number from 1."
        else -> null
    }

    /** PATCH body: only the changed keys (null clears). */
    fun constituencyEdits(nameMr: String, nameEn: String, acNo: String, old: com.jansetu.app.data.remote.Constituency): JsonObject {
        val out = LinkedHashMap<String, JsonElement>()
        if (nameMr.trim() != old.nameMr) out["name_mr"] = JsonPrimitive(nameMr.trim())
        val en = nameEn.trim().ifEmpty { null }
        if (en != old.nameEn) out["name_en"] = en?.let(::JsonPrimitive) ?: JsonNull
        val ac = acNo.trim().toIntOrNull()
        if (ac != old.acNo) out["ac_no"] = ac?.let(::JsonPrimitive) ?: JsonNull
        return JsonObject(out)
    }

    // --- lists -----------------------------------------------------------------------------------------

    fun checkNamed(nameMr: String): String? = if (nameMr.isBlank()) "Write the name in Marathi." else null

    fun checkColorTag(code: String, hex: String, labelMr: String, labelEn: String, isDefault: Boolean, isActive: Boolean): String? = when {
        !TAG_CODE.matches(code.trim()) -> "Code: 2 to 20 small letters or _ (for example ours)."
        !HEX.matches(hex.trim()) -> "Colour: # and 6 hex digits (for example #2E7D32)."
        labelMr.isBlank() || labelEn.isBlank() -> "Write the label in Marathi and English."
        isDefault && !isActive -> "A switched-off tag cannot be the default."
        else -> null
    }

    fun checkCustomField(labelMr: String, labelEn: String, enabled: Boolean): String? =
        if (enabled && labelMr.isBlank() && labelEn.isBlank()) "A field that is on needs a label." else null

    /** A new entry goes at the end of the list. */
    fun nextSortOrder(orders: List<Int>): Int = (orders.maxOrNull() ?: 0) + 10

    /** "#2e7d32" -> 0xFF2E7D32, or null. */
    fun argb(hex: String): Long? = hex.trim().takeIf(HEX::matches)?.substring(1)?.toLong(16)?.or(0xFF000000)

    // --- images ----------------------------------------------------------------------------------------

    /** Power-of-two step that brings the longer side to at most `max` px (BitmapFactory inSampleSize). */
    fun sampleSize(width: Int, height: Int, max: Int = 1280): Int {
        var s = 1
        while (maxOf(width, height) / (s * 2) >= max) s *= 2
        return s
    }

    const val MAX_UPLOAD = 5 * 1024 * 1024
}
