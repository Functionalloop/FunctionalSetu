package com.jansetu.app.ui.more

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jansetu.app.data.remote.ApiResult
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.Terms
import com.jansetu.app.data.remote.TermsAccept
import com.jansetu.app.data.remote.apiCall
import com.jansetu.app.data.remote.apiCallNoBody
import com.jansetu.app.data.remote.userMessage
import com.jansetu.app.ui.common.BusyButton
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.istTime
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Shown while the server has no terms text (it comes from the client). */
const val TERMS_MISSING = "The terms of use have not been published yet. They will show here once they are."

@HiltViewModel
class TermsViewModel @Inject constructor(private val api: JansetuApi) : ViewModel() {
    var terms by mutableStateOf<Terms?>(null)
        private set
    var missing by mutableStateOf(false)
        private set
    /** The version this user accepted (from GET /me). */
    var accepted by mutableStateOf<Int?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    fun load() = viewModelScope.launch {
        loading = true
        val t = apiCall { api.terms() }
        when {
            t is ApiResult.Ok -> { terms = t.value; missing = false; error = null }
            t is ApiResult.Err && t.status == 404 -> { terms = null; missing = true; error = null }
            t is ApiResult.Offline -> error = "The terms of use need internet. Connect and tap Try again."
            else -> error = t.userMessage()
        }
        if (terms != null) (apiCall { api.me() } as? ApiResult.Ok)?.let { accepted = it.value.user.termsVersion }
        loading = false
    }

    fun accept() = viewModelScope.launch {
        val t = terms ?: return@launch
        busy = true
        val r = apiCallNoBody { api.acceptTerms(TermsAccept(t.version)) }
        busy = false
        when {
            r is ApiResult.Ok -> { accepted = t.version; error = null }
            r is ApiResult.Err && r.code == "terms_changed" -> { error = r.message; load() }
            else -> error = r.userMessage()
        }
    }
}

@Composable
fun TermsScreen(onBack: () -> Unit, vm: TermsViewModel = hiltViewModel()) {
    LaunchedEffect(Unit) { vm.load() }
    MorePage("Terms of use", onBack) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (vm.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            ErrorText(vm.error)
            if (vm.error != null && vm.terms == null && !vm.missing) {
                OutlinedButton(onClick = { vm.load() }) { Text("Try again") }
            }
            if (vm.missing) Text(TERMS_MISSING, style = MaterialTheme.typography.bodyLarge)
            vm.terms?.let { t ->
                Text("Version ${t.version} · ${istTime(t.publishedAt) ?: t.publishedAt}", style = MaterialTheme.typography.labelLarge)
                Text(t.bodyEn, style = MaterialTheme.typography.bodyMedium)
                HorizontalDivider()
                Text(t.bodyMr, style = MaterialTheme.typography.bodyMedium)
                HorizontalDivider()
                if (vm.accepted == t.version) {
                    Text("You have accepted these terms.", color = MaterialTheme.colorScheme.primary)
                } else {
                    BusyButton("I accept", vm.busy, onClick = { vm.accept() })
                }
            }
        }
    }
}
