package com.jansetu.app.ui.reports

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.remote.ApiJson
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.ExportIn
import com.jansetu.app.data.remote.ExportJob
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.parseError
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.BusyButton
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.quality.OnlinePage
import com.jansetu.app.ui.quality.POLL_MS
import com.jansetu.app.ui.reports.ReportRules.Report
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import java.io.File
import java.io.IOException
import javax.inject.Inject

const val EXPORT_ROUTE = "export?kind={kind}&report={report}&filter={filter}&search={search}"

/** kind = voter_list, mobile_list, report or turnout; filter = the export's `filter`; search = it came from Search. */
fun exportRoute(kind: String, report: String? = null, filter: JsonObject = JsonObject(emptyMap()), search: Boolean = false) =
    "export?kind=$kind&report=${report.orEmpty()}&filter=${Uri.encode(filter.toString())}&search=$search"

/** Made files sit in the app's cache (shared through the FileProvider) until the next file or a wipe. */
private const val EXPORT_DIR = "exports"

/** Called by LocalDb.wipe: an export holds voter names. */
fun deleteExportFiles(context: Context) {
    File(context.cacheDir, EXPORT_DIR).deleteRecursively()
}

/**
 * Print or export a list (11.3): Excel or PDF made by the server (`POST /exports`, polled every 2 s), downloaded into
 * the cache, then opened, shared or saved to the phone. Voter lists take the Search filters (or a Village Panchayat
 * and part); report files take the report's area.
 */
@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class ExportViewModel @Inject constructor(
    handle: SavedStateHandle,
    private val api: JansetuApi,
    local: LocalDb,
    @ApplicationContext private val context: Context,
) : ViewModel() {
    private val startKind: String = handle["kind"] ?: ReportRules.VOTER_LIST
    val report: Report? = Report.of(handle.get<String>("report")?.ifEmpty { null }) ?: if (startKind == "turnout") Report.TURNOUT else null
    val fromSearch: Boolean = handle["search"] ?: false
    private val baseFilter: JsonObject = handle.get<String>("filter")?.takeIf { it.isNotBlank() }
        ?.let { runCatching { ApiJson.decodeFromString<JsonObject>(it) }.getOrNull() } ?: JsonObject(emptyMap())

    val voterKind = startKind in ReportRules.VOTER_KINDS
    var kind by mutableStateOf(startKind)
        private set
    var format by mutableStateOf("pdf")
    var language by mutableStateOf("mr")
    var columns by mutableStateOf(ReportRules.defaultColumns(startKind).toSet())
        private set
    var groupByHouse by mutableStateOf(false)
    var paper by mutableStateOf("a4")
    var textSize by mutableStateOf("normal")
    var header by mutableStateOf("")

    // Village Panchayat and part, for a voter list opened from the Reports menu (Search brings its own filter).
    private val ward = MutableStateFlow<String?>(null)
    val wards = local.db.areas().byLevel("ward")
    val booths = ward.flatMapLatest { w -> if (w == null) local.db.areas().byLevel("booth") else local.db.areas().children(w) }
    var wardId by mutableStateOf<String?>(null)
        private set
    var boothId by mutableStateOf<String?>(null)
        private set

    var job by mutableStateOf<ExportJob?>(null)
        private set
    var file by mutableStateOf<File?>(null)
        private set
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    private var poller: Job? = null

    val summary: String get() = ReportRules.searchSummary(baseFilter)

    fun pickKind(k: String) { if (k != kind) { kind = k; columns = ReportRules.defaultColumns(k).toSet(); changed() } }
    fun toggle(column: String) { columns = if (column in columns) columns - column else columns + column; changed() }
    fun pickWard(id: String?) { wardId = id; boothId = null; ward.value = id; changed() }
    fun pickBooth(id: String?) { boothId = id; changed() }

    /** Any change after a file was made: the next tap makes a new file. */
    fun changed() { if (job != null && poller?.isActive != true) { job = null; file = null } }

    private fun request(): ExportIn {
        val filter = if (voterKind && !fromSearch) ReportRules.withArea(baseFilter, wardId, boothId) else baseFilter
        return ExportIn(
            kind = kind, format = format, language = language, filter = filter,
            columns = if (voterKind) ReportRules.ordered(columns) else emptyList(),
            options = ReportRules.options(report?.exportReport, format == "pdf", paper, textSize, groupByHouse, header, voterKind),
        )
    }

    fun make() {
        if (voterKind && columns.isEmpty()) { error = "Tick at least one column."; return }
        poller?.cancel()
        file = null
        poller = viewModelScope.launch {
            busy = true
            error = null
            val started = apiCall { api.startExport(request()) }
            if (started !is ApiResult.Ok) { busy = false; error = started.userMessage(); return@launch }
            job = started.value
            while (isActive && job?.let { ReportRules.isWorking(it) } == true) {
                delay(POLL_MS)
                when (val r = apiCall { api.exportJob(started.value.id) }) {
                    is ApiResult.Ok -> { job = r.value; error = null }
                    is ApiResult.Offline -> error = r.userMessage() // keep looking: the file is made on the server anyway
                    else -> { error = r.userMessage(); busy = false; return@launch }
                }
            }
            if (job?.status == "done") download(started.value)
            busy = false
        }
    }

    /** Looks again after a lost connection (the server kept working). */
    fun retry() {
        val j = job ?: return make()
        poller?.cancel()
        poller = viewModelScope.launch {
            busy = true
            error = null
            while (isActive) {
                when (val r = apiCall { api.exportJob(j.id) }) {
                    is ApiResult.Ok -> job = r.value
                    else -> { error = r.userMessage(); break }
                }
                if (job?.let { ReportRules.isWorking(it) } != true) break
                delay(POLL_MS)
            }
            if (job?.status == "done" && error == null) download(j)
            busy = false
        }
    }

    private suspend fun download(j: ExportJob) {
        try {
            val r = api.downloadExport(j.id)
            val body = r.body()
            if (!r.isSuccessful || body == null) { error = parseError(r.code(), r.errorBody()?.string()).message; return }
            val name = ReportRules.fileName(r.headers()["Content-Disposition"], j.format)
            file = withContext(Dispatchers.IO) {
                val dir = File(context.cacheDir, EXPORT_DIR)
                dir.deleteRecursively() // keep only the newest file
                dir.mkdirs()
                File(dir, name).also { f -> body.use { b -> f.outputStream().use { b.byteStream().copyTo(it) } } }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: IOException) {
            error = "The file could not be downloaded. Check the internet and tap Try again."
        }
    }

    suspend fun saveTo(uri: Uri): Boolean = withContext(Dispatchers.IO) {
        val f = file ?: return@withContext false
        runCatching {
            context.contentResolver.openOutputStream(uri)?.use { out -> f.inputStream().use { it.copyTo(out) } } != null
        }.getOrDefault(false)
    }

    override fun onCleared() { poller?.cancel() }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ExportScreen(onBack: () -> Unit, vm: ExportViewModel = hiltViewModel()) {
    val context = LocalContext.current
    val wards by vm.wards.collectAsStateWithLifecycle(emptyList<AreaEntity>())
    val booths by vm.booths.collectAsStateWithLifecycle(emptyList<AreaEntity>())
    val mime = ReportRules.mimeType(vm.job?.format ?: vm.format)
    val scope = rememberCoroutineScope()
    val save = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument(mime)) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        scope.launch {
            val ok = vm.saveTo(uri)
            Toast.makeText(context, if (ok) "Saved." else "Could not save the file.", Toast.LENGTH_LONG).show()
        }
    }

    OnlinePage(vm.report?.let { "Download: ${it.title}" } ?: "Print or export a list", onBack, null, vm.busy) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (vm.voterKind) {
                Choice("List") {
                    FilterChip(vm.kind == ReportRules.VOTER_LIST, { vm.pickKind(ReportRules.VOTER_LIST) }, { Text("Voter list") })
                    FilterChip(vm.kind == ReportRules.MOBILE_LIST, { vm.pickKind(ReportRules.MOBILE_LIST) }, { Text("Mobile numbers") })
                }
                if (vm.fromSearch) {
                    Text("Voters: ${vm.summary}", style = MaterialTheme.typography.bodyMedium)
                    Text("The server applies the same filters; a typed search can match a few voters differently than on this phone.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                } else {
                    if (wards.size > 1) AreaPicker("Village Panchayat", wards, vm.wardId, "Whole area") { vm.pickWard(it) }
                    if (booths.size > 1) AreaPicker("Part", booths, vm.boothId, "All parts") { vm.pickBooth(it) }
                }
                if (vm.kind == ReportRules.MOBILE_LIST) Text("Only voters with a mobile number.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Choice("File") {
                FilterChip(vm.format == "pdf", { vm.format = "pdf"; vm.changed() }, { Text("PDF (to print)") })
                FilterChip(vm.format == "xlsx", { vm.format = "xlsx"; vm.changed() }, { Text("Excel") })
            }
            Choice("Language of the headings and names") {
                listOf("mr" to "मराठी", "en" to "English", "hi" to "हिंदी").forEach { (k, label) ->
                    FilterChip(vm.language == k, { vm.language = k; vm.changed() }, { Text(label) })
                }
            }
            if (vm.voterKind) {
                Choice("Columns") {
                    ReportRules.COLUMNS.forEach { (k, label) -> FilterChip(k in vm.columns, { vm.toggle(k) }, { Text(label) }) }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Group by house", Modifier.weight(1f))
                    Switch(vm.groupByHouse, { vm.groupByHouse = it; vm.changed() })
                }
            }
            if (vm.format == "pdf") {
                Choice("Paper") {
                    FilterChip(vm.paper == "a4", { vm.paper = "a4"; vm.changed() }, { Text("A4") })
                    FilterChip(vm.paper == "legal", { vm.paper = "legal"; vm.changed() }, { Text("Legal") })
                }
                Choice("Text size") {
                    listOf("small" to "Small", "normal" to "Normal", "large" to "Large").forEach { (k, label) ->
                        FilterChip(vm.textSize == k, { vm.textSize = k; vm.changed() }, { Text(label) })
                    }
                }
            }
            OutlinedTextField(
                vm.header, { vm.header = it.take(ReportRules.MAX_HEADER); vm.changed() }, Modifier.fillMaxWidth(),
                label = { Text("Line at the top (optional)") }, singleLine = true,
            )
            BusyButton(if (vm.job == null) "Make the file" else "Make it again", busy = vm.busy, modifier = Modifier.fillMaxWidth()) { vm.make() }
            ErrorText(vm.error)
            vm.job?.let { j ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(ReportRules.statusLine(j), style = MaterialTheme.typography.titleSmall)
                        val f = vm.file
                        if (f != null) {
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(onClick = { open(context, f, j.format) }, Modifier.weight(1f)) { Text("Open") }
                                OutlinedButton(onClick = { share(context, f, j.format) }, Modifier.weight(1f)) { Text("Share") }
                            }
                            OutlinedButton(onClick = { save.launch(f.name) }, Modifier.fillMaxWidth()) { Text("Save to phone") }
                            Text("The file holds voter details: share it only with your team.",
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        } else if (!vm.busy && vm.error != null && j.status != "failed") {
                            OutlinedButton(onClick = { vm.retry() }, Modifier.fillMaxWidth()) { Text("Try again") }
                        }
                    }
                }
            }
            Text(
                "A big list takes a little while: the whole constituency as a PDF is several hundred pages.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Choice(label: String, chips: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, style = MaterialTheme.typography.labelLarge)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) { chips() }
    }
}

private fun uriOf(context: Context, f: File): Uri = FileProvider.getUriForFile(context, context.packageName + ".files", f)

private fun open(context: Context, f: File, format: String) {
    val intent = Intent(Intent.ACTION_VIEW).setDataAndType(uriOf(context, f), ReportRules.mimeType(format))
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    try {
        context.startActivity(intent)
    } catch (e: ActivityNotFoundException) {
        Toast.makeText(context, "No app on this phone opens this file. Use Share or Save to phone.", Toast.LENGTH_LONG).show()
    }
}

private fun share(context: Context, f: File, format: String) {
    val send = Intent(Intent.ACTION_SEND).setType(ReportRules.mimeType(format))
        .putExtra(Intent.EXTRA_STREAM, uriOf(context, f)).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    context.startActivity(Intent.createChooser(send, "Share the file"))
}
