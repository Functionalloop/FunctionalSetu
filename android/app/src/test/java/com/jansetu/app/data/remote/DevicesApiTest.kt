package com.jansetu.app.data.remote

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The Phones screen's calls (GET /devices, approve, block) against answers shaped like docs/openapi.json. */
class DevicesApiTest {
    private val server = MockWebServer()
    private lateinit var api: JansetuApi

    @Before fun setUp() {
        server.start()
        api = ApiFactory.create(server.url("/api/v1/").toString(), FakeTokens(access = "admin-access"), SessionEvents())
    }

    @After fun tearDown() = server.shutdown()

    @Test fun listOfWaitingPhones() = runBlocking {
        server.enqueue(MockResponse().setBody(
            """{"items":[{"id":"d1","status":"pending","model":"vivo I2207","os_version":"Android 15",
               "app_version_code":1,"requested_at":"2026-11-13T05:00:00Z","decided_at":null,"wipe_required":false,
               "user_id":"u1","decided_by":null,"blocked_reason":null,"username":"demo.surveyor",
               "full_name_en":"Demo Surveyor","role":"surveyor","last_seen_at":null,"some_new_field":1}],
               "next_cursor":"abc"}""",
        ))
        val r = apiCall { api.devices(status = "pending", limit = 100) }
        val page = (r as ApiResult.Ok).value
        assertEquals("abc", page.nextCursor)
        val d = page.items.single()
        assertEquals("d1", d.id)
        assertEquals("pending", d.status)
        assertEquals("demo.surveyor", d.username)
        assertEquals("surveyor", d.role)
        assertNull(d.decidedAt)
        val req = server.takeRequest()
        assertEquals("GET", req.method)
        assertEquals("/api/v1/devices?status=pending&limit=100", req.path)
        assertEquals("Bearer admin-access", req.getHeader("Authorization"))
    }

    @Test fun allPhonesSendsNoStatus() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"items":[],"next_cursor":null}"""))
        apiCall { api.devices(status = null, cursor = "c2") }
        assertEquals("/api/v1/devices?cursor=c2", server.takeRequest().path)
    }

    @Test fun approveAndBlock() = runBlocking {
        val answer = """{"id":"d1","status":"%s","model":null,"os_version":null,"app_version_code":null,
            "requested_at":"2026-11-13T05:00:00Z","decided_at":"2026-11-13T05:01:00Z","wipe_required":%s,
            "user_id":"u1","decided_by":"a1","blocked_reason":%s}"""
        server.enqueue(MockResponse().setBody(answer.format("approved", "false", "null")))
        server.enqueue(MockResponse().setBody(answer.format("blocked", "true", "\"Phone lost\"")))

        val approved = apiCall { api.approveDevice("d1") }
        assertEquals("approved", (approved as ApiResult.Ok).value.status)
        val a = server.takeRequest()
        assertEquals("POST", a.method)
        assertEquals("/api/v1/devices/d1/approve", a.path)

        val blocked = apiCall { api.blockDevice("d1", BlockDeviceRequest("Phone lost")) }
        assertEquals("Phone lost", (blocked as ApiResult.Ok).value.blockedReason)
        val b = server.takeRequest()
        assertEquals("/api/v1/devices/d1/block", b.path)
        assertTrue(b.body.readUtf8().contains("\"reason\":\"Phone lost\""))
    }

    @Test fun anAdminOfAnotherAreaGetsTheServerMessage() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(404)
            .setBody("""{"error":{"code":"not_found","message":"Phone not found."}}"""))
        val r = apiCall { api.approveDevice("elsewhere") }
        assertEquals("Phone not found.", r.userMessage())
    }
}
