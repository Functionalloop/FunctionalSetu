package com.jansetu.app.ui.setup

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.work.WorkInfo
import com.jansetu.app.data.SessionRepository
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.sync.PullWorker
import com.jansetu.app.data.sync.SyncKeys
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.SetupPage
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

data class FirstSyncState(val done: Int = 0, val total: Int? = null, val work: WorkInfo.State? = null, val error: String? = null)

@HiltViewModel
class FirstSyncViewModel @Inject constructor(
    private val scheduler: SyncScheduler,
    private val repo: SessionRepository,
    local: LocalDb,
) : ViewModel() {
    // Counted from the database, so the bar is right after the app is reopened half-way.
    val state = combine(
        local.db.voters().voterCount(),
        local.db.syncState().flow(SyncKeys.PULL_TOTAL),
        scheduler.firstDownloadInfo(),
    ) { done, total, info ->
        FirstSyncState(done, total?.toIntOrNull(), info?.state, info?.outputData?.getString(PullWorker.ERROR))
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), FirstSyncState())

    /** Starts the download, or does nothing if it is already running or waiting for a network. */
    fun start() = scheduler.firstDownload()
    fun logout() = viewModelScope.launch { repo.logout() }
}

@Composable
fun FirstSyncScreen(vm: FirstSyncViewModel = hiltViewModel()) {
    LaunchedEffect(Unit) { vm.start() }
    val s by vm.state.collectAsStateWithLifecycle()
    SetupPage(
        "Downloading voter data",
        "Your area's voters are saved on this phone, so you can work without internet. " +
            "You can close the app; the download continues and resumes where it stopped.",
    ) {
        val total = s.total
        if (total != null && total > 0) {
            LinearProgressIndicator(progress = { (s.done.toFloat() / total).coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
            Text("%,d of %,d voters".format(s.done, total), style = MaterialTheme.typography.titleMedium)
        } else {
            LinearProgressIndicator(Modifier.fillMaxWidth())
            Text("Starting…", style = MaterialTheme.typography.titleMedium)
        }
        when (s.work) {
            WorkInfo.State.ENQUEUED -> Text("Waiting for internet…", color = MaterialTheme.colorScheme.onSurfaceVariant)
            WorkInfo.State.FAILED -> {
                ErrorText(s.error ?: "The download stopped.")
                Button(onClick = { vm.start() }, modifier = Modifier.fillMaxWidth()) { Text("Try again") }
            }
            else -> {}
        }
        TextButton(onClick = { vm.logout() }) { Text("Log out") }
    }
}
