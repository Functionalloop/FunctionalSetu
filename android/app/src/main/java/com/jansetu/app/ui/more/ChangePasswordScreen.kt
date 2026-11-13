package com.jansetu.app.ui.more

import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.jansetu.app.ui.common.BusyButton
import com.jansetu.app.ui.common.ErrorText
import com.jansetu.app.ui.common.PasswordField
import com.jansetu.app.ui.setup.SetPasswordViewModel

/** Change password from More (needs internet). The same rules as the first-login screen; this phone stays logged in. */
@Composable
fun ChangePasswordScreen(onBack: () -> Unit, vm: SetPasswordViewModel = hiltViewModel()) {
    val context = LocalContext.current
    LaunchedEffect(vm.done) {
        if (vm.done) {
            Toast.makeText(context, "Password changed.", Toast.LENGTH_LONG).show()
            onBack()
        }
    }
    MorePage("Change password", onBack) {
        Column(
            Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                "At least 8 characters. Your other phones and the portal will ask you to log in again.",
                style = MaterialTheme.typography.bodyMedium,
            )
            if (vm.askCurrent) PasswordField(vm.current, { vm.current = it }, "Current password")
            PasswordField(vm.new, { vm.new = it }, "New password")
            PasswordField(vm.again, { vm.again = it }, "New password again")
            ErrorText(vm.error)
            BusyButton("Change password", vm.busy, onClick = vm::save)
        }
    }
}
