package com.jansetu.app.ui.reports

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.Print
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.Session
import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.local.ColorTagEntity
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.ColorTagReport
import com.jansetu.app.data.remote.Demographics
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.SurveyProgress
import com.jansetu.app.data.remote.TurnoutReport
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.admin.PHONE_ADMIN_ROLES
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.quality.OnlinePage
import com.jansetu.app.ui.reports.ReportRules.Report
import com.jansetu.app.ui.reports.ReportRules.count
import com.jansetu.app.ui.reports.ReportRules.fraction
import com.jansetu.app.ui.reports.ReportRules.share
import com.jansetu.app.ui.search.areaLabel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.launch
import javax.inject.Inject

// --- the menu -------------------------------------------------------------------------------------

/** Reports & charts (11.3, supervisor and above; needs internet): campaign reports of the user's area. */
@Composable
fun ReportsScreen(session: Session, onBack: () -> Unit, onOpen: (String) -> Unit) {
    OnlinePage("Reports & charts", onBack, null, false) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            Report.entries.forEach { r ->
                ReportItem(r.title, r.detail) { onOpen("report/${r.key}") }
            }
            if (session.user.role in PHONE_ADMIN_ROLES) {
                ReportItem("Worker activity", "Surveys, visits, mobiles and voted marks per worker per day") { onOpen("workeractivity") }
            }
            ListItem(
                headlineContent = { Text("Print or export a list") },
                supportingContent = { Text("Voter list or mobile numbers as Excel or PDF. From Search, the list follows your filters.") },
                leadingContent = { Icon(Icons.Default.Print, null) },
                modifier = Modifier.clickable { onOpen(exportRoute(ReportRules.VOTER_LIST)) },
            )
            HorizontalDivider()
            Text(
                "Counts come from the server for your area: work still waiting on a phone is counted once that phone syncs.",
                Modifier.padding(16.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun ReportItem(title: String, detail: String, onClick: () -> Unit) {
    ListItem(
        headlineContent = { Text(title) },
        supportingContent = { Text(detail) },
        leadingContent = { Icon(Icons.Default.BarChart, null) },
        modifier = Modifier.clickable(onClick = onClick),
    )
    HorizontalDivider()
}

// --- one report -----------------------------------------------------------------------------------

/** One report (route `report/{key}`), for the whole area or one Village Panchayat (age and gender: also one part). */
@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class ReportViewModel @Inject constructor(
    handle: SavedStateHandle,
    private val api: JansetuApi,
    local: LocalDb,
) : ViewModel() {
    val report: Report = Report.of(handle["key"]) ?: Report.SURVEY
    private val ward = MutableStateFlow<String?>(null)
    val wards = local.db.areas().byLevel("ward")
    val booths = ward.flatMapLatest { w -> if (w == null) local.db.areas().byLevel("booth") else local.db.areas().children(w) }
    val tags = local.db.lists().colorTags()
    val allAreas = flow { emit(local.db.areas().all()) }

    var wardId by mutableStateOf<String?>(null)
        private set
    var boothId by mutableStateOf<String?>(null)
        private set
    var survey by mutableStateOf<SurveyProgress?>(null)
        private set
    var colourTags by mutableStateOf<ColorTagReport?>(null)
        private set
    var ages by mutableStateOf<Demographics?>(null)
        private set
    var turnout by mutableStateOf<TurnoutReport?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init { load() }

    fun pickWard(id: String?) { wardId = id; boothId = null; ward.value = id; load() }
    fun pickBooth(id: String?) { boothId = id; load() }

    fun load() = viewModelScope.launch {
        loading = true
        val r = when (report) {
            Report.SURVEY -> apiCall { api.surveyProgress(wardId) }.also { if (it is ApiResult.Ok) survey = it.value }
            Report.TAGS -> apiCall { api.colourTagReport(wardId) }.also { if (it is ApiResult.Ok) colourTags = it.value }
            Report.AGE -> apiCall { api.demographics(wardId, boothId) }.also { if (it is ApiResult.Ok) ages = it.value }
            Report.TURNOUT -> apiCall { api.turnoutReport(wardId) }.also { if (it is ApiResult.Ok) turnout = it.value }
        }
        loading = false
        error = r.userMessage()
    }

    /** The export of what is on the screen. */
    fun exportRoute() = exportRoute(report.exportKind, report.exportReport, ReportRules.areaFilter(report, wardId, boothId))
}

@Composable
fun ReportScreen(onBack: () -> Unit, onExport: (String) -> Unit, vm: ReportViewModel = hiltViewModel()) {
    val wards by vm.wards.collectAsStateWithLifecycle(emptyList<AreaEntity>())
    val booths by vm.booths.collectAsStateWithLifecycle(emptyList<AreaEntity>())
    val tags by vm.tags.collectAsStateWithLifecycle(emptyList<ColorTagEntity>())
    val allAreas by vm.allAreas.collectAsStateWithLifecycle(emptyList<AreaEntity>())
    OnlinePage(vm.report.title, onBack, { vm.load() }, vm.loading) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (wards.size > 1) item {
                AreaPicker("Village Panchayat", wards, vm.wardId, "Whole area") { vm.pickWard(it) }
            }
            if (vm.report == Report.AGE && booths.size > 1) item {
                AreaPicker("Part", booths, vm.boothId, if (vm.wardId == null) "All parts" else "All parts of it") { vm.pickBooth(it) }
            }
            item {
                Column {
                    ErrorText(vm.error)
                    OutlinedButton(onClick = { onExport(vm.exportRoute()) }, modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.Default.Print, null)
                        Text("  Download as Excel or PDF")
                    }
                }
            }
            when (vm.report) {
                Report.SURVEY -> vm.survey?.let { surveyProgress(it) }
                Report.TAGS -> vm.colourTags?.let { colourTags(it, tags, allAreas) }
                Report.AGE -> vm.ages?.let { ageAndGender(it) }
                Report.TURNOUT -> vm.turnout?.let { turnout(it) }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AreaPicker(label: String, areas: List<AreaEntity>, selected: String?, allLabel: String, onPick: (String?) -> Unit) {
    var open by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(open, { open = it }) {
        OutlinedTextField(
            value = areas.firstOrNull { it.id == selected }?.let { areaLabel(it) } ?: allLabel,
            onValueChange = {}, readOnly = true, label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
            modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
        )
        ExposedDropdownMenu(open, { open = false }) {
            DropdownMenuItem({ Text(allLabel) }, { onPick(null); open = false })
            areas.forEach { a -> DropdownMenuItem({ Text(areaLabel(a)) }, { onPick(a.id); open = false }) }
        }
    }
}

// --- the four reports (LazyColumn content) ---

private fun androidx.compose.foundation.lazy.LazyListScope.areaBars(lines: List<ReportRules.AreaLine>, doneWord: String) {
    items(lines, key = { it.area.areaId }) { l ->
        val a = l.area
        BarRow(
            ReportRules.areaName(a), "${count(a.done)} of ${count(a.total)} $doneWord · ${ReportRules.percent(a.percent)}",
            fraction(a.done, a.total), indent = l.indented, bold = a.level == "ward",
        )
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.surveyProgress(s: SurveyProgress) {
    item { StatCard("Surveyed", ReportRules.percent(s.percent), "${count(s.surveyed)} of ${count(s.total)} voters", Modifier.fillMaxWidth()) }
    if (s.total == 0) { item { EmptyState("No voters in this area.") }; return }
    item { SectionTitle("By Village Panchayat and part") }
    areaBars(ReportRules.areaLines(s.byArea), "surveyed")
}

private fun androidx.compose.foundation.lazy.LazyListScope.colourTags(r: ColorTagReport, tags: List<ColorTagEntity>, areas: List<AreaEntity>) {
    val byId = tags.associateBy { it.id }
    fun color(id: String?) = if (id == null) ChartColors.noTag else ReportRules.argb(byId[id]?.hex)?.let { Color(it) } ?: ChartColors.noTag
    fun name(id: String?) = if (id == null) "No tag" else byId[id]?.let { it.labelEn.ifBlank { it.labelMr } } ?: "A tag not on this phone"
    val order = tags.map { it.id }
    val totals = ReportRules.orderTags(r.byTag, order)
    val most = totals.maxOfOrNull { it.count } ?: 0
    item { StatCard("Voters", count(r.total), "${count(r.total - (r.byTag.firstOrNull { it.colorTagId == null }?.count ?: 0))} with a colour tag", Modifier.fillMaxWidth()) }
    if (r.total == 0) { item { EmptyState("No voters in this area.") }; return }
    item { SectionTitle("All voters") }
    items(totals, key = { "t" + it.colorTagId }) { t ->
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Swatch(color(t.colorTagId))
                Text("  " + name(t.colorTagId), Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                Text("${count(t.count)} · ${share(t.count, r.total)}", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Bar(fraction(t.count, most), color(t.colorTagId), track = false)
        }
    }
    // Server order: each Village Panchayat followed by its parts; areas without voters are left out.
    val shown = r.byArea.entries.filter { it.value.isNotEmpty() }
    if (shown.isEmpty()) return
    val areaById = areas.associateBy { it.id }
    item { SectionTitle("By Village Panchayat and part") }
    items(shown, key = { "a" + it.key }) { (id, counts) ->
        val list = ReportRules.orderTags(counts, order)
        val area = areaById[id]
        val indented = area?.level == "booth" && area.parentId in r.byArea.keys
        Column(Modifier.padding(start = if (indented) 16.dp else 0.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Text(area?.let { areaLabel(it) + if (it.level == "ward") " (Village Panchayat)" else "" } ?: "An area not on this phone",
                    Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium,
                    fontWeight = if (area?.level == "ward") androidx.compose.ui.text.font.FontWeight.SemiBold else null)
                Text(count(list.sumOf { it.count }), style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            SegmentedBar(list.map { it.count to color(it.colorTagId) })
            Text(list.joinToString(" · ") { "${name(it.colorTagId)} ${count(it.count)}" },
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
private fun androidx.compose.foundation.lazy.LazyListScope.ageAndGender(d: Demographics) {
    item {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            StatCard("Men", count(d.male), share(d.male, d.total), Modifier.weight(1f))
            StatCard("Women", count(d.female), share(d.female, d.total), Modifier.weight(1f))
            if (d.other > 0) StatCard("Other", count(d.other), share(d.other, d.total), Modifier.weight(1f))
        }
    }
    if (d.total == 0) { item { EmptyState("No voters here.") }; return }
    val showOther = d.other > 0
    val most = d.ageBands.maxOfOrNull { maxOf(it.male, it.female, if (showOther) it.other else 0) } ?: 0
    item {
        Column {
            SectionTitle("By age")
            FlowRow(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                LegendItem(ChartColors.men, "Men")
                LegendItem(ChartColors.women, "Women")
                if (showOther) LegendItem(ChartColors.other, "Other")
            }
        }
    }
    items(d.ageBands, key = { it.band }) { b ->
        Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text("${ReportRules.bandLabel(b.band)} · ${count(b.male + b.female + b.other)}", style = MaterialTheme.typography.bodyMedium)
            ValueBar(fraction(b.male, most), count(b.male), ChartColors.men, height = 6.dp)
            ValueBar(fraction(b.female, most), count(b.female), ChartColors.women, height = 6.dp)
            if (showOther) ValueBar(fraction(b.other, most), count(b.other), ChartColors.other, height = 6.dp)
        }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.turnout(t: TurnoutReport) {
    item { StatCard("Voted", ReportRules.percent(t.percent), "${count(t.voted)} of ${count(t.total)} voters on the current roll", Modifier.fillMaxWidth()) }
    if (t.voted == 0) { item { EmptyState("No voted marks yet.") }; return }
    if (t.byHour.isNotEmpty()) {
        val most = t.byHour.maxOf { it.voted }
        item { SectionTitle("By hour (Indian time)") }
        items(t.byHour, key = { "h${it.hour}" }) { h ->
            BarRow(ReportRules.hourRange(h.hour), "${count(h.voted)} · so far ${count(h.cumulative)}", fraction(h.voted, most))
        }
    }
    item { SectionTitle("By Village Panchayat and part") }
    areaBars(ReportRules.areaLines(t.byArea), "voted")
}
