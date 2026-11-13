package com.jansetu.app.ui.polling

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.Session
import com.jansetu.app.data.TurnoutRepository
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.MarkRow
import com.jansetu.app.data.local.OutboxEntity
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.more.MorePage
import com.jansetu.app.ui.search.areaLabel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

const val MARK_VOTED_ROUTE = "markvoted/{boothId}"
fun markVotedRoute(boothId: String) = "markvoted/$boothId"

@HiltViewModel
class MarkVotedViewModel @Inject constructor(
    saved: SavedStateHandle,
    local: LocalDb,
    private val repo: TurnoutRepository,
    private val scheduler: SyncScheduler,
) : ViewModel() {
    private val db = local.db
    val boothId: String = checkNotNull(saved["boothId"])
    val query = MutableStateFlow("")

    /** null until the part is loaded. */
    val rows = combine(db.turnout().part(boothId), query) { all, q -> filterPart(all, q) to all.size }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)
    val unsent = db.outbox().queuedCountOf(OutboxEntity.TURNOUT_TYPES)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)
    val title = MutableStateFlow("Mark voted")

    init {
        viewModelScope.launch { db.areas().area(boothId)?.let { title.value = "Mark voted · Part ${areaLabel(it)}" } }
    }

    fun mark(voterId: String, userId: String) = viewModelScope.launch {
        repo.markVoted(listOf(voterId), "single", userId)
        scheduler.syncNow() // waits for a network; marks stay on the phone until then
    }

    fun undo(voterId: String, userId: String) = viewModelScope.launch {
        repo.undo(voterId, userId)
        scheduler.syncNow()
    }
}

/** Mark voted (8.2): a part's voters by serial; tap Mark. Works offline; an undo asks first. */
@Composable
fun MarkVotedScreen(session: Session, onBack: () -> Unit, vm: MarkVotedViewModel = hiltViewModel()) {
    val title by vm.title.collectAsStateWithLifecycle()
    val query by vm.query.collectAsStateWithLifecycle()
    val rows by vm.rows.collectAsStateWithLifecycle()
    val unsent by vm.unsent.collectAsStateWithLifecycle()
    var undo by rememberSaveable { mutableStateOf<String?>(null) }

    MorePage(title, onBack) {
        Column(Modifier.fillMaxSize()) {
            OutlinedTextField(
                query, { vm.query.value = it },
                label = { Text("Serial number or name") }, singleLine = true,
                leadingIcon = { Icon(Icons.Default.Search, null) },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            )
            if (unsent > 0) Text(
                "$unsent change(s) not sent yet", color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(horizontal = 16.dp),
            )
            val (shown, total) = rows ?: return@Column
            when {
                total == 0 -> EmptyState("No voters of this part on this phone.")
                shown.isEmpty() -> EmptyState("No voter matches \"$query\".")
                else -> LazyColumn(Modifier.weight(1f)) {
                    items(shown, key = { it.id }) { r ->
                        MarkLine(r, onMark = { vm.mark(r.id, session.user.id) }, onUndo = { undo = r.id })
                        HorizontalDivider()
                    }
                }
            }
        }
    }

    val target = undo?.let { id -> rows?.first?.firstOrNull { it.id == id } }
    if (undo != null) AlertDialog(
        onDismissRequest = { undo = null },
        title = { Text("Undo voted mark?") },
        text = { Text(target?.let { "${it.serialNo} · ${it.name()} will show as not voted." } ?: "This voter will show as not voted.") },
        confirmButton = { TextButton(onClick = { undo?.let { vm.undo(it, session.user.id) }; undo = null }) { Text("Undo mark") } },
        dismissButton = { TextButton(onClick = { undo = null }) { Text("Cancel") } },
    )
}

@Composable
private fun MarkLine(r: MarkRow, onMark: () -> Unit, onUndo: () -> Unit) {
    Row(
        Modifier.fillMaxWidth()
            .then(if (r.isVoted) Modifier.clickable(onClick = onUndo) else Modifier)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("${r.serialNo} · ${r.name()}", Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis,
            style = MaterialTheme.typography.bodyLarge)
        if (r.isVoted) {
            Column(horizontalAlignment = Alignment.End, modifier = Modifier.padding(start = 8.dp)) {
                Text("Voted ✓", fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.primary)
                if (r.pending) Text("Not sent", style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        } else {
            FilledTonalButton(onClick = onMark, modifier = Modifier.padding(start = 8.dp)) { Text("Mark") }
        }
    }
}
