package com.jansetu.app.data.local

import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteException
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LocalDbTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private lateinit var local: LocalDb

    @Before fun setUp() {
        local = LocalDb(context, DbKey(context))
        local.wipe()
    }

    @After fun tearDown() = local.wipe()

    @Test fun writesAndReadsAVoter() = runTest {
        val v = FakeVoters.voter(1)
        local.db.voters().savePulledVoters(listOf(v), emptyList())
        local.db.voters().saveLocalSurvey(SurveyEntity(voterId = v.id, mobile1 = "9876543210", version = 0, isSurveyed = true, pending = true))

        assertEquals(v, local.db.voters().voter(v.id))
        assertEquals("9876543210", local.db.voters().survey(v.id)?.mobile1)
        // The search row is built from the voter and the survey.
        assertEquals(1, local.db.voters().countNow(VoterQuery.count(VoterFilter(q = "98765"))))
        assertEquals(1, local.db.voters().countNow(VoterQuery.count(VoterFilter(q = v.epicNo!!.lowercase()))))
    }

    @Test fun pulledSurveyDoesNotOverwriteAPendingLocalChange() = runTest {
        val v = FakeVoters.voter(2)
        local.db.voters().savePulledVoters(listOf(v), emptyList())
        local.db.voters().saveLocalSurvey(SurveyEntity(voterId = v.id, notes = "mine", pending = true))
        local.db.voters().savePulledSurveys(listOf(SurveyEntity(voterId = v.id, notes = "server", version = 3)))
        assertEquals("mine", local.db.voters().survey(v.id)?.notes)
    }

    @Test fun removedVotersGoWithTheirSurveysAndSearchRows() = runTest {
        val v = FakeVoters.voter(3)
        local.db.voters().savePulledVoters(listOf(v), emptyList())
        local.db.voters().saveLocalSurvey(SurveyEntity(voterId = v.id, mobile1 = "9123456780"))
        local.db.voters().savePulledVoters(emptyList(), listOf(v.id))
        assertEquals(null, local.db.voters().voter(v.id))
        assertEquals(null, local.db.voters().survey(v.id))
        assertEquals(0, local.db.voters().countNow(VoterQuery.count(VoterFilter(q = "9123456780"))))
    }

    @Test fun fileIsNotReadableWithoutTheKey() = runTest {
        local.db.voters().savePulledVoters(listOf(FakeVoters.voter(4)), emptyList())
        local.db.close()
        val file = context.getDatabasePath(AppDatabase.NAME)
        assertTrue(file.exists())

        val header = ByteArray(16).also { b -> file.inputStream().use { it.read(b) } }
        assertFalse("plain SQLite header found", String(header, Charsets.US_ASCII).startsWith("SQLite format 3"))
        try {
            SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY).use {
                it.rawQuery("SELECT count(*) FROM voters", null).use { c -> c.moveToFirst() }
            }
            fail("plain SQLite opened the encrypted file")
        } catch (expected: SQLiteException) {
            // "file is not a database"
        }
    }

    @Test fun wipeDeletesTheFileAndTheKey() = runTest {
        local.db.voters().savePulledVoters(listOf(FakeVoters.voter(5)), emptyList())
        local.wipe()
        assertFalse(local.fileExists())
        // A new database opens empty with a new key.
        assertEquals(0, local.db.voters().voterCountNow())
        assertNotNull(local.db)
    }
}
