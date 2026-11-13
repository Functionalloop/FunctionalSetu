package com.jansetu.app.ui.more

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Badge
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.remote.Announcement
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.apiCallNoBody
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.istTime
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Announcements from the admins for this user's area; online only. Opening an unread one marks it read. */
@HiltViewModel
class AnnouncementsViewModel @Inject constructor(private val api: JansetuApi) : ViewModel() {
    var items by mutableStateOf<List<Announcement>>(emptyList())
        private set
    var nextCursor by mutableStateOf<String?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var loaded by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    /** Ids opened on this screen (shown in full). */
    var open by mutableStateOf<Set<String>>(emptySet())
        private set

    fun load(more: Boolean = false) = viewModelScope.launch {
        if (loading) return@launch
        val cursor = if (more) nextCursor ?: return@launch else null
        loading = true
        val r = apiCall { api.announcements(cursor, PAGE) }
        loading = false
        when (r) {
            is ApiResult.Ok -> {
                items = if (more) items + r.value.items else r.value.items
                nextCursor = r.value.nextCursor
                error = null
                loaded = true
            }
            is ApiResult.Offline -> error = "Announcements need internet. Connect and tap Try again."
            else -> error = r.userMessage()
        }
    }

    fun toggle(a: Announcement) {
        open = if (a.id in open) open - a.id else open + a.id
        if (a.isRead) return
        items = items.map { if (it.id == a.id) it.copy(isRead = true) else it }
        viewModelScope.launch {
            val r = apiCallNoBody { api.readAnnouncement(a.id) }
            if (r !is ApiResult.Ok) items = items.map { if (it.id == a.id) it.copy(isRead = false) else it }
        }
    }

    private companion object { const val PAGE = 50 }
}

@Composable
fun AnnouncementsScreen(onBack: () -> Unit, vm: AnnouncementsViewModel = hiltViewModel()) {
    LaunchedEffect(Unit) { vm.load() }
    MorePage("Announcements", onBack, actions = {
        IconButton(onClick = { vm.load() }) { Icon(Icons.Default.Refresh, "Refresh") }
    }) {
        Column(Modifier.fillMaxSize()) {
            if (vm.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (vm.error != null) Column(Modifier.padding(16.dp)) {
                ErrorText(vm.error)
                OutlinedButton(onClick = { vm.load() }) { Text("Try again") }
            }
            if (vm.loaded && vm.items.isEmpty()) EmptyState("No announcements for you.")
            LazyColumn(Modifier.fillMaxSize()) {
                items(vm.items, key = { it.id }) { a ->
                    val expanded = a.id in vm.open
                    Column(
                        Modifier.fillMaxWidth().clickable { vm.toggle(a) }.padding(horizontal = 16.dp, vertical = 12.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (!a.isRead) Badge { Text("New") }
                            Text(
                                "${a.createdBy.fullNameEn} · ${istTime(a.createdAt) ?: a.createdAt}",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        Text(
                            a.body,
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = if (a.isRead) FontWeight.Normal else FontWeight.SemiBold,
                            maxLines = if (expanded) Int.MAX_VALUE else 3,
                        )
                    }
                    HorizontalDivider()
                }
                if (vm.nextCursor != null) item {
                    OutlinedButton(onClick = { vm.load(more = true) }, modifier = Modifier.padding(16.dp)) { Text("Show more") }
                }
            }
        }
    }
}
