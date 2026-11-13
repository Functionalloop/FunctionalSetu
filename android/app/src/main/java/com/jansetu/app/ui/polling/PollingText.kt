package com.jansetu.app.ui.polling

import com.jansetu.app.data.local.MarkRow
import java.time.Instant
import java.time.ZoneId

private val IST = ZoneId.of("Asia/Kolkata")

/** One bar of the Polling day screen: voters marked in this hour (Indian time). */
data class HourCount(val hour: Int, val count: Int) {
    val label: String get() = when {
        hour == 0 -> "12 am"
        hour < 12 -> "$hour am"
        hour == 12 -> "12 pm"
        else -> "${hour - 12} pm"
    }
}

/** Marks counted by the hour they were made in, Indian time; hours with no mark are left out. */
fun byHour(markedAt: List<String>): List<HourCount> =
    markedAt.mapNotNull { runCatching { Instant.parse(it).atZone(IST).hour }.getOrNull() }
        .groupingBy { it }.eachCount()
        .toSortedMap().map { (h, n) -> HourCount(h, n) }

fun percent(voted: Int, total: Int): String = if (total == 0) "0%" else "%.0f%%".format(voted * 100.0 / total)

fun MarkRow.name(): String =
    listOf(firstNameEn, middleNameEn, lastNameEn).filterNot { it.isNullOrBlank() }.joinToString(" ").ifBlank { null }
        ?: listOf(firstNameMr, middleNameMr, lastNameMr).filterNot { it.isNullOrBlank() }.joinToString(" ").ifBlank { null }
        ?: "(no name)"

/**
 * Mark voted search: digits find serials that start with them (104 -> 104, 1040...); words find voters whose
 * English or Marathi name holds every word. Blank = the whole part.
 */
fun filterPart(rows: List<MarkRow>, query: String): List<MarkRow> {
    val q = query.trim()
    if (q.isEmpty()) return rows
    if (q.all { it.isDigit() }) return rows.filter { it.serialNo.toString().startsWith(q) }
    val words = q.lowercase().split(Regex("\\s+"))
    return rows.filter { r ->
        val names = listOfNotNull(r.firstNameEn, r.middleNameEn, r.lastNameEn, r.firstNameMr, r.middleNameMr, r.lastNameMr)
            .joinToString(" ").lowercase()
        words.all { it in names }
    }
}
