package com.jansetu.app.ui.search

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.jansetu.app.data.local.ColorTagEntity

/**
 * Select many (7.8): long-press a voter in Search to start ticking; tap ticks and unticks. The bar
 * offers what can be done with the ticked voters. Share on WhatsApp (5 or fewer) comes with 7.12.
 */
@Composable
fun SelectionBar(count: Int, shown: Int, canTag: Boolean, onSelectShown: () -> Unit, onTag: () -> Unit, onClose: () -> Unit) {
    Surface(color = MaterialTheme.colorScheme.secondaryContainer, tonalElevation = 2.dp) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onClose) { Icon(Icons.Default.Close, "Stop selecting") }
                Text("$count selected", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                TextButton(onClick = onSelectShown) { Text("Select shown ($shown)") }
            }
            if (canTag) Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), horizontalArrangement = Arrangement.End) {
                Button(onClick = onTag, enabled = count > 0) { Text("Set colour tag") }
            }
        }
    }
}

/** Pick the tag for the ticked voters, or no tag. */
@Composable
fun ColorTagDialog(count: Int, tags: List<ColorTagEntity>, onPick: (ColorTagEntity?) -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Colour tag for $count voters") },
        text = {
            Column {
                tags.filter { it.isActive }.forEach { t ->
                    Row(
                        Modifier.fillMaxWidth().clickable { onPick(t) }.padding(vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(Modifier.size(18.dp).clip(CircleShape).background(parseHex(t.hex) ?: Color.Gray))
                        Text(t.labelEn, Modifier.padding(start = 12.dp), style = MaterialTheme.typography.bodyLarge)
                    }
                }
                Row(Modifier.fillMaxWidth().clickable { onPick(null) }.padding(vertical = 10.dp)) {
                    Text("No tag (remove)", style = MaterialTheme.typography.bodyLarge)
                }
                Text("Saved on the phone at once and sent with the next sync.", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        },
        confirmButton = {},
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
