package com.jansetu.app.ui.admin.logs

import com.jansetu.app.data.remote.ApiFactory
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.AuditEntry
import com.jansetu.app.data.remote.FakeTokens
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.SessionEvents
import com.jansetu.app.data.remote.UserSummary
import com.jansetu.app.data.remote.WorkerDay
import com.jansetu.app.data.remote.apiCall
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.LocalDate

/** Activity log, Worker activity, Worker locations (9.8): wording, sums and calls, fake data only. */
class AdminLogsTest {
    private fun obj(s: String): JsonObject = Json.parseToJsonElement(s).jsonObject

    private fun entry(type: String, action: String, old: String? = null, new: String? = null, id: String? = "x") =
        AuditEntry(1, "2026-11-14T05:00:00Z", null, null, action, type, id, old?.let(::obj), new?.let(::obj))

    // --- wording -------------------------------------------------------------------------------------

    @Test fun titles() {
        assertEquals("Survey saved (first time)", LogRules.title(entry("voter_surveys", "insert", new = "{}")))
        assertEquals("Survey saved", LogRules.title(entry("voter_surveys", "update", "{}", "{}")))
        assertEquals("Phone approved", LogRules.title(entry("devices", "update", """{"status":"pending"}""", """{"status":"approved"}""")))
        assertEquals("Phone blocked", LogRules.title(entry("devices", "update", """{"status":"approved"}""", """{"status":"blocked"}""")))
        assertEquals("Phone changed", LogRules.title(entry("devices", "update", """{"status":"approved","model":"a"}""", """{"status":"approved","model":"b"}""")))
        assertEquals("User switched off", LogRules.title(entry("users", "update", """{"is_active":true}""", """{"is_active":false}""")))
        assertEquals("User added", LogRules.title(entry("users", "insert", new = """{"full_name_en":"Demo"}""")))
        assertEquals("Marked voted", LogRules.title(entry("voter_turnout", "insert", new = """{"is_voted":true}""")))
        assertEquals("Voted mark undone", LogRules.title(entry("voter_turnout", "update", """{"is_voted":true}""", """{"is_voted":false}""")))
        assertEquals("Kutumb removed", LogRules.title(entry("families", "update", """{"deleted_at":null}""", """{"deleted_at":"2026-11-14T05:00:00Z"}""")))
        assertEquals("Some table changed", LogRules.title(entry("some_table", "update", "{}", "{}")))
    }

    @Test fun subjects() {
        assertEquals("Demo Admin · demo.admin",
            LogRules.subject(entry("users", "insert", new = """{"full_name_en":"Demo Admin","username":"demo.admin"}""")))
        assertEquals("vivo I2207", LogRules.subject(entry("devices", "update", "{}", """{"model":"vivo I2207"}""")))
        assertEquals("Sarpanch", LogRules.subject(entry("influencer_types", "insert", new = """{"name_mr":"सरपंच","name_en":"Sarpanch"}""")))
        assertNull(LogRules.subject(entry("voter_surveys", "update", "{}", """{"mobile_1":"9123456789"}""")))
    }

    @Test fun changeLinesShowWhatChanged() {
        val e = entry("voter_surveys", "update",
            """{"mobile_1":null,"color_tag_id":"t1","version":1,"updated_at":"a","lat":null,"is_influencer":false,"notes":"x"}""",
            """{"mobile_1":"9123456789","color_tag_id":"t2","version":2,"updated_at":"b","lat":15.7,"is_influencer":true,"notes":"x"}""")
        val lines = LogRules.changeLines(e, mapOf("t1" to "Ours", "t2" to "Doubtful"))
        assertEquals(listOf("Mobile: — → 9123456789", "Colour tag: Ours → Doubtful", "Influencer: No → Yes", "Location saved"), lines)
        // an insert lists fields with a value; ids nobody can name show as "(set)"; bookkeeping is left out
        val ins = LogRules.changeLines(entry("voter_surveys", "insert",
            new = """{"id":"x","tenant_id":"t","mobile_1":"9123456789","notes":"","is_influencer":false,"caste_id":"c9"}"""))
        assertEquals(listOf("Mobile: 9123456789", "Caste: (set)"), ins)
        // the server never sends password hashes, and long lists are cut
        val many = LogRules.changeLines(entry("x", "insert", new = (1..20).joinToString(",", "{", "}") { "\"f$it\":\"v\"" }), max = 5)
        assertEquals(6, many.size)
        assertEquals("and 15 more", many.last())
    }

    // --- ranges and sums -----------------------------------------------------------------------------

    @Test fun ranges() {
        val today = LocalDate.of(2026, 11, 14)
        val p = LogRules.presets(today).toMap()
        assertEquals(today to today, p["Today"])
        assertEquals(LocalDate.of(2026, 11, 8) to today, p["7 days"])
        assertNull(LogRules.checkRange(today.minusDays(91), today))
        assertEquals("At most 92 days at a time.", LogRules.checkRange(today.minusDays(92), today))
        assertTrue(LogRules.checkRange(today, today.minusDays(1))!!.startsWith("The end date"))
    }

    @Test fun workerTotals() {
        val a = UserSummary("a", "u.a", "Anil", null, "surveyor")
        val b = UserSummary("b", "u.b", "Bina", null, "booth_agent")
        val rows = listOf(
            WorkerDay(a, "2026-11-13", surveys = 5, visits = 2, mobilesCollected = 3),
            WorkerDay(a, "2026-11-14", surveys = 1),
            WorkerDay(b, "2026-11-14", votedMarks = 40),
        )
        val (each, all) = LogRules.totals(rows)
        assertEquals(listOf("b", "a"), each.map { it.user!!.id }) // 40 voted marks before 8 surveys and visits
        assertEquals(6, each[1].surveys)
        assertEquals(listOf("2026-11-14", "2026-11-13"), each[1].days.map { it.day }) // newest day first
        assertEquals(listOf(6, 2, 3, 0, 40), listOf(all.surveys, all.visits, all.mobiles, all.newVoters, all.voted))
        assertEquals("6 surveyed · 2 visits · 3 mobiles · 0 not registered · 40 voted",
            LogRules.countsLine(all.surveys, all.visits, all.mobiles, all.newVoters, all.voted))
    }

    @Test fun mapLinks() {
        assertEquals("geo:15.700000,73.800000?q=15.700000,73.800000(Demo+Surveyor)", LogRules.geoUri(15.7, 73.8, "Demo Surveyor"))
        assertEquals("15.70000, 73.80000 · ±12 m", LogRules.placeLine(15.7, 73.8, 12.4))
        assertFalse(LogRules.placeLine(15.7, 73.8, null).contains("±"))
    }

    // --- calls ---------------------------------------------------------------------------------------

    private val server = MockWebServer()
    private lateinit var api: JansetuApi

    @Before fun setUp() {
        server.start()
        api = ApiFactory.create(server.url("/api/v1/").toString(), FakeTokens(access = "admin-access"), SessionEvents())
    }

    @After fun tearDown() = server.shutdown()

    @Test fun calls() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"items":[{"id":7,"occurred_at":"2026-11-14T05:00:00Z","actor":null,
            "device_id":null,"action":"update","entity_type":"devices","entity_id":"d1","old_values":{"status":"pending"},
            "new_values":{"status":"approved"}}],"next_cursor":"c1"}"""))
        server.enqueue(MockResponse().setBody("""{"date_from":"2026-11-08","date_to":"2026-11-14","rows":[{"user":
            {"id":"a","username":"u.a","full_name_en":"Anil","full_name_mr":null,"role":"surveyor"},"day":"2026-11-14",
            "surveys":2,"visits":1,"mobiles_collected":1,"new_voters":0,"voted_marks":0}]}"""))
        server.enqueue(MockResponse().setBody("""{"items":[{"user":{"id":"a","username":"u.a","full_name_en":"Anil",
            "full_name_mr":null,"role":"surveyor"},"kind":"survey","voter_id":"v1","lat":15.7,"lng":73.8,"accuracy_m":null,
            "at":"2026-11-14T05:00:00Z"}],"next_cursor":null}"""))

        val log = (apiCall { api.auditLog("devices", null, "2026-11-08", "2026-11-14", null, 50) } as ApiResult.Ok).value
        assertEquals("Phone approved", LogRules.title(log.items.single()))
        assertEquals("c1", log.nextCursor)
        val act = (apiCall { api.workerActivity("2026-11-08", "2026-11-14", "a") } as ApiResult.Ok).value
        assertEquals(2, act.rows.single().surveys)
        val loc = (apiCall { api.workerLocations("2026-11-14", "2026-11-14") } as ApiResult.Ok).value
        assertEquals(15.7, loc.items.single().lat, 0.0)

        assertEquals("/api/v1/audit-log?entity_type=devices&date_from=2026-11-08&date_to=2026-11-14&limit=50", server.takeRequest().path)
        assertEquals("/api/v1/reports/worker-activity?date_from=2026-11-08&date_to=2026-11-14&user_id=a", server.takeRequest().path)
        assertEquals("/api/v1/worker-locations?date_from=2026-11-14&date_to=2026-11-14", server.takeRequest().path)
    }
}
