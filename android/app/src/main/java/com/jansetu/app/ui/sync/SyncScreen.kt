package com.jansetu.app.ui.sync

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.work.WorkInfo
import com.jansetu.app.data.SessionStore
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.OutboxEntity
import com.jansetu.app.data.remote.ApiJson
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.Conflict
import com.jansetu.app.data.remote.ConflictResolution
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.data.sync.KEEP_PHONE
import com.jansetu.app.data.sync.KEEP_SERVER
import com.jansetu.app.data.sync.SyncKeys
import com.jansetu.app.data.sync.SyncRepository
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.data.sync.conflictValue
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.search.areaLabel
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.displayName
import com.jansetu.app.ui.common.istTime
import com.jansetu.app.ui.voter.fieldLabel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import javax.inject.Inject

data class SyncInfo(
    val unsent: Int = 0,
    val lastSync: String? = null,
    val lastError: String? = null,
    val running: Boolean = false,
    val waiting: Boolean = false,
)

/** [title]: what the change was about (a voter's survey, a Kutumb, a visit). */
data class Problem(val item: OutboxEntity, val title: String) {
    /** Surveys, Kutumb membership and visits are about one voter, whose screen opens on a tap. */
    val voterId: String? get() = item.entityId.takeIf { item.type !in NOT_A_VOTER }
}

/** A conflict from another worker's phone, for a supervisor or above (7.10). */
data class AreaConflict(val c: Conflict, val title: String, val phone: String, val server: String)

private val NOT_A_VOTER = setOf(
    OutboxEntity.TYPE_FAMILY_NEW, OutboxEntity.TYPE_NEW_VOTER, OutboxEntity.TYPE_NEW_VOTER_UPDATE, OutboxEntity.TYPE_PART_NOTE,
)

/** Roles that review the conflicts of other workers in their area (the server checks again). */
private val REVIEW_ROLES = setOf("supervisor", "admin", "super_admin")

private fun title(item: OutboxEntity, names: Map<String, String>): String {
    val name = names[item.entityId] ?: "Voter"
    return when (item.type) {
        OutboxEntity.TYPE_NEW_VOTER, OutboxEntity.TYPE_NEW_VOTER_UPDATE -> "Eligible but Not Registered: " + (names[item.entityId] ?: "")
        OutboxEntity.TYPE_FAMILY_NEW -> "New Kutumb " + (runCatching {
            ApiJson.parseToJsonElement(item.data).jsonObject["label"]?.jsonPrimitive?.content
        }.getOrNull() ?: "")
        OutboxEntity.TYPE_FAMILY -> "Kutumb Connect: $name"
        OutboxEntity.TYPE_VISIT -> "Visit: $name"
        OutboxEntity.TYPE_SLIP_EVENT -> "Voter slip shared: $name"
        OutboxEntity.TYPE_PART_NOTE -> "Part note: " + (names[item.entityId] ?: "")
        else -> name
    }
}

@HiltViewModel
class SyncViewModel @Inject constructor(
    local: LocalDb,
    private val scheduler: SyncScheduler,
    private val sync: SyncRepository,
    private val api: JansetuApi,
    private val store: SessionStore,
) : ViewModel() {
    private val db = local.db
    private val userId get() = store.session.value?.user?.id.orEmpty()
    val canReview = store.session.value?.user?.role in REVIEW_ROLES

    val info = combine(
        db.outbox().queuedCount(),
        db.syncState().flow(SyncKeys.LAST_SYNC_AT),
        db.syncState().flow(SyncKeys.LAST_ERROR),
        scheduler.syncNowInfo(),
    ) { q, last, err, work ->
        SyncInfo(q, last, err, running = work?.state == WorkInfo.State.RUNNING, waiting = work?.state == WorkInfo.State.ENQUEUED)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), SyncInfo())

    val problems = db.outbox().problems().map { items ->
        val names = db.voters().voters(items.map { it.entityId }).associate { it.id to it.displayName() } +
            items.filter { it.type in NOT_A_VOTER }.mapNotNull { i ->
                db.newVoters().get(i.entityId)?.let { i.entityId to (it.fullNameEn ?: it.fullNameMr ?: "") }
            } +
            db.areas().areas(items.filter { it.type == OutboxEntity.TYPE_PART_NOTE }.map { it.entityId })
                .associate { it.id to areaLabel(it) }
        items.map { Problem(it, title(it, names)) }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    /** Outbox item ids with a server call on its way; message from the last decision. */
    var busy by mutableStateOf<Set<String>>(emptySet())
        private set
    var message by mutableStateOf<String?>(null)
        private set

    fun syncNow() = scheduler.syncNow()
    fun dismiss(p: Problem) = viewModelScope.launch { sync.dismiss(p.item) }

    /** Keep mine / keep the server's, decided on the server (7.10). */
    fun decide(p: Problem, keepMine: Boolean) = viewModelScope.launch {
        busy = busy + p.item.id
        val r = sync.resolve(p.item, userId, keepMine)
        busy = busy - p.item.id
        message = when {
            r is ApiResult.Ok && keepMine && !r.value -> "Already decided by your supervisor. The server's copy is used."
            r is ApiResult.Ok -> null
            r is ApiResult.Offline -> "Deciding a conflict needs internet. Connect and try again."
            else -> r.userMessage()
        }
        if (r is ApiResult.Ok) scheduler.syncNow() // the pull brings the decided copy
        if (canReview) loadArea()
    }

    // --- conflicts of other workers in the area (supervisor and above) ---
    var area by mutableStateOf<List<AreaConflict>>(emptyList())
        private set
    var areaLoading by mutableStateOf(false)
        private set
    var areaLoaded by mutableStateOf(false)
        private set
    var areaError by mutableStateOf<String?>(null)
        private set

    fun loadArea() = viewModelScope.launch {
        if (!canReview || areaLoading) return@launch
        areaLoading = true
        val r = apiCall { api.conflicts(limit = 200) }
        when (r) {
            is ApiResult.Ok -> {
                val others = r.value.items.filter { it.clientUser.id != userId } // own ones are the cards above
                val labels = labels()
                val voters = db.voters().voters(others.map { it.entityId }).associate { it.id to it.displayName() }
                area = others.map { c ->
                    val name = voters[c.entityId] ?: db.newVoters().get(c.entityId)?.let { it.fullNameEn ?: it.fullNameMr }
                    val what = if (c.entityType == "new_voter") "Eligible but Not Registered: " else ""
                    AreaConflict(
                        c, what + (name ?: "Record not on this phone"),
                        conflictValue(c.fieldName, c.clientValue, labels), conflictValue(c.fieldName, c.serverValue, labels),
                    )
                }
                areaError = null
                areaLoaded = true
            }
            is ApiResult.Offline -> areaError = "Conflicts of your team need internet."
            else -> areaError = r.userMessage()
        }
        areaLoading = false
    }

    private suspend fun labels(): Map<String, String> {
        val lists = db.lists()
        val entries = listOf("caste", "profession", "influencer_type").flatMap { lists.entries(it).first() }
        return entries.associate { it.id to (it.nameEn ?: it.nameMr) } + lists.colorTags().first().associate { it.id to it.labelEn }
    }

    fun decideArea(a: AreaConflict, keepPhone: Boolean) = viewModelScope.launch {
        busy = busy + a.c.id
        val r = apiCall { api.resolveConflict(a.c.id, ConflictResolution(if (keepPhone) KEEP_PHONE else KEEP_SERVER)) }
        busy = busy - a.c.id
        message = when {
            r is ApiResult.Ok -> null
            r is ApiResult.Err && r.code == "conflict_resolved" -> null // someone else decided it
            r is ApiResult.Offline -> "Deciding a conflict needs internet. Connect and try again."
            else -> r.userMessage()
        }
        if (r is ApiResult.Ok && keepPhone) scheduler.syncNow()
        loadArea()
    }
}

/** 5.11: status, "Sync now", and every change the server did not take (shown, never dropped silently). 7.10: conflicts. */
@Composable
fun SyncScreen(onOpen: (String) -> Unit, vm: SyncViewModel = hiltViewModel()) {
    val info by vm.info.collectAsStateWithLifecycle()
    val problems by vm.problems.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.loadArea() }

    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Column(Modifier.padding(top = 16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Last sync: " + (istTime(info.lastSync) ?: "not yet"))
                Text(
                    if (info.unsent == 0) "All changes have been sent." else "${info.unsent} change(s) not sent yet.",
                    color = if (info.unsent == 0) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.secondary,
                )
                info.lastError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Text("The app also syncs by itself every 15 minutes when there is internet.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        item {
            Button(onClick = vm::syncNow, enabled = !info.running, modifier = Modifier.fillMaxWidth()) {
                if (info.running) Row { CircularProgressIndicator(Modifier.padding(end = 8.dp), strokeWidth = 2.dp); Text("Syncing…") }
                else Text(if (info.waiting) "Waiting for internet…" else "Sync now")
            }
        }
        vm.message?.let { m -> item { ErrorText(m) } }
        if (problems.isNotEmpty()) item { Text("Needs your attention", style = MaterialTheme.typography.titleMedium) }
        items(problems, key = { it.item.id }) { p -> ProblemCard(p, onOpen, vm) }
        if (problems.isEmpty()) item { EmptyState("No conflicts.") }

        if (vm.canReview) {
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Conflicts in your area", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                    IconButton(onClick = { vm.loadArea() }) { Icon(Icons.Default.Refresh, "Refresh") }
                }
                if (vm.areaLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
                ErrorText(vm.areaError)
            }
            if (vm.areaLoaded && vm.area.isEmpty()) item { EmptyState("No open conflicts from your team.") }
            items(vm.area, key = { it.c.id }) { a -> AreaConflictCard(a, onOpen, vm) }
        }
    }
}

@Composable
private fun ProblemCard(p: Problem, onOpen: (String) -> Unit, vm: SyncViewModel) {
    val conflict = p.item.status == OutboxEntity.STATUS_CONFLICT
    val busy = p.item.id in vm.busy
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
        modifier = Modifier.fillMaxWidth().clickable(enabled = p.voterId != null) { p.voterId?.let(onOpen) },
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(p.title, style = MaterialTheme.typography.titleMedium)
            Text(
                if (conflict) (when (p.item.type) {
                    OutboxEntity.TYPE_NEW_VOTER_UPDATE -> "Record"
                    OutboxEntity.TYPE_PART_NOTE -> "Note"
                    else -> "Survey"
                }) +
                    " changed by someone else first" +
                    (p.item.conflictFields?.takeIf { it.isNotBlank() }?.let { f ->
                        " (" + f.split(",").joinToString(", ") { fieldLabel(it.trim()) } + ")"
                    } ?: "") +
                    (if (p.item.type == OutboxEntity.TYPE_PART_NOTE) ". Choose which copy stays."
                    else ". Choose which copy stays (needs internet).")
                else "Not accepted by the server: ${p.item.errorMessage}",
                style = MaterialTheme.typography.bodyMedium,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                if (conflict) {
                    OutlinedButton(onClick = { vm.decide(p, keepMine = false) }, enabled = !busy) { Text("Keep server's") }
                    Button(onClick = { vm.decide(p, keepMine = true) }, enabled = !busy) { Text("Keep mine") }
                    if (busy) CircularProgressIndicator(Modifier.padding(start = 4.dp), strokeWidth = 2.dp)
                } else {
                    OutlinedButton(onClick = { vm.dismiss(p) }) { Text("Dismiss") }
                }
            }
        }
    }
}

@Composable
private fun AreaConflictCard(a: AreaConflict, onOpen: (String) -> Unit, vm: SyncViewModel) {
    val busy = a.c.id in vm.busy
    Card(
        modifier = Modifier.fillMaxWidth().clickable(enabled = a.c.entityType == "voter_survey") { onOpen(a.c.entityId) },
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(a.title, style = MaterialTheme.typography.titleMedium)
            Text(fieldLabel(a.c.fieldName), style = MaterialTheme.typography.labelLarge)
            Text("Phone of ${a.c.clientUser.fullNameEn}: ${a.phone}", style = MaterialTheme.typography.bodyMedium)
            Text("Server: ${a.server}", style = MaterialTheme.typography.bodyMedium)
            Text(istTime(a.c.clientChangedAt ?: a.c.createdAt) ?: "", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedButton(onClick = { vm.decideArea(a, keepPhone = false) }, enabled = !busy) { Text("Keep server's") }
                Button(onClick = { vm.decideArea(a, keepPhone = true) }, enabled = !busy) { Text("Keep phone's") }
                if (busy) CircularProgressIndicator(Modifier.padding(start = 4.dp), strokeWidth = 2.dp)
            }
        }
    }
}
