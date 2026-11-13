package com.jansetu.app.ui.more

import android.os.Build
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.BuildConfig
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.ProblemReportIn
import com.jansetu.app.data.remote.apiCallNoBody
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.data.sync.SyncKeys
import com.jansetu.app.ui.common.BusyButton
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.istTime
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

const val PROBLEM_MAX = 2000

@HiltViewModel
class HelpViewModel @Inject constructor(private val api: JansetuApi, local: LocalDb) : ViewModel() {
    val lastSync = local.db.syncState().flow(SyncKeys.LAST_SYNC_AT)
    val unsent = local.db.outbox().queuedCount()
    var text by mutableStateOf("")
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var sent by mutableStateOf(false)
        private set

    /** Sends the report with the app version and phone model (online). The text stays if it fails. */
    fun send() {
        val body = text.trim()
        if (body.isEmpty()) { error = "Write what went wrong."; return }
        if (busy) return
        busy = true
        viewModelScope.launch {
            val r = apiCallNoBody {
                api.reportProblem(ProblemReportIn(body, BuildConfig.VERSION_CODE, "${Build.MANUFACTURER} ${Build.MODEL}".take(200)))
            }
            busy = false
            if (r is ApiResult.Ok) { text = ""; error = null; sent = true } else error = r.userMessage()
        }
    }

    fun typed(s: String) { text = s.take(PROBLEM_MAX); sent = false }
}

@Composable
fun HelpScreen(onBack: () -> Unit, vm: HelpViewModel = hiltViewModel()) {
    val lastSync by vm.lastSync.collectAsStateWithLifecycle(null)
    val unsent by vm.unsent.collectAsStateWithLifecycle(0)
    MorePage("Help", onBack) {
        Column(
            Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                "• Search, surveys, Kutumbs and visits work without internet. They are sent when the phone syncs: " +
                    "every 15 minutes, or tap Sync now.\n" +
                    "• If something is not sent, open Sync to see why.\n" +
                    "• A new phone, a forgotten password or a lost phone: ask your admin.",
                style = MaterialTheme.typography.bodyMedium,
            )
            HorizontalDivider()
            Text("App: JANSETU ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})", style = MaterialTheme.typography.bodyMedium)
            Text("Phone: ${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE}", style = MaterialTheme.typography.bodyMedium)
            Text("Last sync: ${istTime(lastSync) ?: "not yet"} · not sent: $unsent", style = MaterialTheme.typography.bodyMedium)
            HorizontalDivider()
            Text("Report a problem", style = MaterialTheme.typography.titleMedium)
            Text(
                "Your admin reads it. The app version and phone model are sent with it. Needs internet.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedTextField(
                vm.text, vm::typed, Modifier.fillMaxWidth(), minLines = 4,
                label = { Text("What went wrong?") },
                supportingText = { Text("${vm.text.length} / $PROBLEM_MAX") },
            )
            ErrorText(vm.error)
            if (vm.sent) Text("Sent. Thank you.", color = MaterialTheme.colorScheme.primary)
            BusyButton("Send report", vm.busy, enabled = vm.text.isNotBlank(), onClick = vm::send)
        }
    }
}
