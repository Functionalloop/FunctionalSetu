package com.jansetu.app.ui.share

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
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
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.FieldRepository
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.sync.SyncKeys
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.displayName
import com.jansetu.app.ui.more.MorePage
import com.jansetu.app.ui.slip.SlipSettings
import com.jansetu.app.ui.slip.drawSlip
import com.jansetu.app.ui.slip.shareSlipOnWhatsApp
import com.jansetu.app.ui.slip.slipContent
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import javax.inject.Inject

/** Route argument: voter ids joined by commas (the Kutumb's members, or the voters ticked in Search). */
const val SHARE_ROUTE = "share/{ids}"
fun shareRoute(ids: Collection<String>) = "share/" + ids.joinToString(",")

@HiltViewModel
class ShareViewModel @Inject constructor(
    handle: SavedStateHandle,
    local: LocalDb,
    private val field: FieldRepository,
    private val scheduler: SyncScheduler,
) : ViewModel() {
    private val db = local.db
    private val ids: List<String> = checkNotNull(handle.get<String>("ids")).split(",").filter { it.isNotBlank() }

    var candidates by mutableStateOf<List<ShareTarget>>(emptyList())
        private set
    var ticked by mutableStateOf<Set<String>>(emptySet())
        private set
    /** Voters already sent to on this screen (a Kutumb larger than 5 goes in two rounds). */
    var done by mutableStateOf<Set<String>>(emptySet())
        private set
    var slipsOn by mutableStateOf(true)
        private set
    var sendSlip by mutableStateOf(true)
    var message by mutableStateOf("")
    var run by mutableStateOf<ShareRun?>(null)
        private set
    /** Bumped after each send so the screen redraws the run's progress. */
    var step by mutableStateOf(0)
        private set
    var notice by mutableStateOf<String?>(null)
        private set

    init {
        viewModelScope.launch {
            val voters = db.voters().voters(ids).associateBy { it.id }
            candidates = ids.mapNotNull { id ->
                voters[id]?.let { ShareTarget(id, it.displayName(), db.voters().survey(id)?.mobile1) }
            }
            if (candidates.size <= SHARE_MAX) ticked = candidates.map { it.voterId }.toSet()
            val settings = db.syncState().get(SyncKeys.SETTINGS)
            slipsOn = SlipSettings.parse(settings).featureSlips
            sendSlip = slipsOn
            message = MessageSettings.parse(settings).defaultMessage()
        }
    }

    fun toggle(id: String) {
        if (run != null) return
        val next = tick(ticked, id)
        if (next == null) notice = "At most $SHARE_MAX voters at a time. Send these first, then tick the others."
        else { ticked = next; notice = null }
    }

    fun start() {
        val targets = candidates.filter { it.voterId in ticked }
        if (targets.isEmpty()) { notice = "Tick at least one voter."; return }
        if (!sendSlip && message.isBlank()) { notice = "Write the message first."; return }
        notice = null
        run = ShareRun(targets)
    }

    /** Opens WhatsApp for the next voter: their own slip, or the message. */
    fun sendNext(context: Context) = viewModelScope.launch {
        val r = run ?: return@launch
        val opened = r.sendNext { t -> if (sendSlip) openSlip(context, t) else openMessage(context, t, message.trim()) }
        if (!opened) notice = "WhatsApp is not on this phone."
        step++
        if (r.done) finish(r)
    }

    private suspend fun openSlip(context: Context, t: ShareTarget): Boolean {
        val bmp = withContext(Dispatchers.Default) {
            val v = db.voters().voter(t.voterId) ?: return@withContext null
            val booth = db.areas().areas(listOf(v.boothId)).firstOrNull()
            drawSlip(slipContent(v, booth, SlipSettings.parse(db.syncState().get(SyncKeys.SETTINGS))))
        } ?: return false
        if (!shareSlipOnWhatsApp(context, bmp, t.mobile)) return false
        field.logSlip(t.voterId, "whatsapp") // sent with the next sync, like the single slip (7.7)
        return true
    }

    private fun openMessage(context: Context, t: ShareTarget, text: String): Boolean = try {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://wa.me/91${t.mobile}?text=" + Uri.encode(text))))
        true
    } catch (_: ActivityNotFoundException) {
        false
    }

    private fun finish(r: ShareRun) {
        done = done + r.toSend.map { it.voterId } + r.skipped.map { it.voterId }
        ticked = emptySet()
        if (sendSlip) scheduler.syncNow()
    }

    /** Back to ticking, for the next round. */
    fun newRound() { run = null; notice = null }
}

/**
 * 7.12: Share on WhatsApp, at most 5 voters at a time, through the phone's own WhatsApp (no API).
 * From the Kutumb tab (its members) and from Select many in Search (5 or fewer ticked).
 */
@Composable
fun ShareWhatsAppScreen(onBack: () -> Unit, vm: ShareViewModel = hiltViewModel()) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val run = vm.run
    MorePage("Share on WhatsApp", onBack) {
        Column(
            Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (run == null) {
                Text("Tick up to $SHARE_MAX voters. WhatsApp opens for each one in turn; press send there and come back.",
                    style = MaterialTheme.typography.bodyMedium)
                vm.candidates.forEach { t ->
                    val sentAlready = t.voterId in vm.done
                    Row(Modifier.fillMaxWidth().clickable { vm.toggle(t.voterId) }, verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = t.voterId in vm.ticked, onCheckedChange = { vm.toggle(t.voterId) })
                        Column(Modifier.weight(1f)) {
                            Text(t.name, style = MaterialTheme.typography.bodyLarge)
                            Text(
                                listOfNotNull(t.mobile ?: "No mobile: will be skipped", "Sent".takeIf { sentAlready }).joinToString(" · "),
                                style = MaterialTheme.typography.bodySmall,
                                color = if (t.mobile == null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
                Text("${vm.ticked.size} of $SHARE_MAX ticked", style = MaterialTheme.typography.labelLarge)
                HorizontalDivider()
                Text("Send", style = MaterialTheme.typography.titleMedium)
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.clickable(enabled = vm.slipsOn) { vm.sendSlip = true }) {
                    RadioButton(selected = vm.sendSlip, onClick = { vm.sendSlip = true }, enabled = vm.slipsOn)
                    Text(if (vm.slipsOn) "Each voter's own slip" else "Voter slips are switched off")
                }
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.clickable { vm.sendSlip = false }) {
                    RadioButton(selected = !vm.sendSlip, onClick = { vm.sendSlip = false })
                    Text("A message")
                }
                if (!vm.sendSlip) OutlinedTextField(
                    vm.message, { vm.message = it }, Modifier.fillMaxWidth(), minLines = 4,
                    label = { Text("Message") },
                    supportingText = { Text("From the election settings; change it if you like.") },
                )
                vm.notice?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Button(onClick = vm::start, modifier = Modifier.fillMaxWidth(), enabled = vm.ticked.isNotEmpty()) {
                    Text("Start")
                }
            } else {
                vm.step // read so the screen redraws after each send
                Text("Sent ${run.sent} of ${run.toSend.size}" +
                    (if (run.skipped.isNotEmpty()) " · ${run.skipped.size} skipped (no mobile)" else ""),
                    style = MaterialTheme.typography.titleMedium)
                run.skipped.forEach { Text("Skipped: ${it.name}", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                vm.notice?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                val next = run.current
                if (next != null) {
                    Button(onClick = { scope.launch { vm.sendNext(context) } }, modifier = Modifier.fillMaxWidth()) {
                        Text("Open WhatsApp: ${next.name}")
                    }
                    Text("Press send in WhatsApp, then come back here for the next one.", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                } else {
                    Text("Done.", style = MaterialTheme.typography.bodyLarge)
                    if (vm.candidates.any { it.voterId !in vm.done }) {
                        OutlinedButton(onClick = vm::newRound, modifier = Modifier.fillMaxWidth()) { Text("Send to the others") }
                    }
                    Button(onClick = onBack, modifier = Modifier.fillMaxWidth()) { Text("Close") }
                }
            }
        }
    }
}
