package com.jansetu.app.ui.reports

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Chart colours (light theme only). One blue for single-series bars; men / women / other take the first three
 * categorical slots (blue, orange, aqua: checked for colour-blind separation; aqua is below 3:1 on white, so every
 * bar also prints its number). Colour tags use the admin's own tag colours, always next to the tag's name.
 */
object ChartColors {
    val bar = Color(0xFF2A78D6)
    val men = Color(0xFF2A78D6)
    val women = Color(0xFFEB6834)
    val other = Color(0xFF1BAF7A)
    val track = Color(0xFFE1E0D9)
    val noTag = Color(0xFFC3C2B7)
}

/** A thin horizontal bar from the left edge, rounded at its data end, over a light track. */
@Composable
fun Bar(fraction: Float, color: Color, modifier: Modifier = Modifier, height: Dp = 8.dp, track: Boolean = true) {
    Box(
        modifier.fillMaxWidth().height(height)
            .then(if (track) Modifier.clip(RoundedCornerShape(4.dp)).background(ChartColors.track) else Modifier),
    ) {
        if (fraction > 0f) Box(
            Modifier.fillMaxWidth(fraction.coerceIn(0.01f, 1f)).height(height)
                .clip(RoundedCornerShape(topEnd = 4.dp, bottomEnd = 4.dp)).background(color),
        )
    }
}

/** Label and value on one line, the bar below: fits a phone's width. */
@Composable
fun BarRow(label: String, value: String, fraction: Float, color: Color = ChartColors.bar, indent: Boolean = false, bold: Boolean = false) {
    Column(Modifier.fillMaxWidth().padding(start = if (indent) 16.dp else 0.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium,
                fontWeight = if (bold) FontWeight.SemiBold else null, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(value, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Bar(fraction, color)
    }
}

/** A bar with its number at the right end (bars compared with one another, no track). */
@Composable
fun ValueBar(fraction: Float, value: String, color: Color, height: Dp = 8.dp) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.weight(1f)) { Bar(fraction, color, height = height, track = false) }
        Text(value, Modifier.width(64.dp), style = MaterialTheme.typography.labelSmall, textAlign = TextAlign.End,
            color = MaterialTheme.colorScheme.onSurface)
    }
}

/** One bar in segments (one per colour tag), 2 dp of white between them. */
@Composable
fun SegmentedBar(parts: List<Pair<Int, Color>>, height: Dp = 10.dp) {
    val total = parts.sumOf { it.first }
    if (total <= 0) return
    Row(Modifier.fillMaxWidth().height(height).clip(RoundedCornerShape(4.dp)), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        parts.filter { it.first > 0 }.forEach { (n, c) -> Box(Modifier.weight(n.toFloat()).height(height).background(c)) }
    }
}

@Composable
fun Swatch(color: Color) {
    Box(Modifier.size(10.dp).clip(CircleShape).background(color))
}

/** Legend entry: swatch, name and total. */
@Composable
fun LegendItem(color: Color, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Swatch(color)
        Spacer(Modifier.width(6.dp))
        Text(label, style = MaterialTheme.typography.bodySmall)
    }
}

/** A headline number with its caption. */
@Composable
fun StatCard(label: String, value: String, detail: String?, modifier: Modifier = Modifier) {
    Card(modifier) {
        Column(Modifier.padding(12.dp)) {
            Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(value, style = MaterialTheme.typography.headlineSmall)
            detail?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
    }
}

@Composable
fun SectionTitle(text: String) {
    Text(text, Modifier.padding(top = 8.dp), style = MaterialTheme.typography.titleSmall)
}
