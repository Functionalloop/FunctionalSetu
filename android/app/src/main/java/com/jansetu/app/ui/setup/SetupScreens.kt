package com.jansetu.app.ui.setup

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.SessionRepository
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.BusyButton
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.PasswordField
import com.jansetu.app.ui.common.SetupPage
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import javax.inject.Inject

// ------------------------------------------------------------------ Set password

@HiltViewModel
class SetPasswordViewModel @Inject constructor(private val repo: SessionRepository) : ViewModel() {
    val askCurrent = repo.loginPassword == null
    var current by mutableStateOf("")
    var new by mutableStateOf("")
    var again by mutableStateOf("")
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    fun save() {
        val currentPassword = repo.loginPassword ?: current
        error = when {
            currentPassword.isEmpty() -> "Enter your current password."
            new.length < 8 -> "The new password needs at least 8 characters."
            new != again -> "The two new passwords are not the same."
            new == currentPassword -> "The new password must be different from the current one."
            else -> null
        }
        if (error != null || busy) return
        busy = true
        viewModelScope.launch {
            error = repo.changePassword(currentPassword, new).userMessage()
            busy = false
        }
    }

    fun logout() = viewModelScope.launch { repo.logout() }
}

@Composable
fun SetPasswordScreen(vm: SetPasswordViewModel = hiltViewModel()) {
    SetupPage("Set your password", "This is your first login. Choose a new password of at least 8 characters.") {
        if (vm.askCurrent) PasswordField(vm.current, { vm.current = it }, "Current password")
        PasswordField(vm.new, { vm.new = it }, "New password")
        PasswordField(vm.again, { vm.again = it }, "New password again")
        ErrorText(vm.error)
        BusyButton("Save password", vm.busy, onClick = vm::save)
        TextButton(onClick = { vm.logout() }) { Text("Log out") }
    }
}

// ------------------------------------------------------------------ Waiting for approval

@HiltViewModel
class DeviceWaitingViewModel @Inject constructor(private val repo: SessionRepository) : ViewModel() {
    var checking by mutableStateOf(false)
        private set
    var message by mutableStateOf<String?>(null)
        private set

    /** Polls every 15 s while the screen is open. Approval changes the session; AppRoot moves on. */
    suspend fun poll() {
        while (true) {
            check()
            delay(15_000)
        }
    }

    suspend fun check() {
        checking = true
        val r = repo.refreshDeviceStatus()
        message = when (r) {
            is ApiResult.Ok -> if (r.value == "pending") null else "Phone status: ${r.value}"
            else -> r.userMessage()
        }
        checking = false
    }

    fun checkNow() = viewModelScope.launch { check() }
    fun logout() = viewModelScope.launch { repo.logout() }
}

@Composable
fun DeviceWaitingScreen(vm: DeviceWaitingViewModel = hiltViewModel()) {
    LaunchedEffect(Unit) { vm.poll() }
    SetupPage(
        "Waiting for approval",
        "This phone must be approved by your admin before it can download voter data. " +
            "Ask your admin to approve it. This screen moves on by itself.",
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator()
            Text(if (vm.checking) "Checking…" else "Waiting", style = MaterialTheme.typography.bodyLarge)
        }
        ErrorText(vm.message)
        OutlinedButton(onClick = { vm.checkNow() }, enabled = !vm.checking, modifier = Modifier.fillMaxWidth()) { Text("Check now") }
        TextButton(onClick = { vm.logout() }) { Text("Log out") }
    }
}
