package com.jansetu.app.ui.newvoter

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.NewVoterRepository
import com.jansetu.app.data.Session
import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.local.LocalDb
import com.jansetu.app.data.local.NewVoterEntity
import com.jansetu.app.data.sync.SyncScheduler
import com.jansetu.app.ui.common.EmptyState
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.search.AreaPicker
import com.jansetu.app.ui.search.areaLabel
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import javax.inject.Inject

/** The client's name for "new voter" / "not registered" (12 Nov). */
const val ENR_TITLE = "Eligible but Not Registered"

val FORM6 = listOf("not_applied" to "Form 6 not applied", "applied" to "Applied", "approved" to "Approved", "rejected" to "Rejected")
private val GENDERS = listOf("M" to "Male", "F" to "Female", "O" to "Other")
private val MOBILE = Regex("^[6-9][0-9]{9}$")
private val DMY = DateTimeFormatter.ofPattern("d/M/yyyy")

fun form6Label(code: String) = FORM6.firstOrNull { it.first == code }?.second ?: code

// ------------------------------------------------------------------------------ list

@OptIn(ExperimentalCoroutinesApi::class)
@HiltViewModel
class NewVoterListViewModel @Inject constructor(local: LocalDb) : ViewModel() {
    private val db = local.db
    val status = MutableStateFlow<String?>(null)
    val rows = status.flatMapLatest { db.newVoters().list(it) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), null)
    val booths = db.areas().byLevel("booth").map { l -> l.associateBy { it.id } }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyMap())
}

/** 7.5: everyone added by hand in the user's area, newest first, with the Form 6 status. Works offline. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NewVoterListScreen(onBack: () -> Unit, onOpen: (String) -> Unit, onAdd: () -> Unit, vm: NewVoterListViewModel = hiltViewModel()) {
    val rows by vm.rows.collectAsStateWithLifecycle()
    val status by vm.status.collectAsStateWithLifecycle()
    val booths by vm.booths.collectAsStateWithLifecycle()
    Scaffold(
        topBar = {
            TopAppBar(title = { Text(ENR_TITLE) },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(onClick = onAdd, icon = { Icon(Icons.Default.Add, null) }, text = { Text("Add") })
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(status == null, { vm.status.value = null }, label = { Text("All") })
                FORM6.forEach { (code, label) ->
                    FilterChip(status == code, { vm.status.value = code }, label = { Text(label) })
                }
            }
            val list = rows
            when {
                list == null -> Unit
                list.isEmpty() -> EmptyState(if (status == null) "Nobody added yet. Tap Add for a person who can vote but is not on the roll."
                                             else "Nobody with this Form 6 status.")
                else -> LazyColumn(Modifier.fillMaxSize()) {
                    items(list, key = { it.id }) { r ->
                        Column(Modifier.fillMaxWidth().clickable { onOpen(r.id) }.padding(horizontal = 16.dp, vertical = 10.dp)) {
                            Text(r.fullNameEn ?: r.fullNameMr ?: "(no name)", style = MaterialTheme.typography.titleMedium)
                            Text(
                                listOfNotNull(
                                    r.boothId?.let { booths[it] }?.let { "Part " + areaLabel(it) } ?: "No part",
                                    form6Label(r.form6Status),
                                    r.mobile,
                                ).joinToString(" · "),
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            when {
                                r.conflict -> Text("Changed by someone else too: see Sync", style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.error)
                                r.pending -> Text("Not sent", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.secondary)
                            }
                        }
                        HorizontalDivider()
                    }
                }
            }
        }
    }
}

// ------------------------------------------------------------------------------ form

/** What the form holds while typing (text, as typed). */
data class NewVoterForm(
    val nameEn: String = "", val nameMr: String = "", val relative: String = "", val dob: String = "",
    val gender: String? = null, val mobile: String = "", val address: String = "", val boothId: String? = null,
    val form6: String = "not_applied", val notes: String = "",
) {
    /** The error to show, or null when it can be saved. Same rules as the server (NewVoterFields). */
    fun problem(today: LocalDate = LocalDate.now()): String? = when {
        nameEn.isBlank() && nameMr.isBlank() -> "Give the name."
        mobile.isNotBlank() && !MOBILE.matches(mobile.trim()) -> "Mobile: 10 digits starting with 6, 7, 8 or 9."
        dob.isNotBlank() && parseDob(dob) == null -> "Date of birth: day/month/year, for example 5/1/2008."
        parseDob(dob)?.isAfter(today) == true -> "Date of birth is in the future."
        boothId == null -> "Pick the part."
        else -> null
    }

    fun toEntity(base: NewVoterEntity?, booth: AreaEntity): NewVoterEntity = (base ?: NewVoterEntity(id = "", wardId = "", createdAt = "")).copy(
        fullNameEn = nameEn, fullNameMr = nameMr, relativeName = relative, dob = parseDob(dob)?.toString(),
        gender = gender, mobile = mobile, address = address, wardId = booth.parentId ?: base?.wardId.orEmpty(),
        boothId = booth.id, form6Status = form6, notes = notes,
        // A Kutumb belongs to one part: moving the person to another part drops the link.
        familyId = base?.familyId?.takeIf { base.boothId == booth.id },
    )

    companion object {
        fun parseDob(text: String): LocalDate? = text.trim().takeIf { it.isNotEmpty() }?.let {
            runCatching { LocalDate.parse(it, DMY) }.getOrNull()
        }

        fun of(e: NewVoterEntity) = NewVoterForm(
            nameEn = e.fullNameEn.orEmpty(), nameMr = e.fullNameMr.orEmpty(), relative = e.relativeName.orEmpty(),
            dob = e.dob?.let { runCatching { LocalDate.parse(it).format(DMY) }.getOrNull() }.orEmpty(),
            gender = e.gender, mobile = e.mobile.orEmpty(), address = e.address.orEmpty(), boothId = e.boothId,
            form6 = e.form6Status, notes = e.notes.orEmpty(),
        )
    }
}

@HiltViewModel
class NewVoterFormViewModel @Inject constructor(
    handle: SavedStateHandle,
    local: LocalDb,
    private val repo: NewVoterRepository,
    private val scheduler: SyncScheduler,
) : ViewModel() {
    private val db = local.db
    /** null = a new person. */
    val id: String? = handle.get<String>("id")?.takeIf { it != "new" }
    val booths = db.areas().byLevel("booth").stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())
    val saved = MutableStateFlow<NewVoterEntity?>(null)
    val loaded = MutableStateFlow(id == null)

    init {
        if (id != null) viewModelScope.launch { saved.value = db.newVoters().get(id); loaded.value = true }
    }

    fun save(form: NewVoterForm, userId: String, done: () -> Unit) = viewModelScope.launch {
        val booth = booths.value.firstOrNull { it.id == form.boothId } ?: return@launch
        repo.save(form.toEntity(saved.value, booth), userId)
        scheduler.syncNow()
        done()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NewVoterFormScreen(session: Session, onBack: () -> Unit, vm: NewVoterFormViewModel = hiltViewModel()) {
    val loaded by vm.loaded.collectAsStateWithLifecycle()
    val base by vm.saved.collectAsStateWithLifecycle()
    val booths by vm.booths.collectAsStateWithLifecycle()
    var form by rememberSaveable(loaded, stateSaver = NewVoterFormSaver) { mutableStateOf(base?.let(NewVoterForm::of) ?: NewVoterForm()) }
    var error by rememberSaveable { mutableStateOf<String?>(null) }
    // One part on the phone (a surveyor's usual case): pick it already.
    LaunchedEffect(booths) { if (form.boothId == null && booths.size == 1) form = form.copy(boothId = booths[0].id) }

    Scaffold(topBar = {
        TopAppBar(title = { Text(if (vm.id == null) "Add: $ENR_TITLE" else ENR_TITLE, maxLines = 1) },
            navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
    }) { padding ->
        if (!loaded) return@Scaffold
        Column(
            Modifier.padding(padding).fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (base?.conflict == true) Text("Someone else changed this record too. Choose which copy stays on the Sync screen.",
                color = MaterialTheme.colorScheme.error)
            Field("Name (English)", form.nameEn) { form = form.copy(nameEn = it) }
            Field("Name (Marathi)", form.nameMr) { form = form.copy(nameMr = it) }
            Field("Father / husband name", form.relative) { form = form.copy(relative = it) }
            Field("Date of birth (day/month/year)", form.dob, KeyboardType.Number) { form = form.copy(dob = it.take(10)) }
            Text("Gender", style = MaterialTheme.typography.labelLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                GENDERS.forEach { (code, label) ->
                    FilterChip(form.gender == code, { form = form.copy(gender = if (form.gender == code) null else code) }, label = { Text(label) })
                }
            }
            Field("Mobile", form.mobile, KeyboardType.Phone) { t -> form = form.copy(mobile = t.filter(Char::isDigit).take(10)) }
            Field("Address", form.address) { form = form.copy(address = it) }
            AreaPicker("Part", booths, form.boothId, allowAll = false) { id -> form = form.copy(boothId = id) }
            Text("Form 6", style = MaterialTheme.typography.labelLarge)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FORM6.forEach { (code, label) -> FilterChip(form.form6 == code, { form = form.copy(form6 = code) }, label = { Text(label) }) }
            }
            OutlinedTextField(form.notes, { form = form.copy(notes = it.take(2000)) }, label = { Text("Notes") },
                modifier = Modifier.fillMaxWidth(), minLines = 2)
            ErrorText(error)
            Button(
                onClick = {
                    error = form.problem()
                    if (error == null) vm.save(form, session.user.id, onBack)
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Save") }
            Text("Saved on the phone at once; sent at the next sync.", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.align(Alignment.CenterHorizontally))
        }
    }
}

@Composable
private fun Field(label: String, value: String, keyboard: KeyboardType = KeyboardType.Text, onChange: (String) -> Unit) {
    OutlinedTextField(
        value, { onChange(it.take(500)) }, label = { Text(label) }, singleLine = true, modifier = Modifier.fillMaxWidth(),
        keyboardOptions = KeyboardOptions(keyboardType = keyboard),
    )
}

/** Keeps what was typed across rotation (the form is a plain data class). */
private val NewVoterFormSaver = androidx.compose.runtime.saveable.listSaver<NewVoterForm, String?>(
    save = { listOf(it.nameEn, it.nameMr, it.relative, it.dob, it.gender, it.mobile, it.address, it.boothId, it.form6, it.notes) },
    restore = { l ->
        NewVoterForm(l[0].orEmpty(), l[1].orEmpty(), l[2].orEmpty(), l[3].orEmpty(), l[4], l[5].orEmpty(), l[6].orEmpty(),
            l[7], l[8] ?: "not_applied", l[9].orEmpty())
    },
)
