package com.jansetu.app.data.local

import android.content.Context
import androidx.room.AutoMigration
import androidx.room.Database
import androidx.room.DeleteColumn
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.AutoMigrationSpec
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import dagger.hilt.android.qualifiers.ApplicationContext
import net.zetetic.database.sqlcipher.SupportOpenHelperFactory
import javax.inject.Inject
import javax.inject.Singleton

@Database(
    entities = [
        AreaEntity::class, VoterEntity::class, SurveyEntity::class, VoterFts::class,
        ListEntryEntity::class, ColorTagEntity::class, CustomFieldLabelEntity::class,
        OutboxEntity::class, SyncStateEntity::class,
        FamilyEntity::class, FamilyMemberEntity::class, VisitEntity::class, NewVoterEntity::class,
        PartNoteEntity::class, TurnoutEntity::class,
    ],
    version = 7,
    exportSchema = true,
    autoMigrations = [
        AutoMigration(from = 2, to = 3, spec = Migration2To3::class),
        AutoMigration(from = 3, to = 4, spec = Migration3To4::class),
        AutoMigration(from = 4, to = 5, spec = Migration4To5::class),
        AutoMigration(from = 5, to = 6, spec = Migration5To6::class),
        AutoMigration(from = 6, to = 7, spec = Migration6To7::class),
    ],
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun voters(): VoterDao
    abstract fun areas(): AreaDao
    abstract fun lists(): ListDao
    abstract fun outbox(): OutboxDao
    abstract fun syncState(): SyncStateDao
    abstract fun field(): FieldDao
    abstract fun newVoters(): NewVoterDao
    abstract fun partNotes(): PartNoteDao
    abstract fun turnout(): TurnoutDao

    companion object {
        const val NAME = "jansetu.db"
    }
}

/**
 * Version 3 (7.13, client approved the app flow 13 Nov): no Important voter field and no positions list.
 * Room rebuilds `surveys` without the two columns, keeping every row (pending and conflict flags too).
 * Unsent outbox items were stored as JSON with `is_important` / `position_id`, which the server now
 * refuses (and a refused item is dropped): the keys are taken out here so those surveys still go up.
 */
@DeleteColumn.Entries(
    DeleteColumn(tableName = "surveys", columnName = "is_important"),
    DeleteColumn(tableName = "surveys", columnName = "position_id"),
)
class Migration2To3 : AutoMigrationSpec {
    override fun onPostMigrate(db: SupportSQLiteDatabase) {
        db.execSQL("DELETE FROM list_entries WHERE kind = 'position'")
        val fixed = mutableListOf<Pair<String, String>>()
        db.query("SELECT id, data FROM outbox WHERE type = 'survey'").use { c ->
            while (c.moveToNext()) {
                val data = Json.parseToJsonElement(c.getString(1)).jsonObject
                if (REMOVED.any { it in data }) fixed += c.getString(0) to JsonObject(data - REMOVED).toString()
            }
        }
        fixed.forEach { (id, data) -> db.execSQL("UPDATE outbox SET data = ? WHERE id = ?", arrayOf(data, id)) }
    }

    companion object {
        val REMOVED = setOf("is_important", "position_id")
    }
}

/**
 * Version 4 (7.4): Kutumbs, their members and visits. Room adds the three tables. Kutumbs and visits
 * made before this version came in pull pages the phone did not store (old sync_xid), so a delta pull
 * would never bring them: the watermark is dropped and the next pull is a full download. It keeps
 * every local change (pending surveys are not overwritten, the outbox is untouched).
 */
class Migration3To4 : AutoMigrationSpec {
    override fun onPostMigrate(db: SupportSQLiteDatabase) {
        db.execSQL("DELETE FROM sync_state WHERE key IN ('watermark', 'pull_cursor')")
    }
}

/**
 * Version 5 (7.5): Eligible but Not Registered (`new_voters`). Same reason as 3 -> 4 for a full download:
 * records made before the update came in pull pages this phone did not store.
 */
class Migration4To5 : AutoMigrationSpec {
    override fun onPostMigrate(db: SupportSQLiteDatabase) {
        db.execSQL("DELETE FROM sync_state WHERE key IN ('watermark', 'pull_cursor')")
    }
}

/**
 * Version 6 (7.11): part notes (`part_notes`). Same reason as 3 -> 4 for a full download: notes saved
 * before the update came in pull pages this phone did not store.
 */
class Migration5To6 : AutoMigrationSpec {
    override fun onPostMigrate(db: SupportSQLiteDatabase) {
        db.execSQL("DELETE FROM sync_state WHERE key IN ('watermark', 'pull_cursor')")
    }
}

/**
 * Version 7 (8.2): voted marks (`turnout`). Same reason as 3 -> 4 for a full download: marks made before
 * the update came in pull pages this phone did not store.
 */
class Migration6To7 : AutoMigrationSpec {
    override fun onPostMigrate(db: SupportSQLiteDatabase) {
        db.execSQL("DELETE FROM sync_state WHERE key IN ('watermark', 'pull_cursor')")
    }
}

/**
 * Opens the encrypted database on first use and can delete it (logout of a blocked phone, wipe).
 * Ask for [db] at the time of use instead of keeping a DAO: after [wipe] a new file is opened.
 */
@Singleton
open class LocalDb @Inject constructor(
    @ApplicationContext private val context: Context,
    private val key: DbKey,
) {
    @Volatile private var instance: AppDatabase? = null

    // Facts about the file itself; deleted together with it.
    private val meta = context.getSharedPreferences("jansetu_db_meta", Context.MODE_PRIVATE)

    /** User ID whose area this file holds (null = empty or unknown). */
    fun owner(): String? = meta.getString("owner", null)
    fun setOwner(userId: String) { meta.edit().putString("owner", userId).commit() }
    fun firstSyncDone(): Boolean = meta.getBoolean("first_sync_done", false)
    fun setFirstSyncDone(done: Boolean = true) { meta.edit().putBoolean("first_sync_done", done).commit() }

    // Open so a test can hand in an in-memory database and never touch the app's own file.
    open val db: AppDatabase
        get() = instance ?: synchronized(this) { instance ?: open().also { instance = it } }

    private fun open(): AppDatabase {
        System.loadLibrary("sqlcipher")
        val (passphrase, newKey) = key.passphrase()
        // A new key cannot open a file made with a lost one (app data restored, Keystore reset).
        if (newKey) context.deleteDatabase(AppDatabase.NAME)
        return Room.databaseBuilder(context, AppDatabase::class.java, AppDatabase.NAME)
            .openHelperFactory(SupportOpenHelperFactory(passphrase))
            // Version 2 (12 Nov, client's survey fields): no phone held real data on version 1, so its
            // file is dropped and downloaded again. From version 2 on, real migrations only (2 -> 3 -> ... -> 7 above):
            // a destructive one would delete unsent changes.
            .fallbackToDestructiveMigrationFrom(1)
            .addCallback(object : RoomDatabase.Callback() {
                // Every page read is decrypted; a bigger cache keeps search pages decrypted while typing.
                override fun onOpen(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                    db.query("PRAGMA cache_size = -20000").close()
                }
            })
            .build()
    }

    /** Closes and deletes the database file and forgets its key. */
    fun wipe() = synchronized(this) {
        instance?.close()
        instance = null
        context.deleteDatabase(AppDatabase.NAME)
        com.jansetu.app.ui.slip.deleteSlipFiles(context) // the last slip image shows a voter's name
        com.jansetu.app.ui.reports.deleteExportFiles(context) // so does the last Excel or PDF export (11.3)
        meta.edit().clear().commit()
        key.forget()
    }

    /** Merges the search index after a bulk load (first download); later searches are faster. */
    fun optimizeSearch() = db.openHelper.writableDatabase.execSQL("INSERT INTO voter_fts(voter_fts) VALUES('optimize')")

    fun fileExists(): Boolean = context.getDatabasePath(AppDatabase.NAME).exists()
}
