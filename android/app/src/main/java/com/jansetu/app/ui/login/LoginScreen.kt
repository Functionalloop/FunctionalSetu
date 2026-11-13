package com.jansetu.app.ui.login

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.padding
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.BuildConfig
import com.jansetu.app.data.ServerSetting
import com.jansetu.app.data.SessionRepository
import com.jansetu.app.data.SessionStore
import com.jansetu.app.data.remote.ServerAddress
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.BusyButton
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.PasswordField
import com.jansetu.app.ui.common.SetupPage
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class LoginViewModel @Inject constructor(
    private val repo: SessionRepository,
    store: SessionStore,
    val server: ServerSetting,
) : ViewModel() {
    var workspace by mutableStateOf(store.lastLogin?.first ?: "")
    var username by mutableStateOf(store.lastLogin?.second ?: "")
    var password by mutableStateOf("")
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    val notice: String? = store.notice

    val canSubmit get() = workspace.isNotBlank() && username.isNotBlank() && password.isNotEmpty()

    fun login() {
        if (!canSubmit || busy) return
        busy = true
        error = null
        viewModelScope.launch {
            // On success the session changes and AppRoot moves on by itself.
            error = repo.login(workspace, username, password).userMessage()
            busy = false
        }
    }
}

/** English labels only; the language buttons of the screen flow are not built (plan 5.5). */
@Composable
fun LoginScreen(vm: LoginViewModel = hiltViewModel()) {
    SetupPage("Log in", "Use the workspace code and user ID your admin gave you.") {
        vm.notice?.let {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer)) {
                Text(it, Modifier.padding(12.dp), style = MaterialTheme.typography.bodyMedium)
            }
        }
        OutlinedTextField(
            vm.workspace, { vm.workspace = it.trim() }, label = { Text("Workspace code") }, singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None, keyboardType = KeyboardType.Ascii),
        )
        OutlinedTextField(
            vm.username, { vm.username = it.trim() }, label = { Text("User ID") }, singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None, keyboardType = KeyboardType.Ascii),
        )
        PasswordField(vm.password, { vm.password = it }, "Password")
        ErrorText(vm.error)
        BusyButton("Log in", vm.busy, enabled = vm.canSubmit, onClick = vm::login)
        Text("Version ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (vm.server.canChange) ServerRow(vm.server)
    }
}

/**
 * Debug build only (plan 6.6, laptop fallback): which server this phone talks to, and a way to type
 * another one, e.g. the laptop on a hotspot. The release build always uses the real domain.
 */
@Composable
private fun ServerRow(server: ServerSetting) {
    val current by server.current.collectAsState()
    var editing by remember { mutableStateOf(false) }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Server: ${current}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
             modifier = Modifier.weight(1f))
        TextButton(onClick = { editing = true }) { Text("Change") }
    }
    if (editing) {
        var text by remember { mutableStateOf(ServerAddress.label(current)) }
        var bad by remember { mutableStateOf(false) }
        AlertDialog(
            onDismissRequest = { editing = false },
            title = { Text("Server address") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("The laptop's address on the hotspot and the API port, e.g. 192.168.137.1:8000 " +
                         "(scripts/fallback.ps1 prints it). Default: ${ServerAddress.label(server.default)}.")
                    OutlinedTextField(
                        text, { text = it.trim(); bad = false }, label = { Text("Address") }, singleLine = true,
                        isError = bad, modifier = Modifier.fillMaxWidth(),
                        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None, keyboardType = KeyboardType.Uri),
                    )
                    if (bad) ErrorText("Not an address. Example: 192.168.137.1:8000")
                }
            },
            confirmButton = { TextButton(onClick = { if (server.set(text)) editing = false else bad = true }) { Text("Save") } },
            dismissButton = { TextButton(onClick = { server.reset(); editing = false }) { Text("Use default") } },
        )
    }
}
