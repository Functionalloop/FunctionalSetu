package com.jansetu.app.ui.reports

import com.jansetu.app.data.local.VoterFilter
import com.jansetu.app.data.remote.AreaCount
import com.jansetu.app.data.remote.ColorTagCount
import com.jansetu.app.data.remote.ExportJob
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Reports & charts and Print or export a list (11.3): the rules without Android, tested on the JVM. */
object ReportRules {
    /** The reports of the Reports menu (route `report/{key}`); `key` is also the export's `options.report`. */
    enum class Report(val key: String, val title: String, val detail: String) {
        SURVEY("survey_progress", "Survey progress", "Surveyed voters by Village Panchayat and part"),
        TAGS("colour_tags", "Colour tags", "How many voters carry each colour tag"),
        AGE("demographics", "Age and gender", "Voters by age band, men and women"),
        TURNOUT("turnout", "Polling-day turnout", "Voted so far, by part and by hour"),
        ;

        /** The export for this report: kind turnout has its own file, the others are kind report. */
        val exportKind get() = if (this == TURNOUT) "turnout" else "report"
        val exportReport get() = if (this == TURNOUT) null else key

        companion object {
            fun of(key: String?) = entries.firstOrNull { it.key == key }
        }
    }

    // --- export kinds, columns and options (server: export_jobs.COLUMNS / DEFAULT_COLUMNS / ExportOptions) ---

    const val VOTER_LIST = "voter_list"
    const val MOBILE_LIST = "mobile_list"
    val VOTER_KINDS = setOf(VOTER_LIST, MOBILE_LIST)

    /** Column key -> label, in the order the checklist shows them. */
    val COLUMNS = linkedMapOf(
        "part_no" to "Part", "serial_no" to "Serial", "name" to "Name", "relative_name" to "Relative",
        "gender" to "Gender", "age" to "Age", "house_no" to "House No.", "epic_no" to "EPIC", "mobile" to "Mobile",
        "colour_tag" to "Colour tag", "surveyed" to "Surveyed", "caste" to "Caste", "address" to "Address",
    )

    fun defaultColumns(kind: String): List<String> = when (kind) {
        MOBILE_LIST -> listOf("part_no", "serial_no", "name", "age", "house_no", "mobile")
        else -> listOf("part_no", "serial_no", "name", "relative_name", "gender", "age", "house_no", "epic_no")
    }

    /** Ticked columns in the checklist's order (the server prints them in the order sent). */
    fun ordered(ticked: Set<String>): List<String> = COLUMNS.keys.filter { it in ticked }

    const val MAX_HEADER = 200

    /** `options` of POST /exports; only what differs from the server's defaults is sent. */
    fun options(
        report: String?, pdf: Boolean, paper: String, textSize: String, groupByHouse: Boolean, header: String, voterKind: Boolean,
    ): JsonObject = buildJsonObject {
        report?.let { put("report", it) }
        if (pdf && paper != "a4") put("paper", paper)
        if (pdf && textSize != "normal") put("text_size", textSize)
        if (voterKind && groupByHouse) put("group_by_house", true)
        header.trim().take(MAX_HEADER).takeIf { it.isNotEmpty() }?.let { put("header", it) }
    }

    /**
     * The phone's search filter as the `filter` of a voter export (= the GET /voters keys). The phone searches its
     * own copy, so a typed search can match a few voters differently from the server; the filters match exactly.
     */
    fun apiFilter(f: VoterFilter): JsonObject = buildJsonObject {
        f.q.trim().takeIf { it.isNotEmpty() }?.let { put("q", it) }
        f.wardId?.let { put("ward_id", it) }
        f.boothId?.let { put("booth_id", it) }
        f.ageMin?.let { put("age_min", it) }
        f.ageMax?.let { put("age_max", it) }
        f.gender?.let { put("gender", it) }
        f.colorTagId?.let { put("color_tag_id", it) }
        f.surveyed?.let { put("survey_status", if (it) "surveyed" else "not_surveyed") }
        if (f.influencer == true) put("influencer", true)
    }

    /** The area filter of a report export: ward_id, plus booth_id for the age and gender report only. */
    fun areaFilter(report: Report, wardId: String?, boothId: String?): JsonObject = buildJsonObject {
        wardId?.let { put("ward_id", it) }
        if (report == Report.AGE) boothId?.let { put("booth_id", it) }
    }

    /** Puts the Village Panchayat and part pickers into a voter filter (null removes the key). */
    fun withArea(filter: JsonObject, wardId: String?, boothId: String?): JsonObject = JsonObject(
        filter - "ward_id" - "booth_id" +
            listOfNotNull(wardId?.let { "ward_id" to JsonPrimitive(it) }, boothId?.let { "booth_id" to JsonPrimitive(it) }),
    )

    fun searchSummary(f: JsonObject): String {
        val n = f.keys.count { it != "q" }
        val typed = (f["q"] as? JsonPrimitive)?.content
        return listOfNotNull(
            typed?.let { "search \"$it\"" },
            when (n) { 0 -> null; 1 -> "1 filter"; else -> "$n filters" },
        ).joinToString(", ").ifEmpty { "all voters of your area" }.replaceFirstChar { it.uppercase() }
    }

    // --- the export job ---

    fun isWorking(e: ExportJob) = e.status == "queued" || e.status == "running"

    fun statusLine(e: ExportJob): String = when (e.status) {
        "queued" -> "Waiting for the server…"
        "running" -> "Making the file…"
        "done" -> listOfNotNull(
            "Ready",
            e.rowCount?.let { if (it == 1) "1 row" else "%,d rows".format(it) },
            e.pageCount?.let { if (it == 1) "1 page" else "%,d pages".format(it) },
        ).joinToString(" · ")
        else -> e.error ?: "The file could not be made."
    }

    fun mimeType(format: String) =
        if (format == "pdf") "application/pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    private val FILENAME = Regex("""filename\s*=\s*"?([^";]+)"?""", RegexOption.IGNORE_CASE)
    private val SAFE = Regex("[^A-Za-z0-9._-]")

    /** File name from Content-Disposition, kept to safe characters; else `export.<format>`. */
    fun fileName(contentDisposition: String?, format: String): String {
        val ext = if (format == "pdf") "pdf" else "xlsx"
        val name = contentDisposition?.let { FILENAME.find(it)?.groupValues?.get(1) }
            ?.substringAfterLast('/')?.substringAfterLast('\\')?.replace(SAFE, "_")?.trim('.', '_')
        return if (name.isNullOrEmpty()) "export.$ext" else if (name.endsWith(".$ext")) name else "$name.$ext"
    }

    // --- the charts ---

    /** 0..1 for a bar; 0 when there is nothing to compare with. */
    fun fraction(part: Int, whole: Int): Float = if (whole <= 0) 0f else (part.toFloat() / whole).coerceIn(0f, 1f)

    fun percent(p: Double) = if (p == Math.floor(p)) "${p.toInt()}%" else "%.1f%%".format(p)

    fun share(part: Int, whole: Int): String =
        if (whole <= 0) "0%" else percent(Math.round(part * 1000.0 / whole) / 10.0)

    fun count(n: Int) = "%,d".format(n)

    /** One row of an area chart: a part is indented under its Village Panchayat when that is listed too. */
    data class AreaLine(val area: AreaCount, val indented: Boolean)

    fun areaLines(byArea: List<AreaCount>): List<AreaLine> {
        val wards = byArea.filter { it.level == "ward" }.map { it.areaId }.toSet()
        return byArea.map { AreaLine(it, it.level == "booth" && it.parentId in wards) }
    }

    fun areaName(a: AreaCount) = if (a.level == "booth") a.name else "${a.name} (Village Panchayat)"

    /** "7 AM", "12 PM", "1 PM" for an Indian hour 0-23. */
    fun hourLabel(hour: Int): String {
        val h = ((hour % 24) + 24) % 24
        val shown = if (h % 12 == 0) 12 else h % 12
        return "$shown ${if (h < 12) "AM" else "PM"}"
    }

    /** "7–8 AM" style range for the bar of one hour. */
    fun hourRange(hour: Int) = "${hourLabel(hour).substringBefore(' ')}–${hourLabel(hour + 1)}"

    fun bandLabel(band: String) = if (band == "unknown") "Age not known" else band.replace("-", "–")

    /** Colour tags in the order of the phone's list, with "no tag" (null) last; ids the phone does not know follow. */
    fun orderTags(counts: List<ColorTagCount>, order: List<String>): List<ColorTagCount> {
        val pos = order.withIndex().associate { it.value to it.index }
        return counts.sortedWith(compareBy({ it.colorTagId == null }, { pos[it.colorTagId] ?: Int.MAX_VALUE }))
    }

    /** "#RRGGBB" -> ARGB, or null for a value the phone cannot read. */
    fun argb(hex: String?): Long? {
        val h = hex?.trim()?.removePrefix("#") ?: return null
        if (h.length != 6) return null
        return h.toLongOrNull(16)?.let { 0xFF000000 or it }
    }
}
