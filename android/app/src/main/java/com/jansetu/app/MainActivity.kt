package com.jansetu.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.jansetu.app.ui.nav.AppRoot
import com.jansetu.app.ui.theme.JansetuTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            JansetuTheme {
                Surface(Modifier.fillMaxSize()) { AppRoot() }
            }
        }
    }
}
