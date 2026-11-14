package com.jansetu.app.data.remote

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The 10.6 screens' calls against answers shaped like docs/openapi.json (fake data only). */
class RollApiTest {
    private val server = MockWebServer()
    private lateinit var api: JansetuApi

    @Before fun setUp() {
        server.start()
        api = ApiFactory.create(server.url("/api/v1/").toString(), FakeTokens(access = "a"), SessionEvents())
    }

    @After fun tearDown() = server.shutdown()

    private val voter = """{"id":"%s","local_body_id":"lb","ward_id":"w","booth_id":"b","section_id":null,"part_no":12,
        "booth_no":12,"serial_no":%d,"epic_no":null,"first_name_mr":null,"middle_name_mr":null,"last_name_mr":null,
        "first_name_en":"Asha","middle_name_en":null,"last_name_en":"Naik","relation_type":"husband","relative_name_mr":null,
        "relative_name_en":"Ravi Naik","gender":"F","age":41,"age_as_of":null,"house_no":"88","address_mr":null,
        "address_en":null,"list_type":"main","roll_status":"active","deletion_reason":null,"is_repeated_in_roll":true,
        "deleted_at":null}"""

    @Test fun duplicatePairsAndResolve() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"items":[{"id":"p1","voter_a":${voter.format("va", 340)},
            "voter_b":${voter.format("vb", 18)},"source":"roll_flag","similarity":1.0,"status":"unchecked"}],"next_cursor":null}"""))
        val page = (apiCall { api.duplicates(uncheckedOnly = true, source = "roll_flag", limit = 50) } as ApiResult.Ok).value
        val p = page.items.single()
        assertEquals(340, p.voterA.serialNo)
        assertEquals("vb", p.voterB.id)
        assertEquals("/api/v1/data-quality/duplicates?unchecked_only=true&source=roll_flag&limit=50", server.takeRequest().path)

        server.enqueue(MockResponse().setBody("""{"id":"p1","voter_a":${voter.format("va", 340)},
            "voter_b":${voter.format("vb", 18)},"source":"roll_flag","similarity":1.0,"status":"same_person"}"""))
        apiCall { api.resolvePair("p1", PairResolution(samePerson = true)) }
        val body = server.takeRequest().body.readUtf8()
        assertEquals("""{"same_person":true}""", body) // no keep_voter_id: a supervisor's answer is never a hide

        server.enqueue(MockResponse().setBody("""{"id":"p1","voter_a":${voter.format("va", 340)},
            "voter_b":${voter.format("vb", 18)},"source":"roll_flag","similarity":1.0,"status":"same_person"}"""))
        apiCall { api.resolvePair("p1", PairResolution(samePerson = true, keepVoterId = "va")) }
        assertEquals("""{"same_person":true,"keep_voter_id":"va"}""", server.takeRequest().body.readUtf8())
    }

    @Test fun skippingAMobileRowSendsAnExplicitNull() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"id":"m1","status":"done","matched_count":1,"review_count":0,
            "not_found_count":0,"error":null,"created_at":"2026-11-14T05:00:00Z","finished_at":"2026-11-14T05:00:03Z",
            "rows":[{"id":5,"row_no":2,"name":"A Naik","mobile":"9800000001","address_text":null,"status":"skipped",
            "matched_voter_id":null,"candidate_voter_ids":[]}]}"""))
        val voterId: String? = null
        val r = apiCall { api.resolveMobileRow("m1", 5, buildJsonObject { put("voter_id", voterId) }) }
        assertEquals("skipped", (r as ApiResult.Ok).value.rows.single().status)
        val req = server.takeRequest()
        assertEquals("/api/v1/mobile-imports/m1/rows/5/resolve", req.path)
        assertEquals("""{"voter_id":null}""", req.body.readUtf8()) // the server needs the key
    }

    @Test fun featureOffComesBackAsTheServerMessage() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(403)
            .setBody("""{"error":{"code":"feature_off","message":"Mobile number sheets are switched off in the settings."}}"""))
        val part = MultipartBody.Part.createFormData("file", "n.csv", "mobile\n9800000001\n".toRequestBody("text/csv".toMediaType()))
        val r = apiCall { api.startMobileImport(part) }
        assertEquals("feature_off", (r as ApiResult.Err).code)
        assertTrue(server.takeRequest().body.readUtf8().contains("filename=\"n.csv\""))
    }

    @Test fun rollUploadSendsTheFormFieldsAndLeavesOutNoDate() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(202).setBody("""{"id":"i1","local_body_id":"lb","list_type":"main",
            "title":"Roll Jan 2027","published_on":null,"status":"uploaded","counts":{"rows":0,"to_review":0},"error":null,
            "imported_by":null,"applied_at":null,"created_at":"2026-11-14T05:00:00Z"}"""))
        fun t(s: String) = s.toRequestBody("text/plain".toMediaType())
        val part = MultipartBody.Part.createFormData("file", "roll.csv", "part_no\n".toRequestBody("text/csv".toMediaType()))
        val r = apiCall { api.startRollImport(part, t("lb"), t("main"), t("Roll Jan 2027"), null) }
        assertEquals(0, (r as ApiResult.Ok).value.counts["to_review"])
        val body = server.takeRequest().body.readUtf8()
        listOf("name=\"local_body_id\"", "name=\"list_type\"", "name=\"title\"", "Roll Jan 2027").forEach { assertTrue(it, body.contains(it)) }
        assertFalse(body.contains("published_on"))
    }

    @Test fun pendingRowsAndApply() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"items":[{"id":9,"row_no":3,"part_no":12,"serial_no":104,"epic_no":null,
            "first_name_en":"Ramesh","last_name_en":"Naik","first_name_mr":null,"last_name_mr":null,"gender":"M","age":46,
            "house_no":"23","match_status":"uncertain","matched_voter_id":"v1","similarity":0.62,"match_notes":"name differs",
            "review_status":"pending"}],"next_cursor":"c"}"""))
        val rows = (apiCall { api.rollImportRows("i1", pendingOnly = true, limit = 50) } as ApiResult.Ok).value
        assertEquals("uncertain", rows.items.single().matchStatus)
        assertEquals("/api/v1/rolls/imports/i1/rows?pending_only=true&limit=50", server.takeRequest().path)

        server.enqueue(MockResponse().setResponseCode(409)
            .setBody("""{"error":{"code":"review_not_finished","message":"3 rows still need a decision."}}"""))
        assertEquals("3 rows still need a decision.", apiCall { api.applyRollImport("i1") }.userMessage())
        assertEquals("/api/v1/rolls/imports/i1/apply", server.takeRequest().path)
    }

    @Test fun correctionSendsOnlyTheChangedFields() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"id":"v1","deleted_at":null,"part_no":12}"""))
        val fields = buildJsonObject { put("house_no", JsonPrimitive("23")); put("age", JsonNull) }
        apiCall { api.correctVoter("v1", RollPatch(fields, "typing_mistake", null)) }
        val req = server.takeRequest()
        assertEquals("PATCH", req.method)
        assertEquals("/api/v1/voters/v1/roll", req.path)
        assertEquals("""{"fields":{"house_no":"23","age":null},"reason":"typing_mistake"}""", req.body.readUtf8())

        server.enqueue(MockResponse().setBody("""{"items":[],"next_cursor":null}"""))
        apiCall { api.removedVoters(limit = 50) }
        assertEquals("/api/v1/voters?removed=true&limit=50", server.takeRequest().path)
    }
}
