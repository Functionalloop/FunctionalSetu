package com.jansetu.app.data.sync

import androidx.room.withTransaction
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.OutboxEntity
import com.jansetu.app.data.local.OutboxDao
import com.jansetu.app.data.local.SyncStateEntity
import com.jansetu.app.data.remote.ApiJson
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.ConflictResolution
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.NewVoterDto
import com.jansetu.app.data.remote.PartNoteDto
import com.jansetu.app.data.remote.PushItem
import com.jansetu.app.data.remote.PushRequest
import com.jansetu.app.data.remote.PushResult
import com.jansetu.app.data.remote.SurveyDto
import com.jansetu.app.data.remote.SyncPage
import com.jansetu.app.data.remote.apiCall
import kotlinx.coroutines.sync.Mutex
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
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
        val outcome = record(pull(onProgress))
        if (outcome == SyncOutcome.Done && waitingForServer > 0) {
            // Shown on the Sync and Polling day screens: these changes never go up until the server is updated.
            db.syncState().put(SyncStateEntity(SyncKeys.LAST_ERROR,
                "$waitingForServer change(s) wait on this phone: the server does not take them yet (it needs an update)."))
        }
        return outcome
    }

    /** Items the server answered `not_implemented` in the last push (they stay queued). */
    @Volatile var waitingForServer = 0
        private set

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
                    l.influencerTypes.map { it.toEntity("influencer_type") },
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
            db.field().dropOutside(keep)
            db.newVoters().dropOutside(keep)
            db.partNotes().dropOutside(keep)
        } ?: areas.upsert(page.areas.map { it.toEntity() })
        page.totalVoters?.let { state.put(SyncStateEntity(SyncKeys.PULL_TOTAL, it.toString())) }

        val (gone, live) = page.voters.partition { it.deletedAt != null }
        db.voters().savePulledVoters(live.map { it.toEntity() }, gone.map { it.id } + page.goneVoterIds)
        db.voters().savePulledSurveys(page.surveys.map { it.toEntity() })
        val (goneFamilies, liveFamilies) = page.families.partition { it.deletedAt != null }
        db.field().savePulledFamilies(liveFamilies.mapNotNull { it.toEntity() }, goneFamilies.map { it.id })
        db.field().savePulledMembers(page.familyMembers.map { it.voterId to it.familyId })
        db.field().savePulledVisits(page.visits.map { it.toEntity() })
        db.newVoters().savePulled(page.newVoters.map { it.toEntity() })
        db.partNotes().savePulled(page.partNotes.map { it.toEntity() })
        db.turnout().savePulled(page.turnout.map { it.toEntity() })
        // Marks of voters that left the phone (area dropped, voter removed or gone) go with them.
        if (page.areaIds != null || gone.isNotEmpty() || page.goneVoterIds.isNotEmpty()) db.turnout().dropOrphans()

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
        // Items this server cannot take yet (not_implemented), and their records: skipped for the rest of this
        // run so the items queued after them still go up. A later change of the same record waits behind them.
        val waiting = HashSet<String>()
        val waitingKeys = HashSet<Pair<String, String>>()
        waitingForServer = 0
        while (true) {
            val queued = sendable(outbox, batchSize * 2) { it.id in waiting || (it.type to it.entityId) in waitingKeys }
            if (queued.isEmpty()) return SyncOutcome.Done
            val batch = batchOf(queued, batchSize)
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
                        "applied" -> applied(item, result)
                        "conflict" -> conflicted(item, result)
                        else -> { // rejected
                            if (result.error?.code == "not_implemented") { // server update needed; keep it queued
                                waiting += item.id
                                waitingKeys += item.type to item.entityId
                                continue
                            }
                            outbox.mark(item.id, OutboxEntity.STATUS_REJECTED, result.error?.code,
                                result.error?.message ?: "Refused by the server.", null, null)
                            rejected(item)
                        }
                    }
                }
            }
            waitingForServer = waiting.size
            // A batch item with no answer would come back forever; stop rather than loop.
            if (batch.none { it.id in waiting } && response.results.none { it.id in byId }) return SyncOutcome.Done
        }
    }

    /** The first [want] queued items not [skipped]; reads further down the queue past skipped ones. */
    private suspend fun sendable(outbox: OutboxDao, want: Int, skipped: (OutboxEntity) -> Boolean): List<OutboxEntity> {
        var limit = want
        while (true) {
            val rows = outbox.queued(limit)
            val left = rows.filterNot(skipped)
            if (left.size >= want || rows.size < limit) return left.take(want)
            limit *= 2
        }
    }

    /**
     * At most one item per record per batch (a later edit of the same survey waits for the earlier one's new
     * version). Polling day items must also keep their order across voters' undo and mark again: at a second
     * `unvoted` of one voter the batch ends, so nothing queued after it overtakes it.
     */
    private fun batchOf(queued: List<OutboxEntity>, size: Int): List<OutboxEntity> {
        val batch = mutableListOf<OutboxEntity>()
        val seen = HashSet<Pair<String, String>>()
        for (item in queued) {
            if (!seen.add(item.type to item.entityId)) {
                if (item.type in OutboxEntity.TURNOUT_TYPES) break else continue
            }
            batch += item
            if (batch.size == size) break
        }
        return batch
    }

    private suspend fun stillQueued(item: OutboxEntity) =
        db.outbox().queuedFor(item.entityId, item.type) > 0

    /** The phone's copy no longer waits: the server took it (Kutumb and visit as stored there). */
    private suspend fun applied(item: OutboxEntity, result: PushResult) {
        db.outbox().delete(item.id)
        when (item.type) {
            OutboxEntity.TYPE_SURVEY -> result.survey?.let { appliedSurvey(item, it) }
            OutboxEntity.TYPE_FAMILY_NEW -> result.family?.toEntity()?.let { db.field().upsertFamilies(listOf(it)) }
            OutboxEntity.TYPE_VISIT -> result.visit?.let { db.field().upsertVisits(listOf(it.toEntity())) }
            OutboxEntity.TYPE_NEW_VOTER, OutboxEntity.TYPE_NEW_VOTER_UPDATE -> result.newVoter?.let { appliedNewVoter(item, it) }
            OutboxEntity.TYPE_PART_NOTE -> result.partNote?.let { appliedPartNote(item, it) }
            OutboxEntity.TYPE_VOTED, OutboxEntity.TYPE_UNVOTED -> appliedTurnout(item, result)
            // TYPE_FAMILY: the phone already shows the membership; nothing comes back to keep.
        }
    }

    /**
     * The server refused the item; it stays on the Sync screen. What the phone shows must not claim
     * otherwise: a refused Kutumb or visit is taken off the phone (the server never had it).
     */
    private suspend fun rejected(item: OutboxEntity) {
        when (item.type) {
            OutboxEntity.TYPE_SURVEY ->
                db.voters().survey(item.entityId)?.let { db.voters().upsertSurvey(it.copy(pending = stillQueued(item))) }
            OutboxEntity.TYPE_FAMILY_NEW -> db.field().deleteFamilies(listOf(item.entityId))
            OutboxEntity.TYPE_VISIT -> visitId(item)?.let { db.field().deleteVisit(it) }
            OutboxEntity.TYPE_NEW_VOTER -> db.newVoters().delete(item.entityId)
            OutboxEntity.TYPE_NEW_VOTER_UPDATE -> db.newVoters().get(item.entityId)?.let {
                db.newVoters().upsert(listOf(it.copy(pending = updatesQueued(item.entityId))))
            }
            OutboxEntity.TYPE_PART_NOTE -> db.partNotes().get(item.entityId)?.let {
                db.partNotes().upsert(listOf(it.copy(pending = stillQueued(item))))
            }
            OutboxEntity.TYPE_VOTED, OutboxEntity.TYPE_UNVOTED -> rejectedTurnout(item)
        }
    }

    /** Voters a polling day item names: the mark's voter_ids, or the undone voter. */
    private fun turnoutVoters(item: OutboxEntity): List<String> =
        if (item.type == OutboxEntity.TYPE_UNVOTED) listOf(item.entityId)
        else runCatching {
            ApiJson.parseToJsonElement(item.data).jsonObject["voter_ids"]!!.jsonArray.map { it.jsonPrimitive.content }
        }.getOrDefault(emptyList())

    /**
     * The server's marks of the item's voters replace the phone's, unless a later change of that voter is
     * still queued. A voter the server has no mark for (never marked there) has none on the phone either.
     */
    private suspend fun appliedTurnout(item: OutboxEntity, result: PushResult) {
        val dao = db.turnout()
        val server = result.turnout.associateBy { it.voterId }
        for (voter in turnoutVoters(item)) {
            if (db.outbox().turnoutQueuedFor(voter) > 0) continue
            val mark = server[voter]
            if (mark != null) dao.upsert(listOf(mark.toEntity()))
            else if (dao.get(voter)?.pending == true) dao.delete(listOf(voter))
        }
    }

    /**
     * Refused (e.g. the part left this user): a refused mark was never on the server, so it is taken off the
     * phone; a refused undo leaves the server's mark, so the voter shows as voted again.
     */
    private suspend fun rejectedTurnout(item: OutboxEntity) {
        val dao = db.turnout()
        for (voter in turnoutVoters(item)) {
            if (db.outbox().turnoutQueuedFor(voter) > 0) continue
            val row = dao.get(voter) ?: continue
            if (item.type == OutboxEntity.TYPE_VOTED) { if (row.pending) dao.delete(listOf(voter)) }
            else dao.upsert(listOf(row.copy(isVoted = true, pending = false)))
        }
    }

    /** Someone else saved first: the phone's copy is kept and shown next to the server's (Sync screen). */
    private suspend fun conflicted(item: OutboxEntity, result: PushResult) {
        val fields = result.conflictFields.joinToString(",")
        if (item.type == OutboxEntity.TYPE_PART_NOTE) {
            db.outbox().mark(item.id, OutboxEntity.STATUS_CONFLICT, "conflict", "Someone else changed this part's note first.",
                fields, result.partNote?.let { ApiJson.encodeToString(PartNoteDto.serializer(), it) })
            db.partNotes().get(item.entityId)?.let { db.partNotes().upsert(listOf(it.copy(pending = false, conflict = true))) }
            return
        }
        if (item.type == OutboxEntity.TYPE_NEW_VOTER_UPDATE) {
            db.outbox().mark(item.id, OutboxEntity.STATUS_CONFLICT, "conflict", "Someone else changed this record first.",
                fields, result.newVoter?.let { ApiJson.encodeToString(NewVoterDto.serializer(), it) })
            db.newVoters().get(item.entityId)?.let { db.newVoters().upsert(listOf(it.copy(pending = false, conflict = true))) }
            return
        }
        db.outbox().mark(item.id, OutboxEntity.STATUS_CONFLICT, "conflict", "Someone else changed this survey first.",
            fields, result.survey?.let { ApiJson.encodeToString(SurveyDto.serializer(), it) })
        db.voters().survey(item.entityId)?.let { db.voters().upsertSurvey(it.copy(pending = false, conflict = true)) }
    }

    /** Like a survey: a later edit waiting in the outbox is rebased on the version the server gave. */
    private suspend fun appliedPartNote(item: OutboxEntity, saved: PartNoteDto) {
        val dao = db.partNotes()
        if (stillQueued(item)) {
            db.outbox().rebase(item.entityId, OutboxEntity.TYPE_PART_NOTE, saved.version)
            dao.get(item.entityId)?.let { dao.upsert(listOf(it.copy(version = saved.version))) }
        } else {
            dao.upsert(listOf(saved.toEntity()))
        }
    }

    private suspend fun updatesQueued(id: String) = db.outbox().queuedFor(id, OutboxEntity.TYPE_NEW_VOTER_UPDATE) > 0

    /** Like a survey: a later edit waiting in the outbox is rebased on the version the server gave. */
    private suspend fun appliedNewVoter(item: OutboxEntity, saved: NewVoterDto) {
        val dao = db.newVoters()
        if (updatesQueued(item.entityId)) {
            db.outbox().rebase(item.entityId, OutboxEntity.TYPE_NEW_VOTER_UPDATE, saved.version)
            dao.get(item.entityId)?.let { dao.upsert(listOf(it.copy(version = saved.version))) }
        } else {
            dao.upsert(listOf(saved.toEntity()))
        }
    }

    private fun visitId(item: OutboxEntity): String? =
        runCatching { ApiJson.parseToJsonElement(item.data).jsonObject["id"]?.jsonPrimitive?.content }.getOrNull()

    private suspend fun appliedSurvey(item: OutboxEntity, saved: SurveyDto) {
        val outbox = db.outbox()
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
        if (item.type == OutboxEntity.TYPE_PART_NOTE) {
            val server = item.serverCopy?.let { ApiJson.decodeFromString(PartNoteDto.serializer(), it) }
            if (server != null) db.partNotes().upsert(listOf(server.toEntity()))
            else db.partNotes().get(item.entityId)?.let { db.partNotes().upsert(listOf(it.copy(conflict = false))) }
            return@withTransaction
        }
        if (item.type == OutboxEntity.TYPE_NEW_VOTER_UPDATE) {
            val server = item.serverCopy?.let { ApiJson.decodeFromString(NewVoterDto.serializer(), it) }
            if (server != null) db.newVoters().upsert(listOf(server.toEntity()))
            else db.newVoters().get(item.entityId)?.let { db.newVoters().upsert(listOf(it.copy(conflict = false))) }
            return@withTransaction
        }
        val server = item.serverCopy?.let { ApiJson.decodeFromString(SurveyDto.serializer(), it) }
        if (server != null) db.voters().saveLocalSurvey(server.toEntity())
        else db.voters().survey(item.entityId)?.let { db.voters().upsertSurvey(it.copy(conflict = false)) }
    }

    /**
     * 7.10: decide this phone's conflict on the server (needs internet), then settle the phone.
     * The server's open rows for this record from [userId]'s pushes are all decided the same way;
     * keeping the phone's values writes them on the server, and the next pull brings the new copy.
     * Ok(false) = nothing was open any more (decided by a supervisor): the server's copy is used.
     */
    suspend fun resolve(item: OutboxEntity, userId: String, keepMine: Boolean): ApiResult<Boolean> {
        if (item.type == OutboxEntity.TYPE_PART_NOTE) { // no server rows for notes (7.11): decided here, works offline
            if (keepMine) keepMine(item) else discardMine(item)
            return ApiResult.Ok(keepMine)
        }
        val open = when (val page = apiCall { api.conflicts(entityId = item.entityId, limit = 200) }) {
            is ApiResult.Ok -> page.value.items.filter { it.clientUser.id == userId }
            is ApiResult.Err -> return page
            is ApiResult.Offline -> return page
        }
        val keep = if (keepMine) KEEP_PHONE else KEEP_SERVER
        when (val r = resolveAll(open.map { it.id }) { id -> apiCall { api.resolveConflict(id, ConflictResolution(keep)) } }) {
            is ApiResult.Ok -> Unit
            is ApiResult.Err -> return r
            is ApiResult.Offline -> return r
        }
        val kept = keepMine && open.isNotEmpty()
        if (kept) settleKept(item) else discardMine(item)
        return ApiResult.Ok(kept)
    }

    /** The server now holds the phone's values: drop the item and let the next pull overwrite the local copy. */
    private suspend fun settleKept(item: OutboxEntity) = db.withTransaction {
        db.outbox().delete(item.id)
        if (item.type == OutboxEntity.TYPE_NEW_VOTER_UPDATE) {
            db.newVoters().get(item.entityId)?.let { db.newVoters().upsert(listOf(it.copy(conflict = false, pending = false))) }
        } else {
            db.voters().survey(item.entityId)?.let { db.voters().upsertSurvey(it.copy(conflict = false, pending = false)) }
        }
    }

    /** Conflict, "send mine again" (5.11, phone only): the phone's copy goes on top of the server's version.
     *  The Sync screen decides on the server since 7.10 ([resolve]). */
    suspend fun keepMine(item: OutboxEntity) = db.withTransaction {
        val isNewVoter = item.type == OutboxEntity.TYPE_NEW_VOTER_UPDATE
        val isNote = item.type == OutboxEntity.TYPE_PART_NOTE
        val serverVersion = item.serverCopy?.let {
            when {
                isNewVoter -> ApiJson.decodeFromString(NewVoterDto.serializer(), it).version
                isNote -> ApiJson.decodeFromString(PartNoteDto.serializer(), it).version
                else -> ApiJson.decodeFromString(SurveyDto.serializer(), it).version
            }
        } ?: if (isNewVoter) item.baseVersion else 0
        db.outbox().delete(item.id)
        db.outbox().insert(item.copy(
            id = java.util.UUID.randomUUID().toString(), baseVersion = serverVersion,
            status = OutboxEntity.STATUS_QUEUED, attempts = 0, errorCode = null, errorMessage = null,
            conflictFields = null, serverCopy = null, seq = System.currentTimeMillis(),
        ))
        if (isNote) db.partNotes().get(item.entityId)?.let {
            db.partNotes().upsert(listOf(it.copy(conflict = false, pending = true, version = serverVersion)))
        } else if (isNewVoter) db.newVoters().get(item.entityId)?.let {
            db.newVoters().upsert(listOf(it.copy(conflict = false, pending = true, version = serverVersion)))
        } else db.voters().survey(item.entityId)?.let {
            db.voters().upsertSurvey(it.copy(conflict = false, pending = true, version = serverVersion))
        }
    }

    suspend fun dismiss(item: OutboxEntity) = db.outbox().delete(item.id)

    companion object {
        const val OFFLINE = "No internet. Changes are saved on the phone and will be sent later."
    }
}
