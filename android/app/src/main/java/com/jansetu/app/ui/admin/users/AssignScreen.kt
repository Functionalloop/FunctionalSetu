package com.jansetu.app.ui.admin.users

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.remote.AdminUser
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.AssignmentsIn
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.home.roleLabel
import com.jansetu.app.ui.search.AreaPicker
import com.jansetu.app.ui.search.areaLabel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Who works where in one area, and who may be ticked for it (a part or a whole Village Panchayat). */
private data class Picking(val area: AreaEntity, val title: String, val roles: List<String>)

/**
 * Booths & karyakartas (9.6): per Village Panchayat, the workers of each part and the panchayat's own
 * supervisors. It turns the per-user assignment list around; saving sends PUT /users/{id}/assignments for
 * each user whose list changes. Needs internet; the areas come from this phone's download.
 */
@HiltViewModel
class AssignViewModel @Inject constructor(private val api: JansetuApi, private val local: LocalDb) : ViewModel() {
    var areas by mutableStateOf<List<AreaEntity>>(emptyList())
        private set
    var users by mutableStateOf<List<AdminUser>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init { reload() }

    fun reload() = viewModelScope.launch {
        loading = true
        areas = local.db.areas().all()
        val r = apiCall { api.users(limit = 200) }
        loading = false
        when (r) {
            is ApiResult.Ok -> { users = r.value.items; error = null }
            else -> error = r.userMessage()
        }
    }

    fun constituencyOf(areaId: String): String? = UserRules.constituencyOf(areaId, areas.associateBy { it.id })

    /** One PUT per changed user; stops at the first refusal and shows it. */
    fun save(areaId: String, chosen: Set<String>) = viewModelScope.launch {
        loading = true
        for ((userId, ids) in UserRules.changes(users, areaId, chosen)) {
            val r = apiCall { api.setAssignments(userId, AssignmentsIn(ids)) }
            if (r !is ApiResult.Ok) {
                val who = users.firstOrNull { it.id == userId }?.fullNameEn ?: "a user"
                error = "Not saved for $who: ${r.userMessage()}"
                loading = false
                reload()
                return@launch
            }
        }
        loading = false
        reload()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AssignScreen(onBack: () -> Unit, vm: AssignViewModel = hiltViewModel()) {
    var wardId by rememberSaveable { mutableStateOf<String?>(null) }
    var picking by remember { mutableStateOf<Picking?>(null) }
    val wards = vm.areas.filter { it.level == "ward" }
    val ward = wards.firstOrNull { it.id == wardId } ?: wards.firstOrNull()
    val parts = vm.areas.filter { it.level == "booth" && it.parentId == ward?.id }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Booths & karyakartas") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                actions = { IconButton(onClick = { vm.reload() }) { Icon(Icons.Default.Refresh, "Refresh") } },
            )
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            if (vm.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                AreaPicker("Village Panchayat", wards, ward?.id, allowAll = false) { wardId = it }
                ErrorText(vm.error)
            }
            if (ward == null) {
                Text("No Village Panchayats on this phone. Run Sync first.", Modifier.padding(16.dp))
                return@Column
            }
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item(key = "ward") {
                    AreaCard(
                        title = "Whole Village Panchayat",
                        hint = "Supervisor of this panchayat: sees all its parts.",
                        people = UserRules.assignedTo(vm.users, ward.id),
                        button = "Change",
                        enabled = !vm.loading,
                    ) { picking = Picking(ward, "Village Panchayat ${areaLabel(ward)}", listOf("supervisor")) }
                }
                items(parts, key = { it.id }) { p ->
                    AreaCard(
                        title = "Part ${areaLabel(p)}",
                        hint = null,
                        people = UserRules.assignedTo(vm.users, p.id),
                        button = "Edit",
                        enabled = !vm.loading,
                    ) { picking = Picking(p, "Part ${areaLabel(p)}", listOf("surveyor", "booth_agent")) }
                }
            }
        }
    }

    picking?.let { pk ->
        val candidates = UserRules.candidates(vm.users, pk.area.id, vm.constituencyOf(pk.area.id), pk.roles)
        var ticked by remember(pk.area.id) { mutableStateOf(UserRules.assignedTo(vm.users, pk.area.id).map { it.id }.toSet()) }
        AlertDialog(
            onDismissRequest = { picking = null },
            title = { Text(pk.title) },
            text = {
                LazyColumn(Modifier.heightIn(max = 420.dp)) {
                    items(candidates, key = { it.id }) { u ->
                        TickRow("${u.fullNameEn} · ${roleLabel(u.role)}" + if (!u.isActive) " · switched off" else "", u.id in ticked) {
                            ticked = if (u.id in ticked) ticked - u.id else ticked + u.id
                        }
                    }
                    if (candidates.isEmpty()) item {
                        Text("Nobody to choose. Add a ${pk.roles.joinToString(" or ") { roleLabel(it).lowercase() }} " +
                            "in Users & devices first.")
                    }
                }
            },
            confirmButton = { TextButton(onClick = { vm.save(pk.area.id, ticked); picking = null }) { Text("Save") } },
            dismissButton = { TextButton(onClick = { picking = null }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun AreaCard(title: String, hint: String?, people: List<AdminUser>, button: String, enabled: Boolean, onEdit: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                TextButton(onClick = onEdit, enabled = enabled) { Text(button) }
            }
            if (hint != null) Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (people.isEmpty()) Text("Nobody assigned", color = MaterialTheme.colorScheme.error)
            people.forEach { u ->
                Text("${u.fullNameEn} · ${roleLabel(u.role)}" + if (!u.isActive) " · switched off" else "")
            }
        }
    }
}
