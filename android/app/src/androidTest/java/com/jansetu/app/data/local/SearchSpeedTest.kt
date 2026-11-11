package com.jansetu.app.data.local

import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.junit.AfterClass
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.BeforeClass
import org.junit.Test
import org.junit.runner.RunWith

/**
 * 5.3: 32,000 fake voters; English and Marathi prefix search each answer in under 200 ms.
 * Broad searches (many thousand hits) only log their time: emulator timings swing 3-4x with the
 * laptop's load. Measure them on the real phone (5.13).
 */
@RunWith(AndroidJUnit4::class)
class SearchSpeedTest {
    companion object {
        private lateinit var local: LocalDb
        private const val VOTERS = 32_000

        @BeforeClass @JvmStatic fun fill(): Unit = runBlocking {
            val ctx = InstrumentationRegistry.getInstrumentation().targetContext
            local = LocalDb(ctx, DbKey(ctx))
            local.wipe()
            val t = System.nanoTime()
            (0 until VOTERS).chunked(1000).forEach { page ->
                local.db.voters().savePulledVoters(page.map { FakeVoters.voter(it) }, emptyList())
            }
            local.optimizeSearch() // as the first download does
            Log.i("SearchSpeed", "inserted $VOTERS in ${(System.nanoTime() - t) / 1_000_000} ms")
            Unit
        }

        @AfterClass @JvmStatic fun clean() { local.wipe() }
    }

    private fun timed(label: String, f: VoterFilter): Pair<Long, Int> = runBlocking {
        // Three runs, median: one slow run (page cache after a bulk load, emulator hiccup) is not the answer time.
        val runs = (1..3).map {
            val t = System.nanoTime()
            val rows = local.db.voters().rowsNow(VoterQuery.list(f, 50)) // the list carries the total
            Triple((System.nanoTime() - t) / 1_000_000, rows.size, rows.firstOrNull()?.total ?: 0)
        }
        val ms = runs.map { it.first }.sorted()[1]
        val count = runs[0].third
        Log.i("SearchSpeed", "$label: $count matches, first ${runs[0].second} rows with total in ${runs.map { it.first }} ms")
        ms to count
    }

    @Test fun englishPrefix() {
        val (ms, n) = timed("english 'ram pat'", VoterFilter(q = "ram pat"))
        assertTrue(n > 0); assertTrue("took $ms ms", ms < 200)
    }

    @Test fun englishTwoLetters() {
        val (_, n) = timed("english 'su'", VoterFilter(q = "su"))
        assertTrue(n > 0)
    }

    @Test fun marathiPrefix() {
        val (ms, n) = timed("marathi 'रम पा'", VoterFilter(q = "रम पा"))
        assertTrue(n > 0); assertTrue("took $ms ms", ms < 200)
    }

    @Test fun numberFindsSerialAndEpic() {
        val (_, n) = timed("number '17'", VoterFilter(q = "17"))
        assertTrue(n >= VOTERS / 1000)
    }

    @Test fun searchWithFilters() {
        val f = VoterFilter(q = "sun", gender = "F", ageMin = 30, ageMax = 50)
        val (_, n) = timed("'sun' + F + 30-50", f)
        assertEquals(n, runBlocking { local.db.voters().countNow(VoterQuery.count(f)) })
        assertTrue(n > 0)
    }
}
