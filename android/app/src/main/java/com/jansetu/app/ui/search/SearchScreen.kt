package com.jansetu.app.ui.search

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.VoterFilter
import com.jansetu.app.data.local.VoterQuery
import com.jansetu.app.data.local.VoterRow
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.displayName
import com.jansetu.app.ui.common.genderLabel
import com.jansetu.app.ui.common.nameEn
import com.jansetu.app.ui.common.nameMr
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import javax.inject.Inject

private const val PAGE = 100

@OptIn(FlowPreview::class, ExperimentalCoroutinesApi::class)
@HiltViewModel
class SearchViewModel @Inject constructor(local: LocalDb) : ViewModel() {
    private val dao = local.db.voters()
    val db = local.db

    val filter = MutableStateFlow(VoterFilter())
    private val limit = MutableStateFlow(PAGE)

    // Short debounce: results follow the typing without a query per key press.
    private val debounced = filter.debounce(120)

    val rows = combine(debounced, limit) { f, l -> f to l }
        .flatMapLatest { (f, l) -> dao.rows(VoterQuery.list(f, l)) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val count = rows.map { it.firstOrNull()?.total ?: 0 }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)

    fun setQuery(q: String) { limit.value = PAGE; filter.value = filter.value.copy(q = q) }
    fun setFilter(f: VoterFilter) { limit.value = PAGE; filter.value = f.copy(q = filter.value.q) }
    fun loadMore() { limit.value += PAGE }
}

@Composable
fun SearchScreen(onOpen: (String) -> Unit, vm: SearchViewModel = hiltViewModel()) {
    val filter by vm.filter.collectAsStateWithLifecycle()
    val rows by vm.rows.collectAsStateWithLifecycle()
    val count by vm.count.collectAsStateWithLifecycle()
    var showFilters by remember { mutableStateOf(false) }
    val list = rememberLazyListState()

    val nearEnd by remember { derivedStateOf { (list.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0) >= rows.size - 10 } }
    LaunchedEffect(nearEnd, rows.size, count) { if (nearEnd && rows.size < count && rows.isNotEmpty()) vm.loadMore() }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.padding(start = 12.dp, end = 4.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = filter.q, onValueChange = vm::setQuery, singleLine = true,
                modifier = Modifier.weight(1f),
                placeholder = { Text("Name, EPIC, house, mobile or serial") },
                leadingIcon = { Icon(Icons.Default.Search, null) },
                trailingIcon = { if (filter.q.isNotEmpty()) IconButton(onClick = { vm.setQuery("") }) { Icon(Icons.Default.Clear, "Clear") } },
            )
            IconButton(onClick = { showFilters = true }) {
                val n = filter.activeFilterCount
                if (n > 0) BadgedBox(badge = { Badge { Text("$n") } }) { Icon(Icons.Default.FilterList, "Filters") }
                else Icon(Icons.Default.FilterList, "Filters")
            }
        }
        Text(
            "%,d voters".format(count), style = MaterialTheme.typography.labelLarge,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp), color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (rows.isEmpty()) EmptyState(if (filter.q.isBlank() && filter.activeFilterCount == 0) "No voters on this phone yet." else "No voter matches.")
        LazyColumn(state = list, modifier = Modifier.fillMaxSize()) {
            items(rows, key = { it.id }) { r ->
                VoterLine(r, Modifier.clickable { onOpen(r.id) })
                HorizontalDivider()
            }
        }
    }

    if (showFilters) FiltersScreen(vm.db, filter, onApply = { vm.setFilter(it); showFilters = false }, onClose = { showFilters = false })
}

@Composable
fun VoterLine(r: VoterRow, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier.size(12.dp).clip(CircleShape)
                .background(r.colorHex?.let { parseHex(it) } ?: Color.Transparent),
        )
        Column(Modifier.weight(1f).padding(start = 10.dp)) {
            Text(r.displayName(), style = MaterialTheme.typography.titleMedium)
            if (r.nameEn() != null && r.nameMr() != null) Text(r.nameMr()!!, style = MaterialTheme.typography.bodyMedium)
            Text(
                listOfNotNull(
                    "Part ${r.partNo} · Sr ${r.serialNo}",
                    r.age?.let { "$it ${genderLabel(r.gender)}" } ?: genderLabel(r.gender),
                    r.houseNo?.let { "House $it" },
                    r.epicNo,
                ).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        when {
            r.pending == true -> Text("Not sent", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.secondary)
            r.isSurveyed == true -> Text("Surveyed", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
        }
    }
}

fun parseHex(hex: String): Color? = runCatching {
    val h = hex.removePrefix("#")
    Color(("FF" + h.takeLast(6)).toLong(16))
}.getOrNull()
