package com.jansetu.app.ui.reports

import com.jansetu.app.data.local.VoterFilter
import com.jansetu.app.data.remote.AreaCount
import com.jansetu.app.data.remote.ColorTagCount
import com.jansetu.app.data.remote.ExportJob
import com.jansetu.app.ui.reports.ReportRules.Report
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ReportRulesTest {
    @Test fun searchFilterUsesTheVoterListKeys() {
        val f = VoterFilter(q = "  naik ", wardId = "w1", boothId = "b1", ageMin = 18, ageMax = 30, gender = "F",
            colorTagId = "t1", surveyed = false, influencer = true)
        assertEquals(
            """{"q":"naik","ward_id":"w1","booth_id":"b1","age_min":18,"age_max":30,"gender":"F","color_tag_id":"t1",""" +
                """"survey_status":"not_surveyed","influencer":true}""",
            ReportRules.apiFilter(f).toString(),
        )
        assertEquals("{}", ReportRules.apiFilter(VoterFilter()).toString())
        assertEquals("""{"survey_status":"surveyed"}""", ReportRules.apiFilter(VoterFilter(surveyed = true)).toString())
        // influencer false is "everyone" on the phone: never sent as a filter
        assertEquals("{}", ReportRules.apiFilter(VoterFilter(influencer = false)).toString())
    }

    @Test fun searchSummary() {
        assertEquals("All voters of your area", ReportRules.searchSummary(JsonObject(emptyMap())))
        assertEquals("Search \"naik\", 2 filters",
            ReportRules.searchSummary(ReportRules.apiFilter(VoterFilter(q = "naik", wardId = "w", gender = "M"))))
        assertEquals("1 filter", ReportRules.searchSummary(ReportRules.apiFilter(VoterFilter(boothId = "b"))))
    }

    @Test fun areaPickersReplaceTheAreaKeys() {
        val base = ReportRules.apiFilter(VoterFilter(gender = "M", boothId = "old"))
        assertEquals("""{"gender":"M","ward_id":"w","booth_id":"b"}""", ReportRules.withArea(base, "w", "b").toString())
        assertEquals("""{"gender":"M"}""", ReportRules.withArea(base, null, null).toString())
    }

    @Test fun reportExportsSendBoothOnlyForAgeAndGender() {
        assertEquals("""{"ward_id":"w","booth_id":"b"}""", ReportRules.areaFilter(Report.AGE, "w", "b").toString())
        assertEquals("""{"ward_id":"w"}""", ReportRules.areaFilter(Report.SURVEY, "w", "b").toString())
        assertEquals("{}", ReportRules.areaFilter(Report.TURNOUT, null, null).toString())
        assertEquals("turnout", Report.TURNOUT.exportKind)
        assertNull(Report.TURNOUT.exportReport)
        assertEquals("report", Report.TAGS.exportKind)
        assertEquals("colour_tags", Report.TAGS.exportReport)
        assertEquals(Report.AGE, Report.of("demographics"))
        assertNull(Report.of("nope"))
    }

    @Test fun optionsSendOnlyWhatDiffersFromTheServerDefaults() {
        assertEquals("{}", ReportRules.options(null, true, "a4", "normal", false, " ", true).toString())
        assertEquals("""{"report":"demographics","paper":"legal","text_size":"large","header":"Ward meeting"}""",
            ReportRules.options("demographics", true, "legal", "large", true, " Ward meeting ", false).toString())
        // Excel has no paper or text size; group by house is for voter lists only
        assertEquals("""{"group_by_house":true}""", ReportRules.options(null, false, "legal", "small", true, "", true).toString())
        assertEquals(ReportRules.MAX_HEADER,
            (ReportRules.options(null, false, "a4", "normal", false, "x".repeat(300), true)["header"].toString().length - 2))
    }

    @Test fun columns() {
        assertEquals(listOf("part_no", "serial_no", "name", "age", "house_no", "mobile"), ReportRules.defaultColumns("mobile_list"))
        assertEquals(8, ReportRules.defaultColumns("voter_list").size)
        assertTrue(ReportRules.COLUMNS.keys.containsAll(ReportRules.defaultColumns("voter_list")))
        assertEquals(listOf("serial_no", "name", "mobile"), ReportRules.ordered(setOf("mobile", "name", "serial_no")))
    }

    private fun job(status: String, rows: Int? = null, pages: Int? = null, error: String? = null) =
        ExportJob("e1", "voter_list", "pdf", status, rows, pages, error, "2026-11-14T10:00:00Z")

    @Test fun statusLines() {
        assertEquals("Waiting for the server…", ReportRules.statusLine(job("queued")))
        assertEquals("Making the file…", ReportRules.statusLine(job("running")))
        assertEquals("Ready · 1,234 rows · 31 pages", ReportRules.statusLine(job("done", 1234, 31)))
        assertEquals("Ready · 1 row", ReportRules.statusLine(job("done", 1)))
        assertEquals("Too many voters", ReportRules.statusLine(job("failed", error = "Too many voters")))
        assertTrue(ReportRules.isWorking(job("queued")) && ReportRules.isWorking(job("running")))
        assertFalse(ReportRules.isWorking(job("done")) || ReportRules.isWorking(job("failed")))
    }

    @Test fun fileNames() {
        assertEquals("voter_list-20261114-1030.pdf",
            ReportRules.fileName("attachment; filename=\"voter_list-20261114-1030.pdf\"", "pdf"))
        assertEquals("report.xlsx", ReportRules.fileName("attachment; filename=report", "xlsx"))
        assertEquals("export.pdf", ReportRules.fileName(null, "pdf"))
        // a name with folders or odd characters stays inside the exports folder
        assertEquals("evil.pdf", ReportRules.fileName("attachment; filename=\"../../evil.pdf\"", "pdf"))
        assertEquals("a_b.xlsx", ReportRules.fileName("attachment; filename=\"a b.xlsx\"", "xlsx"))
        assertEquals("application/pdf", ReportRules.mimeType("pdf"))
    }

    @Test fun numbersAndLabels() {
        assertEquals(0.5f, ReportRules.fraction(5, 10))
        assertEquals(0f, ReportRules.fraction(5, 0))
        assertEquals(1f, ReportRules.fraction(12, 10))
        assertEquals("61.7%", ReportRules.percent(61.7))
        assertEquals("100%", ReportRules.percent(100.0))
        assertEquals("33.3%", ReportRules.share(1, 3))
        assertEquals("0%", ReportRules.share(1, 0))
        assertEquals("12 AM", ReportRules.hourLabel(0))
        assertEquals("7 AM", ReportRules.hourLabel(7))
        assertEquals("12 PM", ReportRules.hourLabel(12))
        assertEquals("5 PM", ReportRules.hourLabel(17))
        assertEquals("7–8 AM", ReportRules.hourRange(7))
        assertEquals("11–12 PM", ReportRules.hourRange(11))
        assertEquals("18–25", ReportRules.bandLabel("18-25"))
        assertEquals("Age not known", ReportRules.bandLabel("unknown"))
        assertEquals(0xFF2A78D6, ReportRules.argb("#2a78d6"))
        assertNull(ReportRules.argb("blue"))
        assertNull(ReportRules.argb(null))
    }

    @Test fun partsAreIndentedOnlyUnderAListedVillagePanchayat() {
        fun a(id: String, level: String, parent: String? = null) = AreaCount(id, id, level, 10, 5, 50.0, parent)
        val lines = ReportRules.areaLines(listOf(a("w1", "ward"), a("b1", "booth", "w1"), a("b9", "booth", "w9")))
        assertEquals(listOf(false, true, false), lines.map { it.indented })
        assertEquals("w1 (Village Panchayat)", ReportRules.areaName(lines[0].area))
        assertEquals("b1", ReportRules.areaName(lines[1].area))
    }

    @Test fun tagsFollowThePhonesOrderWithNoTagLast() {
        val counts = listOf(ColorTagCount(null, 9), ColorTagCount("unknown", 1), ColorTagCount("red", 3), ColorTagCount("green", 2))
        assertEquals(listOf("green", "red", "unknown", null),
            ReportRules.orderTags(counts, listOf("green", "red")).map { it.colorTagId })
    }
}
