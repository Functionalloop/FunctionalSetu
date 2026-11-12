package com.jansetu.app.ui.search

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.jansetu.app.data.local.AppDatabase
import com.jansetu.app.data.local.AreaEntity
import com.jansetu.app.data.local.VoterFilter
import com.jansetu.app.data.local.VoterQuery

/** Ward, booth, age, gender, colour tag and survey status (5.8). Shows the count before applying. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun FiltersScreen(db: AppDatabase, initial: VoterFilter, onApply: (VoterFilter) -> Unit, onClose: () -> Unit) {
    var f by remember { mutableStateOf(initial) }
    val wards by remember { db.areas().byLevel("ward") }.collectAsState(emptyList())
    val booths by remember { db.areas().byLevel("booth") }.collectAsState(emptyList())
    val tags by remember { db.lists().colorTags() }.collectAsState(emptyList())
    var count by remember { mutableIntStateOf(0) }
    LaunchedEffect(f) { count = db.voters().countNow(VoterQuery.count(f)) }

    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) {
            // The full-screen dialog draws under the system bars (Android 15 edge-to-edge): keep the
            // Show button above the navigation bar and the keyboard.
            Column(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing)) {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(8.dp)) {
                    IconButton(onClick = onClose) { Icon(Icons.Default.Close, "Close") }
                    Text("Filters", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                    TextButton(onClick = { f = VoterFilter(q = f.q) }) { Text("Clear all") }
                }
                Column(
                    Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    AreaPicker("Ward", wards, f.wardId) { f = f.copy(wardId = it, boothId = null) }
                    AreaPicker("Booth", booths.filter { f.wardId == null || it.parentId == f.wardId }, f.boothId) { f = f.copy(boothId = it) }

                    Text("Age", style = MaterialTheme.typography.titleSmall)
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        NumberField("From", f.ageMin, Modifier.weight(1f)) { f = f.copy(ageMin = it) }
                        NumberField("To", f.ageMax, Modifier.weight(1f)) { f = f.copy(ageMax = it) }
                    }

                    Text("Gender", style = MaterialTheme.typography.titleSmall)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf("M" to "Male", "F" to "Female", "O" to "Other").forEach { (code, label) ->
                            FilterChip(f.gender == code, { f = f.copy(gender = if (f.gender == code) null else code) }, { Text(label) })
                        }
                    }

                    if (tags.isNotEmpty()) {
                        Text("Colour tag", style = MaterialTheme.typography.titleSmall)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            tags.filter { it.isActive || it.id == f.colorTagId }.forEach { t ->
                                FilterChip(
                                    f.colorTagId == t.id, { f = f.copy(colorTagId = if (f.colorTagId == t.id) null else t.id) },
                                    { Text(t.labelEn) },
                                    leadingIcon = { ColorDot(t.hex) },
                                )
                            }
                        }
                    }

                    Text("Important voters", style = MaterialTheme.typography.titleSmall)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(f.important == true, { f = f.copy(important = if (f.important == true) null else true) },
                            { Text("Important only") })
                    }

                    Text("Survey", style = MaterialTheme.typography.titleSmall)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(true to "Surveyed", false to "Not surveyed").forEach { (v, label) ->
                            FilterChip(f.surveyed == v, { f = f.copy(surveyed = if (f.surveyed == v) null else v) }, { Text(label) })
                        }
                    }
                }
                Button(onClick = { onApply(f) }, modifier = Modifier.fillMaxWidth().padding(16.dp)) {
                    Text("Show %,d voters".format(count))
                }
            }
        }
    }
}

@Composable
fun ColorDot(hex: String, size: Int = 14) {
    Box(Modifier.size(size.dp).clip(CircleShape).background(parseHex(hex) ?: Color.Gray))
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AreaPicker(label: String, areas: List<AreaEntity>, selected: String?, onPick: (String?) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val current = areas.firstOrNull { it.id == selected }
    ExposedDropdownMenuBox(expanded = open, onExpandedChange = { open = it }) {
        OutlinedTextField(
            value = current?.let(::areaLabel) ?: "All", onValueChange = {}, readOnly = true,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
            modifier = Modifier.fillMaxWidth().menuAnchor(MenuAnchorType.PrimaryNotEditable),
        )
        ExposedDropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(text = { Text("All") }, onClick = { onPick(null); open = false })
            areas.forEach { a -> DropdownMenuItem(text = { Text(areaLabel(a)) }, onClick = { onPick(a.id); open = false }) }
        }
    }
}

fun areaLabel(a: AreaEntity) = listOfNotNull(a.number?.toString(), a.nameEn ?: a.nameMr).joinToString(" · ")

@Composable
private fun NumberField(label: String, value: Int?, modifier: Modifier, onChange: (Int?) -> Unit) {
    OutlinedTextField(
        value = value?.toString() ?: "",
        onValueChange = { t -> onChange(t.filter(Char::isDigit).take(3).toIntOrNull()) },
        label = { Text(label) }, singleLine = true, modifier = modifier,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
    )
}
