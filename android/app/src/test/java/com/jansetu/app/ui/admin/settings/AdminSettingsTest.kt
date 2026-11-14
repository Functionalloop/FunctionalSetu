package com.jansetu.app.ui.admin.settings

import com.jansetu.app.data.remote.ApiFactory
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.ColorTagIn
import com.jansetu.app.data.remote.Constituency
import com.jansetu.app.data.remote.FakeTokens
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.NamedEntryIn
import com.jansetu.app.data.remote.SessionEvents
import com.jansetu.app.data.remote.apiCall
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Constituencies, Election & candidate, Lists & labels (9.7): the rules and the calls, fake data only. */
class AdminSettingsTest {

    // --- rules ---------------------------------------------------------------------------------------

    @Test fun pollingTimes() {
        assertEquals("7:00 am", SettingsRules.showTime("07:00:00"))
        assertEquals("6:30 pm", SettingsRules.showTime("18:30"))
        assertEquals("", SettingsRules.showTime(""))
        assertEquals("07:05:00", SettingsRules.timeValue(7, 5))
        assertEquals("14 Feb 2027", SettingsRules.showDate("2027-02-14"))
        assertNull(SettingsRules.checkElection("07:00:00", "18:00:00", ""))
        assertNull(SettingsRules.checkElection("", "", "9123456789"))
        assertEquals("Polling must end after it starts.", SettingsRules.checkElection("18:00:00", "07:00:00", ""))
        assertEquals("Set both polling times, or neither.", SettingsRules.checkElection("07:00:00", "", ""))
        assertTrue(SettingsRules.checkElection("", "", "12345")!!.startsWith("Contact"))
    }

    @Test fun settingsKeepWhatTheScreenDoesNotShow() {
        val server = Json.parseToJsonElement(
            """{"election_name_en":"Old","polling_start_time":null,"feature_survey":false,"sms_fields":["election_name"],
               "min_app_version_code":3,"party_name_en":"X"}""",
        ).jsonObject
        val out = SettingsRules.withChanges(server, mapOf(
            "election_name_en" to "  Goa Assembly 2027 ", "polling_start_time" to "07:00:00", "party_name_en" to "  ",
            "code_of_conduct_mode" to true, "symbol_file_id" to null,
        ))
        assertEquals(JsonPrimitive("Goa Assembly 2027"), out["election_name_en"])
        assertEquals(JsonPrimitive("07:00:00"), out["polling_start_time"])
        assertEquals(JsonNull, out["party_name_en"]) // emptied = cleared
        assertEquals(JsonPrimitive(true), out["code_of_conduct_mode"])
        assertEquals(JsonNull, out["symbol_file_id"])
        // untouched keys go back as they came (PUT replaces the whole set)
        assertEquals(JsonPrimitive(false), out["feature_survey"])
        assertEquals(server["sms_fields"], out["sms_fields"])
        assertEquals(JsonPrimitive(3), out["min_app_version_code"])
        assertEquals("Goa Assembly 2027", SettingsRules.text(out, "election_name_en"))
        assertEquals("", SettingsRules.text(out, "party_name_en"))
        assertTrue(SettingsRules.flag(out, "code_of_conduct_mode"))
    }

    @Test fun constituencyForm() {
        assertTrue(SettingsRules.checkConstituency("", "x", "")!!.startsWith("Write the code"))
        assertTrue(SettingsRules.checkConstituency("AC2", " ", "")!!.contains("Marathi"))
        assertNull(SettingsRules.checkConstituency("AC2", "पेडणे", "2"))
        val old = Constituency(id = "c1", code = "AC2", nameMr = "पेडणे", nameEn = "Pernem", acNo = 2)
        assertTrue(SettingsRules.constituencyEdits("पेडणे", "Pernem", "2", old).isEmpty())
        val e = SettingsRules.constituencyEdits("पेडणे", "", "3", old)
        assertEquals(setOf("name_en", "ac_no"), e.keys)
        assertEquals(JsonNull, e["name_en"])
        assertEquals(JsonPrimitive(3), e["ac_no"])
    }

    @Test fun listForms() {
        assertTrue(SettingsRules.checkNamed(" ") != null)
        assertNull(SettingsRules.checkColorTag("ours", "#2e7d32", "आपले", "Ours", isDefault = true, isActive = true))
        assertTrue(SettingsRules.checkColorTag("Ours", "#2e7d32", "a", "b", false, true)!!.startsWith("Code"))
        assertTrue(SettingsRules.checkColorTag("ours", "2e7d32", "a", "b", false, true)!!.startsWith("Colour"))
        assertEquals("A switched-off tag cannot be the default.", SettingsRules.checkColorTag("ours", "#2E7D32", "a", "b", true, false))
        assertTrue(SettingsRules.checkCustomField("", " ", enabled = true) != null)
        assertNull(SettingsRules.checkCustomField("", "", enabled = false))
        assertEquals(10, SettingsRules.nextSortOrder(emptyList()))
        assertEquals(40, SettingsRules.nextSortOrder(listOf(10, 30, 20)))
        assertEquals(0xFF2E7D32, SettingsRules.argb("#2e7d32"))
        assertNull(SettingsRules.argb("green"))
    }

    @Test fun imagesShrinkToAtMost1280() {
        assertEquals(1, SettingsRules.sampleSize(1000, 800))
        assertEquals(2, SettingsRules.sampleSize(4000, 3000)) // decoded 2000 px, then scaled to 1280
        assertEquals(8, SettingsRules.sampleSize(3000, 12000)) // decoded 1500 px
    }

    // --- calls ---------------------------------------------------------------------------------------

    private val server = MockWebServer()
    private lateinit var api: JansetuApi

    @Before fun setUp() {
        server.start()
        api = ApiFactory.create(server.url("/api/v1/").toString(), FakeTokens(access = "admin-access"), SessionEvents())
    }

    @After fun tearDown() = server.shutdown()

    @Test fun electionSettingsRoundTrip() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"election_name_en":"Old","feature_bluetooth_printer":true,"min_app_version_code":1}"""))
        server.enqueue(MockResponse().setBody("""{"election_name_en":"New"}"""))
        val s = (apiCall { api.electionSettings() } as ApiResult.Ok).value
        apiCall { api.saveElectionSettings(SettingsRules.withChanges(s, mapOf("election_name_en" to "New"))) }
        server.takeRequest()
        val put = server.takeRequest()
        assertEquals("PUT", put.method)
        assertEquals("/api/v1/settings/election", put.path)
        assertEquals("""{"election_name_en":"New","feature_bluetooth_printer":true,"min_app_version_code":1}""", put.body.readUtf8())
    }

    @Test fun namedListPathsAndBody() = runBlocking {
        val entry = """{"id":"e1","name_mr":"सरपंच","name_en":"Sarpanch","name_hi":"सरपंच","sort_order":10,"is_active":true}"""
        server.enqueue(MockResponse().setBody("[$entry]"))
        server.enqueue(MockResponse().setBody(entry))
        val e = (apiCall { api.namedList("influencer-types") } as ApiResult.Ok).value.single()
        assertEquals("सरपंच", e.nameHi)
        apiCall { api.saveNamed("influencer-types", e.id, NamedEntryIn(e.nameMr, "Up Sarpanch", e.nameHi, e.sortOrder, false)) }
        assertEquals("/api/v1/masters/influencer-types", server.takeRequest().path)
        val patch = server.takeRequest()
        assertEquals("PATCH", patch.method)
        assertEquals("/api/v1/masters/influencer-types/e1", patch.path)
        val body = Json.parseToJsonElement(patch.body.readUtf8()).jsonObject
        assertEquals(JsonPrimitive("सरपंच"), body["name_hi"]) // kept: the server replaces the whole entry
        assertEquals(JsonPrimitive(false), body["is_active"])
    }

    @Test fun colorTagAndUpload() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(201).setBody(
            """{"id":"t1","code":"ours","hex":"#2E7D32","label_mr":"आपले","label_en":"Ours","label_hi":null,"is_default":true,"sort_order":10,"is_active":true}"""))
        server.enqueue(MockResponse().setResponseCode(201).setBody(
            """{"id":"f1","kind":"symbol","original_name":"s.png","mime_type":"image/png","size_bytes":3,"created_at":"2026-11-14T05:00:00Z"}"""))
        apiCall { api.addColorTag(ColorTagIn("ours", "#2E7D32", "आपले", "Ours", null, true, 10, true)) }
        val r = apiCall {
            api.uploadFile("symbol".toRequestBody("text/plain".toMediaType()),
                MultipartBody.Part.createFormData("file", "s.png", byteArrayOf(1, 2, 3).toRequestBody("image/png".toMediaType())))
        }
        assertEquals("f1", (r as ApiResult.Ok).value.id)
        val tag = server.takeRequest()
        assertEquals("/api/v1/masters/color-tags", tag.path)
        assertTrue("label_hi" !in Json.parseToJsonElement(tag.body.readUtf8()).jsonObject) // null = left out
        val up = server.takeRequest()
        assertEquals("/api/v1/files", up.path)
        assertTrue(up.getHeader("Content-Type")!!.startsWith("multipart/form-data"))
        val text = up.body.readUtf8()
        assertTrue(text.contains("name=\"kind\"") && text.contains("symbol"))
        assertTrue(text.contains("name=\"file\"; filename=\"s.png\""))
    }
}
