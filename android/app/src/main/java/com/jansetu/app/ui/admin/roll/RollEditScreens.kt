package com.jansetu.app.ui.admin.roll

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.Session
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.VoterEntity
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.RemoveRestore
import com.jansetu.app.data.remote.RollPatch
import com.jansetu.app.data.remote.VoterListItem
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.BusyButton
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.displayName
import com.jansetu.app.ui.common.genderLabel
import com.jansetu.app.ui.quality.OnlinePage
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

// --- Correct roll record ----------------------------------------------------------------------------

/**
 * Correct roll record (10.6, super admin; from the voter's Details tab). Starts from this phone's copy and
 * sends only the changed fields with a reason (`PATCH /voters/{id}/roll`); Remove hides the voter
 * (`POST .../remove`). Either way a sync starts, so this phone gets the server's copy.
 */
@HiltViewModel
class RollEditViewModel @Inject constructor(
    handle: SavedStateHandle,
    private val api: JansetuApi,
    private val local: LocalDb,
    private val scheduler: SyncScheduler,
) : ViewModel() {
    private val id: String = checkNotNull(handle["id"])
    var voter by mutableStateOf<VoterEntity?>(null)
        private set
    var original by mutableStateOf(RollRules.RollForm())
        private set
    var form by mutableStateOf(RollRules.RollForm())
    var reason by mutableStateOf("typing_mistake")
    var reference by mutableStateOf("")
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init {
        viewModelScope.launch {
            val v = local.db.voters().voter(id) ?: run { error = "This voter is not on the phone."; return@launch }
            voter = v
            original = RollRules.formOf(v)
            form = original
        }
    }

    fun save(onDone: () -> Unit) {
        val v = voter ?: return
        val check = RollRules.changes(original, form, hasMarathiName = !(v.firstNameMr.isNullOrBlank() && v.lastNameMr.isNullOrBlank()))
        val fields = when (check) {
            is RollRules.Check.Problem -> { error = check.message; return }
            is RollRules.Check.Ok -> check.fields
        }
        viewModelScope.launch {
            busy = true
            val r = apiCall { api.correctVoter(id, RollPatch(fields, reason, RollRules.reference(reference))) }
            busy = false
            when (r) {
                is ApiResult.Ok -> { error = null; scheduler.syncNow(); onDone() }
                else -> error = r.userMessage()
            }
        }
    }

    fun remove(why: String, ref: String, onDone: () -> Unit) = viewModelScope.launch {
        busy = true
        val r = apiCall { api.removeVoter(id, RemoveRestore(why, RollRules.reference(ref))) }
        busy = false
        when (r) {
            is ApiResult.Ok -> { error = null; scheduler.syncNow(); onDone() }
            else -> error = r.userMessage()
        }
    }
}

@Composable
fun RollEditScreen(onBack: () -> Unit, onRemoved: () -> Unit, vm: RollEditViewModel = hiltViewModel()) {
    var removing by remember { mutableStateOf(false) }
    OnlinePage("Correct roll record", onBack, null, vm.busy) {
        val v = vm.voter
        Column(
            Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            ErrorText(vm.error.takeIf { v == null })
            if (v == null) return@Column
            Text("${v.displayName()} · Part ${v.partNo} · Serial ${v.serialNo}", style = MaterialTheme.typography.titleMedium)
            Text("Changes the official roll record. Survey work stays with the voter. Needs internet.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            val f = vm.form
            Field("First name", f.firstName) { vm.form = f.copy(firstName = it) }
            Field("Middle name", f.middleName) { vm.form = f.copy(middleName = it) }
            Field("Last name", f.lastName) { vm.form = f.copy(lastName = it) }
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("father" to "Father", "mother" to "Mother", "husband" to "Husband", "wife" to "Wife", "other" to "Other")
                    .forEach { (code, label) ->
                        FilterChip(f.relationType == code, { vm.form = f.copy(relationType = if (f.relationType == code) null else code) },
                            { Text(label) })
                    }
            }
            Field("Relative's name", f.relativeName) { vm.form = f.copy(relativeName = it) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("M", "F", "O").forEach { g -> FilterChip(f.gender == g, { vm.form = f.copy(gender = g) }, { Text(genderLabel(g)) }) }
            }
            Field("Age", f.age, KeyboardType.Number) { vm.form = f.copy(age = it.filter(Char::isDigit).take(3)) }
            Field("House number", f.houseNo) { vm.form = f.copy(houseNo = it) }
            Field("EPIC", f.epicNo, caps = true) { vm.form = f.copy(epicNo = it.uppercase().take(20)) }
            Field("Serial number in the part", f.serialNo, KeyboardType.Number) { vm.form = f.copy(serialNo = it.filter(Char::isDigit).take(5)) }

            HorizontalDivider()
            Text("Reason", style = MaterialTheme.typography.titleSmall)
            ReasonChips(RollRules.EDIT_REASONS, vm.reason) { vm.reason = it }
            Field("Reference (list number or date)", vm.reference) { vm.reference = it.take(200) }
            ErrorText(vm.error)
            BusyButton("Save correction", busy = vm.busy) { vm.save(onBack) }
            OutlinedButton(onClick = { removing = true }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text("Remove voter (hide)") }
        }
    }

    if (removing) {
        var why by remember { mutableStateOf("duplicate") }
        var ref by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { removing = false },
            title = { Text("Remove this voter?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("The voter is hidden from lists, search and phones. Survey work is kept, and a super admin can " +
                        "restore the voter (More > Matching Engine > Removed voters).")
                    ReasonChips(RollRules.REMOVE_REASONS, why) { why = it }
                    OutlinedTextField(ref, { ref = it.take(200) }, label = { Text("Reference") }, singleLine = true)
                }
            },
            confirmButton = { TextButton(onClick = { removing = false; vm.remove(why, ref, onRemoved) }) { Text("Remove") } },
            dismissButton = { TextButton(onClick = { removing = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun Field(label: String, value: String, type: KeyboardType = KeyboardType.Text, caps: Boolean = false, onChange: (String) -> Unit) {
    OutlinedTextField(
        value, onChange, label = { Text(label) }, singleLine = true, modifier = Modifier.fillMaxWidth(),
        keyboardOptions = KeyboardOptions(
            keyboardType = type,
            capitalization = if (caps) KeyboardCapitalization.Characters else KeyboardCapitalization.Words,
        ),
    )
}

@Composable
private fun ReasonChips(options: List<Pair<String, String>>, selected: String, onPick: (String) -> Unit) {
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        options.forEach { (code, label) -> FilterChip(selected == code, { onPick(code) }, { Text(label) }) }
    }
}

// --- Removed voters -----------------------------------------------------------------------------------

/** Removed voters (10.6): `GET /voters?removed=true` (admins read); a super admin restores one with a reason. */
@HiltViewModel
class RemovedVotersViewModel @Inject constructor(private val api: JansetuApi, private val scheduler: SyncScheduler) : ViewModel() {
    var items by mutableStateOf<List<VoterListItem>>(emptyList())
        private set
    var next by mutableStateOf<String?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var loaded by mutableStateOf(false)
        private set
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init { load() }

    fun load(more: Boolean = false) = viewModelScope.launch {
        val cursor = if (more) next ?: return@launch else null
        loading = true
        val r = apiCall { api.removedVoters(cursor = cursor, limit = 50) }
        loading = false
        when (r) {
            is ApiResult.Ok -> {
                items = if (more) items + r.value.items else r.value.items
                next = r.value.nextCursor
                loaded = true
                error = null
            }
            else -> error = r.userMessage()
        }
    }

    fun restore(v: VoterListItem, why: String, ref: String) = viewModelScope.launch {
        busy = true
        val r = apiCall { api.restoreVoter(v.id, RemoveRestore(why, RollRules.reference(ref))) }
        busy = false
        when (r) {
            is ApiResult.Ok -> { error = null; items = items.filter { it.id != v.id }; scheduler.syncNow() }
            else -> error = r.userMessage()
        }
    }
}

@Composable
fun RemovedVotersScreen(session: Session, onBack: () -> Unit, vm: RemovedVotersViewModel = hiltViewModel()) {
    val superAdmin = session.user.role == "super_admin"
    var restoring by remember { mutableStateOf<VoterListItem?>(null) }
    OnlinePage("Removed voters", onBack, { vm.load() }, vm.loading) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item { ErrorText(vm.error) }
            if (vm.loaded && vm.items.isEmpty()) item { EmptyState("No removed voters.") }
            items(vm.items, key = { it.id }) { v ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(v.fullNameEn ?: v.fullNameMr ?: "(no name)", style = MaterialTheme.typography.titleSmall)
                        Text(listOfNotNull("Part ${v.partNo} · Serial ${v.serialNo}", v.age?.toString(), genderLabel(v.gender),
                            v.houseNo?.let { "House $it" }, v.epicNo?.let { "EPIC $it" }).joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall)
                        if (superAdmin) TextButton(onClick = { restoring = v }, enabled = !vm.busy) { Text("Restore") }
                    }
                }
            }
            if (vm.next != null) item {
                OutlinedButton(onClick = { vm.load(more = true) }, enabled = !vm.loading, modifier = Modifier.fillMaxWidth()) { Text("Show more") }
            }
        }
    }

    restoring?.let { v ->
        var why by remember { mutableStateOf(RollRules.RESTORE_REASONS.first().first) }
        var ref by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { restoring = null },
            title = { Text("Restore this voter?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("The voter comes back to lists, search and phones, with the survey work kept.")
                    ReasonChips(RollRules.RESTORE_REASONS, why) { why = it }
                    OutlinedTextField(ref, { ref = it.take(200) }, label = { Text("Reference") }, singleLine = true)
                }
            },
            confirmButton = { TextButton(onClick = { restoring = null; vm.restore(v, why, ref) }) { Text("Restore") } },
            dismissButton = { TextButton(onClick = { restoring = null }) { Text("Cancel") } },
        )
    }
}
