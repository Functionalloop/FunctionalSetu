package com.jansetu.app.ui.admin.settings

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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.remote.AdminUser
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.Constituency
import com.jansetu.app.data.remote.ConstituencyIn
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.ErrorText
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import javax.inject.Inject

/** Up to 5 per workspace (the database's `geo_units_path` trigger). */
private const val CONSTITUENCY_LIMIT = 5

/** Constituencies (9.7): super admin only, online. Areas below them come from roll imports, not from here. */
@HiltViewModel
class ConstituenciesViewModel @Inject constructor(private val api: JansetuApi) : ViewModel() {
    var items by mutableStateOf<List<Constituency>>(emptyList())
        private set
    var admins by mutableStateOf<List<AdminUser>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)

    init { reload() }

    fun reload() = viewModelScope.launch {
        loading = true
        val r = apiCall { api.constituencies() }
        if (r is ApiResult.Ok) {
            items = r.value; error = null
            (apiCall { api.users(limit = 200) } as? ApiResult.Ok)?.let { u -> admins = u.value.items.filter { it.role == "admin" } }
        } else error = r.userMessage()
        loading = false
    }

    /** Runs a write; on success reloads and calls done(), else shows the server's reason. */
    fun write(call: suspend () -> Any, done: () -> Unit) = viewModelScope.launch {
        loading = true
        val r = apiCall { call() }
        loading = false
        if (r is ApiResult.Ok) { error = null; done(); reload() } else error = r.userMessage()
    }

    fun add(code: String, nameMr: String, nameEn: String, acNo: String, done: () -> Unit) =
        write({ api.createConstituency(ConstituencyIn(code.trim(), nameMr.trim(), nameEn.trim().ifEmpty { null }, acNo.trim().toIntOrNull())) }, done)

    fun save(c: Constituency, edits: JsonObject, done: () -> Unit) =
        if (edits.isEmpty()) done() else { write({ api.updateConstituency(c.id, edits) }, done); Unit }

    fun setActive(c: Constituency, on: Boolean, done: () -> Unit) =
        write({ api.updateConstituency(c.id, JsonObject(mapOf("is_active" to JsonPrimitive(on)))) }, done)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConstituenciesScreen(onBack: () -> Unit, onAddAdmin: () -> Unit, vm: ConstituenciesViewModel = hiltViewModel()) {
    var editing by remember { mutableStateOf<Constituency?>(null) }
    var adding by remember { mutableStateOf(false) }
    val active = vm.items.count { it.isActive }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Constituencies") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                actions = {
                    IconButton(onClick = { vm.reload() }) { Icon(Icons.Default.Refresh, "Refresh") }
                    IconButton(onClick = { vm.error = null; adding = true }, enabled = active < CONSTITUENCY_LIMIT) {
                        Icon(Icons.Default.Add, "Add constituency")
                    }
                },
            )
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            if (vm.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                item { ErrorText(if (editing == null && !adding) vm.error else null) }
                items(vm.items, key = { it.id }) { c ->
                    Card(Modifier.fillMaxWidth().clickable { vm.error = null; editing = c }) {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(constituencyName(c), style = MaterialTheme.typography.titleMedium)
                            Text("%,d voters · %d users".format(c.voterCount, c.userCount) + if (!c.isActive) " · switched off" else "")
                            val admins = vm.admins.filter { it.localBodyId == c.id }
                            Text(if (admins.isEmpty()) "No admin yet" else "Admin: " + admins.joinToString { it.fullNameEn },
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
                item {
                    Text("$active of $CONSTITUENCY_LIMIT constituencies in use. Parts and Village Panchayats come with the roll import.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                item { OutlinedButton(onClick = onAddAdmin, modifier = Modifier.fillMaxWidth()) { Text("Add admin") } }
            }
        }
    }

    if (adding) ConstituencyDialog(null, vm.error, onDismiss = { adding = false }) { code, mr, en, ac ->
        vm.add(code, mr, en, ac) { adding = false }
    }
    editing?.let { c ->
        ConstituencyDialog(c, vm.error, onDismiss = { editing = null },
            onSwitch = { vm.setActive(c, !c.isActive) { editing = null } }) { _, mr, en, ac ->
            vm.save(c, SettingsRules.constituencyEdits(mr, en, ac, c)) { editing = null }
        }
    }
}

fun constituencyName(c: Constituency) = (c.nameEn ?: c.nameMr) + (c.acNo?.let { " (AC $it)" } ?: "")

@Composable
private fun ConstituencyDialog(
    c: Constituency?, serverError: String?, onDismiss: () -> Unit, onSwitch: (() -> Unit)? = null,
    onSave: (code: String, nameMr: String, nameEn: String, acNo: String) -> Unit,
) {
    var code by remember { mutableStateOf(c?.code ?: "") }
    var nameMr by remember { mutableStateOf(c?.nameMr ?: "") }
    var nameEn by remember { mutableStateOf(c?.nameEn ?: "") }
    var acNo by remember { mutableStateOf(c?.acNo?.toString() ?: "") }
    var problem by remember { mutableStateOf<String?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (c == null) "Add constituency" else "Constituency") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                // The code ties roll imports to the constituency: set once.
                OutlinedTextField(code, { code = it.take(40) }, label = { Text("Code") }, singleLine = true, enabled = c == null)
                OutlinedTextField(nameMr, { nameMr = it.take(200) }, label = { Text("Name in Marathi") }, singleLine = true)
                OutlinedTextField(nameEn, { nameEn = it.take(200) }, label = { Text("Name in English") }, singleLine = true)
                OutlinedTextField(acNo, { acNo = it.filter(Char::isDigit).take(4) }, label = { Text("AC number") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                if (c != null && onSwitch != null) Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("In use", Modifier.weight(1f))
                    Switch(c.isActive, { onSwitch() })
                }
                if (c != null && c.isActive) Text("Switching it off hides it from new work; its voters and users stay.",
                    style = MaterialTheme.typography.bodySmall)
                ErrorText(problem ?: serverError)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                problem = SettingsRules.checkConstituency(code, nameMr, acNo)
                if (problem == null) onSave(code, nameMr, nameEn, acNo)
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
