package com.jansetu.app.ui.admin.roll

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.Session
import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.RollImport
import com.jansetu.app.data.remote.RollImportRow
import com.jansetu.app.data.remote.RowResolution
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.BusyButton
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.displayName
import com.jansetu.app.ui.common.istTime
import com.jansetu.app.ui.quality.OnlinePage
import com.jansetu.app.ui.quality.POLL_MS
import com.jansetu.app.ui.quality.SheetFile
import com.jansetu.app.ui.search.areaLabel
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import javax.inject.Inject

private fun text(s: String) = s.toRequestBody("text/plain".toMediaType())

// --- Matching Engine: imports and upload ----------------------------------------------------------

/**
 * Matching Engine (10.6): compares a new official roll with the current one (`/rolls/imports`).
 * A super admin uploads, decides and applies; an admin opens the imports to read (server: 403 on writes).
 * The results screen with New / Deleted / Changed and the report download are 14.6.
 */
@HiltViewModel
class MatchingViewModel @Inject constructor(
    private val api: JansetuApi,
    local: LocalDb,
    @ApplicationContext private val context: Context,
) : ViewModel() {
    val constituencies = local.db.areas().byLevel("local_body")
    var items by mutableStateOf<List<RollImport>>(emptyList())
        private set
    var next by mutableStateOf<String?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var loaded by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    // upload form (super admin)
    var lbId by mutableStateOf<String?>(null)
    var title by mutableStateOf("")
    var listType by mutableStateOf("main")
    var file by mutableStateOf<SheetFile?>(null)
        private set
    var uploading by mutableStateOf(false)
        private set
    var formError by mutableStateOf<String?>(null)
        private set

    fun load(more: Boolean = false) = viewModelScope.launch {
        val cursor = if (more) next ?: return@launch else null
        loading = true
        val r = apiCall { api.rollImports(cursor, 50) }
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

    fun pickFile(uri: Uri) = viewModelScope.launch {
        val (f, problem) = SheetFile.read(context, uri)
        file = f
        formError = problem
    }

    fun upload(onStarted: (String) -> Unit) = viewModelScope.launch {
        val lb = lbId
        val f = file
        formError = when {
            lb == null -> "Choose the constituency."
            title.isBlank() -> "Give the roll a title, e.g. \"Roll Jan 2027\"."
            f == null -> "Choose the roll file (CSV or Excel)."
            else -> null
        }
        if (formError != null || lb == null || f == null) return@launch
        uploading = true
        val r = apiCall { api.startRollImport(f.part(), text(lb), text(listType), text(title.trim()), null) }
        uploading = false
        when (r) {
            is ApiResult.Ok -> {
                file = null; title = ""; formError = null
                items = listOf(r.value) + items
                onStarted(r.value.id)
            }
            else -> formError = r.userMessage()
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MatchingScreen(
    session: Session, onBack: () -> Unit, onOpen: (String) -> Unit, onRemoved: () -> Unit,
    vm: MatchingViewModel = hiltViewModel(),
) {
    val superAdmin = session.user.role == "super_admin"
    val lbs by vm.constituencies.collectAsStateWithLifecycle(emptyList<AreaEntity>())
    LaunchedEffect(lbs) { if (vm.lbId == null && lbs.size == 1) vm.lbId = lbs.single().id }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> uri?.let { vm.pickFile(it) } }
    var formOpen by remember { mutableStateOf(false) }
    DisposableEffect(Unit) { vm.load(); onDispose { } }

    OnlinePage("Matching Engine", onBack, { vm.load() }, vm.loading) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Compares a new official roll with the current one. Survey data stays with each voter; voters missing " +
                        "from the new roll are marked \"not in current roll\", never erased.",
                        style = MaterialTheme.typography.bodyMedium)
                    if (!superAdmin) Text("You can open the comparisons to read them. Only a super admin uploads, decides and applies.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    ErrorText(vm.error)
                }
            }
            if (superAdmin) item {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (!formOpen) {
                            Button(onClick = { formOpen = true }, modifier = Modifier.fillMaxWidth()) { Text("Upload a new roll (CSV or Excel)") }
                            return@Column
                        }
                        Text("Upload a new roll", style = MaterialTheme.typography.titleMedium)
                        if (lbs.size > 1) {
                            var open by remember { mutableStateOf(false) }
                            ExposedDropdownMenuBox(open, { open = it }) {
                                OutlinedTextField(
                                    value = lbs.firstOrNull { it.id == vm.lbId }?.let { areaLabel(it) } ?: "Choose",
                                    onValueChange = {}, readOnly = true, label = { Text("Constituency") },
                                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
                                    modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
                                )
                                ExposedDropdownMenu(open, { open = false }) {
                                    lbs.forEach { lb -> DropdownMenuItem({ Text(areaLabel(lb)) }, { vm.lbId = lb.id; open = false }) }
                                }
                            }
                        }
                        OutlinedTextField(vm.title, { vm.title = it.take(200) }, label = { Text("Title, e.g. Roll Jan 2027") },
                            singleLine = true, modifier = Modifier.fillMaxWidth())
                        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            RollRules.LIST_TYPES.forEach { (code, label) ->
                                FilterChip(vm.listType == code, { vm.listType = code }, { Text(label) })
                            }
                        }
                        OutlinedButton(onClick = { pick.launch(SheetFile.PICK_TYPES) }, modifier = Modifier.fillMaxWidth()) {
                            Text(vm.file?.name ?: "Choose the roll file")
                        }
                        Text("A supplementary list only adds voters; it marks nobody \"not in current roll\". Scanned PDF rolls come later.",
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        ErrorText(vm.formError)
                        BusyButton("Upload and compare", busy = vm.uploading) { vm.upload(onOpen) }
                        TextButton(onClick = { formOpen = false }) { Text("Cancel") }
                    }
                }
            }
            item { OutlinedButton(onClick = onRemoved, modifier = Modifier.fillMaxWidth()) { Text("Removed voters") } }
            item { Text("Comparisons", style = MaterialTheme.typography.titleMedium) }
            if (vm.loaded && vm.items.isEmpty()) item { EmptyState("No roll has been uploaded yet.") }
            items(vm.items, key = { it.id }) { r ->
                Card(Modifier.fillMaxWidth().clickable { onOpen(r.id) }) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text("${r.title} · ${RollRules.listTypeLabel(r.listType)}", style = MaterialTheme.typography.titleSmall)
                        Text(RollRules.statusLine(r))
                        Text(listOfNotNull(istTime(r.createdAt), r.importedBy?.fullNameEn).joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            if (vm.next != null) item {
                OutlinedButton(onClick = { vm.load(more = true) }, enabled = !vm.loading, modifier = Modifier.fillMaxWidth()) { Text("Show older") }
            }
        }
    }
}

// --- one import: decide, apply, discard ------------------------------------------------------------

/**
 * One comparison (route `rollimport/{id}`): progress (polled while the worker reads the file), counts,
 * and the rows that wait for a decision. Apply is offered only when none wait (server 409 otherwise).
 */
@HiltViewModel
class RollImportViewModel @Inject constructor(
    handle: SavedStateHandle,
    private val api: JansetuApi,
    private val local: LocalDb,
    private val scheduler: SyncScheduler,
) : ViewModel() {
    private val id: String = checkNotNull(handle["id"])
    var import by mutableStateOf<RollImport?>(null)
        private set
    var rows by mutableStateOf<List<RollImportRow>>(emptyList())
        private set
    var next by mutableStateOf<String?>(null)
        private set
    var names by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var loading by mutableStateOf(false)
        private set
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    private var poller: Job? = null

    fun start() {
        poller?.cancel()
        poller = viewModelScope.launch {
            while (isActive) {
                val r = loadImport() ?: break
                if (!RollRules.isWorking(r)) { if (r.status == "review") loadRows(); break }
                delay(POLL_MS)
            }
        }
    }

    fun stop() { poller?.cancel() }

    private suspend fun loadImport(): RollImport? {
        loading = true
        val r = apiCall { api.rollImport(id) }
        loading = false
        return when (r) {
            is ApiResult.Ok -> { import = r.value; error = null; r.value }
            else -> { error = r.userMessage(); null }
        }
    }

    private suspend fun loadRows(more: Boolean = false) {
        val cursor = if (more) next ?: return else null
        loading = true
        val r = apiCall { api.rollImportRows(id, pendingOnly = true, cursor = cursor, limit = 50) }
        loading = false
        when (r) {
            is ApiResult.Ok -> {
                rows = if (more) rows + r.value.items else r.value.items
                next = r.value.nextCursor
                nameVoters(r.value.items.mapNotNull { it.matchedVoterId })
            }
            else -> error = r.userMessage()
        }
    }

    fun more() = viewModelScope.launch { loadRows(more = true) }

    private suspend fun nameVoters(ids: List<String>) {
        val missing = ids.distinct() - names.keys
        if (missing.isEmpty()) return
        names = names + missing.chunked(500).flatMap { local.db.voters().voters(it) }.associate { v ->
            v.id to listOfNotNull(v.displayName(), "Part ${v.partNo} · Serial ${v.serialNo}", v.age?.toString(),
                v.houseNo?.let { "House $it" }, v.epicNo?.let { "EPIC $it" }).joinToString(" · ")
        }
    }

    fun resolve(row: RollImportRow, accept: Boolean) = viewModelScope.launch {
        busy = true
        val r = apiCall { api.resolveRollRow(id, row.id, RowResolution(accept)) }
        busy = false
        when (r) {
            is ApiResult.Ok -> {
                rows = rows.map { if (it.id == row.id) r.value else it }
                loadImport() // the counts (and absent rows) follow every decision
            }
            else -> error = r.userMessage()
        }
    }

    fun apply() = finish { api.applyRollImport(id) }
    fun discard() = finish { api.discardRollImport(id) }

    private fun finish(call: suspend () -> RollImport) = viewModelScope.launch {
        busy = true
        val r = apiCall { call() }
        busy = false
        when (r) {
            is ApiResult.Ok -> {
                import = r.value; rows = emptyList(); next = null; error = null
                if (r.value.status == "applied") scheduler.syncNow() // voters changed: bring them to this phone
            }
            else -> error = r.userMessage()
        }
    }
}

@Composable
fun RollImportScreen(session: Session, onBack: () -> Unit, vm: RollImportViewModel = hiltViewModel()) {
    val superAdmin = session.user.role == "super_admin"
    var confirm by remember { mutableStateOf<String?>(null) } // "apply" or "discard"
    DisposableEffect(Unit) { vm.start(); onDispose { vm.stop() } }

    OnlinePage(vm.import?.title ?: "Comparison", onBack, { vm.start() }, vm.loading) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item { ErrorText(vm.error) }
            val r = vm.import ?: return@LazyColumn
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text("${RollRules.listTypeLabel(r.listType)} · ${RollRules.statusLine(r)}", style = MaterialTheme.typography.titleSmall)
                        RollRules.countLines(r).forEach { (label, n) -> Text("$label: ${"%,d".format(n)}") }
                        r.appliedAt?.let { Text("Applied ${istTime(it)}", style = MaterialTheme.typography.bodySmall) }
                    }
                }
            }
            if (r.status == "review" && superAdmin) item {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    BusyButton("Apply this roll", busy = vm.busy, enabled = RollRules.canApply(r)) { confirm = "apply" }
                    if (!RollRules.canApply(r)) Text("Decide the rows below first.", style = MaterialTheme.typography.bodySmall)
                    OutlinedButton(onClick = { confirm = "discard" }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
                        Text("Discard this comparison")
                    }
                }
            }
            if (r.status == "review") {
                item { Text("Rows waiting for a decision", style = MaterialTheme.typography.titleMedium) }
                if (vm.rows.isEmpty()) item { EmptyState("None: every row is decided.") }
                items(vm.rows, key = { it.id }) { row -> ImportRowCard(row, vm.names, superAdmin && !vm.busy) { vm.resolve(row, it) } }
                if (vm.next != null) item {
                    OutlinedButton(onClick = { vm.more() }, enabled = !vm.loading, modifier = Modifier.fillMaxWidth()) { Text("Show more") }
                }
            }
        }
    }

    confirm?.let { what ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text(if (what == "apply") "Apply this roll?" else "Discard this comparison?") },
            text = {
                Text(if (what == "apply") "The voters are updated from this roll. Surveys stay with their voters; voters not in it are " +
                    "marked \"not in current roll\". It takes a few seconds and cannot be undone here."
                else "The uploaded roll and its decisions are thrown away. The current roll is not changed.")
            },
            confirmButton = {
                TextButton(onClick = { confirm = null; if (what == "apply") vm.apply() else vm.discard() }) {
                    Text(if (what == "apply") "Apply" else "Discard")
                }
            },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun ImportRowCard(row: RollImportRow, names: Map<String, String>, canDecide: Boolean, onDecide: (Boolean) -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(RollRules.matchLabel(row.matchStatus), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
            Text("In the new roll: ${RollRules.rowName(row)}", style = MaterialTheme.typography.titleSmall)
            Text(RollRules.rowLine(row), style = MaterialTheme.typography.bodySmall)
            row.matchedVoterId?.let { Text("On record: ${names[it] ?: "a voter not on this phone"}", style = MaterialTheme.typography.bodyMedium) }
            row.matchNotes?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            RollRules.reviewLabel(row)?.let { Text(it, fontWeight = FontWeight.Medium) }
            val a = RollRules.actions(row)
            if (canDecide && (a.accept != null || a.reject != null)) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                a.accept?.let { Button(onClick = { onDecide(true) }, modifier = Modifier.weight(1f)) { Text(it) } }
                a.reject?.let { OutlinedButton(onClick = { onDecide(false) }, modifier = Modifier.weight(1f)) { Text(it) } }
            }
        }
    }
}
