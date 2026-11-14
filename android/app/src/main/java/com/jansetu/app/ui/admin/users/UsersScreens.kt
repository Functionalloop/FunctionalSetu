package com.jansetu.app.ui.admin.users

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.PersonAdd
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.Session
import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.remote.AdminDevice
import com.jansetu.app.data.remote.AdminUser
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.AssignedArea
import com.jansetu.app.data.remote.AssignmentsIn
import com.jansetu.app.data.remote.BlockDeviceRequest
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.NewUser
import com.jansetu.app.data.remote.TemporaryPassword
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.admin.PhoneCard
import com.jansetu.app.ui.admin.PhonesContent
import com.jansetu.app.ui.admin.PhonesViewModel
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.istTime
import com.jansetu.app.ui.home.roleLabel
import com.jansetu.app.ui.search.areaLabel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import javax.inject.Inject

/** One page holds them all: at most 200 users per workspace. */
private const val ALL_USERS = 200

// --- Users & devices -------------------------------------------------------------------------------

@HiltViewModel
class UsersViewModel @Inject constructor(private val api: JansetuApi) : ViewModel() {
    var users by mutableStateOf<List<AdminUser>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var loaded by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    fun reload() = viewModelScope.launch {
        loading = true
        val r = apiCall { api.users(limit = ALL_USERS) }
        loading = false
        when (r) {
            is ApiResult.Ok -> { users = r.value.items; error = null; loaded = true }
            else -> error = r.userMessage()
        }
    }
}

/** Shown words for a user's state, e.g. "Switched off", "Phone waiting". */
fun userFlags(u: AdminUser): List<String> = buildList {
    if (!u.isActive) add("Switched off")
    if (u.pendingDevice) add("Phone waiting")
    if (u.deviceCount == 0 && u.role in UserRules.FIELD_ROLES) add("No phone yet")
    if (u.mustChangePassword) add("Has not set a password yet")
    if (u.lockedUntil != null) add("Locked after wrong passwords")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UsersScreen(
    session: Session, onBack: () -> Unit, onAdd: () -> Unit, onOpen: (String) -> Unit,
    vm: UsersViewModel = hiltViewModel(), phones: PhonesViewModel = hiltViewModel(),
) {
    // Opens on the phones when one is waiting (approved flow), else on the users.
    var tab by rememberSaveable { mutableStateOf(-1) }
    var query by rememberSaveable { mutableStateOf("") }
    LaunchedEffect(Unit) { vm.reload() }
    LaunchedEffect(vm.loaded) { if (vm.loaded && tab == -1) tab = if (vm.users.any { it.pendingDevice }) 1 else 0 }
    val shownTab = tab.coerceAtLeast(0)

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Users & devices") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                actions = {
                    val scope = rememberCoroutineScope()
                    IconButton(onClick = { vm.reload(); scope.launch { phones.reload() } }) { Icon(Icons.Default.Refresh, "Refresh") }
                    IconButton(onClick = onAdd) { Icon(Icons.Default.PersonAdd, "Add user") }
                },
            )
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            TabRow(selectedTabIndex = shownTab) {
                Tab(shownTab == 0, { tab = 0 }, text = { Text(if (vm.loaded) "Users ${vm.users.size}" else "Users") })
                val waiting = vm.users.count { it.pendingDevice }
                Tab(shownTab == 1, { tab = 1 }, text = { Text(if (waiting > 0) "Phones waiting $waiting" else "Phones") })
            }
            if (shownTab == 1) {
                PhonesContent(session, phones)
                return@Column
            }
            if (vm.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                OutlinedTextField(
                    query, { query = it.take(100) }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    label = { Text("Find by name, user ID or mobile") },
                )
                ErrorText(vm.error)
            }
            val q = query.trim().lowercase()
            val shown = vm.users.filter {
                q.isEmpty() || q in it.fullNameEn.lowercase() || q in it.username.lowercase() ||
                    q in (it.fullNameMr ?: "").lowercase() || q in (it.mobile ?: "")
            }
            if (vm.loaded && shown.isEmpty()) EmptyState(if (q.isEmpty()) "No users yet. Add one with the + button." else "Nobody matches.")
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 16.dp)) {
                items(shown, key = { it.id }) { u ->
                    ListItem(
                        headlineContent = { Text(u.fullNameEn + if (u.id == session.user.id) " (you)" else "") },
                        supportingContent = {
                            Column {
                                Text(listOfNotNull(u.username, roleLabel(u.role), u.mobile).joinToString(" · "))
                                val flags = userFlags(u)
                                if (flags.isNotEmpty()) Text(flags.joinToString(" · "), color = MaterialTheme.colorScheme.tertiary)
                            }
                        },
                        modifier = Modifier.clickable { onOpen(u.id) },
                    )
                    HorizontalDivider()
                }
            }
        }
    }
}

// --- Add user --------------------------------------------------------------------------------------

@HiltViewModel
class AddUserViewModel @Inject constructor(private val api: JansetuApi, private val local: LocalDb) : ViewModel() {
    var constituencies by mutableStateOf<List<AreaEntity>>(emptyList())
        private set
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
    var created by mutableStateOf<TemporaryPassword?>(null)
        private set

    init {
        viewModelScope.launch { constituencies = local.db.areas().all().filter { it.level == "local_body" } }
    }

    fun create(session: Session, name: String, nameMr: String, username: String, mobile: String, role: String,
               constituency: String?) {
        // An admin's users go in the admin's constituency (the server sets it); a super admin picks one.
        val superAdmin = session.user.role == "super_admin"
        val lb = if (superAdmin) constituency ?: constituencies.singleOrNull()?.id else null
        UserRules.checkNew(name, username, mobile, needsConstituency = superAdmin && lb == null)?.let { error = it; return }
        viewModelScope.launch {
            busy = true
            val r = apiCall {
                api.createUser(NewUser(username.trim(), name.trim(), nameMr.trim().ifBlank { null },
                                       mobile.trim().ifBlank { null }, role, lb))
            }
            busy = false
            when (r) {
                is ApiResult.Ok -> { created = r.value; error = null }
                else -> error = r.userMessage()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddUserScreen(session: Session, onBack: () -> Unit, onCreated: (String) -> Unit, vm: AddUserViewModel = hiltViewModel()) {
    var name by rememberSaveable { mutableStateOf("") }
    var nameMr by rememberSaveable { mutableStateOf("") }
    var username by rememberSaveable { mutableStateOf("") }
    var mobile by rememberSaveable { mutableStateOf("") }
    var role by rememberSaveable { mutableStateOf("surveyor") }
    var constituency by rememberSaveable { mutableStateOf<String?>(null) }
    val superAdmin = session.user.role == "super_admin"

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Add user") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            )
        },
    ) { padding ->
        Column(
            Modifier.padding(padding).imePadding().fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            OutlinedTextField(name, { name = it.take(200) }, label = { Text("Full name") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(nameMr, { nameMr = it.take(200) }, label = { Text("Name in Marathi (optional)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(username, { username = it.take(40).replace(" ", "") }, label = { Text("User ID (for login)") },
                singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(mobile, { mobile = it.filter(Char::isDigit).take(10) }, label = { Text("Mobile (optional)") },
                singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone), modifier = Modifier.fillMaxWidth())
            Text("Role", style = MaterialTheme.typography.labelLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                UserRules.rolesFor(session.user.role).forEach { r -> FilterChip(role == r, { role = r }, { Text(roleLabel(r)) }) }
            }
            if (!superAdmin) Text("Only the super admin can add an admin.", style = MaterialTheme.typography.bodySmall)
            if (superAdmin && vm.constituencies.size > 1) {
                Text("Constituency", style = MaterialTheme.typography.labelLarge)
                vm.constituencies.forEach { c ->
                    FilterChip(constituency == c.id, { constituency = c.id }, { Text(c.nameEn ?: c.nameMr) })
                }
            }
            Text(
                "A temporary password is shown once after Create. The user sets a new one at the first login. " +
                    if (role in UserRules.FIELD_ROLES) "Then give them their areas." else "",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            ErrorText(vm.error)
            Button(onClick = { vm.create(session, name, nameMr, username, mobile, role, constituency) },
                enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text(if (vm.busy) "Creating…" else "Create user") }
        }
    }

    vm.created?.let { t -> TemporaryPasswordDialog(t, "User created") { onCreated(t.user.id) } }
}

/** The temporary password, shown once, with Copy. */
@Composable
fun TemporaryPasswordDialog(t: TemporaryPassword, title: String, onDone: () -> Unit) {
    val clipboard = LocalClipboardManager.current
    AlertDialog(
        onDismissRequest = {}, // only Done closes it: the password is not shown again
        title = { Text(title) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("User ID: ${t.user.username}")
                Text("Temporary password:")
                Text(t.temporaryPassword, style = MaterialTheme.typography.headlineSmall, fontFamily = FontFamily.Monospace)
                Text("Give it to ${t.user.fullNameEn} in person or by phone. It is shown only now; " +
                    "they must set their own password at the first login.", style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = { TextButton(onClick = onDone) { Text("Done") } },
        dismissButton = { TextButton(onClick = { clipboard.setText(AnnotatedString(t.temporaryPassword)) }) { Text("Copy") } },
    )
}

// --- one user --------------------------------------------------------------------------------------

@HiltViewModel
class UserDetailViewModel @Inject constructor(
    saved: SavedStateHandle, private val api: JansetuApi, private val local: LocalDb,
) : ViewModel() {
    val userId: String = checkNotNull(saved["id"])
    var user by mutableStateOf<AdminUser?>(null)
        private set
    var areas by mutableStateOf<List<AssignedArea>>(emptyList())
        private set
    var phones by mutableStateOf<List<AdminDevice>>(emptyList())
        private set
    /** Wards and parts on this phone, for the area picker. */
    var localAreas by mutableStateOf<List<AreaEntity>>(emptyList())
        private set
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
    var password by mutableStateOf<TemporaryPassword?>(null)

    init { reload() }

    fun reload() = viewModelScope.launch {
        busy = true
        localAreas = local.db.areas().all()
        val u = apiCall { api.user(userId) }
        if (u is ApiResult.Ok) {
            user = u.value
            if (u.value.role in UserRules.FIELD_ROLES) {
                (apiCall { api.assignments(userId) } as? ApiResult.Ok)?.let { areas = it.value.areas }
            }
            // Phones of the constituency, this user's only (a short list).
            (apiCall { api.devices(limit = 200) } as? ApiResult.Ok)?.let { p -> phones = p.value.items.filter { it.userId == userId } }
            error = null
        } else error = u.userMessage()
        busy = false
    }

    private fun run(call: suspend () -> Any?) = viewModelScope.launch {
        busy = true
        val r = apiCall { call() }
        busy = false
        if (r is ApiResult.Ok) reload() else error = r.userMessage()
    }

    fun save(edits: JsonObject) { if (edits.isNotEmpty()) run { api.updateUser(userId, edits) } }
    fun setActive(on: Boolean) = run { api.updateUser(userId, JsonObject(mapOf("is_active" to JsonPrimitive(on)))) }
    fun setAreas(ids: List<String>) = run { api.setAssignments(userId, AssignmentsIn(ids)) }
    fun approve(d: AdminDevice) = run { api.approveDevice(d.id) }
    fun block(d: AdminDevice) = run { api.blockDevice(d.id, BlockDeviceRequest(null)) }

    fun resetPassword() = viewModelScope.launch {
        busy = true
        val r = apiCall { api.resetPassword(userId) }
        busy = false
        when (r) {
            is ApiResult.Ok -> { password = r.value; user = r.value.user; error = null }
            else -> error = r.userMessage()
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UserDetailScreen(session: Session, onBack: () -> Unit, vm: UserDetailViewModel = hiltViewModel()) {
    var editing by remember { mutableStateOf(false) }
    var pickingAreas by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf<String?>(null) } // "reset" / "off"
    val u = vm.user

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(u?.fullNameEn ?: "User") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                actions = { IconButton(onClick = { vm.reload() }) { Icon(Icons.Default.Refresh, "Refresh") } },
            )
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (vm.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            ErrorText(vm.error)
            if (u == null) return@Column
            val isMe = u.id == session.user.id
            val mayChange = UserRules.mayChange(session.user.role, u)

            Text(listOfNotNull(u.fullNameMr, u.username, roleLabel(u.role), u.mobile).joinToString(" · "))
            Text(
                listOfNotNull(
                    if (u.isActive) "Active" else "Switched off",
                    u.lastLoginAt?.let { "last login ${istTime(it)}" } ?: "never logged in",
                ).joinToString(" · ") + userFlags(u).filter { it != "Switched off" }.joinToString("") { " · $it" },
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (!mayChange) Text("Only the super admin can change an admin.", style = MaterialTheme.typography.bodySmall)
            if (mayChange) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { editing = true }, enabled = !vm.busy) { Text("Edit") }
                if (!isMe) {
                    OutlinedButton(onClick = { confirm = "reset" }, enabled = !vm.busy) { Text("Reset password") }
                    OutlinedButton(onClick = { if (u.isActive) confirm = "off" else vm.setActive(true) }, enabled = !vm.busy) {
                        Text(if (u.isActive) "Switch off" else "Switch on")
                    }
                }
            }

            if (u.role in UserRules.FIELD_ROLES) {
                HorizontalDivider()
                Text("Areas", style = MaterialTheme.typography.titleMedium)
                val byId = vm.localAreas.associateBy { it.id }
                if (vm.areas.isEmpty()) Text("None yet: this user sees no voters.")
                vm.areas.forEach { a ->
                    Text((if (a.level == "booth") "Part " else "Village Panchayat ") +
                        (byId[a.id]?.let(::areaLabel) ?: listOfNotNull(a.number?.toString(), a.nameEn ?: a.nameMr).joinToString(" · ")))
                }
                if (mayChange) OutlinedButton(onClick = { pickingAreas = true }, enabled = !vm.busy) { Text("Change areas") }
            }

            HorizontalDivider()
            Text("Phones", style = MaterialTheme.typography.titleMedium)
            if (vm.phones.isEmpty()) Text("No phone yet. The user's phone appears here after their first login.")
            vm.phones.forEach { d ->
                // Blocking from here has no reason field; the Phones tab has one.
                PhoneCard(d = d, isMine = d.userId == session.user.id,
                    busy = vm.busy, onApprove = { vm.approve(d) }, onBlock = { vm.block(d) })
            }
            Spacer(Modifier.heightIn(min = 24.dp))
        }
    }

    if (editing && u != null) EditUserDialog(session, u, onDismiss = { editing = false }) { vm.save(it); editing = false }
    if (pickingAreas && u != null) AreaPickerDialog(
        areas = UserRules.inConstituency(vm.localAreas, u.localBodyId),
        chosen = vm.areas.map { it.id }.toSet(),
        onDismiss = { pickingAreas = false },
    ) { vm.setAreas(it); pickingAreas = false }
    when (confirm) {
        "reset" -> AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text("Reset password?") },
            text = { Text("${u?.fullNameEn} is logged out everywhere and gets a new temporary password. Their phone stays approved.") },
            confirmButton = { TextButton(onClick = { confirm = null; vm.resetPassword() }) { Text("Reset") } },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancel") } },
        )
        "off" -> AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text("Switch off this user?") },
            text = { Text("${u?.fullNameEn} is logged out everywhere and cannot log in until switched on again. " +
                "Changes on their phone that were not sent yet stay on the phone.") },
            confirmButton = { TextButton(onClick = { confirm = null; vm.setActive(false) }) { Text("Switch off") } },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancel") } },
        )
    }
    vm.password?.let { t -> TemporaryPasswordDialog(t, "New temporary password") { vm.password = null } }
}

@Composable
private fun EditUserDialog(session: Session, u: AdminUser, onDismiss: () -> Unit, onSave: (JsonObject) -> Unit) {
    var name by remember { mutableStateOf(u.fullNameEn) }
    var nameMr by remember { mutableStateOf(u.fullNameMr ?: "") }
    var mobile by remember { mutableStateOf(u.mobile ?: "") }
    var role by remember { mutableStateOf(u.role) }
    var problem by remember { mutableStateOf<String?>(null) }
    val isMe = u.id == session.user.id
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit user") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it.take(200) }, label = { Text("Full name") }, singleLine = true)
                OutlinedTextField(nameMr, { nameMr = it.take(200) }, label = { Text("Name in Marathi") }, singleLine = true)
                OutlinedTextField(mobile, { mobile = it.filter(Char::isDigit).take(10) }, label = { Text("Mobile") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone))
                // Nobody changes their own role; a super admin's role is never changed here.
                if (!isMe && u.role != "super_admin") {
                    Text("Role", style = MaterialTheme.typography.labelLarge)
                    UserRules.rolesFor(session.user.role).forEach { r -> FilterChip(role == r, { role = r }, { Text(roleLabel(r)) }) }
                }
                ErrorText(problem)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                problem = UserRules.checkEdit(name, mobile)
                if (problem == null) onSave(UserRules.edits(u, name, nameMr, mobile, role))
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/** Tick wards (Village Panchayats) and parts of the user's constituency. */
@Composable
fun AreaPickerDialog(areas: List<AreaEntity>, chosen: Set<String>, onDismiss: () -> Unit, onSave: (List<String>) -> Unit) {
    var ticked by remember { mutableStateOf(chosen) }
    val wards = areas.filter { it.level == "ward" }
    val parts = areas.filter { it.level == "booth" }.groupBy { it.parentId }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Areas") },
        text = {
            LazyColumn(Modifier.heightIn(max = 420.dp)) {
                wards.forEach { w ->
                    item(key = w.id) { TickRow("Village Panchayat ${areaLabel(w)}", w.id in ticked, bold = true) { ticked = ticked.flip(w.id) } }
                    items(parts[w.id].orEmpty(), key = { it.id }) { p ->
                        TickRow("   Part ${areaLabel(p)}", p.id in ticked || w.id in ticked, enabled = w.id !in ticked) { ticked = ticked.flip(p.id) }
                    }
                }
                if (wards.isEmpty()) item { Text("No areas on this phone. Run Sync first.") }
            }
        },
        confirmButton = {
            // A part under a ticked Village Panchayat is covered by it: send the Panchayat only.
            TextButton(onClick = {
                val wardIds = ticked.filter { id -> wards.any { it.id == id } }.toSet()
                onSave(ticked.filter { id -> parts.values.flatten().none { it.id == id && it.parentId in wardIds } })
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

private fun Set<String>.flip(id: String) = if (id in this) this - id else this + id

@Composable
fun TickRow(label: String, checked: Boolean, enabled: Boolean = true, bold: Boolean = false, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = onClick), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
        Checkbox(checked, { onClick() }, enabled = enabled)
        Text(label, style = if (bold) MaterialTheme.typography.titleSmall else MaterialTheme.typography.bodyMedium)
    }
}
