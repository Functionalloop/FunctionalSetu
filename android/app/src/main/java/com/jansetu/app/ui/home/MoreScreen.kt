package com.jansetu.app.ui.home

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.BuildConfig
import com.jansetu.app.data.Session
import com.jansetu.app.ui.newvoter.ENR_TITLE
import androidx.compose.material.icons.filled.PersonAdd
import androidx.compose.material.icons.filled.Cake
import androidx.compose.material.icons.automirrored.filled.Help
import androidx.compose.material.icons.filled.Campaign
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Lock
import androidx.compose.ui.graphics.vector.ImageVector
import com.jansetu.app.data.SessionRepository
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.ui.admin.PHONE_ADMIN_ROLES
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class MoreViewModel @Inject constructor(private val repo: SessionRepository, local: LocalDb) : ViewModel() {
    val unsent = local.db.outbox().queuedCount()
    fun logout() = viewModelScope.launch { repo.logout() }
}

/** Shell for the More menu; later steps add their items here (polling day, admin, reports). */
@Composable
fun MoreScreen(
    session: Session, onPhones: () -> Unit, onNewVoters: () -> Unit, onBirthdays: () -> Unit,
    /** Opens a More page by route: announcements, terms, help, password (7.9). */
    onOpen: (String) -> Unit,
    vm: MoreViewModel = hiltViewModel(),
) {
    val unsent by vm.unsent.collectAsStateWithLifecycle(0)
    var confirm by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        ListItem(
            headlineContent = { Text(session.user.fullNameEn) },
            supportingContent = { Text("${session.user.username} · ${roleLabel(session.user.role)} · ${session.workspace.nameEn}") },
            leadingContent = { Icon(Icons.Default.Person, null) },
        )
        HorizontalDivider()
        ListItem(
            headlineContent = { Text("Birthdays") },
            supportingContent = { Text("The next 7 days, from the date of birth in the survey") },
            leadingContent = { Icon(Icons.Default.Cake, null) },
            modifier = Modifier.clickable(onClick = onBirthdays),
        )
        HorizontalDivider()
        if (session.canSurvey) { // survey roles, as on the server (7.5)
            ListItem(
                headlineContent = { Text(ENR_TITLE) },
                supportingContent = { Text("People who can vote but are not on the roll; Form 6 status") },
                leadingContent = { Icon(Icons.Default.PersonAdd, null) },
                modifier = Modifier.clickable(onClick = onNewVoters),
            )
            HorizontalDivider()
        }
        if (session.user.role in PHONE_ADMIN_ROLES) {
            ListItem(
                headlineContent = { Text("Phones") },
                supportingContent = { Text("Approve waiting phones, block a lost one (needs internet)") },
                leadingContent = { Icon(Icons.Default.PhoneAndroid, null) },
                modifier = Modifier.clickable(onClick = onPhones),
            )
            HorizontalDivider()
        }
        MoreItem("Announcements", "Notices from your admins (needs internet)", Icons.Default.Campaign) { onOpen("announcements") }
        MoreItem("Change password", "Needs internet", Icons.Default.Lock) { onOpen("password") }
        MoreItem("Help", "How sync works; report a problem", Icons.AutoMirrored.Filled.Help) { onOpen("help") }
        MoreItem("Terms of use", "Read and accept (needs internet)", Icons.Default.Description) { onOpen("terms") }
        ListItem(
            headlineContent = { Text("About") },
            supportingContent = { Text("JANSETU ${BuildConfig.VERSION_NAME}") },
            leadingContent = { Icon(Icons.Default.Info, null) },
        )
        HorizontalDivider()
        ListItem(
            headlineContent = { Text("Log out") },
            supportingContent = { Text("Deletes the voter data from this phone") },
            leadingContent = { Icon(Icons.AutoMirrored.Filled.Logout, null) },
            modifier = Modifier.clickable { confirm = true },
        )
    }

    if (confirm) AlertDialog(
        onDismissRequest = { confirm = false },
        title = { Text("Log out?") },
        text = {
            Text(
                if (unsent > 0) "$unsent change(s) have not been sent to the server yet and will be LOST. " +
                    "Go to Sync and send them first, unless you are sure."
                else "The voter data will be deleted from this phone. You can log in again and download it.",
            )
        },
        confirmButton = { TextButton(onClick = { confirm = false; vm.logout() }) { Text("Log out") } },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text("Cancel") } },
    )
}

@Composable
private fun MoreItem(title: String, detail: String, icon: ImageVector, onClick: () -> Unit) {
    ListItem(
        headlineContent = { Text(title) },
        supportingContent = { Text(detail) },
        leadingContent = { Icon(icon, null) },
        modifier = Modifier.clickable(onClick = onClick),
    )
    HorizontalDivider()
}
