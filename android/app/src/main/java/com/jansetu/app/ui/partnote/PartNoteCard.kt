package com.jansetu.app.ui.partnote

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.PART_NOTE_MAX
import com.jansetu.app.data.PartNoteRepository
import com.jansetu.app.data.SessionStore
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.PartNoteEntity
import com.jansetu.app.data.sync.SyncScheduler
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class PartNoteViewModel @Inject constructor(
    private val local: LocalDb,
    private val repo: PartNoteRepository,
    private val scheduler: SyncScheduler,
    private val store: SessionStore,
) : ViewModel() {
    fun note(boothId: String): Flow<PartNoteEntity?> = local.db.partNotes().flow(boothId)

    fun save(boothId: String, text: String) = viewModelScope.launch {
        repo.save(boothId, text, store.session.value?.user?.id.orEmpty())
        scheduler.syncNow()
    }
}

/** 7.11: the part's shared note, on the walk list and the Survey tab. Works offline; sent with the next sync. */
@Composable
fun PartNoteCard(boothId: String, canEdit: Boolean, modifier: Modifier = Modifier, vm: PartNoteViewModel = hiltViewModel()) {
    val note by remember(boothId) { vm.note(boothId) }.collectAsStateWithLifecycle(null)
    var expanded by rememberSaveable(boothId) { mutableStateOf(false) }
    var editing by rememberSaveable(boothId) { mutableStateOf(false) }
    val text = note?.note.orEmpty()

    Card(
        modifier.fillMaxWidth().clickable { expanded = !expanded },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
    ) {
        Row(Modifier.padding(start = 12.dp, top = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text("Part note", style = MaterialTheme.typography.labelLarge)
                Text(
                    text.ifEmpty { if (canEdit) "No note for this part yet. Tap the pencil to add one." else "No note for this part yet." },
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = if (expanded) Int.MAX_VALUE else 3,
                    overflow = TextOverflow.Ellipsis,
                )
                when {
                    note?.conflict == true -> Text("Someone else changed this note at the same time. See the Sync screen.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                    note?.pending == true -> Text("Not sent to the server yet.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.secondary)
                }
            }
            if (canEdit) IconButton(onClick = { editing = true }) { Icon(Icons.Default.Edit, "Edit the part note") }
        }
    }

    if (editing) {
        var draft by rememberSaveable(boothId) { mutableStateOf(text) }
        AlertDialog(
            onDismissRequest = { editing = false },
            title = { Text("Part note") },
            text = {
                OutlinedTextField(
                    draft, { draft = it.take(PART_NOTE_MAX) }, Modifier.fillMaxWidth(), minLines = 4,
                    supportingText = { Text("Everyone working in this part sees it · ${draft.length} / $PART_NOTE_MAX") },
                )
            },
            confirmButton = {
                TextButton(onClick = { editing = false; vm.save(boothId, draft) }, enabled = draft.trim() != text) { Text("Save") }
            },
            dismissButton = { TextButton(onClick = { editing = false }) { Text("Cancel") } },
        )
    }
}
