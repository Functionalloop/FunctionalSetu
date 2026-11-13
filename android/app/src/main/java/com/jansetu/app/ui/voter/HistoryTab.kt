package com.jansetu.app.ui.voter

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.HistoryChange
import com.jansetu.app.data.remote.HistoryEntry
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.istTime
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import javax.inject.Inject

/** Tab "Information Updation" (7.6): the voter's history from the server. Not stored on the phone: needs internet. */
@HiltViewModel
class HistoryViewModel @Inject constructor(handle: SavedStateHandle, private val api: JansetuApi) : ViewModel() {
    private val voterId: String = checkNotNull(handle["id"])

    var items by mutableStateOf<List<HistoryEntry>>(emptyList())
        private set
    var nextCursor by mutableStateOf<String?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var loaded by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    fun load(more: Boolean = false) = viewModelScope.launch {
        if (loading) return@launch
        val cursor = if (more) nextCursor ?: return@launch else null
        loading = true
        val r = apiCall { api.history(voterId, cursor, PAGE) }
        loading = false
        when (r) {
            is ApiResult.Ok -> {
                items = if (more) items + r.value.items else r.value.items
                nextCursor = r.value.nextCursor
                error = null
                loaded = true
            }
            is ApiResult.Offline -> error = "Information Updation needs internet. Connect and tap Try again."
            else -> error = r.userMessage()
        }
    }

    private companion object { const val PAGE = 50 }
}

@Composable
fun HistoryTab(vm: HistoryViewModel = hiltViewModel()) {
    LaunchedEffect(Unit) { if (!vm.loaded) vm.load() }
    when {
        !vm.loaded && vm.loading -> Column(Modifier.fillMaxSize(), Arrangement.Center, Alignment.CenterHorizontally) {
            CircularProgressIndicator()
        }
        !vm.loaded -> Column(Modifier.fillMaxSize().padding(24.dp), Arrangement.Center, Alignment.CenterHorizontally) {
            Text(vm.error ?: "", color = MaterialTheme.colorScheme.error)
            OutlinedButton(onClick = { vm.load() }, modifier = Modifier.padding(top = 12.dp)) { Text("Try again") }
        }
        vm.items.isEmpty() -> EmptyState("No updates yet. Survey, Kutumb, visit and voted changes show here.")
        else -> LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(vm.items) { HistoryCard(it) }
            item {
                vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                if (vm.nextCursor != null) OutlinedButton(
                    onClick = { vm.load(more = true) }, enabled = !vm.loading, modifier = Modifier.fillMaxWidth(),
                ) { Text(if (vm.loading) "Loading…" else "Show older") }
            }
        }
    }
}

@Composable
private fun HistoryCard(e: HistoryEntry) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(entryTitle(e), style = MaterialTheme.typography.titleSmall)
            Text(
                listOfNotNull(e.by?.fullNameEn ?: "System", istTime(e.at)).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            changeLines(e).forEach { Text(it, style = MaterialTheme.typography.bodyMedium) }
        }
    }
}

// --- wording (plain functions, tested in HistoryTextTest) ------------------------------------

private val KIND = mapOf(
    "survey" to "Survey", "family" to "Kutumb Connect", "visit" to "Visit", "voted" to "Voted",
    "roll_edit" to "Roll correction", "slip" to "Voter slip", "new_voter_match" to "Matched to a new voter",
)

fun entryTitle(e: HistoryEntry): String {
    val kind = KIND[e.kind] ?: e.kind.replace('_', ' ').replaceFirstChar { it.uppercase() }
    return when {
        e.kind == "slip" -> "$kind shared (${CHANNEL[e.action] ?: e.action})"
        e.kind == "visit" -> kind
        e.action == "insert" -> if (e.kind == "survey") "Survey: first save" else "$kind: added"
        e.action == "delete" -> "$kind: removed"
        else -> "$kind: updated"
    }
}

private val CHANNEL = mapOf("pdf" to "PDF", "print" to "print", "whatsapp" to "WhatsApp", "sms" to "SMS", "bluetooth" to "Bluetooth")

private val FIELD = mapOf(
    "mobile_1" to "Mobile", "mobile_2" to "Second mobile", "email" to "Email", "dob" to "Date of birth",
    "caste_id" to "Caste", "profession_id" to "Profession", "society" to "Society", "flat_no" to "Flat no.",
    "has_new_address" to "New address", "new_address_en" to "New address", "new_address_mr" to "New address (Marathi)",
    "demands" to "Demands", "notes" to "Notes", "color_tag_id" to "Colour tag", "is_influencer" to "Influencer",
    "influencer_type_id" to "Influencer type", "in_self_help_group" to "Self help group",
    "self_help_group_name" to "Self help group name", "ration_card" to "Ration card", "karyakarta_id" to "Karyakarta",
    "dead_marked" to "Marked dead", "dead_marked_by" to "Marked dead by", "dead_confirmed_by" to "Death confirmed by",
    "family_id" to "Kutumb", "outcome" to "Result", "revisit_at" to "Come again on", "note" to "Note",
    "is_voted" to "Voted", "source" to "Marked from", "house_no" to "House no.", "booth_id" to "Part",
    "ward_id" to "Village Panchayat", "section_id" to "Section", "serial_no" to "Serial no.", "epic_no" to "EPIC no.",
    "gender" to "Gender", "age" to "Age", "roll_status" to "Roll status", "relative_name_en" to "Relative's name",
    "first_name_en" to "First name", "middle_name_en" to "Middle name", "last_name_en" to "Last name",
)

private val OUTCOME = mapOf("met" to "Met", "not_home" to "Not home", "revisit" to "Come again", "shifted" to "Shifted")

fun fieldLabel(key: String) = FIELD[key] ?: key.replace('_', ' ').replaceFirstChar { it.uppercase() }

/** One value as people read it: the server's label for a reference, Yes / No, Indian time for a time. */
fun valueText(key: String, value: kotlinx.serialization.json.JsonElement?, label: String?): String {
    if (label != null) return label
    if (value == null || value is JsonNull) return "—"
    val p = value as? JsonPrimitive ?: return value.toString()
    p.booleanOrNull?.let { if (!p.isString) return if (it) "Yes" else "No" }
    val s = p.content
    if (key == "outcome") return OUTCOME[s] ?: s
    if (p.isString && s.length > 10 && s[10] == 'T') return istTime(s) ?: s
    return s
}

/** "Field: old → new" lines; lat / lng become one "Location" line. */
fun changeLines(e: HistoryEntry): List<String> {
    val lines = mutableListOf<String>()
    var location = false
    for ((key, ch) in e.changes) {
        if (key == "lat" || key == "lng") { location = true; continue }
        lines += line(key, ch, e.action)
    }
    if (location) lines += if (e.action == "insert") "Location saved" else "Location changed"
    return lines
}

private fun line(key: String, ch: HistoryChange, action: String): String {
    val new = valueText(key, ch.new, ch.newLabel)
    return when (action) {
        "update" -> "${fieldLabel(key)}: ${valueText(key, ch.old, ch.oldLabel)} → $new"
        "delete" -> "${fieldLabel(key)}: ${valueText(key, ch.old, ch.oldLabel)}"
        else -> "${fieldLabel(key)}: $new"
    }
}
