package com.jansetu.app.ui.slip

import android.graphics.Bitmap
import android.widget.Toast
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.FieldRepository
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.sync.SyncKeys
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.EmptyState
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

/** A voter's slip, ready to show and share. Null [bitmap]: slips are switched off for the workspace. */
data class Slip(val content: SlipContent, val bitmap: Bitmap?, val mobile: String?, val fileName: String)

@HiltViewModel
class SlipViewModel @Inject constructor(
    handle: SavedStateHandle,
    local: LocalDb,
    private val field: FieldRepository,
    private val scheduler: SyncScheduler,
) : ViewModel() {
    private val voterId: String = checkNotNull(handle["id"])
    private val db = local.db

    val slip = flow {
        val v = db.voters().voter(voterId) ?: return@flow
        val booth = v.boothId?.let { db.areas().areas(listOf(it)).firstOrNull() }
        val settings = SlipSettings.parse(db.syncState().get(SyncKeys.SETTINGS))
        val content = slipContent(v, booth, settings)
        emit(Slip(content, if (settings.featureSlips) drawSlip(content) else null,
            db.voters().survey(voterId)?.mobile1, "voter-slip-part${v.partNo}-serial${v.serialNo}"))
    }.flowOn(Dispatchers.Default).stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)

    /** The share is logged offline (outbox `slip_event`) and sent with the next sync. */
    fun logShare(channel: String) = viewModelScope.launch {
        field.logSlip(voterId, channel)
        scheduler.syncNow()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SlipScreen(onBack: () -> Unit, vm: SlipViewModel = hiltViewModel()) {
    val slip by vm.slip.collectAsStateWithLifecycle()
    val context = LocalContext.current
    Scaffold(topBar = {
        TopAppBar(
            title = { Text("Voter slip") },
            navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
        )
    }) { padding ->
        val s = slip ?: return@Scaffold
        val bmp = s.bitmap
        if (bmp == null) {
            EmptyState("Voter slips are switched off for this workspace.", Modifier.padding(padding))
            return@Scaffold
        }
        Column(
            Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Image(bmp.asImageBitmap(), "Voter slip", Modifier.fillMaxWidth(), contentScale = ContentScale.FillWidth)
            if (s.content.missing.isNotEmpty()) Text(
                "Not on the slip yet: ${s.content.missing.joinToString(" and ")}. An admin sets them in Election & candidate; " +
                    "they come with the next sync.",
                color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall,
            )
            if (s.mobile == null) Text(
                "No mobile number: WhatsApp opens and you pick the chat.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Button(onClick = {
                if (shareSlipOnWhatsApp(context, bmp, s.mobile)) vm.logShare("whatsapp")
                else {
                    Toast.makeText(context, "WhatsApp is not on this phone.", Toast.LENGTH_SHORT).show()
                    shareSlipAnywhere(context, bmp)
                }
            }, modifier = Modifier.fillMaxWidth()) { Text("Share on WhatsApp") }
            OutlinedButton(onClick = {
                if (saveSlipToPictures(context, bmp, s.fileName)) {
                    Toast.makeText(context, "Saved in Pictures/JANSETU", Toast.LENGTH_SHORT).show()
                } else shareSlipAnywhere(context, bmp) // Android 8-9: save through the share sheet (Files, Drive)
            }, modifier = Modifier.fillMaxWidth()) { Text("Save as image") }
        }
    }
}
