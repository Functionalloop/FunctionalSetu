package com.jansetu.app.ui.quality

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.MobileImport
import com.jansetu.app.data.remote.MobileImportRow
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.BusyButton
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.displayName
import com.jansetu.app.ui.common.istTime
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import javax.inject.Inject

/** Seconds between looks at a sheet or a roll import that is still being matched. */
const val POLL_MS = 2_000L

// --- the list of sheets ---------------------------------------------------------------------------

/** Mobile numbers & contacts (10.6, admin and super admin): sheets of the team, and Import a sheet. */
@HiltViewModel
class MobileSheetsViewModel @Inject constructor(
    private val api: JansetuApi,
    @ApplicationContext private val context: Context,
) : ViewModel() {
    var items by mutableStateOf<List<MobileImport>>(emptyList())
        private set
    var next by mutableStateOf<String?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var loaded by mutableStateOf(false)
        private set
    var uploading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    fun load(more: Boolean = false) = viewModelScope.launch {
        val cursor = if (more) next ?: return@launch else null
        loading = true
        val r = apiCall { api.mobileImports(cursor, 50) }
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

    fun upload(uri: Uri, onStarted: (String) -> Unit) = viewModelScope.launch {
        uploading = true
        val (file, problem) = SheetFile.read(context, uri)
        if (file == null) { uploading = false; error = problem; return@launch }
        val r = apiCall { api.startMobileImport(file.part()) }
        uploading = false
        when (r) {
            is ApiResult.Ok -> { error = null; items = listOf(r.value) + items; onStarted(r.value.id) }
            else -> error = r.userMessage()
        }
    }
}

@Composable
fun MobileSheetsScreen(onBack: () -> Unit, onOpen: (String) -> Unit, vm: MobileSheetsViewModel = hiltViewModel()) {
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> uri?.let { vm.upload(it, onOpen) } }
    // Load on every visit, so a sheet finished or reviewed meanwhile shows its new counts.
    DisposableEffect(Unit) { vm.load(); onDispose { } }
    OnlinePage("Mobile numbers", onBack, { vm.load() }, vm.loading) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    BusyButton("Import a sheet of numbers", busy = vm.uploading) { pick.launch(SheetFile.PICK_TYPES) }
                    Text(
                        "CSV or Excel with a mobile column, and a name or EPIC column (part, house and address help). " +
                            "Numbers the server is sure of are saved on the voter's survey at once, only where a slot is " +
                            "empty; the rest wait here for you. Phones get them at their next sync.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    ErrorText(vm.error)
                }
            }
            if (vm.loaded && vm.items.isEmpty()) item { EmptyState("No sheets yet.") }
            items(vm.items, key = { it.id }) { m ->
                Card(Modifier.fillMaxWidth().clickable { onOpen(m.id) }) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text("Sheet of ${istTime(m.createdAt) ?: m.createdAt}", style = MaterialTheme.typography.titleSmall)
                        Text(QualityRules.sheetLine(m))
                    }
                }
            }
            if (vm.next != null) item {
                OutlinedButton(onClick = { vm.load(more = true) }, enabled = !vm.loading, modifier = Modifier.fillMaxWidth()) { Text("Show older") }
            }
        }
    }
}

// --- one sheet ------------------------------------------------------------------------------------

/**
 * One sheet (route `mobilesheet/{id}`): counts while the job runs (polled), then the rows that need a
 * person first. A row under review offers its candidate voters (names from this phone's database;
 * an admin's phone holds the whole constituency); Skip leaves the number unused.
 */
@HiltViewModel
class MobileSheetViewModel @Inject constructor(
    handle: SavedStateHandle,
    private val api: JansetuApi,
    private val local: LocalDb,
) : ViewModel() {
    private val id: String = checkNotNull(handle["id"])
    var sheet by mutableStateOf<MobileImport?>(null)
        private set
    var names by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var loading by mutableStateOf(false)
        private set
    var busy by mutableStateOf<Long?>(null)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    private var poller: Job? = null

    fun start() {
        poller?.cancel()
        poller = viewModelScope.launch {
            while (isActive) {
                load()
                if (sheet?.let { QualityRules.isWorking(it) } != true) break
                delay(POLL_MS)
            }
        }
    }

    fun stop() { poller?.cancel() }

    private suspend fun load() {
        loading = true
        val r = apiCall { api.mobileImport(id) }
        loading = false
        when (r) {
            is ApiResult.Ok -> show(r.value)
            else -> error = r.userMessage()
        }
    }

    private suspend fun show(m: MobileImport) {
        sheet = m
        error = null
        val ids = m.rows.flatMap { it.candidateVoterIds + listOfNotNull(it.matchedVoterId) }.distinct() - names.keys
        if (ids.isNotEmpty()) names = names + ids.chunked(500).flatMap { local.db.voters().voters(it) }.associate { v ->
            v.id to listOfNotNull(
                v.displayName(), "Part ${v.partNo} · Serial ${v.serialNo}", v.age?.toString(), v.houseNo?.let { "House $it" },
            ).joinToString(" · ")
        }
    }

    /** voterId null = skip the row. */
    fun resolve(row: MobileImportRow, voterId: String?) = viewModelScope.launch {
        busy = row.id
        val body = buildJsonObject { put("voter_id", voterId) } // the key is sent also when null
        val r = apiCall { api.resolveMobileRow(id, row.id, body) }
        busy = null
        when (r) {
            is ApiResult.Ok -> show(r.value)
            else -> error = r.userMessage()
        }
    }
}

@Composable
fun MobileSheetScreen(onBack: () -> Unit, vm: MobileSheetViewModel = hiltViewModel()) {
    DisposableEffect(Unit) { vm.start(); onDispose { vm.stop() } }
    OnlinePage("Mobile number sheet", onBack, { vm.start() }, vm.loading) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item { ErrorText(vm.error) }
            val m = vm.sheet ?: return@LazyColumn
            item {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text("Sheet of ${istTime(m.createdAt) ?: m.createdAt}", style = MaterialTheme.typography.titleMedium)
                    Text(QualityRules.sheetLine(m))
                    if (m.rows.size >= 500) Text("Showing the first 500 rows; the rest are on the portal.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (m.status == "done" && m.rows.isEmpty()) item { EmptyState("No rows.") }
            items(m.rows, key = { it.id }) { row -> SheetRowCard(row, vm.names, vm.busy) { vm.resolve(row, it) } }
        }
    }
}

@Composable
private fun SheetRowCard(row: MobileImportRow, names: Map<String, String>, busy: Long?, onPick: (String?) -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("${row.name ?: "(no name)"} → ${row.mobile}", style = MaterialTheme.typography.titleSmall)
            listOfNotNull("Row ${row.rowNo}", row.addressText).joinToString(" · ").let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(QualityRules.rowLabel(row.status), fontWeight = FontWeight.Medium,
                color = if (QualityRules.rowOpen(row.status)) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary)
            row.matchedVoterId?.let { Text(names[it] ?: "A voter not on this phone", style = MaterialTheme.typography.bodySmall) }
            if (QualityRules.rowOpen(row.status)) {
                if (row.candidateVoterIds.isNotEmpty()) Text("Is it one of these?", style = MaterialTheme.typography.bodySmall)
                row.candidateVoterIds.forEach { c ->
                    OutlinedButton(onClick = { onPick(c) }, enabled = busy == null, modifier = Modifier.fillMaxWidth()) {
                        Text(names[c] ?: "A voter not on this phone")
                    }
                }
                TextButton(onClick = { onPick(null) }, enabled = busy == null) { Text("Skip this number") }
            }
        }
    }
}
