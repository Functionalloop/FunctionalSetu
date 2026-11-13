package com.jansetu.app.ui.polling

import com.jansetu.app.data.local.MarkRow

/** At most this many serials at a time, as on the server (MAX_MARKS). */
const val MAX_BULK = 2000

/**
 * What "Mark many voted" would do with typed serials: [toMark] (voters of the part not voted yet, by serial),
 * [already] (voted already, left as they are), [missing] (serials with no voter of the part on the current roll).
 * [error] = the text cannot be read; nothing is marked then.
 */
data class BulkPlan(
    val toMark: List<MarkRow> = emptyList(),
    val already: Int = 0,
    val missing: List<Int> = emptyList(),
    val error: String? = null,
)

/**
 * "12, 15, 18-25" -> [12, 15, 18, ..., 25]: sorted, each once. Commas or spaces between parts; "18 - 25" is a
 * range too. The same rules as the server's parse_serials, so a typed list means the same on both sides.
 */
fun parseSerials(text: String): Result<List<Int>> {
    val joined = text.trim().replace(Regex("\\s*-\\s*"), "-")
    val parts = joined.split(Regex("[,\\s]+")).filter { it.isNotEmpty() }
    if (parts.isEmpty()) return Result.failure(IllegalArgumentException("Type serial numbers, e.g. 12, 15, 18-25"))
    val out = sortedSetOf<Int>()
    for (part in parts) {
        val m = Regex("^(\\d{1,5})(?:-(\\d{1,5}))?$").matchEntire(part)
            ?: return Result.failure(IllegalArgumentException("\"$part\" is not a serial number or a range like 18-25"))
        val lo = m.groupValues[1].toInt()
        val hi = m.groupValues[2].ifEmpty { null }?.toInt() ?: lo
        if (lo < 1 || hi < lo) return Result.failure(IllegalArgumentException("\"$part\": serials start at 1 and a range goes from low to high"))
        if (hi - lo + 1 + out.size > MAX_BULK) return Result.failure(IllegalArgumentException("At most $MAX_BULK serials at a time"))
        out.addAll(lo..hi)
    }
    return Result.success(out.toList())
}

fun planBulk(text: String, part: List<MarkRow>): BulkPlan {
    if (text.isBlank()) return BulkPlan()
    val serials = parseSerials(text).getOrElse { return BulkPlan(error = it.message) }
    val bySerial = part.associateBy { it.serialNo }
    val found = serials.mapNotNull { bySerial[it] }
    return BulkPlan(
        toMark = found.filterNot { it.isVoted },
        already = found.count { it.isVoted },
        missing = serials.filter { it !in bySerial },
    )
}

/** "99, 100-103": missing serials written back as short ranges. */
fun serialsText(serials: List<Int>): String {
    if (serials.isEmpty()) return ""
    val out = mutableListOf<String>()
    var start = serials[0]
    var prev = start
    for (s in serials.drop(1) + Int.MIN_VALUE) {
        if (s == prev + 1) { prev = s; continue }
        out += if (start == prev) "$start" else "$start-$prev"
        start = s; prev = s
    }
    return out.joinToString(", ")
}
