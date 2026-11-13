package com.jansetu.app.data.sync

import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.jansetu.app.data.FieldRepository
import com.jansetu.app.data.PartNoteRepository
import com.jansetu.app.data.local.AppDatabase
import com.jansetu.app.data.local.DbKey
import com.jansetu.app.data.local.FakeVoters
import com.jansetu.app.data.local.FamilyEntity
import com.jansetu.app.data.local.FamilyMemberEntity
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.OutboxEntity
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
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

private class FieldTokens : TokenStore {
    override val accessToken = "t"
    override val refreshToken = "r"
    override fun saveTokens(access: String, refresh: String) {}
    override fun clearTokens() {}
}

/**
 * 7.4: Kutumb Connect and the walk list on the phone, with their sync. Fake voters only.
 * Uses an in-memory database (never the app's own file), so it is safe to run on a real phone.
 */
@RunWith(AndroidJUnit4::class)
class FieldSyncTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val server = MockWebServer()
    private lateinit var mem: AppDatabase
    private lateinit var local: LocalDb
    private lateinit var field: FieldRepository
    private lateinit var sync: SyncRepository

    /** Every push item the fake server got, in order. */
    private val pushed = mutableListOf<JsonObject>()
    /** The fake server's answer to one push item; default: applied, echoing what the server stores. */
    private var answer: (JsonObject) -> String = ::applied
    private var pullBody = """{"watermark":"1"}"""

    private val user = "00000000-0000-0000-0000-00000000aaaa"
    // v0, v1 in house 12; v2 in house 7; v3 without a house number.
    private val v: List<VoterEntity> = listOf("12", "12", "7", null).mapIndexed { i, house ->
        FakeVoters.voter(i).copy(serialNo = i + 1, houseNo = house)
    }

    @Before fun setUp() = runBlocking {
        mem = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        local = object : LocalDb(context, DbKey(context)) {
            override val db: AppDatabase get() = mem
        }
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                if (!request.requestUrl!!.encodedPath.endsWith("/sync/push")) return MockResponse().setBody(pullBody)
                val items = ApiJson.parseToJsonElement(request.body.readUtf8()).jsonObject["items"]!!.jsonArray.map { it.jsonObject }
                synchronized(pushed) { pushed += items }
                return MockResponse().setBody("""{"results":[${items.joinToString(",") { answer(it) }}]}""")
            }
        }
        server.start()
        val api = ApiFactory.create(server.url("/api/v1/").toString(), FieldTokens(), SessionEvents())
        field = FieldRepository(local, api)
        sync = SyncRepository(api, local)
        mem.voters().savePulledVoters(v, emptyList())
    }

    @After fun tearDown() {
        server.shutdown()
        mem.close()
    }

    private fun JsonObject.str(key: String) = this[key]?.jsonPrimitive?.content

    private fun applied(item: JsonObject): String {
        val id = item.str("id")
        val entity = item.str("entity_id")
        val data = item["data"]!!.jsonObject
        val stored = when (item.str("type")) {
            "family_new" -> """"family":{"id":"$entity","ward_id":"${FakeVoters.ward}","booth_id":"${data.str("booth_id")}",
                "label":"${data.str("label")}","source":"manual","updated_at":"2026-11-13T10:00:01Z","deleted_at":null}"""
            "family" -> """"family_member":{"voter_id":"$entity","family_id":${data.str("family_id")?.let { "\"$it\"" }},
                "updated_at":"2026-11-13T10:00:01Z"}"""
            "visit" -> """"visit":{"id":"${data.str("id")}","voter_id":"$entity","family_id":null,"booth_id":"${FakeVoters.booth}",
                "house_no":"${v.first { it.id == entity }.houseNo}","outcome":"${data.str("outcome")}",
                "visited_at":"2026-11-13T10:00:00.000000Z","revisit_at":null,"note":null,"visited_by":"$user","lat":null,"lng":null}"""
            "slip_event" -> return """{"id":"$id","status":"applied","duplicate":false}"""
            "part_note" -> """"part_note":{"booth_id":"$entity","note":"${data.str("note")}",
                "version":${item.str("base_version")!!.toInt() + 1},"updated_at":"2026-11-13T10:00:01Z","updated_by":"$user"}"""
            "survey" -> """"survey":{"voter_id":"$entity","color_tag_id":${data.str("color_tag_id")?.let { "\"$it\"" }},
                "version":1,"is_surveyed":true,"updated_at":"2026-11-13T10:00:01Z"}"""
            else -> error("unexpected type")
        }
        return """{"id":"$id","status":"applied","duplicate":false,$stored}"""
    }

    private suspend fun queued() = mem.outbox().queued(100)

    // --- part notes (7.11) ---
    @Test fun partNoteSavedOfflineIsOneItemAndTheServerVersionComesBack() = runBlocking {
        val notes = PartNoteRepository(local)
        notes.save(FakeVoters.booth, "Dogs in lane 3", user)
        notes.save(FakeVoters.booth, "  Dogs in lane 3; temple on Sunday ", user) // edited before it was sent
        val items = queued()
        assertEquals(1, items.size)
        assertEquals(OutboxEntity.TYPE_PART_NOTE to 0, items[0].type to items[0].baseVersion)
        assertTrue(mem.partNotes().get(FakeVoters.booth)!!.pending)

        assertEquals(SyncOutcome.Done, sync.push())
        assertEquals("Dogs in lane 3; temple on Sunday", pushed.single()["data"]!!.jsonObject.str("note"))
        val saved = mem.partNotes().get(FakeVoters.booth)!!
        assertEquals(1, saved.version)
        assertFalse(saved.pending)

        notes.save(FakeVoters.booth, "Next text", user) // the next edit builds on version 1
        assertEquals(1, queued().single().baseVersion)
    }

    @Test fun pulledPartNoteIsStoredButNeverOverwritesOneChangedHere() = runBlocking {
        val other = "00000000-0000-0000-0000-0000000000b2"
        PartNoteRepository(local).save(FakeVoters.booth, "Mine, not sent", user)
        pullBody = """{"watermark":"7","part_notes":[
            {"booth_id":"${FakeVoters.booth}","note":"Server text","version":3},
            {"booth_id":"$other","note":"Another part","version":1}]}"""
        assertEquals(SyncOutcome.Done, sync.pull())
        assertEquals("Mine, not sent", mem.partNotes().get(FakeVoters.booth)!!.note)
        assertEquals("Another part", mem.partNotes().get(other)!!.note) // what a second phone gets from its sync
    }

    @Test fun stalePartNoteIsAConflictNotALostNote() = runBlocking {
        val notes = PartNoteRepository(local)
        notes.save(FakeVoters.booth, "Phone text", user)
        answer = { item -> """{"id":"${item.str("id")}","status":"conflict","duplicate":false,"conflict_fields":["note"],
            "part_note":{"booth_id":"${FakeVoters.booth}","note":"Supervisor text","version":4}}""" }
        assertEquals(SyncOutcome.Done, sync.push())
        val mine = mem.partNotes().get(FakeVoters.booth)!!
        assertEquals("Phone text", mine.note) // kept on the phone
        assertTrue(mine.conflict)
        val problem = mem.outbox().problems().first().single()
        assertEquals(OutboxEntity.STATUS_CONFLICT, problem.status)

        // Keep mine: decided on the phone (notes have no server conflict rows), sent on top of version 4
        assertEquals(com.jansetu.app.data.remote.ApiResult.Ok(true), sync.resolve(problem, user, keepMine = true))
        assertEquals(4, queued().single().baseVersion)
        assertFalse(mem.partNotes().get(FakeVoters.booth)!!.conflict)
        answer = ::applied
        assertEquals(SyncOutcome.Done, sync.push())
        assertEquals(5 to "Phone text", mem.partNotes().get(FakeVoters.booth)!!.let { it.version to it.note })
    }

    @Test fun keepServersPartNoteShowsTheServerText() = runBlocking {
        PartNoteRepository(local).save(FakeVoters.booth, "Phone text", user)
        answer = { item -> """{"id":"${item.str("id")}","status":"conflict","duplicate":false,"conflict_fields":["note"],
            "part_note":{"booth_id":"${FakeVoters.booth}","note":"Supervisor text","version":4}}""" }
        sync.push()
        sync.resolve(mem.outbox().problems().first().single(), user, keepMine = false)
        val now = mem.partNotes().get(FakeVoters.booth)!!
        assertEquals("Supervisor text" to 4, now.note to now.version)
        assertFalse(now.conflict || now.pending)
        assertTrue(queued().isEmpty())
    }

    @Test fun kutumbMadeOfflineShowsAtOnceAndGoesUpBeforeItsMembers() = runBlocking {
        val k = field.newKutumb(FakeVoters.booth, FakeVoters.ward, "  Naik  ", listOf(v[0].id))
        field.putIn(v[1].id, k)

        // At once, before any sync: the name, both members, "not sent yet".
        val shown = mem.field().familyOf(v[0].id).first()!!
        assertEquals("Naik", shown.label)
        assertTrue(shown.pending)
        assertEquals(listOf(v[0].id, v[1].id), mem.field().members(k).first().map { it.id })
        assertEquals(k, mem.field().familyOf(v[1].id).first()!!.id)
        assertEquals(listOf("Naik"), mem.field().boothFamilies(FakeVoters.booth).first().map { it.label })

        assertEquals(SyncOutcome.Done, sync.push())
        assertEquals(listOf("family_new", "family", "family"), pushed.map { it.str("type") })
        assertEquals(k, pushed[0].str("entity_id"))
        assertEquals("Naik", pushed[0]["data"]!!.jsonObject.str("label"))
        assertEquals(k, pushed[0]["data"]!!.jsonObject.str("id"))
        assertEquals(FakeVoters.booth, pushed[0]["data"]!!.jsonObject.str("booth_id"))
        assertEquals(listOf(v[0].id, v[1].id), pushed.drop(1).map { it.str("entity_id") })
        assertTrue(pushed.drop(1).all { it["data"]!!.jsonObject.str("family_id") == k })
        assertTrue(pushed.all { it["base_version"]!!.jsonPrimitive.content == "0" })

        assertFalse("the server has it now", mem.field().family(k)!!.pending)
        assertTrue(queued().isEmpty())
    }

    @Test fun onlyTheLastMembershipChangeIsSent() = runBlocking {
        val a = field.newKutumb(FakeVoters.booth, FakeVoters.ward, "A", listOf(v[0].id))
        val b = field.newKutumb(FakeVoters.booth, FakeVoters.ward, "B", emptyList())
        field.putIn(v[2].id, a)
        field.putIn(v[2].id, b) // moved before a sync
        field.takeOut(v[0].id)  // and v0 taken out again
        assertNull(mem.field().familyOf(v[0].id).first())
        assertEquals(b, mem.field().familyOf(v[2].id).first()!!.id)

        val items = queued()
        assertEquals(listOf("family_new", "family_new", "family", "family"), items.map { it.type })
        // B is queued before the item that names it.
        assertEquals(listOf(a, b, v[2].id, v[0].id), items.map { it.entityId })
        assertTrue(items[2].data.contains(b))
        assertTrue(items[3].data.contains("\"leave_family\":true"))
    }

    @Test fun renameBeforeTheFirstSyncChangesTheQueuedKutumb() = runBlocking {
        val k = field.newKutumb(FakeVoters.booth, FakeVoters.ward, "Naik", listOf(v[0].id))
        assertNull(field.rename(k, "Ramesh Naik"))
        assertEquals("Ramesh Naik", mem.field().family(k)!!.label)
        val item = queued().single { it.type == OutboxEntity.TYPE_FAMILY_NEW }
        assertTrue(item.data.contains("\"Ramesh Naik\""))
        assertEquals("A Kutumb needs a name.", field.rename(k, "   "))
    }

    @Test fun houseMarkedNotHomeOfflineShowsOnTheWalkListAndSyncs() = runBlocking {
        val before = mem.field().houses(FakeVoters.booth).first()
        assertEquals(listOf("7", "12", null), before.map { it.house }) // number order, no house number last
        assertEquals(listOf(1, 2, 1), before.map { it.voters })

        field.markVisit(v[1].id, "not_home", user)

        val house12 = mem.field().houses(FakeVoters.booth).first().single { it.house == "12" }
        assertEquals("not_home", house12.lastOutcome)
        assertEquals(true, house12.lastPending)
        assertNull(mem.field().houses(FakeVoters.booth).first().single { it.house == "7" }.lastOutcome)

        assertEquals(SyncOutcome.Done, sync.push())
        val item = pushed.single()
        assertEquals("visit", item.str("type"))
        assertEquals(v[1].id, item.str("entity_id"))
        val data = item["data"]!!.jsonObject
        assertEquals("not_home", data.str("outcome"))
        assertTrue(data.str("id")!!.isNotEmpty())

        val after = mem.field().houses(FakeVoters.booth).first().single { it.house == "12" }
        assertEquals("not_home", after.lastOutcome)
        assertEquals(false, after.lastPending)
        assertTrue(queued().isEmpty())
    }

    @Test fun pullStoresKutumbsAndVisitsButKeepsChangesNotSentYet() = runBlocking {
        val k1 = UUID.randomUUID().toString()
        val k2 = UUID.randomUUID().toString()
        val visit = UUID.randomUUID().toString()
        mem.field().upsertFamilies(listOf(FamilyEntity(k2, FakeVoters.ward, FakeVoters.booth, "Old", null)))
        mem.field().upsertMembers(listOf(FamilyMemberEntity(v[3].id, k2), FamilyMemberEntity(v[2].id, k2)))
        val mine = field.newKutumb(FakeVoters.booth, FakeVoters.ward, "Mine", listOf(v[0].id)) // not sent yet

        pullBody = """{"watermark":"5",
            "area_ids":["${FakeVoters.ward}","${FakeVoters.booth}"],
            "families":[{"id":"$k1","ward_id":"${FakeVoters.ward}","booth_id":"${FakeVoters.booth}","label":"Gawde",
                         "source":"manual","updated_at":"2026-11-13T09:00:00Z","deleted_at":null},
                        {"id":"$k2","ward_id":"${FakeVoters.ward}","booth_id":"${FakeVoters.booth}","label":"Old",
                         "source":"manual","updated_at":"2026-11-13T09:00:00Z","deleted_at":"2026-11-13T09:30:00Z"}],
            "family_members":[{"voter_id":"${v[1].id}","family_id":"$k1","updated_at":"2026-11-13T09:00:00Z"},
                              {"voter_id":"${v[0].id}","family_id":"$k1","updated_at":"2026-11-13T09:00:00Z"},
                              {"voter_id":"${v[2].id}","family_id":null,"updated_at":"2026-11-13T09:00:00Z"}],
            "visits":[{"id":"$visit","voter_id":"${v[2].id}","family_id":null,"booth_id":"${FakeVoters.booth}","house_no":"7",
                       "outcome":"met","visited_at":"2026-11-13T09:10:00Z","revisit_at":null,"note":null,
                       "visited_by":"$user","lat":null,"lng":null}]}"""
        assertEquals(SyncOutcome.Done, sync.pull())

        assertEquals(k1, mem.field().familyOf(v[1].id).first()!!.id)
        assertEquals("the phone's own change waits for the push", mine, mem.field().familyOf(v[0].id).first()!!.id)
        assertNull("taken out on the server", mem.field().familyOf(v[2].id).first())
        assertNull("deleted Kutumb goes", mem.field().family(k2))
        assertNull("with its members", mem.field().familyOf(v[3].id).first())
        assertEquals("met", mem.field().houses(FakeVoters.booth).first().single { it.house == "7" }.lastOutcome)
    }

    @Test fun partLeavingThePhoneTakesItsKutumbsAndVisits() = runBlocking {
        field.newKutumb(FakeVoters.booth, FakeVoters.ward, "Naik", listOf(v[0].id, v[1].id))
        field.markVisit(v[2].id, "met", user)
        pullBody = """{"watermark":"9","area_ids":["${FakeVoters.ward}"]}""" // the booth is no longer this user's
        assertEquals(SyncOutcome.Done, sync.pull())

        assertEquals(0, mem.voters().voterCountNow())
        assertTrue(mem.field().boothFamilies(FakeVoters.booth).first().isEmpty())
        assertTrue(mem.field().houses(FakeVoters.booth).first().isEmpty())
        assertNull(mem.field().member(v[0].id))
    }

    @Test fun refusedKutumbOrVisitIsTakenOffThePhoneAndShown() = runBlocking {
        val k = field.newKutumb(FakeVoters.booth, FakeVoters.ward, "Naik", listOf(v[0].id))
        field.markVisit(v[2].id, "met", user)
        answer = { item ->
            """{"id":"${item.str("id")}","status":"rejected","duplicate":false,
                "error":{"code":"not_found","message":"Booth not found."}}"""
        }
        assertEquals(SyncOutcome.Done, sync.push())

        assertNull(mem.field().family(k))
        assertNull(mem.field().familyOf(v[0].id).first())
        assertNull(mem.field().houses(FakeVoters.booth).first().single { it.house == "7" }.lastOutcome)
        val problems = mem.outbox().problems().first()
        assertEquals(setOf("family_new", "family", "visit"), problems.map { it.type }.toSet())
        assertTrue(problems.all { it.status == OutboxEntity.STATUS_REJECTED })
    }

    @Test fun slipSharedOfflineLeavesOneOutboxItemThatGoesUp() = runBlocking {
        field.logSlip(v[0].id, "whatsapp")
        val item = queued().single()
        assertEquals(OutboxEntity.TYPE_SLIP_EVENT, item.type)
        assertEquals(v[0].id, item.entityId)
        val data = ApiJson.parseToJsonElement(item.data).jsonObject
        assertEquals("whatsapp", data.str("channel"))
        assertTrue(data.str("id")!!.length == 36 && data.str("at") != null)

        field.logSlip(v[0].id, "whatsapp") // shared again: a second event, not a replacement
        assertEquals(2, queued().size)
        assertEquals(SyncOutcome.Done, sync.push())
        assertEquals(listOf("slip_event", "slip_event"), pushed.map { it.str("type") })
        assertTrue(queued().isEmpty())
    }

    @Test fun slipIsDrawn() {
        val content = com.jansetu.app.ui.slip.slipContent(v[0], null, com.jansetu.app.ui.slip.SlipSettings(pollingDate = "2027-02-14"))
        val bmp = com.jansetu.app.ui.slip.drawSlip(content)
        assertEquals(1080, bmp.width)
        assertTrue(bmp.height in 500..2500)
    }

    @Test fun taggingFiftyVotersMakesFiftyItemsAndOnePush() = runBlocking {
        val many = (100 until 150).map { FakeVoters.voter(it).copy(serialNo = it) }
        mem.voters().savePulledVoters(many, emptyList())
        val outbox = com.jansetu.app.data.OutboxRepository(local)
        mem.voters().saveLocalSurvey(com.jansetu.app.data.local.SurveyEntity(voterId = many[0].id, notes = "keep me", version = 3))

        assertEquals(50, outbox.setColorTag(many.map { it.id }, "tag-green"))
        assertEquals(50, queued().size)
        assertEquals(0, outbox.setColorTag(many.map { it.id }, "tag-green")) // already that tag: nothing new
        val first = ApiJson.parseToJsonElement(queued().first { it.entityId == many[0].id }.data).jsonObject
        assertEquals("keep me", first.str("notes")) // the whole survey goes up, so nothing is cleared
        assertEquals(3, queued().first { it.entityId == many[0].id }.baseVersion)

        val requests = server.requestCount
        assertEquals(SyncOutcome.Done, sync.push())
        assertEquals("one push request", 1, server.requestCount - requests)
        assertEquals(50, pushed.count { it.str("type") == "survey" })
        assertTrue(queued().isEmpty())
        assertEquals("tag-green", mem.voters().survey(many[1].id)!!.colorTagId)
    }

    @Test fun birthdaysComeFromTheSurveyDateOfBirth() = runBlocking {
        mem.voters().saveLocalSurvey(com.jansetu.app.data.local.SurveyEntity(voterId = v[0].id, dob = "1980-11-13"))
        mem.voters().saveLocalSurvey(com.jansetu.app.data.local.SurveyEntity(voterId = v[1].id, dob = "1984-02-29"))
        mem.voters().saveLocalSurvey(com.jansetu.app.data.local.SurveyEntity(voterId = v[2].id))
        assertEquals(listOf(v[0].id), mem.voters().birthdays(listOf("11-13", "11-14")).map { it.id })
        assertEquals(listOf(v[1].id), mem.voters().birthdays(listOf("02-28", "02-29")).map { it.id })
    }
}
