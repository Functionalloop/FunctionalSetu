package com.jansetu.app.data.local

import androidx.room.testing.MigrationTestHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * 7.13: a phone on database version 2 keeps its unsent surveys after the update to version 3.
 * 7.4: version 3 to 4 adds the Kutumb and visit tables and asks for a full download.
 * Runs on a plain (unencrypted) file: the migration is the same SQL with or without SQLCipher.
 */
@RunWith(AndroidJUnit4::class)
class MigrationTest {
    private val name = "migration-test.db"

    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(), AppDatabase::class.java,
        listOf(Migration2To3(), Migration3To4()), FrameworkSQLiteOpenHelperFactory(),
    )

    @Test fun version2To3KeepsUnsentSurveysAndCleansTheirOutboxItems() {
        helper.createDatabase(name, 2).apply {
            // An unsent survey (pending) of an important voter with a position, and a synced one.
            execSQL(
                """INSERT INTO surveys (voter_id, mobile_1, has_new_address, notes, is_important, position_id,
                       is_influencer, influencer_type_id, in_self_help_group, ration_card, version, is_surveyed,
                       pending, conflict)
                   VALUES ('v1', '9876543210', 0, 'unsent note', 1, 'pos-1', 1, 'inf-1', 0, 'PHH', 3, 1, 1, 0),
                          ('v2', NULL, 0, NULL, 0, NULL, 0, NULL, 0, NULL, 1, 1, 0, 0)""",
            )
            execSQL(
                """INSERT INTO outbox (id, type, entity_id, base_version, changed_at, data, status, attempts, seq)
                   VALUES ('o1', 'survey', 'v1', 3, '2026-11-13T10:00:00Z',
                           '{"notes":"unsent note","is_important":true,"position_id":"pos-1","is_influencer":true,"influencer_type_id":"inf-1"}',
                           'queued', 0, 1)""",
            )
            execSQL(
                """INSERT INTO list_entries (id, kind, name_mr, name_en, sort_order, is_active)
                   VALUES ('pos-1', 'position', 'सरपंच', 'Sarpanch', 1, 1),
                          ('inf-1', 'influencer_type', 'पत्रकार', 'News Reporter', 10, 1)""",
            )
            close()
        }

        // Validates the new table shapes against the version 3 schema too.
        val db = helper.runMigrationsAndValidate(name, 3, true, *emptyArray())

        db.query("SELECT voter_id, mobile_1, notes, is_influencer, influencer_type_id, ration_card, version, pending " +
                 "FROM surveys ORDER BY voter_id").use { c ->
            assertEquals(2, c.count)
            c.moveToFirst()
            assertEquals("v1", c.getString(0))
            assertEquals("9876543210", c.getString(1))
            assertEquals("unsent note", c.getString(2))
            assertEquals(1, c.getInt(3))
            assertEquals("inf-1", c.getString(4))
            assertEquals("PHH", c.getString(5))
            assertEquals(3, c.getInt(6))
            assertEquals("still waiting to be sent", 1, c.getInt(7))
        }
        db.query("SELECT data, status FROM outbox WHERE id = 'o1'").use { c ->
            c.moveToFirst()
            val data = Json.parseToJsonElement(c.getString(0)).jsonObject
            assertFalse("is_important" in data)
            assertFalse("position_id" in data)
            assertEquals("unsent note", data["notes"]!!.jsonPrimitive.content)
            assertEquals("inf-1", data["influencer_type_id"]!!.jsonPrimitive.content)
            assertEquals("queued", c.getString(1))
        }
        db.query("SELECT kind FROM list_entries").use { c ->
            assertEquals(1, c.count)
            c.moveToFirst()
            assertEquals("influencer_type", c.getString(0))
        }
        db.close()
    }

    @Test fun version3To4AddsKutumbTablesAndAsksForAFullDownload() {
        val file = "migration-test-4.db"
        helper.createDatabase(file, 3).apply {
            execSQL("INSERT INTO sync_state (key, value) VALUES ('watermark', '123'), ('pull_cursor', 'x'), ('settings', '{}')")
            execSQL(
                """INSERT INTO outbox (id, type, entity_id, base_version, changed_at, data, status, attempts, seq)
                   VALUES ('o1', 'survey', 'v1', 3, '2026-11-13T10:00:00Z', '{"notes":"unsent"}', 'queued', 0, 1)""",
            )
            close()
        }

        val db = helper.runMigrationsAndValidate(file, 4, true, *emptyArray())

        db.query("SELECT key FROM sync_state").use { c ->
            assertEquals("only the watermark and cursor go", 1, c.count)
            c.moveToFirst()
            assertEquals("settings", c.getString(0))
        }
        db.query("SELECT status FROM outbox WHERE id = 'o1'").use { c ->
            assertEquals(1, c.count)
            c.moveToFirst()
            assertEquals("queued", c.getString(0))
        }
        listOf("families", "family_members", "visits").forEach { t ->
            db.query("SELECT count(*) FROM $t").use { c -> c.moveToFirst(); assertEquals(0, c.getInt(0)) }
        }
        db.close()
    }
}
