package com.jansetu.app.ui.admin.users

import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.remote.AdminUser
import com.jansetu.app.data.remote.ApiFactory
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.AssignmentsIn
import com.jansetu.app.data.remote.FakeTokens
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.NewUser
import com.jansetu.app.data.remote.SessionEvents
import com.jansetu.app.data.remote.apiCall
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
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

/** Users & devices, Add user and Booths & karyakartas (9.6): the rules and the calls, fake data only. */
class AdminUsersTest {
    private fun user(id: String, role: String = "surveyor", areas: List<String> = emptyList(), lb: String = "c1", active: Boolean = true) =
        AdminUser(id = id, username = "u.$id", fullNameEn = "User $id", role = role, localBodyId = lb, isActive = active, areaIds = areas)

    private fun area(id: String, level: String, parent: String?) =
        AreaEntity(id, parent, level, id, null, id, id, null, null, null, 0)

    // --- rules ---------------------------------------------------------------------------------------

    @Test fun rolesByCaller() {
        assertEquals(listOf("supervisor", "surveyor", "booth_agent"), UserRules.rolesFor("admin"))
        assertTrue("admin" in UserRules.rolesFor("super_admin"))
        assertFalse(UserRules.mayChange("admin", user("a", role = "admin")))
        assertTrue(UserRules.mayChange("admin", user("s")))
        assertTrue(UserRules.mayChange("super_admin", user("a", role = "admin")))
    }

    @Test fun addUserForm() {
        assertEquals("Write the full name.", UserRules.checkNew(" ", "abc", "", false))
        assertTrue(UserRules.checkNew("A", "ab", "", false)!!.startsWith("User ID"))
        assertTrue(UserRules.checkNew("A", "has space", "", false)!!.startsWith("User ID"))
        assertTrue(UserRules.checkNew("A", "abc", "12345", false)!!.startsWith("Mobile"))
        assertTrue(UserRules.checkNew("A", "abc", "5123456789", false)!!.startsWith("Mobile"))
        assertEquals("Choose the constituency.", UserRules.checkNew("A", "abc", "9123456789", true))
        assertNull(UserRules.checkNew("A", "demo.s-1_x", "", false))
    }

    @Test fun editsSendOnlyWhatChanged() {
        val u = user("s").copy(fullNameMr = "Old", mobile = "9123456789")
        assertTrue(UserRules.edits(u, "User s", "Old", "9123456789", "surveyor").isEmpty())
        val e = UserRules.edits(u, " New name ", "", "9123456789", "booth_agent")
        assertEquals(setOf("full_name_en", "full_name_mr", "role"), e.keys)
        assertEquals(JsonPrimitive("New name"), e["full_name_en"])
        assertEquals(JsonNull, e["full_name_mr"]) // emptied = cleared
        assertEquals(JsonPrimitive("booth_agent"), e["role"])
    }

    @Test fun areasOfOneConstituency() {
        val areas = listOf(
            area("c1", "local_body", "ac"), area("w1", "ward", "c1"), area("p1", "booth", "w1"),
            area("c2", "local_body", "ac"), area("w2", "ward", "c2"), area("p2", "booth", "w2"),
        )
        val byId = areas.associateBy { it.id }
        assertEquals("c1", UserRules.constituencyOf("p1", byId))
        assertEquals("c2", UserRules.constituencyOf("w2", byId))
        assertNull(UserRules.constituencyOf("missing", byId))
        assertEquals(listOf("w1", "p1"), UserRules.inConstituency(areas, "c1").map { it.id })
        assertEquals(listOf("w1", "p1", "w2", "p2"), UserRules.inConstituency(areas, null).map { it.id })
    }

    @Test fun boothsTurnedAround() {
        val users = listOf(
            user("a", areas = listOf("p1", "p2")),
            user("b", areas = listOf("p2")),
            user("c"),
            user("d", lb = "c2"),                         // other constituency
            user("e", active = false),                    // switched off
            user("f", role = "supervisor"),               // not a part role
            user("g", role = "booth_agent", areas = listOf("p1"), active = false), // switched off but assigned
        )
        assertEquals(listOf("a", "g"), UserRules.assignedTo(users, "p1").map { it.id })
        val cand = UserRules.candidates(users, "p1", "c1", listOf("surveyor", "booth_agent")).map { it.id }
        assertEquals(listOf("a", "b", "c", "g"), cand) // not d (other constituency), e (off), f (supervisor)

        // Tick c, untick g, keep a: c gains p1, g loses it, a and the rest are left alone.
        val ch = UserRules.changes(users, "p1", setOf("a", "c"))
        assertEquals(setOf("c", "g"), ch.keys)
        assertEquals(listOf("p1"), ch["c"])
        assertEquals(emptyList<String>(), ch["g"])
        assertTrue(UserRules.changes(users, "p2", setOf("a", "b")).isEmpty())
    }

    // --- calls ---------------------------------------------------------------------------------------

    private val server = MockWebServer()
    private lateinit var api: JansetuApi

    @Before fun setUp() {
        server.start()
        api = ApiFactory.create(server.url("/api/v1/").toString(), FakeTokens(access = "admin-access"), SessionEvents())
    }

    @After fun tearDown() = server.shutdown()

    private val userJson = """{"id":"u1","username":"demo.new","full_name_en":"Demo New","full_name_mr":null,
        "role":"surveyor","mobile":null,"local_body_id":"c1","is_active":true,"must_change_password":true,
        "last_login_at":null,"locked_until":null,"created_at":"2026-11-14T05:00:00Z","device_count":0,
        "pending_device":false,"area_ids":["p1"],"some_new_field":1}"""

    @Test fun createUserShowsTheTemporaryPassword() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(201).setBody("""{"user":$userJson,"temporary_password":"Abc123xyzQ"}"""))
        val r = apiCall { api.createUser(NewUser("demo.new", "Demo New", null, null, "surveyor", null)) }
        val t = (r as ApiResult.Ok).value
        assertEquals("Abc123xyzQ", t.temporaryPassword)
        assertEquals(listOf("p1"), t.user.areaIds)
        val req = server.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("/api/v1/users", req.path)
        val body = Json.parseToJsonElement(req.body.readUtf8()).jsonObject
        assertEquals(JsonPrimitive("demo.new"), body["username"])
        assertEquals(JsonPrimitive("surveyor"), body["role"])
        assertFalse("local_body_id" in body) // an admin's users go in the admin's constituency
    }

    @Test fun patchSendsNullToClear() = runBlocking {
        server.enqueue(MockResponse().setBody(userJson))
        val u = user("u1").copy(mobile = "9123456789")
        apiCall { api.updateUser("u1", UserRules.edits(u, "User u1", "", "", "surveyor")) }
        val req = server.takeRequest()
        assertEquals("PATCH", req.method)
        assertEquals("/api/v1/users/u1", req.path)
        assertEquals("""{"mobile":null}""", req.body.readUtf8())
    }

    @Test fun assignmentsPutTheFullList() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"areas":[{"id":"p1","parent_id":"w1","level":"booth","code":"1",
            "number":1,"name_mr":"x","name_en":"Part one"}]}"""))
        val r = apiCall { api.setAssignments("u1", AssignmentsIn(listOf("p1", "w2"))) }
        assertEquals("booth", (r as ApiResult.Ok).value.areas.single().level)
        val req = server.takeRequest()
        assertEquals("PUT", req.method)
        assertEquals("/api/v1/users/u1/assignments", req.path)
        assertEquals("""{"area_ids":["p1","w2"]}""", req.body.readUtf8())
    }
}
