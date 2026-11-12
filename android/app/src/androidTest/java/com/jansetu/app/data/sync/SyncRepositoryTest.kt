package com.jansetu.app.data.sync

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.jansetu.app.data.Fix
import com.jansetu.app.data.OutboxRepository
import com.jansetu.app.data.local.DbKey
import com.jansetu.app.data.local.FakeVoters
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.OutboxEntity
import com.jansetu.app.data.local.SurveyEntity
import com.jansetu.app.data.remote.ApiFactory
import com.jansetu.app.data.remote.ApiJson
import com.jansetu.app.data.remote.SessionEvents
import com.jansetu.app.data.remote.TokenStore
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

private class Tokens : TokenStore {
    override val accessToken = "t"
    override val refreshToken = "r"
    override fun saveTokens(access: String, refresh: String) {}
    override fun clearTokens() {}
}

/** Fake /sync/pull with [total] voters in pages of [pageSize]; can fail from a given page on. */
private class FakeServer(val total: Int, val pageSize: Int) : Dispatcher() {
    @Volatile var failFromPage: Int? = null
    val pushBodies = mutableListOf<JsonObject>()
    var pushAnswer: (JsonObject) -> MockResponse = { MockResponse().setResponseCode(500) }

    private fun voterJson(i: Int): String {
        val v = FakeVoters.voter(i)
        return """{"id":"${v.id}","local_body_id":"${v.localBodyId}","ward_id":"${v.wardId}","booth_id":"${v.boothId}",
            "part_no":${v.partNo},"serial_no":${v.serialNo},"epic_no":"${v.epicNo}","first_name_en":"${v.firstNameEn}",
            "last_name_en":"${v.lastNameEn}","gender":"${v.gender}","age":${v.age},"list_type":"main","roll_status":"active",
            "is_repeated_in_roll":false}"""
    }

    override fun dispatch(request: RecordedRequest): MockResponse {
        val url = request.requestUrl!!
        if (url.encodedPath.endsWith("/sync/push")) {
            val body = ApiJson.parseToJsonElement(request.body.readUtf8()).jsonObject
            synchronized(pushBodies) { pushBodies += body }
            return pushAnswer(body)
        }
        val page = url.queryParameter("cursor")?.toInt() ?: 1
        if (failFromPage != null && page >= failFromPage!!) return MockResponse().setResponseCode(503)
        val from = (page - 1) * pageSize
        val to = minOf(total, from + pageSize)
        val next = if (to < total) "\"${page + 1}\"" else "null"
        val first = if (page == 1) """
            "area_ids":["${FakeVoters.ward}","${FakeVoters.booth}"],
            "areas":[{"id":"${FakeVoters.ward}","level":"ward","code":"W1","name_mr":"वार्ड 1","name_en":"Ward 1"},
                     {"id":"${FakeVoters.booth}","parent_id":"${FakeVoters.ward}","level":"booth","code":"B1","name_mr":"बूथ 1","name_en":"Booth 1"}],
            "lists":{"castes":[],"professions":[],"color_tags":[],"custom_field_labels":[]},
            "total_voters":$total,""" else ""
        val voters = (from until to).joinToString(",") { voterJson(it) }
        return MockResponse().setBody("""{"watermark":"1000",$first "next_cursor":$next,"voters":[$voters]}""")
    }
}

@RunWith(AndroidJUnit4::class)
class SyncRepositoryTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val server = MockWebServer()
    private lateinit var local: LocalDb
    private lateinit var sync: SyncRepository
    private lateinit var fake: FakeServer

    @Before fun setUp() {
        fake = FakeServer(total = 2_500, pageSize = 500)
        server.dispatcher = fake
        server.start()
        local = LocalDb(context, DbKey(context))
        local.wipe()
        sync = SyncRepository(ApiFactory.create(server.url("/api/v1/").toString(), Tokens(), SessionEvents()), local)
    }

    @After fun tearDown() {
        server.shutdown()
        local.wipe()
    }

    /** 5.6: stopping at page 3 and running again finishes with the right voter count. */
    @Test fun firstDownloadResumesAfterAStop() = runBlocking {
        fake.failFromPage = 3
        val stopped = sync.pull(pageSize = 500)
        assertTrue(stopped is SyncOutcome.Failed)
        assertEquals(1_000, local.db.voters().voterCountNow())
        assertEquals("3", local.db.syncState().get(SyncKeys.PULL_CURSOR))

        // A new LocalDb = the app was closed and opened again.
        local = LocalDb(context, DbKey(context))
        sync = SyncRepository(ApiFactory.create(server.url("/api/v1/").toString(), Tokens(), SessionEvents()), local)
        fake.failFromPage = null
        assertEquals(SyncOutcome.Done, sync.pull(pageSize = 500))
        assertEquals(2_500, local.db.voters().voterCountNow())
        assertEquals("1000", local.db.syncState().get(SyncKeys.WATERMARK))
        assertEquals(null, local.db.syncState().get(SyncKeys.PULL_CURSOR))
        // Resumed from page 3: pages 1 and 2 were not asked for again.
        val asked = (1..server.requestCount).map { server.takeRequest().requestUrl!!.queryParameter("cursor") }
        assertEquals(listOf(null, "2", "3", "3", "4", "5"), asked)
    }

    @Test fun failedPushIsRetriedWithTheSameId() = runBlocking {
        sync.pull(pageSize = 500)
        val v = FakeVoters.voter(7)
        OutboxRepository(local).saveSurvey(SurveyEntity(voterId = v.id, mobile1 = "9876543210"), Fix(15.5, 73.8, 10.0))
        assertEquals(1, local.db.outbox().queued(10).size)

        fake.pushAnswer = { MockResponse().setResponseCode(503) }
        assertTrue(sync.push() is SyncOutcome.Failed)
        assertEquals(1, local.db.outbox().queued(10).size)

        fake.pushAnswer = { body ->
            val item = body["items"]!!.jsonArray[0].jsonObject
            val id = item["id"]!!.jsonPrimitive.content
            MockResponse().setBody("""{"results":[{"id":"$id","status":"applied","duplicate":false,
                "survey":{"voter_id":"${v.id}","mobile_1":"9876543210","version":1,"is_surveyed":true,"lat":15.5,"lng":73.8}}]}""")
        }
        assertEquals(SyncOutcome.Done, sync.push())
        val ids = fake.pushBodies.map { it["items"]!!.jsonArray[0].jsonObject["id"]!!.jsonPrimitive.content }
        assertEquals(2, ids.size)
        assertEquals("the retry must reuse the phone-made id", ids[0], ids[1])
        assertEquals(0, local.db.outbox().queued(10).size)
        val s = local.db.voters().survey(v.id)!!
        assertEquals(1, s.version)
        assertEquals(false, s.pending)
        // The location went in the push body.
        val data = fake.pushBodies[0]["items"]!!.jsonArray[0].jsonObject["data"]!!.jsonObject
        assertEquals(15.5, data["location"]!!.jsonObject["lat"]!!.jsonPrimitive.content.toDouble(), 0.0)
    }

    @Test fun conflictIsShownNotLost() = runBlocking {
        sync.pull(pageSize = 500)
        val v = FakeVoters.voter(9)
        OutboxRepository(local).saveSurvey(SurveyEntity(voterId = v.id, notes = "mine"), null)
        fake.pushAnswer = { body ->
            val id = body["items"]!!.jsonArray[0].jsonObject["id"]!!.jsonPrimitive.content
            MockResponse().setBody("""{"results":[{"id":"$id","status":"conflict","duplicate":false,"conflict_fields":["notes"],
                "survey":{"voter_id":"${v.id}","notes":"theirs","version":4,"is_surveyed":true}}]}""")
        }
        assertEquals(SyncOutcome.Done, sync.push())

        val problems = local.db.outbox().problems().first()
        assertEquals(1, problems.size)
        assertEquals(OutboxEntity.STATUS_CONFLICT, problems[0].status)
        assertEquals("notes", problems[0].conflictFields)
        assertEquals("mine", local.db.voters().survey(v.id)!!.notes) // the phone's copy is kept
        assertTrue(local.db.voters().survey(v.id)!!.conflict)

        // "Send mine again" queues it on top of the server's version 4.
        sync.keepMine(problems[0])
        val requeued = local.db.outbox().queued(10).single()
        assertEquals(4, requeued.baseVersion)
        assertTrue(requeued.id != problems[0].id)
    }

    @Test fun twoEditsBeforeASyncBecomeOneItem() = runBlocking {
        sync.pull(pageSize = 500)
        val v = FakeVoters.voter(11)
        val repo = OutboxRepository(local)
        repo.saveSurvey(SurveyEntity(voterId = v.id, notes = "one"), null)
        repo.saveSurvey(local.db.voters().survey(v.id)!!.copy(notes = "two"), null)
        val items = local.db.outbox().queued(10)
        assertEquals(1, items.size)
        assertTrue(items[0].data.contains("\"two\""))
    }

    @Test fun wipeSignalIsReported() = runBlocking {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest) = MockResponse().setBody("""{"watermark":"1","wipe":true}""")
        }
        assertEquals(SyncOutcome.Wipe, sync.pull())
    }
}
