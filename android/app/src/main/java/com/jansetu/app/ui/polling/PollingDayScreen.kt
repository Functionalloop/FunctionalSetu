package com.jansetu.app.ui.polling

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.HowToVote
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.Session
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.OutboxEntity
import com.jansetu.app.data.local.PartTurnout
import com.jansetu.app.data.local.SyncStateEntity
import com.jansetu.app.data.sync.SyncKeys
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.istTime
import com.jansetu.app.ui.search.AreaPicker
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

private const val POLLING_BOOTH = "polling_booth"

@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class PollingDayViewModel @Inject constructor(local: LocalDb, private val scheduler: SyncScheduler) : ViewModel() {
    private val db = local.db
    val booths = db.areas().byLevel("booth").stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    /** The part picked by hand (remembered on the phone); null = the first part. */
    private val picked = MutableStateFlow<String?>(null)

    init {
        viewModelScope.launch { if (picked.value == null) picked.value = db.syncState().get(POLLING_BOOTH) }
    }

    val booth = combine(booths, picked) { list, id -> list.firstOrNull { it.id == id } ?: list.firstOrNull() }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    val counts = booth.flatMapLatest { b -> if (b == null) flowOf(PartTurnout(0, 0)) else db.turnout().partCounts(b.id) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), PartTurnout(0, 0))

    val hours = booth.flatMapLatest { b -> if (b == null) flowOf(emptyList()) else db.turnout().markTimes(b.id) }
        .map(::byHour).stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val unsent = db.outbox().queuedCountOf(OutboxEntity.TURNOUT_TYPES)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)
    val lastSync = db.syncState().flow(SyncKeys.LAST_SYNC_AT)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    fun pick(boothId: String) {
        picked.value = boothId
        viewModelScope.launch { db.syncState().put(SyncStateEntity(POLLING_BOOTH, boothId)) }
    }

    fun syncNow() = scheduler.syncNow()
}

/**
 * Polling day tab (8.2): a part's turnout from the phone's own data (works offline), by hour, and the
 * marks not sent yet. Counts include other workers' marks up to the last sync.
 */
@Composable
fun PollingDayScreen(session: Session, onMarkVoted: (String) -> Unit, vm: PollingDayViewModel = hiltViewModel()) {
    if (!session.canPoll) {
        EmptyState("Polling day is not part of your role. Booth agents and supervisors mark who has voted.")
        return
    }
    val booths by vm.booths.collectAsStateWithLifecycle()
    val booth by vm.booth.collectAsStateWithLifecycle()
    val counts by vm.counts.collectAsStateWithLifecycle()
    val hours by vm.hours.collectAsStateWithLifecycle()
    val unsent by vm.unsent.collectAsStateWithLifecycle()
    val lastSync by vm.lastSync.collectAsStateWithLifecycle()

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Polling day", style = MaterialTheme.typography.headlineSmall)
        if (booths.size > 1) AreaPicker("Part", booths, booth?.id, allowAll = false) { id -> id?.let(vm::pick) }
        val b = booth
        if (b == null) {
            EmptyState("No part on this phone yet.")
            return@Column
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Stat("Voted", "%,d".format(counts.voted), Modifier.weight(1f))
            Stat("Voters", "%,d".format(counts.voters), Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Stat("Turnout", percent(counts.voted, counts.voters), Modifier.weight(1f))
            Stat("Not sent yet", "%,d".format(unsent), Modifier.weight(1f), warn = unsent > 0)
        }
        if (hours.isNotEmpty()) {
            Text("Marked by hour", style = MaterialTheme.typography.titleSmall)
            val most = hours.maxOf { it.count }
            hours.forEach { h ->
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(h.label, Modifier.width(52.dp), style = MaterialTheme.typography.bodySmall)
                    LinearProgressIndicator(progress = { h.count.toFloat() / most }, modifier = Modifier.weight(1f))
                    Text("${h.count}", Modifier.width(40.dp), style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        Button(onClick = { onMarkVoted(b.id) }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Default.HowToVote, null); Text("  Mark voted")
        }
        if (unsent > 0) {
            Text(
                "$unsent change(s) not sent yet. They go up by themselves when there is internet.",
                color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium,
            )
            OutlinedButton(onClick = vm::syncNow, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Default.Sync, null); Text("  Sync now")
            }
        }
        Text(
            "Includes other workers' marks up to the last sync: " + (istTime(lastSync) ?: "not yet"),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun Stat(label: String, value: String, modifier: Modifier, warn: Boolean = false) {
    val colors = if (warn) CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)
    else CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
    Card(modifier, colors = colors) {
        Column(Modifier.padding(16.dp)) {
            Text(value, style = MaterialTheme.typography.headlineMedium)
            Text(label, style = MaterialTheme.typography.bodyMedium)
        }
    }
}
