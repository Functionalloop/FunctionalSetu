package com.jansetu.app.data.remote

import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.Timeout
import java.util.concurrent.atomic.AtomicInteger

class FakeTokens(var access: String? = "old-access", var refresh: String? = "old-refresh") : TokenStore {
    override val accessToken get() = access
    override val refreshToken get() = refresh
    override fun saveTokens(access: String, refresh: String) { this.access = access; this.refresh = refresh }
    override fun clearTokens() { access = null; refresh = null }
}

private fun error(status: Int, code: String) =
    MockResponse().setResponseCode(status).setBody("""{"error":{"code":"$code","message":"msg $code"}}""")

private const val TOKENS = """{"access_token":"new-access","refresh_token":"new-refresh","expires_in":900,
  "must_change_password":false,"user":{"id":"u","username":"s1","full_name_en":"S","role":"surveyor"},
  "workspace":{"id":"w","code":"demo","name_en":"Demo"},"device":{"id":"d","status":"approved"}}"""

private const val DEVICE = """{"id":"d","status":"approved","wipe_required":false}"""

class ApiClientTest {
    private val server = MockWebServer()
    private val tokens = FakeTokens()
    private val events = SessionEvents()
    private lateinit var api: JansetuApi
    private val refreshes = AtomicInteger()

    @get:Rule val timeout: Timeout = Timeout.seconds(20)

    @Before fun setUp() {
        server.start()
        api = ApiFactory.create(server.url("/api/v1/").toString(), tokens, events)
    }

    @After fun tearDown() = server.shutdown()

    /** Answers like the API: data calls need the current access token. */
    private fun fakeApi(refresh: (RecordedRequest) -> MockResponse) = object : Dispatcher() {
        override fun dispatch(request: RecordedRequest): MockResponse = when (request.path) {
            "/api/v1/auth/refresh" -> { refreshes.incrementAndGet(); refresh(request) }
            "/api/v1/devices/me" ->
                if (request.getHeader("Authorization") == "Bearer new-access") MockResponse().setBody(DEVICE)
                else error(401, "token_expired")
            else -> error(404, "not_found")
        }
    }

    @Test fun expiredTokenIsRefreshedOnceAndTheCallSucceeds() = runBlocking {
        server.dispatcher = fakeApi { MockResponse().setBody(TOKENS) }
        val r = apiCall { api.myDevice() }
        assertEquals(ApiResult.Ok(DeviceDetail("d", "approved", false)), r)
        assertEquals(1, refreshes.get())
        assertEquals("new-access", tokens.access)
        assertEquals("new-refresh", tokens.refresh)
        // The refresh call sent the old refresh token and no access token.
        val calls = (1..server.requestCount).map { server.takeRequest() }
        val refreshCall = calls.single { it.path == "/api/v1/auth/refresh" }
        assertTrue(refreshCall.body.readUtf8().contains("old-refresh"))
        assertNull(refreshCall.getHeader("Authorization"))
    }

    @Test fun parallelCallsShareOneRefresh() = runBlocking {
        server.dispatcher = fakeApi { MockResponse().setBody(TOKENS) }
        val results = (1..5).map { async(kotlinx.coroutines.Dispatchers.IO) { apiCall { api.myDevice() } } }.awaitAll()
        assertTrue(results.all { it is ApiResult.Ok })
        assertEquals(1, refreshes.get())
    }

    @Test fun deadRefreshTokenLogsOut() = runBlocking {
        server.dispatcher = fakeApi { error(401, "invalid_refresh_token") }
        val r = apiCall { api.myDevice() }
        assertEquals("token_expired", (r as ApiResult.Err).code)
        assertNull(tokens.access)
        val e = withTimeout(1000) { events.events.first() }
        assertEquals(SessionEvent.LoggedOut("msg invalid_refresh_token"), e)
    }

    @Test fun blockedPhoneSendsTheWipeEvent() = runBlocking {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest) = error(403, "device_blocked")
        }
        val r = apiCall { api.myDevice() }
        assertEquals("device_blocked", (r as ApiResult.Err).code)
        assertEquals(SessionEvent.Blocked, withTimeout(1000) { events.events.first() })
    }

    @Test fun errorBodyIsMapped() = runBlocking {
        server.enqueue(error(401, "invalid_credentials"))
        val r = apiCall { api.login(LoginRequest("demo", "x", "y", null)) }
        assertEquals(ApiResult.Err(401, "invalid_credentials", "msg invalid_credentials"), r)
    }

    @Test fun noServerIsOffline() = runBlocking {
        server.shutdown()
        assertTrue(apiCall { api.myDevice() } is ApiResult.Offline)
    }

    @Test fun watermarkStaysText() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"watermark":"18446744073709551000","next_cursor":null,"extra_field":1}"""))
        val page = (apiCall { api.pull() } as ApiResult.Ok).value
        assertEquals("18446744073709551000", page.watermark)
    }
}
