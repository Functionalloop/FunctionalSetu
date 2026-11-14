package com.jansetu.app.ui.admin

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.Session
import com.jansetu.app.data.remote.AdminDevice
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.BlockDeviceRequest
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.istTime
import com.jansetu.app.ui.home.roleLabel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Roles that see Users & devices and Booths & karyakartas (the server checks again: admin and above). */
val PHONE_ADMIN_ROLES = setOf("admin", "super_admin")

enum class PhoneFilter(val label: String, val status: String?) {
    Waiting("Waiting", "pending"), Approved("Approved", "approved"), Blocked("Blocked", "blocked"), All("All", null)
}

/**
 * Phones of the admin's constituency (super admin: all), from the server; needs internet.
 * Built early (6.5) for the demo; since 9.6 the Phones tab of Users & devices.
 */
@HiltViewModel
class PhonesViewModel @Inject constructor(private val api: JansetuApi) : ViewModel() {
    var filter by mutableStateOf(PhoneFilter.Waiting)
        private set
    var items by mutableStateOf<List<AdminDevice>>(emptyList())
        private set
    var nextCursor by mutableStateOf<String?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var loaded by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    /** Phone ids with an approve / block call on its way. */
    var busy by mutableStateOf<Set<String>>(emptySet())
        private set

    fun select(f: PhoneFilter) {
        if (f == filter) return
        filter = f
        items = emptyList()
        loaded = false
        viewModelScope.launch { reload() }
    }

    /** First page again (the list is short: phones of one constituency). */
    suspend fun reload() {
        loading = true
        val wanted = filter
        val r = apiCall { api.devices(status = wanted.status, limit = PAGE) }
        loading = false
        if (wanted != filter) return // the filter changed while this call ran
        when (r) {
            is ApiResult.Ok -> { items = r.value.items; nextCursor = r.value.nextCursor; error = null; loaded = true }
            else -> error = r.userMessage()
        }
    }

    fun loadMore() = viewModelScope.launch {
        val cursor = nextCursor ?: return@launch
        loading = true
        val wanted = filter
        val r = apiCall { api.devices(status = wanted.status, cursor = cursor, limit = PAGE) }
        loading = false
        if (wanted != filter) return@launch
        when (r) {
            is ApiResult.Ok -> { items = items + r.value.items; nextCursor = r.value.nextCursor; error = null }
            else -> error = r.userMessage()
        }
    }

    /** While the Waiting list is open, a newly waiting phone shows up by itself. */
    suspend fun poll() {
        while (true) {
            reload()
            delay(if (filter == PhoneFilter.Waiting) 10_000 else 60_000)
        }
    }

    fun approve(d: AdminDevice) = act(d) { api.approveDevice(d.id) }

    fun block(d: AdminDevice, reason: String) =
        act(d) { api.blockDevice(d.id, BlockDeviceRequest(reason.trim().ifBlank { null })) }

    private fun act(d: AdminDevice, call: suspend () -> AdminDevice) = viewModelScope.launch {
        busy = busy + d.id
        val r = apiCall { call() }
        busy = busy - d.id
        when (r) {
            is ApiResult.Ok -> { error = null; reload() }
            else -> error = r.userMessage()
        }
    }

    private companion object { const val PAGE = 100 }
}

/** The phone list with its filters and the block dialog: the Phones tab of Users & devices (9.6). */
@Composable
fun PhonesContent(session: Session, vm: PhonesViewModel, modifier: Modifier = Modifier) {
    var blocking by remember { mutableStateOf<AdminDevice?>(null) }
    LaunchedEffect(Unit) { vm.poll() }

    run {
        Column(modifier.fillMaxSize()) {
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                PhoneFilter.entries.forEach { f -> FilterChip(vm.filter == f, { vm.select(f) }, { Text(f.label) }) }
            }
            if (vm.loading) LinearProgressIndicator(Modifier.fillMaxWidth()) else Spacer(Modifier.padding(2.dp))
            Column(Modifier.padding(horizontal = 16.dp)) { ErrorText(vm.error) }

            if (vm.loaded && vm.items.isEmpty()) {
                EmptyState(
                    when (vm.filter) {
                        PhoneFilter.Waiting -> "No phone is waiting for approval.\nThis list checks again every 10 seconds."
                        else -> "No phones here."
                    },
                )
            }
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(vm.items, key = { it.id }) { d ->
                    PhoneCard(
                        d = d,
                        isMine = d.userId == session.user.id,
                        busy = d.id in vm.busy,
                        onApprove = { vm.approve(d) },
                        onBlock = { blocking = d },
                    )
                }
                if (vm.nextCursor != null) item {
                    OutlinedButton(onClick = { vm.loadMore() }, enabled = !vm.loading, modifier = Modifier.fillMaxWidth()) { Text("Load more") }
                }
            }
        }
    }

    blocking?.let { d ->
        var reason by remember(d.id) { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { blocking = null },
            title = { Text("Block this phone?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(
                        "${d.fullNameEn ?: d.username ?: "This user"} can no longer use JANSETU on this phone. " +
                            "The next time it reaches the server, the voter data on it is deleted, " +
                            "including changes not yet sent. Approve it again to undo.",
                    )
                    OutlinedTextField(
                        value = reason, onValueChange = { reason = it.take(500) },
                        label = { Text("Reason (optional)") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = { TextButton(onClick = { vm.block(d, reason); blocking = null }) { Text("Block") } },
            dismissButton = { TextButton(onClick = { blocking = null }) { Text("Cancel") } },
        )
    }
}

@Composable
fun PhoneCard(d: AdminDevice, isMine: Boolean, busy: Boolean, onApprove: () -> Unit, onBlock: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(d.fullNameEn ?: d.username ?: "Unknown user", style = MaterialTheme.typography.titleMedium)
            Text(
                listOfNotNull(d.username, d.role?.let(::roleLabel)).joinToString(" · ") + if (isMine) " · this is you" else "",
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                listOfNotNull(d.model, d.osVersion, d.appVersionCode?.let { "app $it" }).joinToString(" · ").ifBlank { "Unknown phone" },
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(statusLine(d), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (d.blockedReason != null) Text("Reason: ${d.blockedReason}", style = MaterialTheme.typography.bodySmall)

            Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (d.status != "approved") {
                    Button(onClick = onApprove, enabled = !busy) { Text(if (d.status == "pending") "Approve" else "Approve again") }
                }
                // Blocking your own phone would lock you out of this screen.
                if (d.status != "blocked" && d.status != "wiped" && !isMine) {
                    OutlinedButton(onClick = onBlock, enabled = !busy) { Text("Block") }
                }
            }
        }
    }
}

private fun statusLine(d: AdminDevice): String = when (d.status) {
    "pending" -> "Waiting since ${istTime(d.requestedAt) ?: "?"}"
    "approved" -> "Approved ${istTime(d.decidedAt) ?: ""}".trim() + (d.lastSeenAt?.let { " · last used ${istTime(it)}" } ?: "")
    "blocked" -> "Blocked ${istTime(d.decidedAt) ?: ""}".trim()
    "wiped" -> "Blocked, data deleted from the phone"
    else -> d.status
}
