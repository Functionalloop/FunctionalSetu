package com.jansetu.app.ui.voter

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Message
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.LocationFix
import com.jansetu.app.data.OutboxRepository
import com.jansetu.app.data.Session
import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.SurveyEntity
import com.jansetu.app.data.local.VoterEntity
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.displayName
import com.jansetu.app.ui.family.KutumbTab
import com.jansetu.app.ui.common.genderLabel
import com.jansetu.app.ui.common.istTime
import com.jansetu.app.ui.common.nameEn
import com.jansetu.app.ui.common.nameMr
import com.jansetu.app.ui.search.areaLabel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.stateIn
import javax.inject.Inject

@HiltViewModel
class VoterViewModel @Inject constructor(
    handle: SavedStateHandle,
    local: LocalDb,
    val outbox: OutboxRepository,
    val location: LocationFix,
    val scheduler: SyncScheduler,
) : ViewModel() {
    val id: String = checkNotNull(handle["id"])
    val db = local.db

    val voter = db.voters().voterFlow(id).stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)
    val survey = db.voters().surveyFlow(id).stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)
    val areas = flow {
        val v = db.voters().voter(id) ?: return@flow
        emit(db.areas().areas(listOfNotNull(v.wardId, v.boothId)).associateBy { it.id })
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyMap())
    val castes = db.lists().entries("caste")
    val professions = db.lists().entries("profession")
    val influencerTypes = db.lists().entries("influencer_type")
    val colorTags = db.lists().colorTags()
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VoterScreen(session: Session, onBack: () -> Unit, onOpen: (String) -> Unit, vm: VoterViewModel = hiltViewModel()) {
    val voter by vm.voter.collectAsStateWithLifecycle()
    val survey by vm.survey.collectAsStateWithLifecycle()
    val areas by vm.areas.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableIntStateOf(0) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(voter?.displayName() ?: "", maxLines = 1) },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            )
        },
    ) { padding ->
        val v = voter ?: return@Scaffold
        Column(Modifier.padding(padding).fillMaxSize()) {
            TabRow(selectedTabIndex = tab) {
                Tab(tab == 0, { tab = 0 }, text = { Text("Details") })
                Tab(tab == 1, { tab = 1 }, text = { Text("Survey") })
                Tab(tab == 2, { tab = 2 }, text = { Text("Kutumb Connect", maxLines = 1) })
            }
            when (tab) {
                0 -> DetailsTab(v, survey, areas)
                1 -> SurveyScreen(vm, v, survey, readOnly = !session.canSurvey)
                else -> KutumbTab(v, canEdit = session.canSurvey, onOpen = onOpen)
            }
        }
    }
}

@Composable
private fun DetailsTab(v: VoterEntity, s: SurveyEntity?, areas: Map<String, AreaEntity>) {
    val context = LocalContext.current
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        v.nameEn()?.let { Text(it, style = MaterialTheme.typography.headlineSmall) }
        v.nameMr()?.let { Text(it, style = MaterialTheme.typography.titleLarge) }
        val relation = when (v.relationType) {
            "father" -> "Father"; "mother" -> "Mother"; "husband" -> "Husband"; "wife" -> "Wife"; null -> null; else -> "Relative"
        }
        val relative = v.relativeNameEn ?: v.relativeNameMr
        if (relation != null && relative != null) Field(relation, relative)
        Field("Age / gender", listOfNotNull(v.age?.toString(), genderLabel(v.gender)).joinToString(" · "))
        Field("EPIC", v.epicNo ?: "–")
        Field("Part / serial", "Part ${v.partNo} · Serial ${v.serialNo}")
        areas[v.wardId]?.let { Field("Ward", areaLabel(it)) }
        areas[v.boothId]?.let { b -> Field("Booth", areaLabel(b) + (b.addressEn?.let { "\n$it" } ?: "")) }
        Field("House", v.houseNo ?: "–")
        (v.addressEn ?: v.addressMr)?.let { Field("Address", it) }
        if (v.rollStatus != "active") Field("Roll status", v.rollStatus.replace('_', ' '))

        listOfNotNull(s?.mobile1, s?.mobile2).forEach { m ->
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                Column(Modifier.padding(12.dp)) {
                    Text(m, style = MaterialTheme.typography.titleMedium)
                    // Three equal buttons; full-size buttons squeezed the last one on narrow phones.
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        ContactButton(Icons.Default.Call, "Call") { context.open(Intent(Intent.ACTION_DIAL, Uri.parse("tel:$m"))) }
                        ContactButton(Icons.Default.Chat, "WhatsApp") { context.open(Intent(Intent.ACTION_VIEW, Uri.parse("https://wa.me/91$m"))) }
                        ContactButton(Icons.AutoMirrored.Filled.Message, "SMS") { context.open(Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:$m"))) }
                    }
                }
            }
        }
        if (s?.mobile1 == null) Text("No mobile number yet. Add it in the Survey tab.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        s?.updatedAt?.let { Text("Survey updated ${istTime(it)}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}

@Composable
private fun RowScope.ContactButton(icon: ImageVector, label: String, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick, modifier = Modifier.weight(1f),
        contentPadding = PaddingValues(horizontal = 6.dp, vertical = 8.dp),
    ) {
        Icon(icon, null, Modifier.size(18.dp))
        Spacer(Modifier.width(4.dp))
        Text(label, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun Field(label: String, value: String) {
    Row {
        Text(label, Modifier.width(110.dp), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, Modifier.fillMaxWidth(), style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
    }
}

/** Hands the action to the phone's own app (dialer, WhatsApp, SMS); no permission needed. */
private fun Context.open(intent: Intent) {
    try {
        startActivity(intent)
    } catch (e: ActivityNotFoundException) {
        Toast.makeText(this, "No app on this phone can do this.", Toast.LENGTH_SHORT).show()
    }
}
