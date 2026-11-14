package com.jansetu.app.ui.quality

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
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
import com.jansetu.app.data.remote.DataQualitySummary
import com.jansetu.app.data.remote.DuplicatePair
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.PairResolution
import com.jansetu.app.data.remote.SyncVoter
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.search.areaLabel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Roles that see Data quality and Repeated voters (server: supervisor and above). */
val QUALITY_ROLES = setOf("supervisor", "admin", "super_admin")

/** Top bar with Back and Refresh, and a thin progress line while loading. Online pages of 10.6. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OnlinePage(title: String, onBack: () -> Unit, onRefresh: (() -> Unit)?, loading: Boolean, content: @Composable () -> Unit) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(title) },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                actions = { if (onRefresh != null) IconButton(onClick = onRefresh) { Icon(Icons.Default.Refresh, "Refresh") } },
            )
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            content()
        }
    }
}

// --- Data quality ---------------------------------------------------------------------------------

/** Data quality (10.6): counts for the user's area from `GET /data-quality/summary`, by Village Panchayat. */
@HiltViewModel
class DataQualityViewModel @Inject constructor(private val api: JansetuApi, local: LocalDb) : ViewModel() {
    val wards = local.db.areas().byLevel("ward")
    var wardId by mutableStateOf<String?>(null)
        private set
    var summary by mutableStateOf<DataQualitySummary?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init { load() }

    fun pick(ward: String?) { wardId = ward; load() }

    fun load() = viewModelScope.launch {
        loading = true
        val r = apiCall { api.dataQuality(wardId) }
        loading = false
        when (r) {
            is ApiResult.Ok -> { summary = r.value; error = null }
            else -> error = r.userMessage()
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DataQualityScreen(onBack: () -> Unit, onPairs: (String) -> Unit, vm: DataQualityViewModel = hiltViewModel()) {
    val wards by vm.wards.collectAsStateWithLifecycle(emptyList<AreaEntity>())
    OnlinePage("Data quality", onBack, { vm.load() }, vm.loading) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(vertical = 8.dp)) {
            if (wards.size > 1) item {
                var open by remember { mutableStateOf(false) }
                ExposedDropdownMenuBox(open, { open = it }, Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) {
                    OutlinedTextField(
                        value = wards.firstOrNull { it.id == vm.wardId }?.let { areaLabel(it) } ?: "Whole area",
                        onValueChange = {}, readOnly = true, label = { Text("Village Panchayat") },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
                        modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
                    )
                    ExposedDropdownMenu(open, { open = false }) {
                        DropdownMenuItem({ Text("Whole area") }, { vm.pick(null); open = false })
                        wards.forEach { w -> DropdownMenuItem({ Text(areaLabel(w)) }, { vm.pick(w.id); open = false }) }
                    }
                }
            }
            item { Column(Modifier.padding(horizontal = 16.dp)) { ErrorText(vm.error) } }
            val s = vm.summary ?: return@LazyColumn
            items(QualityRules.lines(s)) { line ->
                val note = when {
                    line.source != null -> if (line.count > 0) "Tap to check them" else "Nothing to check"
                    line.label.startsWith("Missing") -> QualityRules.share(line.count, s.voters)
                    else -> null
                }
                ListItem(
                    headlineContent = { Text(line.label) },
                    supportingContent = { note?.let { Text(it) } },
                    trailingContent = {
                        Row {
                            Text("%,d".format(line.count), style = MaterialTheme.typography.titleMedium)
                            if (line.source != null) Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null)
                        }
                    },
                    modifier = if (line.source != null) Modifier.clickable { onPairs(line.source) } else Modifier,
                )
                HorizontalDivider()
            }
            item {
                Text(
                    "Counts are for ${"%,d".format(s.voters)} voters on the current roll. Missing numbers and birth dates are " +
                        "filled in the Survey tab. Pairs not checked yet are counted once.",
                    Modifier.padding(16.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

// --- Repeated voters / possible duplicates ----------------------------------------------------------

/**
 * Repeated voters (10.6): pairs from `GET /data-quality/duplicates` (route arg `source`: "" = all,
 * roll_flag = Repeated in the roll). Anyone who sees the pair marks Same person / Different people;
 * a super admin may also hide one record (the other is kept). A hidden voter leaves phones at the next sync.
 */
@HiltViewModel
class DuplicatesViewModel @Inject constructor(
    handle: SavedStateHandle,
    private val api: JansetuApi,
    private val local: LocalDb,
    private val scheduler: SyncScheduler,
) : ViewModel() {
    val source: String? = handle.get<String>("source")?.ifEmpty { null }
    var uncheckedOnly by mutableStateOf(true)
        private set
    var items by mutableStateOf<List<DuplicatePair>>(emptyList())
        private set
    var onPhone by mutableStateOf<Set<String>>(emptySet())
        private set
    var next by mutableStateOf<String?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var loaded by mutableStateOf(false)
        private set
    var busy by mutableStateOf<String?>(null)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init { load() }

    fun show(unchecked: Boolean) { uncheckedOnly = unchecked; load() }

    fun load(more: Boolean = false) = viewModelScope.launch {
        val cursor = if (more) next ?: return@launch else null
        loading = true
        val r = apiCall { api.duplicates(uncheckedOnly, source, cursor, 50) }
        loading = false
        when (r) {
            is ApiResult.Ok -> {
                items = if (more) items + r.value.items else r.value.items
                next = r.value.nextCursor
                loaded = true
                error = null
                val ids = r.value.items.flatMap { listOf(it.voterA.id, it.voterB.id) }
                onPhone = onPhone + ids.chunked(500).flatMap { local.db.voters().voters(it) }.map { it.id }
            }
            else -> error = r.userMessage()
        }
    }

    fun resolve(pair: DuplicatePair, same: Boolean, keep: String? = null) = viewModelScope.launch {
        busy = pair.id
        val r = apiCall { api.resolvePair(pair.id, PairResolution(same, keep)) }
        busy = null
        when (r) {
            is ApiResult.Ok -> {
                error = null
                items = if (uncheckedOnly) items.filter { it.id != pair.id } else items.map { if (it.id == pair.id) r.value else it }
                if (keep != null) scheduler.syncNow() // the hidden voter leaves this phone with the next pull
            }
            else -> error = r.userMessage()
        }
    }
}

@Composable
fun DuplicatesScreen(session: Session, onBack: () -> Unit, onOpen: (String) -> Unit, vm: DuplicatesViewModel = hiltViewModel()) {
    val superAdmin = session.user.role == "super_admin"
    var hiding by remember { mutableStateOf<DuplicatePair?>(null) }
    OnlinePage(QualityRules.pairTitle(vm.source), onBack, { vm.load() }, vm.loading) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(vm.uncheckedOnly, { vm.show(true) }, { Text("Not checked yet") })
                        FilterChip(!vm.uncheckedOnly, { vm.show(false) }, { Text("All pairs") })
                    }
                    Text(
                        if (superAdmin) "Same person: you can also hide one record (survey work is kept; Restore under Matching Engine)."
                        else "Same person or different people: a super admin decides later which record to hide.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    ErrorText(vm.error)
                }
            }
            if (vm.loaded && vm.items.isEmpty()) item { EmptyState("No pairs to check.") }
            items(vm.items, key = { it.id }) { p ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(QualityRules.sourceLabel(p.source), style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.primary)
                        PairVoter(p.voterA, p.voterA.id in vm.onPhone) { onOpen(p.voterA.id) }
                        HorizontalDivider()
                        PairVoter(p.voterB, p.voterB.id in vm.onPhone) { onOpen(p.voterB.id) }
                        if (p.status != "unchecked") Text("Checked: ${QualityRules.statusLabel(p.status)}", fontWeight = FontWeight.Medium)
                        val bothLive = p.voterA.deletedAt == null && p.voterB.deletedAt == null
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (p.status == "unchecked") {
                                Button(onClick = { if (superAdmin && bothLive) hiding = p else vm.resolve(p, true) },
                                    enabled = vm.busy == null, modifier = Modifier.weight(1f)) { Text("Same person") }
                                OutlinedButton(onClick = { vm.resolve(p, false) }, enabled = vm.busy == null,
                                    modifier = Modifier.weight(1f)) { Text("Different") }
                            } else if (superAdmin && p.status == "same_person" && bothLive) {
                                OutlinedButton(onClick = { hiding = p }, enabled = vm.busy == null) { Text("Hide one record…") }
                            }
                        }
                    }
                }
            }
            if (vm.next != null) item {
                OutlinedButton(onClick = { vm.load(more = true) }, enabled = !vm.loading, modifier = Modifier.fillMaxWidth()) { Text("Show more") }
            }
        }
    }

    hiding?.let { p ->
        AlertDialog(
            onDismissRequest = { hiding = null },
            title = { Text("Same person") },
            text = {
                Text("Keep one record and hide the other? The hidden one leaves lists, search and phones; its survey " +
                    "work is kept and it can be restored.")
            },
            confirmButton = {
                Column {
                    TextButton(onClick = { hiding = null; vm.resolve(p, true, keep = p.voterA.id) }) {
                        Text("Keep Serial ${p.voterA.serialNo} (part ${p.voterA.partNo}), hide the other")
                    }
                    TextButton(onClick = { hiding = null; vm.resolve(p, true, keep = p.voterB.id) }) {
                        Text("Keep Serial ${p.voterB.serialNo} (part ${p.voterB.partNo}), hide the other")
                    }
                    if (p.status == "unchecked") TextButton(onClick = { hiding = null; vm.resolve(p, true) }) { Text("Only mark as the same person") }
                }
            },
            dismissButton = { TextButton(onClick = { hiding = null }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun PairVoter(v: SyncVoter, onPhone: Boolean, onOpen: () -> Unit) {
    Column(if (onPhone) Modifier.fillMaxWidth().clickable(onClick = onOpen) else Modifier.fillMaxWidth()) {
        Text(QualityRules.name(v) + if (v.deletedAt != null) " (hidden)" else "", style = MaterialTheme.typography.titleSmall)
        QualityRules.relativeLine(v)?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
        Text(QualityRules.voterLine(v), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (onPhone) Text("Open voter", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
    }
}
