package com.jansetu.app.ui.nav

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.SessionStore
import com.jansetu.app.data.remote.SessionEvent
import com.jansetu.app.data.remote.SessionEvents
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.data.sync.WipeHandler
import com.jansetu.app.ui.login.LoginScreen
import com.jansetu.app.ui.setup.DeviceWaitingScreen
import com.jansetu.app.ui.setup.FirstSyncScreen
import com.jansetu.app.ui.setup.SetPasswordScreen
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class RootViewModel @Inject constructor(
    private val store: SessionStore,
    events: SessionEvents,
    private val wipe: WipeHandler,
    private val scheduler: SyncScheduler,
) : ViewModel() {
    val session = store.session

    init {
        viewModelScope.launch {
            events.events.collect { e ->
                when (e) {
                    SessionEvent.Blocked -> if (store.session.value != null || store.accessToken != null) wipe.wipe(WipeHandler.BLOCKED)
                    // Keep the database: the same user logging in again keeps unsent changes.
                    is SessionEvent.LoggedOut -> if (store.session.value != null) {
                        scheduler.cancel()
                        store.signOut("Your login has ended. Please log in again. (${e.message})")
                    }
                }
            }
        }
    }

    fun onMainShown() = scheduler.startPeriodic()
}

/** Picks the screen from the stored session; each step moves on by itself when the session changes. */
@Composable
fun AppRoot(vm: RootViewModel = hiltViewModel()) {
    val session by vm.session.collectAsStateWithLifecycle()
    val s = session
    when {
        s == null -> LoginScreen()
        s.mustChangePassword -> SetPasswordScreen()
        s.deviceStatus == "pending" -> DeviceWaitingScreen()
        !s.firstSyncDone -> FirstSyncScreen()
        else -> {
            LaunchedEffect(Unit) { vm.onMainShown() }
            MainScreen(s)
        }
    }
}
