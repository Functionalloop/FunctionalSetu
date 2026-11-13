package com.jansetu.app.ui.polling

import com.jansetu.app.data.local.MarkRow
import org.junit.Assert.assertEquals
import org.junit.Test

class PollingTextTest {
    private fun row(serial: Int, first: String?, last: String?, firstMr: String? = null) =
        MarkRow("v$serial", serial, first, null, last, firstMr, null, null, isVoted = false, pending = false)

    private val part = listOf(row(1, "Ramesh", "Naik"), row(10, "Sunita", "Naik"), row(104, "Vishnu", "Gawas"),
        row(105, null, null, "रमेश"))

    @Test fun hoursAreIndianTimeAndInOrder() {
        // 03:30 UTC = 9:00 IST; 06:45 UTC = 12:15 IST; 08:10 UTC = 1:40 pm IST
        val hours = byHour(listOf("2026-11-14T06:45:00Z", "2026-11-14T03:30:00Z", "2026-11-14T03:59:00Z",
            "2026-11-14T08:10:00.123456Z", "not a date"))
        assertEquals(listOf("9 am" to 2, "12 pm" to 1, "1 pm" to 1), hours.map { it.label to it.count })
    }

    @Test fun digitsFindSerialsThatStartWithThem() {
        assertEquals(listOf(10, 104, 105), filterPart(part, "10").map { it.serialNo })
        assertEquals(listOf(104), filterPart(part, " 104 ").map { it.serialNo })
    }

    @Test fun wordsFindEveryWordInEnglishOrMarathiNames() {
        assertEquals(listOf(1, 10), filterPart(part, "naik").map { it.serialNo })
        assertEquals(listOf(1), filterPart(part, "naik ram").map { it.serialNo })
        assertEquals(listOf(105), filterPart(part, "रमेश").map { it.serialNo })
        assertEquals(part, filterPart(part, "  "))
    }

    @Test fun percentAndNames() {
        assertEquals("0%", percent(0, 0))
        assertEquals("33%", percent(1, 3))
        assertEquals("Ramesh Naik", part[0].name())
        assertEquals("रमेश", part[3].name())
    }
}
