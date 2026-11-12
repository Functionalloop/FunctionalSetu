package com.jansetu.app.ui.login

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.padding
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.BuildConfig
import com.jansetu.app.data.SessionRepository
import com.jansetu.app.data.SessionStore
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
    }
}
