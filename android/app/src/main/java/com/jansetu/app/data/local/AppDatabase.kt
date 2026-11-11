package com.jansetu.app.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import dagger.hilt.android.qualifiers.ApplicationContext
import net.zetetic.database.sqlcipher.SupportOpenHelperFactory
import javax.inject.Inject
import javax.inject.Singleton

@Database(
    entities = [
        AreaEntity::class, VoterEntity::class, SurveyEntity::class, VoterFts::class,
        ListEntryEntity::class, ColorTagEntity::class, CustomFieldLabelEntity::class,
        OutboxEntity::class, SyncStateEntity::class,
    ],
    version = 1,
    exportSchema = true,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun voters(): VoterDao
    abstract fun areas(): AreaDao
    abstract fun lists(): ListDao
    abstract fun outbox(): OutboxDao
    abstract fun syncState(): SyncStateDao

    companion object {
        const val NAME = "jansetu.db"
    }
}

/**
 * Opens the encrypted database on first use and can delete it (logout of a blocked phone, wipe).
 * Ask for [db] at the time of use instead of keeping a DAO: after [wipe] a new file is opened.
 */
@Singleton
class LocalDb @Inject constructor(
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

    val db: AppDatabase
        get() = instance ?: synchronized(this) { instance ?: open().also { instance = it } }

    private fun open(): AppDatabase {
        System.loadLibrary("sqlcipher")
        val (passphrase, newKey) = key.passphrase()
        // A new key cannot open a file made with a lost one (app data restored, Keystore reset).
        if (newKey) context.deleteDatabase(AppDatabase.NAME)
        return Room.databaseBuilder(context, AppDatabase::class.java, AppDatabase.NAME)
            .openHelperFactory(SupportOpenHelperFactory(passphrase))
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
        meta.edit().clear().commit()
        key.forget()
    }

    /** Merges the search index after a bulk load (first download); later searches are faster. */
    fun optimizeSearch() = db.openHelper.writableDatabase.execSQL("INSERT INTO voter_fts(voter_fts) VALUES('optimize')")

    fun fileExists(): Boolean = context.getDatabasePath(AppDatabase.NAME).exists()
}
