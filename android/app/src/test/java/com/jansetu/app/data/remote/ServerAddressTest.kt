package com.jansetu.app.data.remote

import kotlinx.coroutines.runBlocking
import okhttp3.HttpUrl
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Laptop fallback (6.6): the address typed on the debug Login screen. */
class ServerAddressTest {
    private fun n(s: String) = ServerAddress.normalize(s)?.toString()

    @Test fun shortFormsBecomeTheApiBase() {
        assertEquals("http://192.168.137.1:8000/api/v1/", n("192.168.137.1:8000"))
        assertEquals("http://192.168.137.1:8000/api/v1/", n(" http://192.168.137.1:8000/ "))
        assertEquals("http://192.168.137.1:8000/api/v1/", n("192.168.137.1:8000/api"))
        assertEquals("http://192.168.137.1:8000/api/v1/", n("192.168.137.1:8000/api/v1/"))
        assertEquals("https://myjansetu.com/api/v1/", n("https://myjansetu.com"))
    }

    @Test fun nonsenseIsRefused() {
        assertNull(n(""))
        assertNull(n("   "))
        assertNull(n("http://"))
        assertNull(n("192.168.137.1:8000/other/path"))
        assertNull(n("192.168.137.1:99999"))
    }

    @Test fun labelHidesTheDefaultPort() {
        assertEquals("myjansetu.com", ServerAddress.label(n("https://myjansetu.com")!!.let(::url)))
        assertEquals("192.168.137.1:8000", ServerAddress.label(url(n("192.168.137.1:8000")!!)))
    }

    @Test fun callsGoToTheTypedAddressInsteadOfTheBuiltInOne() = runBlocking {
        val laptop = MockWebServer().apply { start() }
        try {
            laptop.enqueue(MockResponse().setBody("""{"id":"d","status":"approved","wipe_required":false}"""))
            var typed: HttpUrl? = null
            val api = ApiFactory.create("https://unreachable.invalid/api/v1/", FakeTokens(), SessionEvents(),
                                        server = { typed })
            typed = ServerAddress.normalize("${laptop.hostName}:${laptop.port}")
            val r = apiCall { api.myDevice() }
            assertEquals("approved", (r as ApiResult.Ok).value.status)
            assertEquals("/api/v1/devices/me", laptop.takeRequest().path)
        } finally {
            laptop.shutdown()
        }
    }

    private fun url(s: String) = okhttp3.HttpUrl.Companion.run { s.toHttpUrl() }
    private fun url(u: HttpUrl) = u
}
