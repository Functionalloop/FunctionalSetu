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
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.work.WorkInfo
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.OutboxEntity
import com.jansetu.app.data.remote.ApiJson
import com.jansetu.app.data.sync.SyncKeys
import com.jansetu.app.data.sync.SyncRepository
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.displayName
import com.jansetu.app.ui.common.istTime
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.combine
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
    /** Every type but a new Kutumb is about one voter, whose screen opens on a tap. */
    val voterId: String? get() = item.entityId.takeIf { item.type != OutboxEntity.TYPE_FAMILY_NEW }
}

private fun title(item: OutboxEntity, names: Map<String, String>): String {
    val name = names[item.entityId] ?: "Voter"
    return when (item.type) {
        OutboxEntity.TYPE_FAMILY_NEW -> "New Kutumb " + (runCatching {
            ApiJson.parseToJsonElement(item.data).jsonObject["label"]?.jsonPrimitive?.content
        }.getOrNull() ?: "")
        OutboxEntity.TYPE_FAMILY -> "Kutumb Connect: $name"
        OutboxEntity.TYPE_VISIT -> "Visit: $name"
        else -> name
    }
}

@HiltViewModel
class SyncViewModel @Inject constructor(
    local: LocalDb,
    private val scheduler: SyncScheduler,
    private val sync: SyncRepository,
) : ViewModel() {
    private val db = local.db

    val info = combine(
        db.outbox().queuedCount(),
        db.syncState().flow(SyncKeys.LAST_SYNC_AT),
        db.syncState().flow(SyncKeys.LAST_ERROR),
        scheduler.syncNowInfo(),
    ) { q, last, err, work ->
        SyncInfo(q, last, err, running = work?.state == WorkInfo.State.RUNNING, waiting = work?.state == WorkInfo.State.ENQUEUED)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), SyncInfo())

    val problems = db.outbox().problems().map { items ->
        val names = db.voters().voters(items.map { it.entityId }).associate { it.id to it.displayName() }
        items.map { Problem(it, title(it, names)) }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun syncNow() = scheduler.syncNow()
    fun useServer(p: Problem) = viewModelScope.launch { sync.discardMine(p.item) }
    fun keepMine(p: Problem) = viewModelScope.launch { sync.keepMine(p.item); scheduler.syncNow() }
    fun dismiss(p: Problem) = viewModelScope.launch { sync.dismiss(p.item) }
}

/** 5.11: status, "Sync now", and every change the server did not take (shown, never dropped silently). */
@Composable
fun SyncScreen(onOpen: (String) -> Unit, vm: SyncViewModel = hiltViewModel()) {
    val info by vm.info.collectAsStateWithLifecycle()
    val problems by vm.problems.collectAsStateWithLifecycle()

    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Column(Modifier.padding(top = 16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Sync", style = MaterialTheme.typography.headlineSmall)
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
        if (problems.isNotEmpty()) item { Text("Needs your attention", style = MaterialTheme.typography.titleMedium) }
        items(problems, key = { it.item.id }) { p -> ProblemCard(p, onOpen, vm) }
        if (problems.isEmpty()) item { EmptyState("No conflicts.") }
    }
}

@Composable
private fun ProblemCard(p: Problem, onOpen: (String) -> Unit, vm: SyncViewModel) {
    val conflict = p.item.status == OutboxEntity.STATUS_CONFLICT
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
        modifier = Modifier.fillMaxWidth().clickable(enabled = p.voterId != null) { p.voterId?.let(onOpen) },
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(p.title, style = MaterialTheme.typography.titleMedium)
            Text(
                if (conflict) "Survey changed by someone else first" +
                    (p.item.conflictFields?.takeIf { it.isNotBlank() }?.let { " (${it.replace(",", ", ")})" } ?: "") +
                    ". The server kept both; choose which copy stays."
                else "Not accepted by the server: ${p.item.errorMessage}",
                style = MaterialTheme.typography.bodyMedium,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (conflict) {
                    OutlinedButton(onClick = { vm.useServer(p) }) { Text("Use server copy") }
                    Button(onClick = { vm.keepMine(p) }) { Text("Send mine again") }
                } else {
                    OutlinedButton(onClick = { vm.dismiss(p) }) { Text("Dismiss") }
                }
            }
        }
    }
}
