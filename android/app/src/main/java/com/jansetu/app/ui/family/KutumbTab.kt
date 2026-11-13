package com.jansetu.app.ui.family

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
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.FieldRepository
import com.jansetu.app.data.KUTUMB_NAME_MAX
import com.jansetu.app.data.local.FamilyEntity
import com.jansetu.app.data.local.FamilyRow
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.MemberOf
import com.jansetu.app.data.local.VoterEntity
import com.jansetu.app.data.local.VoterFilter
import com.jansetu.app.data.local.VoterQuery
import com.jansetu.app.data.local.VoterRow
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.nameEn
import com.jansetu.app.ui.common.nameMr
import com.jansetu.app.ui.search.VoterLine
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

/** One search result of "Add a member", with the Kutumb the voter is in now. */
data class Candidate(val row: VoterRow, val now: MemberOf?)

@OptIn(FlowPreview::class, ExperimentalCoroutinesApi::class)
@HiltViewModel
class KutumbViewModel @Inject constructor(
    handle: SavedStateHandle,
    local: LocalDb,
    private val field: FieldRepository,
    private val scheduler: SyncScheduler,
) : ViewModel() {
    val voterId: String = checkNotNull(handle["id"])
    private val db = local.db

    val family = db.field().familyOf(voterId).stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    val members = family.flatMapLatest { f -> if (f == null) flowOf(emptyList()) else db.field().members(f.id) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun boothFamilies(boothId: String): Flow<List<FamilyRow>> = db.field().boothFamilies(boothId)

    /** "Add a member": search text; results only in the Kutumb's booth (the server refuses another part). */
    val query = MutableStateFlow("")
    private val searchBooth = MutableStateFlow<String?>(null)

    val candidates = searchBooth.flatMapLatest { booth ->
        if (booth == null) flowOf(emptyList())
        else query.debounce(150).flatMapLatest { q -> db.voters().rows(VoterQuery.list(VoterFilter(q = q, boothId = booth), 50)) }
    }.flatMapLatest { rows ->
        // Watches family_members too, so a voter just added shows "In this Kutumb" at once.
        if (rows.isEmpty()) flowOf(emptyList())
        else db.field().memberOf(rows.map { it.id }).map { m ->
            val now = m.associateBy { it.voterId }
            rows.map { Candidate(it, now[it.id]) }
        }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun startSearch(boothId: String) { query.value = ""; searchBooth.value = boothId }
    fun stopSearch() { searchBooth.value = null }

    fun newKutumb(voter: VoterEntity, label: String) = change { field.newKutumb(voter.boothId, voter.wardId, label, listOf(voter.id)) }
    fun putIn(voterId: String, familyId: String) = change { field.putIn(voterId, familyId) }
    fun takeOut(voterId: String) = change { field.takeOut(voterId) }

    /** Calls back with an error text, or null when renamed. */
    fun rename(familyId: String, label: String, done: (String?) -> Unit) = viewModelScope.launch {
        done(field.rename(familyId, label))
    }

    private fun change(block: suspend () -> Unit) = viewModelScope.launch {
        block()
        scheduler.syncNow() // goes up when there is internet; the phone already shows it
    }
}

/**
 * Kutumb Connect tab (7.4, client's name for Family): a Kutumb is made by hand, a free-text name
 * and its members, in one part. No head, nothing from house numbers. Booth agents only read it.
 */
@Composable
fun KutumbTab(
    voter: VoterEntity, canEdit: Boolean, onOpen: (String) -> Unit, onShare: (List<String>) -> Unit,
    vm: KutumbViewModel = hiltViewModel(),
) {
    val family by vm.family.collectAsStateWithLifecycle()
    var adding by rememberSaveable { mutableStateOf(false) }
    val f = family

    when {
        adding && f != null && canEdit -> AddMember(vm, f, onDone = { adding = false; vm.stopSearch() })
        f != null -> KutumbView(vm, voter, f, canEdit, onOpen, onShare, onAdd = { vm.startSearch(f.boothId); adding = true })
        else -> NoKutumb(vm, voter, canEdit)
    }
}

@Composable
private fun KutumbView(
    vm: KutumbViewModel, voter: VoterEntity, f: FamilyEntity, canEdit: Boolean,
    onOpen: (String) -> Unit, onShare: (List<String>) -> Unit, onAdd: () -> Unit,
) {
    val members by vm.members.collectAsStateWithLifecycle()
    var editing by rememberSaveable(f.id) { mutableStateOf(false) }

    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (editing) RenameField(vm, f, onClose = { editing = false })
                else Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Kutumb name", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(f.label ?: "(no name)", style = MaterialTheme.typography.headlineSmall)
                    }
                    if (canEdit) IconButton(onClick = { editing = true }) { Icon(Icons.Default.Edit, "Rename") }
                }
                Text(
                    listOfNotNull("${members.size} member" + (if (members.size == 1) "" else "s"), "Part ${voter.partNo}",
                        "Not sent yet".takeIf { f.pending }).joinToString(" · "),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                // 7.12: slip or message to the members, 5 at a time (a larger Kutumb goes in two rounds)
                if (members.isNotEmpty()) OutlinedButton(onClick = { onShare(members.map { it.id }) }, modifier = Modifier.fillMaxWidth()) {
                    Text("Share on WhatsApp")
                }
            }
            HorizontalDivider()
        }
        items(members, key = { it.id }) { m ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                VoterLine(m, Modifier.weight(1f).clickable(enabled = m.id != voter.id) { onOpen(m.id) })
                if (canEdit) TextButton(onClick = { vm.takeOut(m.id) }) { Text("Remove") }
            }
            HorizontalDivider()
        }
        if (canEdit) item {
            Column(Modifier.padding(16.dp)) {
                OutlinedButton(onClick = onAdd, modifier = Modifier.fillMaxWidth()) { Text("+ Add a member (search)") }
            }
        }
    }
}

@Composable
private fun RenameField(vm: KutumbViewModel, f: FamilyEntity, onClose: () -> Unit) {
    var name by rememberSaveable(f.id) { mutableStateOf(f.label ?: "") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        NameField(name, { name = it; error = null })
        ErrorText(error)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = onClose) { Text("Cancel") }
            Button(enabled = name.isNotBlank() && !busy, onClick = {
                busy = true
                vm.rename(f.id, name) { e -> busy = false; error = e; if (e == null) onClose() }
            }) { Text("Save name") }
        }
    }
}

@Composable
private fun NoKutumb(vm: KutumbViewModel, voter: VoterEntity, canEdit: Boolean) {
    // The surveyor types the name, usually the head of the family's; the voter's own name to start.
    var name by rememberSaveable(voter.id) { mutableStateOf(listOfNotNull(voter.nameEn() ?: voter.nameMr()).joinToString()) }
    var filter by rememberSaveable { mutableStateOf("") }
    val families by remember(voter.boothId) { vm.boothFamilies(voter.boothId) }.collectAsStateWithLifecycle(emptyList())
    val shown = families.filter { filter.isBlank() || (it.label ?: "").contains(filter.trim(), ignoreCase = true) }

    LazyColumn(Modifier.fillMaxSize()) {
        item {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Not in a Kutumb yet.", style = MaterialTheme.typography.titleMedium)
                if (canEdit) {
                    Text("New Kutumb", style = MaterialTheme.typography.titleSmall)
                    NameField(name, { name = it })
                    Button(onClick = { vm.newKutumb(voter, name) }, enabled = name.isNotBlank(), modifier = Modifier.fillMaxWidth()) {
                        Text("Make Kutumb with this voter")
                    }
                    Text("Add to a Kutumb", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 8.dp))
                    if (families.size > 8) OutlinedTextField(
                        value = filter, onValueChange = { filter = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                        placeholder = { Text("Kutumb name") }, leadingIcon = { Icon(Icons.Default.Search, null) },
                    )
                }
            }
        }
        if (canEdit) {
            items(shown, key = { it.id }) { k ->
                Row(
                    Modifier.fillMaxWidth().clickable { vm.putIn(voter.id, k.id) }.padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(k.label ?: "(no name)", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text("${k.members} member" + (if (k.members == 1) "" else "s"), color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                HorizontalDivider()
            }
            if (families.isEmpty()) item { EmptyState("No Kutumb in this part yet.") }
        }
    }
}

@Composable
private fun AddMember(vm: KutumbViewModel, f: FamilyEntity, onDone: () -> Unit) {
    val q by vm.query.collectAsStateWithLifecycle()
    val found by vm.candidates.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.padding(start = 12.dp, end = 4.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = q, onValueChange = { vm.query.value = it }, singleLine = true, modifier = Modifier.weight(1f),
                placeholder = { Text("Name, EPIC, house or serial") },
                leadingIcon = { Icon(Icons.Default.Search, null) },
                trailingIcon = { if (q.isNotEmpty()) IconButton(onClick = { vm.query.value = "" }) { Icon(Icons.Default.Clear, "Clear") } },
            )
            TextButton(onClick = onDone) { Text("Done") }
        }
        Text("Voters of this part. Tap to add to ${f.label ?: "this Kutumb"}.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp))
        LazyColumn(Modifier.fillMaxSize()) {
            items(found, key = { it.row.id }) { c ->
                val here = c.now?.familyId == f.id
                Column(Modifier.clickable(enabled = !here) { vm.putIn(c.row.id, f.id) }) {
                    VoterLine(c.row)
                    val note = when {
                        here -> "In this Kutumb"
                        c.now != null -> "Now in ${c.now.label ?: "another Kutumb"}; tap to move here"
                        else -> null
                    }
                    if (note != null) Text(note, style = MaterialTheme.typography.labelMedium,
                        color = if (here) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.secondary,
                        modifier = Modifier.padding(start = 38.dp, bottom = 8.dp))
                }
                HorizontalDivider()
            }
            if (found.isEmpty()) item { EmptyState("No voter matches.") }
        }
    }
}

@Composable
private fun NameField(value: String, onChange: (String) -> Unit) {
    OutlinedTextField(
        value = value, onValueChange = { onChange(it.take(KUTUMB_NAME_MAX)) }, singleLine = true,
        label = { Text("Kutumb name (typed by the surveyor)") }, modifier = Modifier.fillMaxWidth(),
    )
}
