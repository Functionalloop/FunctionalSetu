package com.jansetu.app.data.remote

import com.jansetu.app.data.local.VoterFilter
import com.jansetu.app.ui.reports.ReportRules
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The 11.3 screens' calls against answers shaped like docs/openapi.json (fake data only). */
class ReportsApiTest {
    private val server = MockWebServer()
    private lateinit var api: JansetuApi

    @Before fun setUp() {
        server.start()
        api = ApiFactory.create(server.url("/api/v1/").toString(), FakeTokens(access = "a"), SessionEvents())
    }

    @After fun tearDown() = server.shutdown()

    @Test fun reports() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"total":20,"surveyed":5,"percent":25.0,"by_area":[
            {"area_id":"w1","name":"Ward 1","level":"ward","total":20,"done":5,"percent":25.0,"parent_id":null},
            {"area_id":"b1","name":"Part 1","level":"booth","total":20,"done":5,"percent":25.0,"parent_id":"w1"}]}"""))
        val s = (apiCall { api.surveyProgress("w1") } as ApiResult.Ok).value
        assertEquals(5, s.surveyed)
        assertEquals("w1", s.byArea[1].parentId)
        assertNull(s.byArea[0].parentId)
        assertEquals("/api/v1/reports/survey-progress?ward_id=w1", server.takeRequest().path)

        server.enqueue(MockResponse().setBody("""{"total":20,"by_tag":[{"color_tag_id":"t1","count":4},{"color_tag_id":null,"count":16}],
            "by_area":{"w1":[{"color_tag_id":"t1","count":4},{"color_tag_id":null,"count":16}],"b1":[]}}"""))
        val t = (apiCall { api.colourTagReport() } as ApiResult.Ok).value
        assertNull(t.byTag[1].colorTagId)
        assertEquals(listOf("w1", "b1"), t.byArea.keys.toList()) // the server's order is kept
        assertEquals("/api/v1/reports/colour-tags", server.takeRequest().path)

        server.enqueue(MockResponse().setBody("""{"total":3,"male":1,"female":2,"other":0,
            "age_bands":[{"band":"18-25","male":1,"female":1,"other":0},{"band":"unknown","male":0,"female":1,"other":0}]}"""))
        val d = (apiCall { api.demographics("w1", "b1") } as ApiResult.Ok).value
        assertEquals("unknown", d.ageBands.last().band)
        assertEquals("/api/v1/reports/demographics?ward_id=w1&booth_id=b1", server.takeRequest().path)

        server.enqueue(MockResponse().setBody("""{"total":10,"voted":3,"percent":30.0,"by_area":[],
            "by_hour":[{"hour":7,"voted":1,"cumulative":1},{"hour":8,"voted":0,"cumulative":1},{"hour":9,"voted":2,"cumulative":3}]}"""))
        val tu = (apiCall { api.turnoutReport() } as ApiResult.Ok).value
        assertEquals(listOf(1, 1, 3), tu.byHour.map { it.cumulative })
        assertEquals("/api/v1/reports/turnout", server.takeRequest().path)
    }

    private val job = """{"id":"e1","kind":"voter_list","format":"pdf","status":"%s","row_count":%s,"page_count":%s,
        "error":null,"created_at":"2026-11-14T10:00:00Z","finished_at":null}"""

    @Test fun exportStartPollAndDownload() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(202).setBody(job.format("queued", "null", "null")))
        val body = ExportIn(
            kind = "voter_list", format = "pdf", language = "en",
            filter = ReportRules.apiFilter(VoterFilter(boothId = "b1", surveyed = false)),
            columns = ReportRules.ordered(setOf("name", "serial_no")),
            options = ReportRules.options(null, true, "legal", "normal", true, "", true),
        )
        val started = (apiCall { api.startExport(body) } as ApiResult.Ok).value
        assertEquals("queued", started.status)
        val req = server.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("/api/v1/exports", req.path)
        assertEquals(
            """{"kind":"voter_list","format":"pdf","language":"en","filter":{"booth_id":"b1","survey_status":"not_surveyed"},""" +
                """"columns":["serial_no","name"],"options":{"paper":"legal","group_by_house":true}}""",
            req.body.readUtf8(),
        )

        server.enqueue(MockResponse().setBody(job.format("done", "120", "4")))
        val done = (apiCall { api.exportJob("e1") } as ApiResult.Ok).value
        assertEquals("Ready · 120 rows · 4 pages", ReportRules.statusLine(done))
        assertEquals("/api/v1/exports/e1", server.takeRequest().path)

        server.enqueue(MockResponse().setBody(Buffer().write(byteArrayOf(0x25, 0x50, 0x44, 0x46)))
            .setHeader("Content-Type", "application/pdf")
            .setHeader("Content-Disposition", "attachment; filename=\"voter_list-20261114-1030.pdf\""))
        val r = api.downloadExport("e1")
        assertTrue(r.isSuccessful)
        assertEquals("voter_list-20261114-1030.pdf", ReportRules.fileName(r.headers()["Content-Disposition"], "pdf"))
        assertEquals("%PDF", r.body()!!.string())
        assertEquals("/api/v1/exports/e1/download", server.takeRequest().path)
    }

    @Test fun downloadBeforeDoneIsAPlainMessage() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(409)
            .setBody("""{"error":{"code":"export_not_ready","message":"The file is not ready yet."}}"""))
        val r = api.downloadExport("e1")
        val err = parseError(r.code(), r.errorBody()?.string())
        assertEquals("export_not_ready", err.code)
        assertEquals("The file is not ready yet.", err.message)
    }
}
