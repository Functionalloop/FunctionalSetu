package com.jansetu.app.ui.admin.logs

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.remote.AdminUser
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.AuditEntry
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.WorkerLocation
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.displayName
import com.jansetu.app.ui.common.istTime
import com.jansetu.app.ui.home.roleLabel
import com.jansetu.app.ui.search.areaLabel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale
import javax.inject.Inject

private const val PAGE = 50

/** Names for ids in log rows: team users, this phone's areas and lists, and voters on this phone. */
class LogNames @Inject constructor(private val api: JansetuApi, private val local: LocalDb) {
    suspend fun team(): List<AdminUser> = (apiCall { api.users(limit = 200) } as? ApiResult.Ok)?.value?.items.orEmpty()

    suspend fun labels(team: List<AdminUser>): Map<String, String> {
        val db = local.db
        val out = HashMap<String, String>()
        team.forEach { out[it.id] = it.fullNameEn }
        db.areas().all().forEach { out[it.id] = (if (it.level == "booth") "Part " else "") + areaLabel(it) }
        listOf("caste", "profession", "influencer_type").forEach { k ->
            db.lists().entries(k).first().forEach { out[it.id] = it.nameEn ?: it.nameMr }
        }
        db.lists().colorTags().first().forEach { out[it.id] = it.labelEn }
        return out
    }

    /** "Name · Part 12/345" for voters on this phone; others stay unnamed. */
    suspend fun voters(ids: Collection<String>): Map<String, String> =
        ids.distinct().chunked(500).flatMap { local.db.voters().voters(it) }
            .associate { it.id to "${it.displayName()} · Part ${it.partNo}/${it.serialNo}" }
}

// --- shared filters ---------------------------------------------------------------------------------

private val SHOWN_DAY = DateTimeFormatter.ofPattern("d MMM", Locale.ENGLISH)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun UserFilter(team: List<AdminUser>, selected: String?, onPick: (String?) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val current = team.firstOrNull { it.id == selected }
    ExposedDropdownMenuBox(expanded = open, onExpandedChange = { open = it }) {
        OutlinedTextField(
            value = current?.fullNameEn ?: "Everyone", onValueChange = {}, readOnly = true, label = { Text("Worker") },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
            modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
        )
        ExposedDropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(text = { Text("Everyone") }, onClick = { onPick(null); open = false })
            team.forEach { u ->
                DropdownMenuItem(text = { Text("${u.fullNameEn} · ${roleLabel(u.role)}") }, onClick = { onPick(u.id); open = false })
            }
        }
    }
}

/** Quick ranges plus From / To; `optional` adds "All dates" (Activity log). */
@Composable
private fun DateFilter(from: LocalDate?, to: LocalDate?, optional: Boolean, onPick: (LocalDate?, LocalDate?) -> Unit) {
    val presets = LogRules.presets(LogRules.today())
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        if (optional) FilterChip(from == null && to == null, { onPick(null, null) }, { Text("All dates") })
        presets.forEach { (label, range) -> FilterChip(from == range.first && to == range.second, { onPick(range.first, range.second) }, { Text(label) }) }
    }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        DayButton("From", from) { onPick(it, to ?: it) }
        Text("to")
        DayButton("To", to) { onPick(from ?: it, it) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DayButton(label: String, day: LocalDate?, onPick: (LocalDate) -> Unit) {
    var open by remember { mutableStateOf(false) }
    OutlinedButton(onClick = { open = true }) { Text(day?.format(SHOWN_DAY) ?: label) }
    if (open) {
        val state = rememberDatePickerState(initialSelectedDateMillis = (day ?: LogRules.today()).atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli())
        DatePickerDialog(
            onDismissRequest = { open = false },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { onPick(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate()) }
                    open = false
                }) { Text("OK") }
            },
            dismissButton = { TextButton(onClick = { open = false }) { Text("Cancel") } },
        ) { DatePicker(state) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LogScaffold(title: String, onBack: () -> Unit, onRefresh: () -> Unit, loading: Boolean, content: @Composable () -> Unit) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(title) },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                actions = { IconButton(onClick = onRefresh) { Icon(Icons.Default.Refresh, "Refresh") } },
            )
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            content()
        }
    }
}

// --- Activity log -----------------------------------------------------------------------------------

/** Activity log (9.8): who changed what and when (`GET /audit-log`), the team's changes, newest first. */
@HiltViewModel
class ActivityLogViewModel @Inject constructor(private val api: JansetuApi, private val names: LogNames) : ViewModel() {
    var team by mutableStateOf<List<AdminUser>>(emptyList())
        private set
    private var labels: Map<String, String> = emptyMap()
    var voterNames by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var items by mutableStateOf<List<AuditEntry>>(emptyList())
        private set
    var next by mutableStateOf<String?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var loaded by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    var kind by mutableStateOf<String?>(null)
        private set
    var userId by mutableStateOf<String?>(null)
        private set
    var from by mutableStateOf<LocalDate?>(LogRules.today().minusDays(6))
        private set
    var to by mutableStateOf<LocalDate?>(LogRules.today())
        private set

    init {
        viewModelScope.launch {
            team = names.team()
            labels = names.labels(team)
            load()
        }
    }

    fun filter(kind: String? = this.kind, userId: String? = this.userId, from: LocalDate? = this.from, to: LocalDate? = this.to) {
        // No day limit here (the log is paged); the dates only need to be in order.
        if (from != null && to != null && to.isBefore(from)) { error = "The end date is before the start date."; return }
        this.kind = kind; this.userId = userId; this.from = from; this.to = to
        load()
    }

    fun load(more: Boolean = false) = viewModelScope.launch {
        val cursor = if (more) next ?: return@launch else null
        loading = true
        val r = apiCall { api.auditLog(kind, userId, from?.toString(), to?.toString(), cursor, PAGE) }
        loading = false
        when (r) {
            is ApiResult.Ok -> {
                items = if (more) items + r.value.items else r.value.items
                next = r.value.nextCursor
                error = null
                loaded = true
                val ids = r.value.items.filter { it.entityType in LogRules.VOTER_ENTITIES }.mapNotNull { it.entityId }
                if (ids.isNotEmpty()) voterNames = voterNames + names.voters(ids)
            }
            else -> error = r.userMessage()
        }
    }

    /** Names for ids in the detail lines (users, areas, list entries). */
    fun idNames(): Map<String, String> = labels
}

@Composable
fun ActivityLogScreen(onBack: () -> Unit, vm: ActivityLogViewModel = hiltViewModel()) {
    var open by remember { mutableStateOf<Long?>(null) }
    LogScaffold("Activity log", onBack, { vm.load() }, vm.loading) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        LogRules.KINDS.forEach { (label, type) -> FilterChip(vm.kind == type, { vm.filter(kind = type) }, { Text(label) }) }
                    }
                    UserFilter(vm.team, vm.userId) { vm.filter(userId = it) }
                    DateFilter(vm.from, vm.to, optional = true) { f, t -> vm.filter(from = f, to = t) }
                    ErrorText(vm.error)
                }
            }
            if (vm.loaded && vm.items.isEmpty()) item { EmptyState("No changes for these filters.") }
            items(vm.items, key = { it.id }) { e ->
                Card(Modifier.fillMaxWidth().clickable { open = if (open == e.id) null else e.id }) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(LogRules.title(e), style = MaterialTheme.typography.titleSmall)
                        val about = e.entityId?.let { vm.voterNames[it] } ?: LogRules.subject(e)
                        about?.let { Text(it) }
                        Text(listOfNotNull(istTime(e.occurredAt), e.actor?.fullNameEn ?: "System").joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        val lines = LogRules.changeLines(e, vm.idNames())
                        if (open == e.id) lines.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                        else if (lines.isNotEmpty()) Text("${lines.size} detail(s) · tap to see", style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.primary)
                    }
                }
            }
            if (vm.next != null) item {
                OutlinedButton(onClick = { vm.load(more = true) }, enabled = !vm.loading, modifier = Modifier.fillMaxWidth()) { Text("Show older") }
            }
        }
    }
}

// --- Worker activity --------------------------------------------------------------------------------

/** Worker activity (9.8): surveys, visits, mobiles, not registered and voted marks per worker per day. */
@HiltViewModel
class WorkerActivityViewModel @Inject constructor(private val api: JansetuApi, private val names: LogNames) : ViewModel() {
    var team by mutableStateOf<List<AdminUser>>(emptyList())
        private set
    var totals by mutableStateOf<Pair<List<LogRules.Totals>, LogRules.Totals>?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var userId by mutableStateOf<String?>(null)
        private set
    var from by mutableStateOf(LogRules.today().minusDays(6))
        private set
    var to by mutableStateOf(LogRules.today())
        private set

    init {
        viewModelScope.launch { team = names.team() }
        load()
    }

    fun filter(userId: String? = this.userId, from: LocalDate = this.from, to: LocalDate = this.to) {
        LogRules.checkRange(from, to)?.let { error = it; return }
        this.userId = userId; this.from = from; this.to = to
        load()
    }

    fun load() = viewModelScope.launch {
        loading = true
        val r = apiCall { api.workerActivity(from.toString(), to.toString(), userId) }
        loading = false
        when (r) {
            is ApiResult.Ok -> { totals = LogRules.totals(r.value.rows); error = null }
            else -> error = r.userMessage()
        }
    }
}

@Composable
fun WorkerActivityScreen(onBack: () -> Unit, vm: WorkerActivityViewModel = hiltViewModel()) {
    var open by remember { mutableStateOf<String?>(null) }
    LogScaffold("Worker activity", onBack, { vm.load() }, vm.loading) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    UserFilter(vm.team, vm.userId) { vm.filter(userId = it) }
                    DateFilter(vm.from, vm.to, optional = false) { f, t -> if (f != null && t != null) vm.filter(from = f, to = t) }
                    ErrorText(vm.error)
                }
            }
            val (each, all) = vm.totals ?: return@LazyColumn
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text("Team · ${vm.from.format(SHOWN_DAY)} to ${vm.to.format(SHOWN_DAY)}", style = MaterialTheme.typography.titleSmall)
                        Text(LogRules.countsLine(all.surveys, all.visits, all.mobiles, all.newVoters, all.voted))
                    }
                }
            }
            if (each.isEmpty()) item { EmptyState("Nothing saved in these days.") }
            items(each, key = { it.user!!.id }) { t ->
                Card(Modifier.fillMaxWidth().clickable { open = if (open == t.user!!.id) null else t.user.id }) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text("${t.user!!.fullNameEn} · ${roleLabel(t.user.role)}", style = MaterialTheme.typography.titleSmall)
                        Text(LogRules.countsLine(t.surveys, t.visits, t.mobiles, t.newVoters, t.voted))
                        if (open == t.user.id) t.days.forEach { d ->
                            Text("${LocalDate.parse(d.day).format(SHOWN_DAY)}: " +
                                LogRules.countsLine(d.surveys, d.visits, d.mobilesCollected, d.newVoters, d.votedMarks),
                                style = MaterialTheme.typography.bodySmall)
                        } else if (t.days.size > 1) Text("Tap for each day", style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.primary)
                    }
                }
            }
            item {
                Text("Workers with nothing saved in these days are not listed. Surveys count each voter once a day.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

// --- Worker locations -------------------------------------------------------------------------------

/** Worker locations (9.8): where surveys and visits were saved. No live tracking; opens the phone's map app. */
@HiltViewModel
class WorkerLocationsViewModel @Inject constructor(private val api: JansetuApi, private val names: LogNames) : ViewModel() {
    var team by mutableStateOf<List<AdminUser>>(emptyList())
        private set
    var voterNames by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var items by mutableStateOf<List<WorkerLocation>>(emptyList())
        private set
    var next by mutableStateOf<String?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var loaded by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var userId by mutableStateOf<String?>(null)
        private set
    var from by mutableStateOf(LogRules.today())
        private set
    var to by mutableStateOf(LogRules.today())
        private set

    init {
        viewModelScope.launch { team = names.team() }
        load()
    }

    fun filter(userId: String? = this.userId, from: LocalDate = this.from, to: LocalDate = this.to) {
        LogRules.checkRange(from, to)?.let { error = it; return }
        this.userId = userId; this.from = from; this.to = to
        load()
    }

    fun load(more: Boolean = false) = viewModelScope.launch {
        val cursor = if (more) next ?: return@launch else null
        loading = true
        val r = apiCall { api.workerLocations(from.toString(), to.toString(), userId, cursor, PAGE) }
        loading = false
        when (r) {
            is ApiResult.Ok -> {
                items = if (more) items + r.value.items else r.value.items
                next = r.value.nextCursor
                error = null
                loaded = true
                voterNames = voterNames + names.voters(r.value.items.mapNotNull { it.voterId })
            }
            else -> error = r.userMessage()
        }
    }
}

@Composable
fun WorkerLocationsScreen(onBack: () -> Unit, vm: WorkerLocationsViewModel = hiltViewModel()) {
    val context = LocalContext.current
    var noMapApp by remember { mutableStateOf(false) }
    LogScaffold("Worker locations", onBack, { vm.load() }, vm.loading) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    UserFilter(vm.team, vm.userId) { vm.filter(userId = it) }
                    DateFilter(vm.from, vm.to, optional = false) { f, t -> if (f != null && t != null) vm.filter(from = f, to = t) }
                    ErrorText(vm.error ?: if (noMapApp) "No map app on this phone." else null)
                    Text("Where surveys and visits were saved, newest first. Not live tracking.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (vm.loaded && vm.items.isEmpty()) item { EmptyState("No locations for these filters.") }
            items(vm.items) { l ->
                Card(Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text("${l.user.fullNameEn} · ${if (l.kind == "visit") "Visit" else "Survey"}", style = MaterialTheme.typography.titleSmall)
                            l.voterId?.let { vm.voterNames[it] }?.let { Text(it) }
                            Text(listOfNotNull(istTime(l.at), LogRules.placeLine(l.lat, l.lng, l.accuracyM)).joinToString(" · "),
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        TextButton(onClick = {
                            noMapApp = try {
                                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(LogRules.geoUri(l.lat, l.lng, l.user.fullNameEn))))
                                false
                            } catch (_: ActivityNotFoundException) { true }
                        }) { Text("Map") }
                    }
                }
            }
            if (vm.next != null) item {
                OutlinedButton(onClick = { vm.load(more = true) }, enabled = !vm.loading, modifier = Modifier.fillMaxWidth()) { Text("Show older") }
            }
        }
    }
}
