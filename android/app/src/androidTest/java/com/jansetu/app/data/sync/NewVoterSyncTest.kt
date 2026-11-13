package com.jansetu.app.data.sync

import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.jansetu.app.data.NewVoterRepository
import com.jansetu.app.data.local.AppDatabase
import com.jansetu.app.data.local.DbKey
import com.jansetu.app.data.local.FakeVoters
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.NewVoterEntity
import com.jansetu.app.data.local.OutboxEntity
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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

private class NvTokens : TokenStore {
    override val accessToken = "t"
    override val refreshToken = "r"
    override fun saveTokens(access: String, refresh: String) {}
    override fun clearTokens() {}
}

/**
 * 7.5: Eligible but Not Registered on the phone, with its sync. Fake data only.
 * In-memory database (never the app's own file): safe to run on a real phone.
 */
@RunWith(AndroidJUnit4::class)
class NewVoterSyncTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val server = MockWebServer()
    private lateinit var mem: AppDatabase
    private lateinit var repo: NewVoterRepository
    private lateinit var sync: SyncRepository

    private val pushed = mutableListOf<JsonObject>()
    /** The server's record versions, as the fake server keeps them. */
    private val serverVersion = mutableMapOf<String, Int>()
    private var answer: (JsonObject) -> String = ::serverAnswer
    private var pullBody = """{"watermark":"1"}"""
    /** GET /sync/conflicts answer, and the resolve calls received: conflict id -> keep. */
    private var conflictsBody = """{"items":[]}"""
    private val resolved = mutableMapOf<String, String>()
    private val user = "00000000-0000-0000-0000-00000000aaaa"

    @Before fun setUp() {
        mem = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        val local = object : LocalDb(context, DbKey(context)) {
            override val db: AppDatabase get() = mem
        }
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val path = request.requestUrl!!.encodedPath
                if (path.endsWith("/sync/conflicts")) return MockResponse().setBody(conflictsBody)
                if (path.endsWith("/resolve")) {
                    val keep = ApiJson.parseToJsonElement(request.body.readUtf8()).jsonObject["keep"]!!.jsonPrimitive.content
                    synchronized(resolved) { resolved[path.split("/").dropLast(1).last()] = keep }
                    return MockResponse().setBody(conflictJson("x", "x", "x"))
                }
                if (!path.endsWith("/sync/push")) return MockResponse().setBody(pullBody)
                val items = ApiJson.parseToJsonElement(request.body.readUtf8()).jsonObject["items"]!!.jsonArray.map { it.jsonObject }
                synchronized(pushed) { pushed += items }
                return MockResponse().setBody("""{"results":[${items.joinToString(",") { answer(it) }}]}""")
            }
        }
        server.start()
        val api = ApiFactory.create(server.url("/api/v1/").toString(), NvTokens(), SessionEvents())
        repo = NewVoterRepository(local)
        sync = SyncRepository(api, local)
    }

    @After fun tearDown() {
        server.shutdown()
        mem.close()
    }

    private fun JsonObject.str(key: String) = this[key]?.jsonPrimitive?.content

    private fun record(id: String, version: Int, notes: String?, form6: String = "not_applied") = """{"id":"$id",
        "full_name_en":"Fake Person","ward_id":"${FakeVoters.ward}","booth_id":"${FakeVoters.booth}","form6_status":"$form6",
        "notes":${notes?.let { "\"$it\"" }},"version":$version,"created_by":"$user","created_at":"2026-11-13T10:00:00Z",
        "updated_at":"2026-11-13T10:00:01Z"}"""

    /** Applies like the server: create gives version 1; an update on the current version adds 1, else conflict. */
    private fun serverAnswer(item: JsonObject): String {
        val id = item.str("entity_id")!!
        val data = item["data"]!!.jsonObject
        val base = item.str("base_version")!!.toInt()
        val head = """"id":"${item.str("id")}","duplicate":false"""
        return when (item.str("type")) {
            "new_voter" -> { serverVersion[id] = 1; """{$head,"status":"applied","new_voter":${record(id, 1, data.str("notes"), data.str("form6_status")!!)}}""" }
            else -> {
                val now = serverVersion[id] ?: 0
                if (base != now) """{$head,"status":"conflict","conflict_fields":["notes"],"new_voter":${record(id, now, "server copy")}}"""
                else {
                    serverVersion[id] = now + 1
                    """{$head,"status":"applied","new_voter":${record(id, now + 1, data.str("notes"), data.str("form6_status")!!)}}"""
                }
            }
        }
    }

    private fun person(notes: String? = null, form6: String = "not_applied") = NewVoterEntity(
        id = "", fullNameEn = "  Fake Person ", wardId = FakeVoters.ward, boothId = FakeVoters.booth,
        form6Status = form6, notes = notes, mobile = "", createdAt = "",
    )

    @Test fun addedOfflineShowsAtOnceAndGoesUpAsOneCreate() = runBlocking {
        val id = repo.save(person(notes = "first"), user)
        repo.save(mem.newVoters().get(id)!!.copy(notes = "second"), user) // edited before any sync

        val shown = mem.newVoters().list(null).first().single()
        assertEquals("Fake Person", shown.fullNameEn) // trimmed
        assertNull("blank mobile = no value", shown.mobile)
        assertTrue(shown.pending)
        val items = mem.outbox().queued(10)
        assertEquals("one create carrying the last values", listOf(OutboxEntity.TYPE_NEW_VOTER), items.map { it.type })

        assertEquals(SyncOutcome.Done, sync.push())
        val sent = pushed.single()
        assertEquals("new_voter", sent.str("type"))
        assertEquals(id, sent.str("entity_id"))
        assertEquals(id, sent["data"]!!.jsonObject.str("id"))
        assertEquals("second", sent["data"]!!.jsonObject.str("notes"))
        assertEquals("0", sent.str("base_version"))
        val saved = mem.newVoters().get(id)!!
        assertFalse(saved.pending)
        assertEquals(1, saved.version)
    }

    @Test fun editsAfterTheCreateAreUpdatesOnTheServersVersion() = runBlocking {
        val id = repo.save(person(), user)
        sync.push()
        repo.save(mem.newVoters().get(id)!!.copy(form6Status = "applied"), user)
        repo.save(mem.newVoters().get(id)!!.copy(notes = "Form 6 given"), user) // same unsent item
        val queued = mem.outbox().queued(10).single()
        assertEquals(OutboxEntity.TYPE_NEW_VOTER_UPDATE, queued.type)
        assertEquals(1, queued.baseVersion)

        assertEquals(SyncOutcome.Done, sync.push())
        val saved = mem.newVoters().get(id)!!
        assertEquals(2, saved.version)
        assertEquals("applied", saved.form6Status)
        assertEquals("Form 6 given", saved.notes)
        assertFalse(saved.pending)
    }

    @Test fun editWhileTheCreateIsOnItsWayIsRebased() = runBlocking {
        val id = repo.save(person(), user)
        mem.outbox().countAttempt(mem.outbox().queued(10).map { it.id }) // sent, no answer yet
        repo.save(mem.newVoters().get(id)!!.copy(notes = "later"), user)
        assertEquals(listOf(OutboxEntity.TYPE_NEW_VOTER, OutboxEntity.TYPE_NEW_VOTER_UPDATE), mem.outbox().queued(10).map { it.type })
        assertEquals(1, mem.outbox().queued(10)[1].baseVersion)

        assertEquals(SyncOutcome.Done, sync.push())
        assertEquals(listOf("new_voter", "new_voter_update"), pushed.map { it.str("type") })
        val saved = mem.newVoters().get(id)!!
        assertEquals(2, saved.version)
        assertEquals("later", saved.notes)
    }

    @Test fun staleEditIsAConflictKeptOnThePhone() = runBlocking {
        val id = repo.save(person(), user)
        sync.push()
        serverVersion[id] = 4 // someone else saved three times meanwhile
        repo.save(mem.newVoters().get(id)!!.copy(notes = "mine"), user)
        assertEquals(SyncOutcome.Done, sync.push())

        val mine = mem.newVoters().get(id)!!
        assertEquals("mine", mine.notes)
        assertTrue(mine.conflict)
        val problem = mem.outbox().problems().first().single()
        assertEquals(OutboxEntity.STATUS_CONFLICT, problem.status)
        assertEquals("notes", problem.conflictFields)

        sync.keepMine(problem) // "Send mine again" on top of the server's version 4
        assertEquals(4, mem.outbox().queued(10).single().baseVersion)
        assertEquals(SyncOutcome.Done, sync.push())
        assertEquals(5, mem.newVoters().get(id)!!.version)
        assertFalse(mem.newVoters().get(id)!!.conflict)
    }

    private fun conflictJson(id: String, entity: String, by: String) =
        """{"id":"$id","entity_type":"new_voter","entity_id":"$entity","field_name":"notes","client_value":"mine",
            "server_value":"server copy","client_user":{"id":"$by","username":"u","full_name_en":"Fake","role":"surveyor"},
            "created_at":"2026-11-13T10:00:00Z","status":"open"}"""

    @Test fun keepMineIsDecidedOnTheServer() = runBlocking { // 7.10
        val id = repo.save(person(), user)
        sync.push()
        serverVersion[id] = 4
        repo.save(mem.newVoters().get(id)!!.copy(notes = "mine"), user)
        sync.push()
        val other = "00000000-0000-0000-0000-00000000bbbb"
        conflictsBody = """{"items":[${conflictJson("c1", id, user)},${conflictJson("c2", id, other)}]}"""

        val r = sync.resolve(mem.outbox().problems().first().single(), user, keepMine = true)
        assertEquals(com.jansetu.app.data.remote.ApiResult.Ok(true), r)
        assertEquals(mapOf("c1" to KEEP_PHONE), resolved) // only this user's row; the other worker's stays
        assertTrue(mem.outbox().problems().first().isEmpty())
        assertTrue(mem.outbox().queued(10).isEmpty()) // nothing sent again: the server wrote it
        val now = mem.newVoters().get(id)!!
        assertFalse(now.conflict || now.pending) // the next pull overwrites it with the decided copy
    }

    @Test fun keepMineAfterTheSupervisorDecidedUsesTheServerCopy() = runBlocking { // 7.10
        val id = repo.save(person(), user)
        sync.push()
        serverVersion[id] = 2
        repo.save(mem.newVoters().get(id)!!.copy(notes = "mine"), user)
        sync.push()
        conflictsBody = """{"items":[]}""" // nothing open any more

        val r = sync.resolve(mem.outbox().problems().first().single(), user, keepMine = true)
        assertEquals(com.jansetu.app.data.remote.ApiResult.Ok(false), r)
        assertTrue(resolved.isEmpty())
        assertEquals("server copy", mem.newVoters().get(id)!!.notes)
        assertTrue(mem.outbox().problems().first().isEmpty())
    }

    @Test fun useServerCopyDropsMine() = runBlocking {
        val id = repo.save(person(), user)
        sync.push()
        serverVersion[id] = 2
        repo.save(mem.newVoters().get(id)!!.copy(notes = "mine"), user)
        sync.push()
        sync.discardMine(mem.outbox().problems().first().single())
        val now = mem.newVoters().get(id)!!
        assertEquals("server copy", now.notes)
        assertFalse(now.conflict || now.pending)
        assertTrue(mem.outbox().problems().first().isEmpty())
    }

    @Test fun refusedCreateLeavesThePhone() = runBlocking {
        val id = repo.save(person(), user)
        answer = { """{"id":"${it.str("id")}","status":"rejected","duplicate":false,"error":{"code":"not_found","message":"Area not found."}}""" }
        assertEquals(SyncOutcome.Done, sync.push())
        assertNull(mem.newVoters().get(id))
        assertEquals(OutboxEntity.STATUS_REJECTED, mem.outbox().problems().first().single().status)
    }

    @Test fun pullStoresRecordsButKeepsOnesChangedHere() = runBlocking {
        val theirs = UUID.randomUUID().toString()
        val mine = repo.save(person(notes = "mine"), user) // not sent yet
        pullBody = """{"watermark":"3","area_ids":["${FakeVoters.ward}","${FakeVoters.booth}"],
            "new_voters":[${record(theirs, 2, "theirs", "approved")},${record(mine, 1, "server")}]}"""
        assertEquals(SyncOutcome.Done, sync.pull())
        assertEquals("approved", mem.newVoters().get(theirs)!!.form6Status)
        assertEquals("mine", mem.newVoters().get(mine)!!.notes)
        assertEquals(listOf("approved"), mem.newVoters().list("approved").first().map { it.form6Status })

        pullBody = """{"watermark":"4","area_ids":["${FakeVoters.ward}"]}""" // the part left this phone
        assertEquals(SyncOutcome.Done, sync.pull())
        assertTrue(mem.newVoters().list(null).first().isEmpty())
    }
}
