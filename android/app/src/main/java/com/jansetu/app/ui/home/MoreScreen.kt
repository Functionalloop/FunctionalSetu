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
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.HowToVote
import androidx.compose.material.icons.filled.Map
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Sync
import androidx.compose.ui.graphics.vector.ImageVector
import com.jansetu.app.data.SessionRepository
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.ui.admin.PHONE_ADMIN_ROLES
import com.jansetu.app.ui.quality.QUALITY_ROLES
import androidx.compose.material.icons.automirrored.filled.CompareArrows
import androidx.compose.material.icons.filled.ContactPhone
import androidx.compose.material.icons.filled.FactCheck
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
    session: Session, problems: Int, onPhones: () -> Unit, onNewVoters: () -> Unit, onBirthdays: () -> Unit,
    /** Opens a More page by route: sync (8.2: off the bottom bar), announcements, terms, help, password (7.9). */
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
        MoreItem(
            "Sync",
            when {
                problems > 0 -> "$problems item(s) need your attention"
                unsent > 0 -> "$unsent change(s) not sent yet"
                else -> "Send and receive changes"
            },
            Icons.Default.Sync,
        ) { onOpen("sync") }
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
        if (session.user.role in QUALITY_ROLES) { // 10.6, 11.3
            MoreItem("Reports & charts", "Survey progress, colour tags, age and gender, turnout; print or export a list (needs internet)",
                Icons.Default.BarChart) { onOpen("reports") }
            MoreItem("Data quality", "Missing numbers, possible duplicates, repeated voters (needs internet)",
                Icons.Default.FactCheck) { onOpen("quality") }
        }
        if (session.user.role in PHONE_ADMIN_ROLES) {
            MoreItem("Mobile numbers & contacts", "Import a sheet of numbers and check the matches (needs internet)",
                Icons.Default.ContactPhone) { onOpen("mobiles") }
        }
        if (session.user.role in PHONE_ADMIN_ROLES) {
            // 9.6: Phones became a tab of Users & devices.
            ListItem(
                headlineContent = { Text("Users & devices") },
                supportingContent = { Text("Add users, reset passwords, approve or block phones (needs internet)") },
                leadingContent = { Icon(Icons.Default.PhoneAndroid, null) },
                modifier = Modifier.clickable(onClick = onPhones),
            )
            HorizontalDivider()
            MoreItem("Booths & karyakartas", "Who works in which part and Village Panchayat (needs internet)",
                Icons.Default.Groups) { onOpen("assign") }
            // 9.7
            MoreItem("Election & candidate", "Polling date and time, candidate, party, slip message (needs internet)",
                Icons.Default.HowToVote) { onOpen("election") }
            MoreItem("Lists & labels", "Castes, professions, influencer list, colour tags, messages (needs internet)",
                Icons.AutoMirrored.Filled.List) { onOpen("lists") }
            // 9.8
            MoreItem("Activity log", "Who changed what and when (needs internet)", Icons.Default.History) { onOpen("activity") }
            MoreItem("Worker activity", "Surveys, visits, mobiles and voted marks per worker per day (needs internet)",
                Icons.Default.BarChart) { onOpen("workeractivity") }
            MoreItem("Worker locations", "Where surveys and visits were saved (needs internet)", Icons.Default.Place) { onOpen("locations") }
            // 10.6: its own item; a super admin uploads, decides and applies, an admin reads
            MoreItem("Matching Engine",
                if (session.user.role == "super_admin") "Compare a new official roll with the current one (needs internet)"
                else "Roll comparisons, read only (needs internet)",
                Icons.AutoMirrored.Filled.CompareArrows) { onOpen("matching") }
            if (session.user.role == "super_admin") {
                MoreItem("Constituencies", "Up to 5 in the workspace; add an admin (needs internet)", Icons.Default.Map) { onOpen("constituencies") }
            }
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
