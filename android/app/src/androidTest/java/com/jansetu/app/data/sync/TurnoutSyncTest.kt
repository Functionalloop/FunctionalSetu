package com.jansetu.app.data.sync

import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.jansetu.app.data.TurnoutRepository
import com.jansetu.app.data.local.AppDatabase
import com.jansetu.app.data.local.DbKey
import com.jansetu.app.data.local.FakeVoters
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.OutboxEntity
import com.jansetu.app.data.local.TurnoutEntity
import com.jansetu.app.data.local.VoterEntity
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
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

private class TurnoutTokens : TokenStore {
    override val accessToken = "t"
    override val refreshToken = "r"
    override fun saveTokens(access: String, refresh: String) {}
    override fun clearTokens() {}
}

/**
 * 8.2: voted marks on the phone and their sync. Fake voters only, in-memory database (safe on a real phone).
 * The fake server keeps one mark per voter, like voter_turnout: the first mark wins.
 */
@RunWith(AndroidJUnit4::class)
class TurnoutSyncTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val server = MockWebServer()
    private lateinit var mem: AppDatabase
    private lateinit var local: LocalDb
    private lateinit var repo: TurnoutRepository
    private lateinit var sync: SyncRepository

    private val me = "00000000-0000-0000-0000-00000000aaaa"
    private val other = "00000000-0000-0000-0000-00000000bbbb"
    private val v: List<VoterEntity> = (0 until 4).map { FakeVoters.voter(it).copy(serialNo = it + 1) }

    @Volatile private var offline = false
    /** Every push item the fake server got, in order. */
    private val pushed = mutableListOf<JsonObject>()
    /** The fake server's marks: voter id -> (is_voted, marked_by). */
    private val marks = mutableMapOf<String, Pair<Boolean, String>>()
    private var refuse: String? = null

    @Before fun setUp() = runBlocking {
        mem = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        local = object : LocalDb(context, DbKey(context)) {
            override val db: AppDatabase get() = mem
        }
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                if (offline) return MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST) // AT_START is ignored with a custom dispatcher
                if (!request.requestUrl!!.encodedPath.endsWith("/sync/push")) return MockResponse().setBody("""{"watermark":"1"}""")
                val items = ApiJson.parseToJsonElement(request.body.readUtf8()).jsonObject["items"]!!.jsonArray.map { it.jsonObject }
                synchronized(pushed) { pushed += items }
                return MockResponse().setBody("""{"results":[${items.joinToString(",") { answer(it) }}]}""")
            }
        }
        server.start()
        val api = ApiFactory.create(server.url("/api/v1/").toString(), TurnoutTokens(), SessionEvents())
        repo = TurnoutRepository(local)
        sync = SyncRepository(api, local)
        mem.voters().savePulledVoters(v, emptyList())
    }

    @After fun tearDown() {
        server.shutdown()
        mem.close()
    }

    private fun JsonObject.str(key: String) = this[key]?.jsonPrimitive?.content

    /** Applies one item like the server: a voter already voted stays as it was; undo keeps the row. */
    private fun answer(item: JsonObject): String {
        val id = item.str("id")
        refuse?.let { return """{"id":"$id","status":"rejected","duplicate":false,"error":{"code":"$it","message":"No."}}""" }
        val voters = if (item.str("type") == "unvoted") listOf(item.str("entity_id")!!)
        else item["data"]!!.jsonObject["voter_ids"]!!.jsonArray.map { it.jsonPrimitive.content }
        for (voter in voters) {
            val now = marks[voter]
            if (item.str("type") == "voted") { if (now?.first != true) marks[voter] = true to me }
            else if (now != null) marks[voter] = false to now.second
        }
        val rows = voters.mapNotNull { voter ->
            marks[voter]?.let { (voted, by) ->
                """{"voter_id":"$voter","is_voted":$voted,"marked_by":"$by","marked_at":"2026-11-14T03:30:00Z","source":"single"}"""
            }
        }
        return """{"id":"$id","status":"applied","duplicate":false,"turnout":[${rows.joinToString(",")}]}"""
    }

    private suspend fun unsent() = mem.outbox().queuedCountOf(OutboxEntity.TURNOUT_TYPES).first()
    private suspend fun mark(i: Int) = mem.turnout().get(v[i].id)

    @Test fun marksMadeOfflineUploadOnReconnectAndTheUnsentCountIsShown() = runBlocking {
        offline = true
        assertEquals(1, repo.markVoted(listOf(v[0].id), "single", me))
        assertEquals(1, repo.markVoted(listOf(v[1].id), "single", me))
        assertEquals(0, repo.markVoted(listOf(v[1].id), "single", me)) // already marked on the phone
        assertEquals(2, unsent())
        assertTrue(mark(0)!!.isVoted && mark(0)!!.pending)
        assertEquals(2, mem.turnout().partCounts(FakeVoters.booth).first().voted) // counted offline too

        assertTrue(sync.push() is SyncOutcome.Failed)
        assertEquals("still waiting after a failed try", 2, unsent())

        offline = false
        assertEquals(SyncOutcome.Done, sync.push())
        assertEquals(0, unsent())
        assertEquals(listOf("voted", "voted"), pushed.map { it.str("type") })
        assertEquals(mapOf(v[0].id to (true to me), v[1].id to (true to me)), marks)
        assertFalse(mark(0)!!.pending)
        assertEquals("2026-11-14T03:30:00Z", mark(0)!!.markedAt)
    }

    @Test fun aVoterSomeoneElseMarkedFirstShowsTheirMark() = runBlocking {
        marks[v[0].id] = true to other
        repo.markVoted(listOf(v[0].id), "single", me)
        sync.push()
        val row = mark(0)!!
        assertTrue(row.isVoted)
        assertEquals(other, row.markedBy)
        assertFalse(row.pending)
    }

    @Test fun undoOfAMarkNeverSentLeavesNothingToSend() = runBlocking {
        repo.markVoted(listOf(v[0].id, v[1].id), "booth_list", me)
        repo.undo(v[0].id, me)
        assertNull(mark(0))
        val item = mem.outbox().queued(10).single()
        assertEquals(listOf(v[1].id), item.data.let { ApiJson.parseToJsonElement(it).jsonObject["voter_ids"]!!.jsonArray.map { e -> e.jsonPrimitive.content } })
        repo.undo(v[1].id, me)
        assertEquals(0, unsent())
        assertNull(mark(1))
    }

    @Test fun undoOfASentMarkGoesUpAndTheServerKeepsTheRow() = runBlocking {
        repo.markVoted(listOf(v[0].id), "single", me)
        sync.push()
        repo.undo(v[0].id, me)
        assertEquals(OutboxEntity.TYPE_UNVOTED, mem.outbox().queued(10).single().type)
        assertTrue(!mark(0)!!.isVoted && mark(0)!!.pending)
        sync.push()
        assertEquals(false to me, marks[v[0].id])
        assertFalse(mark(0)!!.pending)
        assertFalse(mark(0)!!.isVoted)
    }

    @Test fun undoAndMarkAgainKeepTheirOrderAcrossBatches() = runBlocking {
        repo.markVoted(listOf(v[0].id), "single", me)
        sync.push()
        offline = true
        repo.undo(v[0].id, me)                        // unvoted #1
        sync.push()                                   // tried: on its way
        repo.markVoted(listOf(v[0].id), "single", me) // voted A
        sync.push()
        repo.undo(v[0].id, me)                        // A was tried, so unvoted #2 is queued
        repo.markVoted(listOf(v[0].id), "single", me) // voted B: must not overtake unvoted #2
        assertEquals(listOf("unvoted", "voted", "unvoted", "voted"), mem.outbox().queued(10).map { it.type })

        offline = false
        pushed.clear()
        assertEquals(SyncOutcome.Done, sync.push())
        assertEquals(listOf("unvoted", "voted", "unvoted", "voted"), pushed.map { it.str("type") })
        assertEquals(true to me, marks[v[0].id])
        assertTrue(mark(0)!!.isVoted && !mark(0)!!.pending)
    }

    @Test fun undoOfAMarkNeverSentAfterAnUndoOnItsWayStaysUndone() = runBlocking {
        repo.markVoted(listOf(v[0].id), "single", me)
        sync.push()
        repo.undo(v[0].id, me)                        // unvoted, queued
        repo.markVoted(listOf(v[0].id), "single", me) // voted, never sent
        repo.undo(v[0].id, me)                        // takes that mark back
        assertEquals(listOf("unvoted"), mem.outbox().queued(10).map { it.type })
        assertTrue(!mark(0)!!.isVoted && mark(0)!!.pending) // a pull cannot bring the old mark back
        sync.push()
        assertEquals(false to me, marks[v[0].id])
    }

    @Test fun aRefusedMarkIsTakenOffThePhoneAndARefusedUndoShowsVotedAgain() = runBlocking {
        repo.markVoted(listOf(v[0].id), "single", me)
        mem.turnout().upsert(listOf(TurnoutEntity(v[1].id, true, other, "2026-11-14T03:00:00Z", "single")))
        repo.undo(v[1].id, me)
        refuse = "forbidden_role"
        sync.push()
        assertNull(mark(0))
        assertTrue(mark(1)!!.isVoted && !mark(1)!!.pending)
        assertEquals(2, mem.outbox().problems().first().size) // shown on the Sync screen
    }

    @Test fun aPulledMarkNeverOverwritesOneNotSentYet() = runBlocking {
        offline = true
        repo.markVoted(listOf(v[0].id), "single", me)
        mem.turnout().savePulled(listOf(
            TurnoutEntity(v[0].id, false, other, "2026-11-14T02:00:00Z", "single"),
            TurnoutEntity(v[2].id, true, other, "2026-11-14T02:00:00Z", "single"),
        ))
        assertTrue(mark(0)!!.isVoted && mark(0)!!.pending)
        assertEquals(other, mark(2)!!.markedBy)
    }

    @Test fun marksOfVotersThatLeaveThePhoneGo() = runBlocking {
        mem.turnout().upsert(listOf(TurnoutEntity(v[3].id, true, other, "2026-11-14T02:00:00Z", "single")))
        mem.voters().removeVoters(listOf(v[3].id))
        mem.turnout().dropOrphans()
        assertNull(mark(3))
    }
}
