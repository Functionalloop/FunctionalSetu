package com.jansetu.app.ui.more

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.BuildConfig
import com.jansetu.app.data.UpdateChecker
import com.jansetu.app.data.UpdateRequired
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.BusyButton
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.SetupPage
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class UpdateViewModel @Inject constructor(private val checker: UpdateChecker) : ViewModel() {
    var checking by mutableStateOf(false)
        private set
    var message by mutableStateOf<String?>(null)
        private set

    /** Asks the server again; if the minimum went down (or the app was updated), AppRoot moves on by itself. */
    fun checkAgain() = viewModelScope.launch {
        checking = true
        val r = checker.check()
        message = if (r is ApiResult.Ok) null else r.userMessage()
        checking = false
    }
}

/** Shown instead of everything else while this app is below the minimum version (7.9). */
@Composable
fun UpdateRequiredScreen(update: UpdateRequired, vm: UpdateViewModel = hiltViewModel()) {
    val context = LocalContext.current
    var openError by remember { mutableStateOf<String?>(null) }
    SetupPage(
        "Update required",
        "This version of JANSETU (${BuildConfig.VERSION_NAME}) is too old. Install the new version to go on. " +
            "Work not yet sent stays on the phone and is sent after the update.",
    ) {
        if (update.apkUrl != null) {
            BusyButton("Download the new app", busy = false) {
                openError = try {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(update.apkUrl)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    null
                } catch (_: ActivityNotFoundException) {
                    "No browser on this phone to download the app. Ask your admin."
                }
            }
            Text(
                "When the download ends, open the file and tap Install. If the phone asks, allow installing from this source.",
                style = MaterialTheme.typography.bodyMedium,
            )
        } else {
            Text("Connect to the internet and tap Check again to get the download link.", style = MaterialTheme.typography.bodyMedium)
        }
        ErrorText(openError ?: vm.message)
        OutlinedButton(onClick = { vm.checkAgain() }, enabled = !vm.checking, modifier = Modifier.fillMaxWidth()) {
            Text(if (vm.checking) "Checking…" else "Check again")
        }
    }
}
