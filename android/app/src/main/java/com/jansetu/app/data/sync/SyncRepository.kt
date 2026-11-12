package com.jansetu.app.data.sync

import androidx.room.withTransaction
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.OutboxEntity
import com.jansetu.app.data.local.SyncStateEntity
import com.jansetu.app.data.remote.ApiJson
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.PushItem
import com.jansetu.app.data.remote.PushRequest
import com.jansetu.app.data.remote.SurveyDto
import com.jansetu.app.data.remote.SyncPage
import com.jansetu.app.data.remote.apiCall
import kotlinx.coroutines.sync.Mutex
import kotlinx.serialization.json.jsonObject
import java.time.Instant
import javax.inject.Inject
import javax.inject.Singleton

sealed interface SyncOutcome {
    data object Done : SyncOutcome
    /** The server says this phone is blocked: delete everything (WipeHandler). */
    data object Wipe : SyncOutcome
    /** Stopped part-way (no network, server error). Safe to run again; it resumes. */
    data class Failed(val message: String, val offline: Boolean, val code: String? = null) : SyncOutcome
}

/** Keys in the sync_state table. */
object SyncKeys {
    const val WATERMARK = "watermark"
    const val PULL_CURSOR = "pull_cursor"
    const val PULL_TOTAL = "pull_total"
    const val SETTINGS = "settings"
    const val LAST_SYNC_AT = "last_sync_at"
    const val LAST_ERROR = "last_error"
}

/**
 * Pull and push, as context/sync.md ("What the phone must do") describes.
 * Every page is saved in one transaction together with the cursor that follows it, so the app
 * can be killed at any point and the next run carries on from the last saved page.
 */
@Singleton
class SyncRepository @Inject constructor(
    private val api: JansetuApi,
    private val local: LocalDb,
) {
    private val db get() = local.db

    /** Held by the workers so a periodic sync and "Sync now" never pull at the same time. */
    val lock = Mutex()

    /** Push first, then pull (the pull then brings back what the push saved). */
    suspend fun syncNow(onProgress: suspend (done: Int, total: Int?) -> Unit = { _, _ -> }): SyncOutcome {
        val pushed = push()
        if (pushed != SyncOutcome.Done) return record(pushed)
        return record(pull(onProgress))
    }

    private suspend fun record(o: SyncOutcome): SyncOutcome {
        if (o == SyncOutcome.Wipe) return o
        val state = db.syncState()
        if (o is SyncOutcome.Failed) state.put(SyncStateEntity(SyncKeys.LAST_ERROR, o.message))
        else {
            state.delete(SyncKeys.LAST_ERROR)
            state.put(SyncStateEntity(SyncKeys.LAST_SYNC_AT, Instant.now().toString()))
        }
        return o
    }

    // ---------------------------------------------------------------- pull

    /**
     * First download when no watermark is stored, else a delta pull. Resumes from a saved cursor.
     * Repeats as a first download when the server adds an area the phone does not have yet.
     */
    suspend fun pull(onProgress: suspend (done: Int, total: Int?) -> Unit = { _, _ -> }, pageSize: Int = 1000): SyncOutcome {
        repeat(3) {
            when (val r = pullOnce(onProgress, pageSize)) {
                PullResult.NeedsFirstDownload -> {
                    db.syncState().delete(SyncKeys.WATERMARK)
                    db.syncState().delete(SyncKeys.PULL_CURSOR)
                }
                is PullResult.End -> return r.outcome
            }
        }
        return SyncOutcome.Done
    }

    private sealed interface PullResult {
        data object NeedsFirstDownload : PullResult
        data class End(val outcome: SyncOutcome) : PullResult
    }

    private suspend fun pullOnce(onProgress: suspend (Int, Int?) -> Unit, pageSize: Int): PullResult {
        val state = db.syncState()
        var cursor = state.get(SyncKeys.PULL_CURSOR)
        val since = state.get(SyncKeys.WATERMARK)
        var needsFirstDownload = false

        while (true) {
            val r = apiCall { api.pull(since = if (cursor == null) since else null, cursor = cursor, limit = pageSize) }
            val page = when (r) {
                is ApiResult.Ok -> r.value
                is ApiResult.Offline -> return PullResult.End(SyncOutcome.Failed(OFFLINE, offline = true))
                is ApiResult.Err -> {
                    if (r.code == "device_blocked") return PullResult.End(SyncOutcome.Wipe)
                    if (r.code == "invalid_cursor") { // e.g. after a server update: start the pull again
                        state.delete(SyncKeys.PULL_CURSOR); cursor = null; continue
                    }
                    return PullResult.End(SyncOutcome.Failed(r.message, offline = false, code = r.code))
                }
            }
            if (page.wipe) return PullResult.End(SyncOutcome.Wipe)
            if (save(page, firstDownload = since == null)) needsFirstDownload = true
            onProgress(db.voters().voterCountNow(), state.get(SyncKeys.PULL_TOTAL)?.toIntOrNull())
            cursor = page.nextCursor ?: break
        }
        if (since == null) local.optimizeSearch() // after a first download: thousands of rows at once
        return if (needsFirstDownload) PullResult.NeedsFirstDownload else PullResult.End(SyncOutcome.Done)
    }

    /** Saves one page and the cursor after it, atomically. Returns true when a new area appeared. */
    private suspend fun save(page: SyncPage, firstDownload: Boolean): Boolean = db.withTransaction {
        var newArea = false
        val state = db.syncState()
        val areas = db.areas()

        page.settings?.let { state.put(SyncStateEntity(SyncKeys.SETTINGS, it.toString())) }
        page.lists?.let { l ->
            db.lists().upsertEntries(
                l.castes.map { it.toEntity("caste") } + l.professions.map { it.toEntity("profession") } +
                    l.positions.map { it.toEntity("position") } + l.influencerTypes.map { it.toEntity("influencer_type") },
            )
            db.lists().upsertColorTags(l.colorTags.map { it.toEntity() })
            db.lists().upsertLabels(l.customFieldLabels.map { it.toEntity() })
        }
        page.areaIds?.let { keep ->
            // Page 1: the full list of this phone's areas. Drop the rest and their voters.
            // An id the phone does not have = a new assignment. Its voters have old sync_xid, so a
            // delta cannot bring them: run a first download after this pull.
            if (!firstDownload && (keep.toSet() - areas.ids().toSet()).isNotEmpty()) newArea = true
            areas.upsert(page.areas.map { it.toEntity() })
            areas.deleteOthers(keep)
            db.voters().removeVoters(db.voters().votersOutside(keep))
        } ?: areas.upsert(page.areas.map { it.toEntity() })
        page.totalVoters?.let { state.put(SyncStateEntity(SyncKeys.PULL_TOTAL, it.toString())) }

        val (gone, live) = page.voters.partition { it.deletedAt != null }
        db.voters().savePulledVoters(live.map { it.toEntity() }, gone.map { it.id } + page.goneVoterIds)
        db.voters().savePulledSurveys(page.surveys.map { it.toEntity() })

        if (page.nextCursor != null) {
            state.put(SyncStateEntity(SyncKeys.PULL_CURSOR, page.nextCursor))
        } else {
            state.delete(SyncKeys.PULL_CURSOR)
            state.put(SyncStateEntity(SyncKeys.WATERMARK, page.watermark))
        }
        newArea
    }

    // ---------------------------------------------------------------- push

    /**
     * Sends the outbox in order, at most one item per record per batch (a later edit of the same
     * survey must wait for the earlier one's new version). Network failure: stop; the same items
     * with the same ids go next time.
     */
    suspend fun push(batchSize: Int = 200): SyncOutcome {
        val outbox = db.outbox()
        while (true) {
            val queued = outbox.queued(batchSize * 2)
            if (queued.isEmpty()) return SyncOutcome.Done
            val batch = queued.distinctBy { it.type to it.entityId }.take(batchSize)
            outbox.countAttempt(batch.map { it.id })

            val request = PushRequest(batch.map {
                PushItem(it.id, it.type, it.entityId, it.baseVersion, it.changedAt, ApiJson.parseToJsonElement(it.data).jsonObject)
            })
            val response = when (val r = apiCall { api.push(request) }) {
                is ApiResult.Ok -> r.value
                is ApiResult.Offline -> return SyncOutcome.Failed(OFFLINE, offline = true)
                is ApiResult.Err ->
                    return if (r.code == "device_blocked") SyncOutcome.Wipe
                    else SyncOutcome.Failed(r.message, offline = false, code = r.code)
            }
            val byId = batch.associateBy { it.id }
            db.withTransaction {
                for (result in response.results) {
                    val item = byId[result.id] ?: continue
                    when (result.status) {
                        "applied" -> applied(item, result.survey)
                        "conflict" -> {
                            outbox.mark(item.id, OutboxEntity.STATUS_CONFLICT, "conflict",
                                "Someone else changed this survey first.",
                                result.conflictFields.joinToString(","),
                                result.survey?.let { ApiJson.encodeToString(SurveyDto.serializer(), it) })
                            db.voters().survey(item.entityId)?.let {
                                db.voters().upsertSurvey(it.copy(pending = false, conflict = true))
                            }
                        }
                        else -> { // rejected
                            if (result.error?.code == "not_implemented") continue // server update needed; keep it queued
                            outbox.mark(item.id, OutboxEntity.STATUS_REJECTED, result.error?.code,
                                result.error?.message ?: "Refused by the server.", null, null)
                            db.voters().survey(item.entityId)?.let { db.voters().upsertSurvey(it.copy(pending = stillQueued(item))) }
                        }
                    }
                }
            }
            if (response.results.all { it.status == "rejected" && it.error?.code == "not_implemented" }) {
                return SyncOutcome.Done // only types this server cannot take yet are left; they stay queued
            }
        }
    }

    private suspend fun stillQueued(item: OutboxEntity) =
        db.outbox().queuedFor(item.entityId, item.type) > 0

    private suspend fun applied(item: OutboxEntity, saved: SurveyDto?) {
        val outbox = db.outbox()
        outbox.delete(item.id)
        if (item.type != OutboxEntity.TYPE_SURVEY || saved == null) return
        val more = outbox.queuedFor(item.entityId, item.type) > 0
        if (more) {
            // A later edit is waiting: it now builds on the version the server just gave.
            outbox.rebase(item.entityId, item.type, saved.version)
            db.voters().survey(item.entityId)?.let { db.voters().upsertSurvey(it.copy(version = saved.version)) }
        } else {
            db.voters().saveLocalSurvey(saved.toEntity())
        }
    }

    /** Conflict, "use the server's copy": drop the phone's change. */
    suspend fun discardMine(item: OutboxEntity) = db.withTransaction {
        db.outbox().delete(item.id)
        val server = item.serverCopy?.let { ApiJson.decodeFromString(SurveyDto.serializer(), it) }
        if (server != null) db.voters().saveLocalSurvey(server.toEntity())
        else db.voters().survey(item.entityId)?.let { db.voters().upsertSurvey(it.copy(conflict = false)) }
    }

    /** Conflict, "send mine again": the phone's copy goes on top of the server's version. */
    suspend fun keepMine(item: OutboxEntity) = db.withTransaction {
        val serverVersion = item.serverCopy?.let { ApiJson.decodeFromString(SurveyDto.serializer(), it).version } ?: 0
        db.outbox().delete(item.id)
        db.outbox().insert(item.copy(
            id = java.util.UUID.randomUUID().toString(), baseVersion = serverVersion,
            status = OutboxEntity.STATUS_QUEUED, attempts = 0, errorCode = null, errorMessage = null,
            conflictFields = null, serverCopy = null, seq = System.currentTimeMillis(),
        ))
        db.voters().survey(item.entityId)?.let { db.voters().upsertSurvey(it.copy(conflict = false, pending = true, version = serverVersion)) }
    }

    suspend fun dismiss(item: OutboxEntity) = db.outbox().delete(item.id)

    companion object {
        const val OFFLINE = "No internet. Changes are saved on the phone and will be sent later."
    }
}
