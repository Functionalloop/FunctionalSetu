package com.jansetu.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Navy = Color(0xFF1B4F8A)
val Saffron = Color(0xFFF28C28)

private val Colors = lightColorScheme(
    primary = Navy,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD6E4F5),
    onPrimaryContainer = Color(0xFF0B2A4D),
    secondary = Saffron,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFFFE3C7),
    onSecondaryContainer = Color(0xFF4A2600),
    background = Color.White,
    surface = Color.White,
    surfaceVariant = Color(0xFFF1F4F8),
    error = Color(0xFFB3261E),
)

// Light only: field work is outdoors in daylight.
@Composable
fun JansetuTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Colors, content = content)
}
