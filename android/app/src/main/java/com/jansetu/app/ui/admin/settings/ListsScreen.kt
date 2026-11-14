package com.jansetu.app.ui.admin.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.ColorTagDto
import com.jansetu.app.data.remote.ColorTagIn
import com.jansetu.app.data.remote.CustomFieldLabelDto
import com.jansetu.app.data.remote.CustomFieldLabelIn
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.MessageTemplateDto
import com.jansetu.app.data.remote.MessageTemplateIn
import com.jansetu.app.data.remote.NamedEntryIn
import com.jansetu.app.data.remote.NamedListEntry
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.ErrorText
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Tabs of Lists & labels; `path` = the /masters/{path} of a simple list. */
enum class ListTab(val label: String, val path: String?) {
    Castes("Castes", "castes"), Professions("Professions", "professions"), Influencer("Influencer", "influencer-types"),
    ColorTags("Colour tags", null), Fields("Survey fields", null), Messages("Messages", null),
}

/** Colours offered for a tag (any #RRGGBB can be typed). */
private val SWATCHES = listOf("#2E7D32", "#C62828", "#F9A825", "#1565C0", "#6A1B9A", "#EF6C00", "#00838F", "#616161")

/**
 * Lists & labels (9.7): admin and super admin, online. Entries are never deleted, only switched off (old surveys
 * keep them). Phones get changes at their next sync.
 */
@HiltViewModel
class ListsViewModel @Inject constructor(private val api: JansetuApi) : ViewModel() {
    var named by mutableStateOf<Map<ListTab, List<NamedListEntry>>>(emptyMap())
        private set
    var tags by mutableStateOf<List<ColorTagDto>>(emptyList())
        private set
    var fields by mutableStateOf<List<CustomFieldLabelDto>>(emptyList())
        private set
    var templates by mutableStateOf<List<MessageTemplateDto>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)

    fun load(tab: ListTab) = viewModelScope.launch {
        loading = true
        val r = when (tab) {
            ListTab.ColorTags -> apiCall { api.colorTags() }.also { if (it is ApiResult.Ok) tags = it.value }
            ListTab.Fields -> apiCall { api.customFields() }.also { if (it is ApiResult.Ok) fields = it.value }
            ListTab.Messages -> apiCall { api.messageTemplates() }.also { if (it is ApiResult.Ok) templates = it.value }
            else -> apiCall { api.namedList(tab.path!!) }.also { if (it is ApiResult.Ok) named = named + (tab to it.value) }
        }
        loading = false
        error = r.userMessage()
    }

    /** Runs a write; on success reloads the tab and calls done(), else keeps the dialog open with the reason. */
    fun write(tab: ListTab, call: suspend JansetuApi.() -> Any, done: () -> Unit) = viewModelScope.launch {
        loading = true
        val r = apiCall { api.call() }
        loading = false
        if (r is ApiResult.Ok) { error = null; done(); load(tab) } else error = r.userMessage()
    }

    fun nextOrder(tab: ListTab): Int = SettingsRules.nextSortOrder(
        if (tab == ListTab.ColorTags) tags.map { it.sortOrder } else named[tab].orEmpty().map { it.sortOrder },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ListsScreen(onBack: () -> Unit, vm: ListsViewModel = hiltViewModel()) {
    var tab by rememberSaveable { mutableStateOf(ListTab.Castes) }
    /** The open dialog: an entry, or Unit for a new one. */
    var editing by remember { mutableStateOf<Any?>(null) }
    LaunchedEffect(tab) { vm.load(tab) }
    val canAdd = tab.path != null || tab == ListTab.ColorTags
    val close = { editing = null }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Lists & labels") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                actions = {
                    IconButton(onClick = { vm.load(tab) }) { Icon(Icons.Default.Refresh, "Refresh") }
                    if (canAdd) IconButton(onClick = { vm.error = null; editing = Unit }) { Icon(Icons.Default.Add, "Add") }
                },
            )
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            ScrollableTabRow(selectedTabIndex = tab.ordinal, edgePadding = 8.dp) {
                ListTab.entries.forEach { t -> Tab(tab == t, { tab = t; editing = null }, text = { Text(t.label) }) }
            }
            if (vm.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            Column(Modifier.padding(horizontal = 16.dp)) { ErrorText(if (editing == null) vm.error else null) }
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 16.dp)) {
                when (tab) {
                    ListTab.ColorTags -> items(vm.tags, key = { it.id }) { t ->
                        Row_(t.labelEn + if (t.isDefault) " · default" else "", "${t.labelMr} · ${t.code}", t.isActive,
                            swatch = SettingsRules.argb(t.hex)) { vm.error = null; editing = t }
                    }
                    ListTab.Fields -> items(vm.fields, key = { it.fieldKey }) { f ->
                        Row_(listOfNotNull(f.labelEn, f.labelMr).joinToString(" · ").ifEmpty { "No label" },
                            SettingsRules.CUSTOM_FIELDS[f.fieldKey] ?: f.fieldKey, f.isEnabled, offWord = "hidden in the survey") {
                            vm.error = null; editing = f
                        }
                    }
                    ListTab.Messages -> items(vm.templates, key = { it.kind }) { m ->
                        Row_(SettingsRules.TEMPLATE_KINDS[m.kind] ?: m.kind, (m.bodyEn ?: m.bodyMr ?: "Not written yet").take(80), true) {
                            vm.error = null; editing = m
                        }
                    }
                    else -> items(vm.named[tab].orEmpty(), key = { it.id }) { e ->
                        Row_(e.nameEn ?: e.nameMr, if (e.nameEn != null) e.nameMr else null, e.isActive) { vm.error = null; editing = e }
                    }
                }
                item {
                    Text("Changes reach the phones at their next sync. Entries are switched off, never deleted: old surveys keep them.",
                        Modifier.padding(16.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }

    when (val e = editing) {
        null -> {}
        is NamedListEntry -> NamedDialog(e, vm.error, close) { body -> vm.write(tab, { saveNamed(tab.path!!, e.id, body) }, close) }
        is ColorTagDto -> TagDialog(e, vm.error, close) { body -> vm.write(tab, { saveColorTag(e.id, body) }, close) }
        is CustomFieldLabelDto -> FieldDialog(e, vm.error, close) { body -> vm.write(tab, { saveCustomField(e.fieldKey, body) }, close) }
        is MessageTemplateDto -> MessageDialog(e, vm.error, close) { body -> vm.write(tab, { saveMessageTemplate(e.kind, body) }, close) }
        else -> when { // Unit: a new entry
            tab == ListTab.ColorTags -> TagDialog(null, vm.error, close, vm.nextOrder(tab)) { body -> vm.write(tab, { addColorTag(body) }, close) }
            tab.path != null -> NamedDialog(null, vm.error, close, vm.nextOrder(tab)) { body -> vm.write(tab, { addNamed(tab.path!!, body) }, close) }
        }
    }
}

@Composable
private fun Row_(title: String, subtitle: String?, on: Boolean, offWord: String = "switched off", swatch: Long? = null, onClick: () -> Unit) {
    ListItem(
        headlineContent = { Text(title) },
        supportingContent = {
            val line = listOfNotNull(subtitle, if (!on) offWord else null).joinToString(" · ")
            if (line.isNotEmpty()) Text(line, color = if (on) Color.Unspecified else MaterialTheme.colorScheme.error)
        },
        leadingContent = swatch?.let { { Box(Modifier.size(24.dp).background(Color(it), CircleShape)) } },
        trailingContent = { Icon(Icons.Default.Edit, "Edit") },
        modifier = Modifier.clickable(onClick = onClick),
    )
    HorizontalDivider()
}

@Composable
private fun EditDialog(title: String, problem: String?, onDismiss: () -> Unit, onSave: () -> Unit, content: @Composable () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                content()
                ErrorText(problem)
            }
        },
        confirmButton = { TextButton(onClick = onSave) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun OnSwitch(label: String, on: Boolean, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f))
        Switch(on, onChange)
    }
}

@Composable
private fun NamedDialog(e: NamedListEntry?, serverError: String?, onDismiss: () -> Unit, newOrder: Int = 0, onSave: (NamedEntryIn) -> Unit) {
    var mr by remember { mutableStateOf(e?.nameMr ?: "") }
    var en by remember { mutableStateOf(e?.nameEn ?: "") }
    var active by remember { mutableStateOf(e?.isActive ?: true) }
    var problem by remember { mutableStateOf<String?>(null) }
    EditDialog(if (e == null) "Add" else "Edit", problem ?: serverError, onDismiss, onSave = {
        problem = SettingsRules.checkNamed(mr)
        if (problem == null) onSave(NamedEntryIn(mr.trim(), en.trim().ifEmpty { null }, e?.nameHi, e?.sortOrder ?: newOrder, active))
    }) {
        OutlinedTextField(mr, { mr = it.take(200) }, label = { Text("Name in Marathi") }, singleLine = true)
        OutlinedTextField(en, { en = it.take(200) }, label = { Text("Name in English") }, singleLine = true)
        if (e != null) OnSwitch("In use (offered in the survey)", active) { active = it }
    }
}

@Composable
private fun TagDialog(t: ColorTagDto?, serverError: String?, onDismiss: () -> Unit, newOrder: Int = 0, onSave: (ColorTagIn) -> Unit) {
    var code by remember { mutableStateOf(t?.code ?: "") }
    var hex by remember { mutableStateOf(t?.hex ?: SWATCHES.first()) }
    var mr by remember { mutableStateOf(t?.labelMr ?: "") }
    var en by remember { mutableStateOf(t?.labelEn ?: "") }
    var default by remember { mutableStateOf(t?.isDefault ?: false) }
    var active by remember { mutableStateOf(t?.isActive ?: true) }
    var problem by remember { mutableStateOf<String?>(null) }
    EditDialog(if (t == null) "Add colour tag" else "Colour tag", problem ?: serverError, onDismiss, onSave = {
        problem = SettingsRules.checkColorTag(code, hex, mr, en, default, active)
        if (problem == null) onSave(ColorTagIn(code.trim(), hex.trim(), mr.trim(), en.trim(), t?.labelHi, default, t?.sortOrder ?: newOrder, active))
    }) {
        // The code is what surveys store: set once.
        OutlinedTextField(code, { code = it.lowercase().take(20) }, label = { Text("Code (for example ours)") }, singleLine = true, enabled = t == null)
        OutlinedTextField(en, { en = it.take(100) }, label = { Text("Label in English") }, singleLine = true)
        OutlinedTextField(mr, { mr = it.take(100) }, label = { Text("Label in Marathi") }, singleLine = true)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SWATCHES.forEach { s ->
                val selected = s.equals(hex, ignoreCase = true)
                Box(
                    Modifier.size(32.dp).background(Color(SettingsRules.argb(s)!!), CircleShape)
                        .then(if (selected) Modifier.border(3.dp, MaterialTheme.colorScheme.onSurface, CircleShape) else Modifier)
                        .clickable { hex = s },
                )
            }
        }
        OutlinedTextField(hex, { hex = it.take(7) }, label = { Text("Colour") }, singleLine = true,
            leadingIcon = SettingsRules.argb(hex)?.let { c -> { Box(Modifier.size(20.dp).background(Color(c), CircleShape)) } })
        OnSwitch("Default for new surveys", default) { default = it }
        if (t != null) OnSwitch("In use", active) { active = it }
    }
}

@Composable
private fun FieldDialog(f: CustomFieldLabelDto, serverError: String?, onDismiss: () -> Unit, onSave: (CustomFieldLabelIn) -> Unit) {
    var mr by remember { mutableStateOf(f.labelMr ?: "") }
    var en by remember { mutableStateOf(f.labelEn ?: "") }
    var on by remember { mutableStateOf(f.isEnabled) }
    var problem by remember { mutableStateOf<String?>(null) }
    EditDialog(SettingsRules.CUSTOM_FIELDS[f.fieldKey] ?: f.fieldKey, problem ?: serverError, onDismiss, onSave = {
        problem = SettingsRules.checkCustomField(mr, en, on)
        if (problem == null) onSave(CustomFieldLabelIn(mr.trim().ifEmpty { null }, en.trim().ifEmpty { null }, f.labelHi, on))
    }) {
        OutlinedTextField(en, { en = it.take(100) }, label = { Text("Label in English") }, singleLine = true)
        OutlinedTextField(mr, { mr = it.take(100) }, label = { Text("Label in Marathi") }, singleLine = true)
        OnSwitch("Show in the survey", on) { on = it }
    }
}

@Composable
private fun MessageDialog(m: MessageTemplateDto, serverError: String?, onDismiss: () -> Unit, onSave: (MessageTemplateIn) -> Unit) {
    var mr by remember { mutableStateOf(m.bodyMr ?: "") }
    var en by remember { mutableStateOf(m.bodyEn ?: "") }
    EditDialog(SettingsRules.TEMPLATE_KINDS[m.kind] ?: m.kind, serverError, onDismiss, onSave = {
        onSave(MessageTemplateIn(mr.trim().ifEmpty { null }, en.trim().ifEmpty { null }, m.bodyHi))
    }) {
        OutlinedTextField(en, { en = it.take(2000) }, label = { Text("English") }, minLines = 4)
        OutlinedTextField(mr, { mr = it.take(2000) }, label = { Text("Marathi") }, minLines = 4)
    }
}
