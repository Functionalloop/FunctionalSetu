package com.jansetu.app.ui.admin.settings

import android.app.TimePickerDialog
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.ErrorText
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import javax.inject.Inject

/** Text keys of the settings this screen shows (everything else goes back to the server as it came). */
private val TEXT_KEYS = listOf(
    "election_name_mr", "election_name_en", "election_type", "polling_date", "polling_start_time", "polling_end_time",
    "candidate_name_mr", "candidate_name_en", "party_name_mr", "party_name_en", "candidate_message_mr",
    "candidate_message_en", "contact_no",
)
private val FLAG_KEYS = listOf("code_of_conduct_mode", "slip_show_candidate")

/** Settings key of an uploaded image -> the file kind the server wants for it. */
private val IMAGE_KEYS = linkedMapOf("candidate_photo_file_id" to "candidate_photo", "symbol_file_id" to "symbol")

/**
 * Election & candidate (9.7): admin and super admin, online. GET /settings/election, edit, PUT the whole object.
 * Phones get the change (slip, polling time) on their next sync.
 */
@HiltViewModel
class ElectionViewModel @Inject constructor(
    private val api: JansetuApi, @ApplicationContext private val context: Context,
) : ViewModel() {
    private var server: JsonObject? = null
    val form = mutableStateMapOf<String, String>()
    val flags = mutableStateMapOf<String, Boolean>()
    /** Image key -> file id (null = none). */
    val files = mutableStateMapOf<String, String?>()
    val images = mutableStateMapOf<String, ImageBitmap>()
    var loaded by mutableStateOf(false)
        private set
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
    var notice by mutableStateOf<String?>(null)

    init { reload() }

    fun reload() = viewModelScope.launch {
        busy = true
        val r = apiCall { api.electionSettings() }
        busy = false
        if (r is ApiResult.Ok) show(r.value) else error = r.userMessage()
    }

    private fun show(s: JsonObject) {
        server = s
        TEXT_KEYS.forEach { form[it] = SettingsRules.text(s, it) }
        FLAG_KEYS.forEach { flags[it] = SettingsRules.flag(s, it) }
        IMAGE_KEYS.keys.forEach { k ->
            val id = SettingsRules.text(s, k).ifEmpty { null }
            files[k] = id
            if (id == null) images.remove(k) else loadImage(k, id)
        }
        loaded = true
        error = null
    }

    private fun loadImage(key: String, id: String) = viewModelScope.launch {
        val r = apiCall { api.file(id) } as? ApiResult.Ok ?: return@launch
        val bmp = withContext(Dispatchers.IO) { r.value.use { body -> BitmapFactory.decodeStream(body.byteStream()) } }
        if (bmp != null && files[key] == id) images[key] = bmp.asImageBitmap()
    }

    fun save() {
        val s = server ?: return
        SettingsRules.checkElection(form["polling_start_time"].orEmpty(), form["polling_end_time"].orEmpty(),
            form["contact_no"].orEmpty())?.let { error = it; return }
        val changes: Map<String, Any?> = form + flags + files
        viewModelScope.launch {
            busy = true
            val r = apiCall { api.saveElectionSettings(SettingsRules.withChanges(s, changes)) }
            busy = false
            if (r is ApiResult.Ok) { show(r.value); notice = "Saved. Phones get it at their next sync." } else error = r.userMessage()
        }
    }

    /** Shrinks the picked image (longer side 1280 px), uploads it, and holds its id until Save. */
    fun upload(key: String, uri: Uri) = viewModelScope.launch {
        busy = true
        val prepared = withContext(Dispatchers.IO) { runCatching { prepare(uri) }.getOrNull() }
        if (prepared == null) { busy = false; error = "Could not read that picture."; return@launch }
        val (bytes, mime, bitmap) = prepared
        if (bytes.size > SettingsRules.MAX_UPLOAD) { busy = false; error = "The picture is still over 5 MB."; return@launch }
        val ext = if (mime == "image/png") "png" else "jpg"
        val r = apiCall {
            api.uploadFile(
                IMAGE_KEYS.getValue(key).toRequestBody("text/plain".toMediaType()),
                MultipartBody.Part.createFormData("file", "$key.$ext", bytes.toRequestBody(mime.toMediaType())),
            )
        }
        busy = false
        if (r is ApiResult.Ok) { files[key] = r.value.id; images[key] = bitmap.asImageBitmap(); error = null; notice = "Picture ready: tap Save." }
        else error = r.userMessage()
    }

    fun removeImage(key: String) { files[key] = null; images.remove(key) }

    private fun prepare(uri: Uri): Triple<ByteArray, String, Bitmap> {
        val resolver = context.contentResolver
        val png = resolver.getType(uri) == "image/png" // keeps a symbol's transparent background
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        resolver.openInputStream(uri)!!.use { BitmapFactory.decodeStream(it, null, bounds) }
        val opts = BitmapFactory.Options().apply { inSampleSize = SettingsRules.sampleSize(bounds.outWidth, bounds.outHeight) }
        var bmp = resolver.openInputStream(uri)!!.use { BitmapFactory.decodeStream(it, null, opts) }!!
        val longer = maxOf(bmp.width, bmp.height)
        if (longer > 1280) bmp = Bitmap.createScaledBitmap(bmp, bmp.width * 1280 / longer, bmp.height * 1280 / longer, true)
        val out = ByteArrayOutputStream()
        bmp.compress(if (png) Bitmap.CompressFormat.PNG else Bitmap.CompressFormat.JPEG, 85, out)
        return Triple(out.toByteArray(), if (png) "image/png" else "image/jpeg", bmp)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ElectionScreen(onBack: () -> Unit, vm: ElectionViewModel = hiltViewModel()) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Election & candidate") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                actions = { IconButton(onClick = { vm.reload() }) { Icon(Icons.Default.Refresh, "Reload") } },
            )
        },
    ) { padding ->
        Column(
            Modifier.padding(padding).imePadding().fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (vm.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            ErrorText(vm.error)
            if (!vm.loaded) return@Column
            val f = vm.form

            Text("Election", style = MaterialTheme.typography.titleMedium)
            Field(vm, "election_name_en", "Election name (English)")
            Field(vm, "election_name_mr", "Election name (Marathi)")
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SettingsRules.ELECTION_TYPES.forEach { (code, label) ->
                    FilterChip(f["election_type"] == code, { f["election_type"] = if (f["election_type"] == code) "" else code }, { Text(label) })
                }
            }
            DateRow("Polling date", f["polling_date"].orEmpty()) { f["polling_date"] = it }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Polling time", Modifier.weight(1f))
                TimeButton("From", f["polling_start_time"].orEmpty()) { f["polling_start_time"] = it }
                TimeButton("To", f["polling_end_time"].orEmpty()) { f["polling_end_time"] = it }
            }
            Text("The polling time is printed on the voter slip.", style = MaterialTheme.typography.bodySmall)

            HorizontalDivider()
            Text("Candidate", style = MaterialTheme.typography.titleMedium)
            Field(vm, "candidate_name_en", "Candidate name (English)")
            Field(vm, "candidate_name_mr", "Candidate name (Marathi)")
            Field(vm, "party_name_en", "Party (English)")
            Field(vm, "party_name_mr", "Party (Marathi)")
            Field(vm, "contact_no", "Contact number", keyboard = KeyboardType.Phone)
            ImageRow(vm, "symbol_file_id", "Party symbol")
            ImageRow(vm, "candidate_photo_file_id", "Candidate photo")
            Field(vm, "candidate_message_en", "Message for WhatsApp (English)", lines = 4)
            Field(vm, "candidate_message_mr", "Message for WhatsApp (Marathi)", lines = 4)
            SwitchRow("Show the candidate on voter slips", vm.flags["slip_show_candidate"] == true) { vm.flags["slip_show_candidate"] = it }
            SwitchRow("Code of conduct: hide the candidate on every phone", vm.flags["code_of_conduct_mode"] == true) {
                vm.flags["code_of_conduct_mode"] = it
            }

            vm.notice?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
            Button(onClick = { vm.notice = null; vm.save() }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) { Text("Save") }
        }
    }
}

@Composable
private fun Field(vm: ElectionViewModel, key: String, label: String, lines: Int = 1, keyboard: KeyboardType = KeyboardType.Text) {
    OutlinedTextField(
        vm.form[key].orEmpty(), { vm.form[key] = if (keyboard == KeyboardType.Phone) it.filter(Char::isDigit).take(10) else it.take(2000) },
        label = { Text(label) }, singleLine = lines == 1, minLines = lines, modifier = Modifier.fillMaxWidth(),
        keyboardOptions = KeyboardOptions(keyboardType = keyboard),
    )
}

@Composable
private fun SwitchRow(label: String, on: Boolean, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f))
        Switch(on, onChange)
    }
}

@Composable
private fun TimeButton(label: String, value: String, onPick: (String) -> Unit) {
    val context = LocalContext.current
    OutlinedButton(onClick = {
        val t = SettingsRules.parseTime(value)
        TimePickerDialog(context, { _, h, m -> onPick(SettingsRules.timeValue(h, m)) }, t?.hour ?: 7, t?.minute ?: 0, false).show()
    }) { Text(SettingsRules.showTime(value).ifEmpty { label }) }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DateRow(label: String, value: String, onPick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f))
        OutlinedButton(onClick = { open = true }) { Text(SettingsRules.showDate(value).ifEmpty { "Choose" }) }
        if (value.isNotEmpty()) TextButton(onClick = { onPick("") }) { Text("Clear") }
    }
    if (open) {
        val initial = runCatching { LocalDate.parse(value).atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli() }.getOrNull()
        val state = rememberDatePickerState(initialSelectedDateMillis = initial)
        DatePickerDialog(
            onDismissRequest = { open = false },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { onPick(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString()) }
                    open = false
                }) { Text("OK") }
            },
            dismissButton = { TextButton(onClick = { open = false }) { Text("Cancel") } },
        ) { DatePicker(state) }
    }
}

@Composable
private fun ImageRow(vm: ElectionViewModel, key: String, label: String) {
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri -> uri?.let { vm.upload(key, it) } }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Column(Modifier.weight(1f)) {
            Text(label)
            if (vm.files[key] == null) Text("None", style = MaterialTheme.typography.bodySmall)
        }
        vm.images[key]?.let { Image(it, label, Modifier.size(56.dp)) }
        OutlinedButton(onClick = { pick.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
            enabled = !vm.busy) { Text(if (vm.files[key] == null) "Choose" else "Change") }
        if (vm.files[key] != null) TextButton(onClick = { vm.removeImage(key) }) { Text("Remove") }
    }
}
