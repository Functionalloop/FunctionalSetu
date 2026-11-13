package com.jansetu.app.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.Session
import com.jansetu.app.ui.newvoter.ENR_TITLE
import androidx.compose.material.icons.filled.PersonAdd
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.sync.SyncKeys
import com.jansetu.app.ui.common.istTime
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import javax.inject.Inject

data class HomeCounts(
    val voters: Int = 0,
    val surveyed: Int = 0,
    val withMobile: Int = 0,
    val unsent: Int = 0,
    val lastSync: String? = null,
)

/** Every number comes from the phone's own database (works in airplane mode). */
@HiltViewModel
class HomeViewModel @Inject constructor(local: LocalDb) : ViewModel() {
    private val db = local.db
    val counts = combine(
        db.voters().voterCount(),
        db.voters().surveyedCount(),
        db.voters().withMobileCount(),
        db.outbox().queuedCount(),
        db.syncState().flow(SyncKeys.LAST_SYNC_AT),
    ) { v, s, m, q, last -> HomeCounts(v, s, m, q, last) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), HomeCounts())
}

@Composable
fun HomeScreen(
    session: Session, onSearch: () -> Unit, onSync: () -> Unit, onNewVoters: () -> Unit,
    vm: HomeViewModel = hiltViewModel(),
) {
    val c by vm.counts.collectAsStateWithLifecycle()
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(session.workspace.nameEn, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.secondary)
        Text("Hello, ${session.user.fullNameEn}", style = MaterialTheme.typography.headlineSmall)
        Text(roleLabel(session.user.role), color = MaterialTheme.colorScheme.onSurfaceVariant)

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            CountCard("Voters", c.voters, Modifier.weight(1f))
            CountCard("Surveyed", c.surveyed, Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            CountCard("With mobile", c.withMobile, Modifier.weight(1f))
            CountCard("Not sent yet", c.unsent, Modifier.weight(1f))
        }
        if (c.voters > 0) {
            val pct = c.surveyed * 100 / c.voters
            Text("$pct% of voters surveyed", style = MaterialTheme.typography.bodyLarge)
        }
        Text(
            "Last sync: " + (istTime(c.lastSync) ?: "not yet"),
            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Button(onClick = onSearch, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Default.Search, null); Text("  Search voters")
        }
        if (session.canSurvey) OutlinedButton(onClick = onNewVoters, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Default.PersonAdd, null); Text("  $ENR_TITLE")
        }
        OutlinedButton(onClick = onSync, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Default.Sync, null); Text("  Sync")
        }
    }
}

@Composable
private fun CountCard(label: String, value: Int, modifier: Modifier) {
    Card(modifier, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
        Column(Modifier.padding(16.dp)) {
            Text("%,d".format(value), style = MaterialTheme.typography.headlineMedium)
            Text(label, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

fun roleLabel(role: String) = when (role) {
    "super_admin" -> "Super admin"
    "admin" -> "Admin"
    "supervisor" -> "Supervisor"
    "surveyor" -> "Surveyor"
    "booth_agent" -> "Booth agent"
    else -> role
}
