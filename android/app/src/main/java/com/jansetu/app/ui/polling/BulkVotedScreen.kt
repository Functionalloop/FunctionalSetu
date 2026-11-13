package com.jansetu.app.ui.polling

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
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
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.more.MorePage
import com.jansetu.app.ui.search.areaLabel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

const val BULK_VOTED_ROUTE = "markmany/{boothId}"
fun bulkVotedRoute(boothId: String) = "markmany/$boothId"

@HiltViewModel
class BulkVotedViewModel @Inject constructor(
    saved: SavedStateHandle,
    local: LocalDb,
    private val repo: TurnoutRepository,
    private val scheduler: SyncScheduler,
) : ViewModel() {
    private val db = local.db
    val boothId: String = checkNotNull(saved["boothId"])
    /** The part's voters on the current roll, by serial; null until loaded. */
    val part = db.turnout().part(boothId).stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)
    val title = MutableStateFlow("Mark many voted")
    /** After a save: how many were marked (shown until the next change). */
    val done = MutableStateFlow<Int?>(null)

    init {
        viewModelScope.launch { db.areas().area(boothId)?.let { title.value = "Mark many voted · Part ${areaLabel(it)}" } }
    }

    fun mark(voterIds: List<String>, source: String, userId: String, after: () -> Unit) = viewModelScope.launch {
        done.value = repo.markVoted(voterIds, source, userId)
        scheduler.syncNow() // waits for a network; the marks stay on the phone until then
        after()
    }
}

/**
 * Mark many voted (8.3): typed serials and ranges ("12, 15, 18-25"), or ticked from the part's list of voters
 * not marked yet. Voters already marked are left as they are. One `voted` item for the whole batch; offline too.
 */
@Composable
fun BulkVotedScreen(session: Session, onBack: () -> Unit, vm: BulkVotedViewModel = hiltViewModel()) {
    val title by vm.title.collectAsStateWithLifecycle()
    val part by vm.part.collectAsStateWithLifecycle()
    val done by vm.done.collectAsStateWithLifecycle()
    var tickMode by rememberSaveable { mutableStateOf(false) }
    var text by rememberSaveable { mutableStateOf("") }
    var ticked by rememberSaveable { mutableStateOf(listOf<String>()) }

    MorePage(title, onBack) {
        val rows = part ?: return@MorePage
        if (rows.isEmpty()) { EmptyState("No voters of this part on this phone."); return@MorePage }
        Column(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(top = 8.dp)) {
                listOf("Type serials", "Tick in the list").forEachIndexed { i, label ->
                    SegmentedButton(selected = tickMode == (i == 1), onClick = { tickMode = i == 1; vm.done.value = null },
                        shape = SegmentedButtonDefaults.itemShape(i, 2)) { Text(label) }
                }
            }
            done?.let { Text("$it voter(s) marked voted.", color = MaterialTheme.colorScheme.primary) }
            if (!tickMode) {
                val plan = planBulk(text, rows)
                OutlinedTextField(
                    text, { text = it; vm.done.value = null },
                    label = { Text("Serial numbers") }, placeholder = { Text("12, 15, 18-25") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                    isError = plan.error != null, minLines = 2, modifier = Modifier.fillMaxWidth(),
                )
                when {
                    plan.error != null -> Text(plan.error, color = MaterialTheme.colorScheme.error)
                    text.isNotBlank() -> {
                        Text(listOfNotNull(
                            "${plan.toMark.size + plan.already} voters",
                            plan.already.takeIf { it > 0 }?.let { "$it already marked" },
                        ).joinToString(" · "), style = MaterialTheme.typography.titleSmall)
                        if (plan.missing.isNotEmpty()) Text(
                            "Not in this part: ${serialsText(plan.missing)}",
                            color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
                Button(
                    onClick = { vm.mark(plan.toMark.map { it.id }, "bulk_typed", session.user.id) { text = "" } },
                    enabled = plan.error == null && plan.toMark.isNotEmpty(), modifier = Modifier.fillMaxWidth(),
                ) { Text("Mark ${plan.toMark.size} voted") }
                Text("Voters already marked are left as they are.", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                val open = rows.filterNot { it.isVoted }
                val chosen = ticked.toSet()
                Button(
                    onClick = { vm.mark(ticked, "booth_list", session.user.id) { ticked = emptyList() } },
                    enabled = ticked.isNotEmpty(), modifier = Modifier.fillMaxWidth(),
                ) { Text("Mark ${ticked.size} voted") }
                if (open.isEmpty()) EmptyState("Every voter of this part is marked.")
                else LazyColumn(Modifier.weight(1f)) {
                    items(open, key = { it.id }) { r ->
                        Row(
                            Modifier.fillMaxWidth().clickable {
                                ticked = if (r.id in chosen) ticked - r.id else ticked + r.id
                                vm.done.value = null
                            }.padding(vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(r.id in chosen, onCheckedChange = null)
                            Text("${r.serialNo} · ${r.name()}", maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        HorizontalDivider()
                    }
                }
            }
        }
    }
}
