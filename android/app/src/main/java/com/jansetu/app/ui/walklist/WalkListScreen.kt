package com.jansetu.app.ui.walklist

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.AssistChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.FieldRepository
import com.jansetu.app.data.Session
import com.jansetu.app.data.local.HouseRow
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.SyncStateEntity
import com.jansetu.app.data.local.VoterRow
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.partnote.PartNoteCard
import com.jansetu.app.ui.common.istTime
import com.jansetu.app.ui.search.AreaPicker
import com.jansetu.app.ui.search.VoterLine
import com.jansetu.app.ui.search.votersText
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Visit outcomes as the server names them (VisitOutcome), with the words on the buttons. */
val OUTCOMES = listOf("met" to "Met", "not_home" to "Not home", "revisit" to "Come again", "shifted" to "Shifted")

fun outcomeLabel(code: String?) = OUTCOMES.firstOrNull { it.first == code }?.second

private const val WALK_BOOTH = "walk_list_booth"

@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class WalkListViewModel @Inject constructor(
    local: LocalDb,
    private val field: FieldRepository,
    private val scheduler: SyncScheduler,
) : ViewModel() {
    private val db = local.db
    val booths = db.areas().byLevel("booth").stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    /** The part picked by hand (remembered on the phone); null = the first part. */
    private val picked = MutableStateFlow<String?>(null)

    init {
        viewModelScope.launch { if (picked.value == null) picked.value = db.syncState().get(WALK_BOOTH) }
    }

    val booth = combine(booths, picked) { list, id -> list.firstOrNull { it.id == id } ?: list.firstOrNull() }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    val houses = booth.flatMapLatest { b -> if (b == null) flowOf(emptyList()) else db.field().houses(b.id) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    fun pick(boothId: String) {
        picked.value = boothId
        viewModelScope.launch { db.syncState().put(SyncStateEntity(WALK_BOOTH, boothId)) }
    }

    fun voters(boothId: String, house: String?): Flow<List<VoterRow>> = db.field().houseVoters(boothId, house)

    /** A house mark is a visit on the house's first voter in roll order. */
    fun mark(voterId: String, outcome: String, userId: String) = viewModelScope.launch {
        field.markVisit(voterId, outcome, userId)
        scheduler.syncNow()
    }
}

/**
 * Walk list (7.4): a part's voters house by house, from the roll's house numbers (not Kutumbs).
 * A house can be marked met / not home / come again / shifted, offline; the mark syncs as a visit.
 */
@Composable
fun WalkListScreen(session: Session, onOpen: (String) -> Unit, vm: WalkListViewModel = hiltViewModel()) {
    val booths by vm.booths.collectAsStateWithLifecycle()
    val booth by vm.booth.collectAsStateWithLifecycle()
    val houses by vm.houses.collectAsStateWithLifecycle()
    var open by rememberSaveable(booth?.id) { mutableStateOf(setOf<String>()) }

    Column(Modifier.fillMaxSize()) {
        Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Walk list", style = MaterialTheme.typography.headlineSmall)
            if (booths.size > 1) AreaPicker("Part", booths, booth?.id, allowAll = false) { id -> id?.let(vm::pick) }
            houses?.let { h ->
                val visited = h.count { it.lastOutcome != null }
                Text("${h.size} houses · ${votersText(h.sumOf { it.voters })} · $visited visited",
                    style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            booth?.let { PartNoteCard(it.id, canEdit = session.canSurvey) }
        }
        val b = booth
        when {
            b == null -> EmptyState("No part on this phone yet.")
            houses?.isEmpty() == true -> EmptyState("No voters in this part on this phone.")
            else -> LazyColumn(Modifier.fillMaxSize().padding(top = 6.dp)) {
                items(houses.orEmpty(), key = { it.house ?: "\u0000" }) { h ->
                    val key = h.house ?: "\u0000"
                    House(
                        h, expanded = key in open,
                        onToggle = { open = if (key in open) open - key else open + key },
                    ) {
                        HouseVoters(vm, b.id, h, session, onOpen)
                    }
                    HorizontalDivider()
                }
            }
        }
    }
}

@Composable
private fun House(h: HouseRow, expanded: Boolean, onToggle: () -> Unit, content: @Composable () -> Unit) {
    Column {
        Row(
            Modifier.fillMaxWidth().clickable(onClick = onToggle).padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(h.house?.let { "House $it" } ?: "No house number", style = MaterialTheme.typography.titleMedium)
                Text(
                    if (h.voters <= 3 && h.names != null) h.names else listOfNotNull(h.names, "+ ${h.voters - 3}").joinToString(" "),
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
            }
            Column(horizontalAlignment = Alignment.End, modifier = Modifier.padding(horizontal = 8.dp)) {
                outcomeLabel(h.lastOutcome)?.let {
                    Text(it + if (h.lastOutcome == "met") " ✓" else "", fontWeight = FontWeight.Medium, color = outcomeColor(h.lastOutcome))
                    Text(if (h.lastPending == true) "Not sent" else istTime(h.lastVisitAt) ?: "",
                        style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                } ?: Text(votersText(h.voters), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Icon(if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore, if (expanded) "Close" else "Open")
        }
        if (expanded) content()
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun HouseVoters(vm: WalkListViewModel, boothId: String, h: HouseRow, session: Session, onOpen: (String) -> Unit) {
    val voters by remember(boothId, h.house) { vm.voters(boothId, h.house) }.collectAsStateWithLifecycle(emptyList())
    Column(Modifier.padding(start = 8.dp, bottom = 8.dp)) {
        voters.forEach { v -> VoterLine(v, Modifier.clickable { onOpen(v.id) }) }
        val first = voters.firstOrNull()
        // Booth agents do not do door-to-door work (survey roles only, as on the server).
        if (session.canSurvey && first != null && h.house != null) {
            Text("Mark this house", style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(start = 8.dp, top = 4.dp))
            FlowRow(Modifier.padding(horizontal = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OUTCOMES.forEach { (code, label) ->
                    AssistChip(onClick = { vm.mark(first.id, code, session.user.id) }, label = { Text(label) })
                }
            }
        }
    }
}

@Composable
private fun outcomeColor(code: String?): Color = when (code) {
    "met" -> MaterialTheme.colorScheme.primary
    "not_home", "revisit" -> MaterialTheme.colorScheme.secondary
    else -> MaterialTheme.colorScheme.onSurfaceVariant
}
