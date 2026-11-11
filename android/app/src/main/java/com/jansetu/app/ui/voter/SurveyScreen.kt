package com.jansetu.app.ui.voter

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.jansetu.app.data.local.ListEntryEntity
import com.jansetu.app.data.local.SurveyEntity
import com.jansetu.app.data.local.VoterEntity
import com.jansetu.app.ui.common.BusyButton
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.search.ColorDot
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

private val MOBILE = Regex("^[6-9][0-9]{9}$")
private val DEVANAGARI = Regex("[\\u0900-\\u097F]")

/** The editable survey fields, as typed. */
data class SurveyForm(
    val mobile1: String = "",
    val mobile2: String = "",
    val dob: String = "",
    val casteId: String? = null,
    val professionId: String? = null,
    val colorTagId: String? = null,
    val hasNewAddress: Boolean = false,
    val newAddress: String = "",
    val notes: String = "",
) {
    fun error(): String? = when {
        mobile1.isNotEmpty() && !MOBILE.matches(mobile1) -> "Mobile 1 must be 10 digits starting with 6, 7, 8 or 9."
        mobile2.isNotEmpty() && !MOBILE.matches(mobile2) -> "Mobile 2 must be 10 digits starting with 6, 7, 8 or 9."
        mobile2.isNotEmpty() && mobile1.isEmpty() -> "Fill Mobile 1 before Mobile 2."
        newAddress.length > 500 -> "The new address is too long (500 characters at most)."
        notes.length > 2000 -> "Notes are too long (2000 characters at most)."
        else -> null
    }

    /** Fields not on this form (custom fields) are kept from the stored copy: the server replaces all of them. */
    fun applyTo(base: SurveyEntity): SurveyEntity {
        val addr = newAddress.trim().takeIf { hasNewAddress && it.isNotEmpty() }
        val marathi = addr != null && DEVANAGARI.containsMatchIn(addr)
        return base.copy(
            mobile1 = mobile1.ifEmpty { null }, mobile2 = mobile2.ifEmpty { null }, dob = dob.ifEmpty { null },
            casteId = casteId, professionId = professionId, colorTagId = colorTagId,
            hasNewAddress = hasNewAddress,
            newAddressMr = if (marathi) addr else null,
            newAddressEn = if (!marathi) addr else null,
            notes = notes.trim().ifEmpty { null },
        )
    }

    companion object {
        fun of(s: SurveyEntity?) = if (s == null) SurveyForm() else SurveyForm(
            mobile1 = s.mobile1 ?: "", mobile2 = s.mobile2 ?: "", dob = s.dob ?: "",
            casteId = s.casteId, professionId = s.professionId, colorTagId = s.colorTagId,
            hasNewAddress = s.hasNewAddress, newAddress = s.newAddressMr ?: s.newAddressEn ?: "", notes = s.notes ?: "",
        )
    }
}

/** Survey tab (5.10). Saved on the phone and queued for sync; read-only for a booth agent. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SurveyScreen(vm: VoterViewModel, voter: VoterEntity, stored: SurveyEntity?, readOnly: Boolean) {
    val castes by vm.castes.collectAsState(emptyList())
    val professions by vm.professions.collectAsState(emptyList())
    val tags by vm.colorTags.collectAsState(emptyList())
    val scope = rememberCoroutineScope()

    // The form starts from the stored copy once; later saves come back through the same flow.
    var loaded by rememberSaveable { mutableStateOf(false) }
    var form by remember { mutableStateOf(SurveyForm.of(stored)) }
    LaunchedEffect(stored) { if (!loaded) { form = SurveyForm.of(stored); loaded = stored != null } }

    var error by remember { mutableStateOf<String?>(null) }
    var saved by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    fun save() = scope.launch {
        busy = true
        val fix = vm.location.current() // null without permission or signal; the survey is saved anyway
        vm.outbox.saveSurvey(form.applyTo(stored ?: SurveyEntity(voterId = voter.id)), fix)
        vm.scheduler.syncNow()
        saved = if (fix != null) "Saved on the phone with location. It will be sent at the next sync."
        else "Saved on the phone (no location). It will be sent at the next sync."
        busy = false
    }

    val askLocation = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { save() }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (readOnly) Text("Booth agents can see the survey but not change it.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (stored?.conflict == true) Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
            Text("Someone else changed this survey at the same time. See the Sync screen.", Modifier.padding(12.dp))
        }
        if (stored?.pending == true) Text("Not sent to the server yet.", color = MaterialTheme.colorScheme.secondary)

        val enabled = !readOnly
        Digits("Mobile 1", form.mobile1, enabled) { form = form.copy(mobile1 = it) }
        Digits("Mobile 2", form.mobile2, enabled) { form = form.copy(mobile2 = it) }
        Picker("Caste", castes, form.casteId, enabled) { form = form.copy(casteId = it) }
        Picker("Profession", professions, form.professionId, enabled) { form = form.copy(professionId = it) }

        if (tags.isNotEmpty()) {
            Text("Colour tag", style = MaterialTheme.typography.titleSmall)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                tags.filter { it.isActive || it.id == form.colorTagId }.forEach { t ->
                    FilterChip(
                        selected = form.colorTagId == t.id, enabled = enabled,
                        onClick = { form = form.copy(colorTagId = if (form.colorTagId == t.id) null else t.id) },
                        label = { Text(t.labelEn) }, leadingIcon = { ColorDot(t.hex) },
                    )
                }
            }
        }

        DobField(form.dob, enabled) { form = form.copy(dob = it) }

        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Lives at a different address now", Modifier.weight(1f))
            Switch(form.hasNewAddress, { form = form.copy(hasNewAddress = it) }, enabled = enabled)
        }
        if (form.hasNewAddress) OutlinedTextField(
            form.newAddress, { form = form.copy(newAddress = it) }, label = { Text("New address") },
            enabled = enabled, modifier = Modifier.fillMaxWidth(), minLines = 2,
        )
        OutlinedTextField(
            form.notes, { form = form.copy(notes = it) }, label = { Text("Notes") },
            enabled = enabled, modifier = Modifier.fillMaxWidth(), minLines = 3,
        )

        if (!readOnly) {
            ErrorText(error)
            saved?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
            BusyButton("Save survey", busy) {
                error = form.error()
                saved = null
                if (error == null) {
                    if (vm.location.hasPermission()) save()
                    else askLocation.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
                }
            }
            Text("Location is read once when you save.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun Digits(label: String, value: String, enabled: Boolean, onChange: (String) -> Unit) {
    OutlinedTextField(
        value, { t -> onChange(t.filter(Char::isDigit).take(10)) }, label = { Text(label) }, singleLine = true,
        enabled = enabled, modifier = Modifier.fillMaxWidth(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Picker(label: String, items: List<ListEntryEntity>, selected: String?, enabled: Boolean, onPick: (String?) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val current = items.firstOrNull { it.id == selected }
    ExposedDropdownMenuBox(expanded = open && enabled, onExpandedChange = { if (enabled) open = it }) {
        OutlinedTextField(
            value = current?.let { it.nameEn ?: it.nameMr } ?: "", onValueChange = {}, readOnly = true, enabled = enabled,
            label = { Text(label) }, trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
            modifier = Modifier.fillMaxWidth().menuAnchor(MenuAnchorType.PrimaryNotEditable),
        )
        ExposedDropdownMenu(expanded = open && enabled, onDismissRequest = { open = false }) {
            DropdownMenuItem(text = { Text("(none)") }, onClick = { onPick(null); open = false })
            items.filter { it.isActive || it.id == selected }.forEach { e ->
                DropdownMenuItem(text = { Text(listOfNotNull(e.nameEn, e.nameMr).joinToString(" · ")) }, onClick = { onPick(e.id); open = false })
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DobField(value: String, enabled: Boolean, onChange: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Column(Modifier.weight(1f)) {
            Text("Date of birth", style = MaterialTheme.typography.titleSmall)
            Text(value.ifEmpty { "Not set" }, style = MaterialTheme.typography.bodyLarge)
        }
        OutlinedButton(onClick = { open = true }, enabled = enabled) { Text("Choose") }
        if (value.isNotEmpty()) TextButton(onClick = { onChange("") }, enabled = enabled) { Text("Clear") }
    }
    if (open) {
        val initial = runCatching { LocalDate.parse(value).atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli() }.getOrNull()
        val state = rememberDatePickerState(
            initialSelectedDateMillis = initial,
            yearRange = 1900..LocalDate.now().year,
            selectableDates = object : SelectableDates {
                override fun isSelectableDate(utcTimeMillis: Long) = utcTimeMillis <= System.currentTimeMillis()
            },
        )
        DatePickerDialog(
            onDismissRequest = { open = false },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { onChange(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString()) }
                    open = false
                }) { Text("OK") }
            },
            dismissButton = { TextButton(onClick = { open = false }) { Text("Cancel") } },
        ) { DatePicker(state) }
    }
}
