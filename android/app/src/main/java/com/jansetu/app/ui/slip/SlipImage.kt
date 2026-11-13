package com.jansetu.app.ui.slip

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import androidx.core.content.FileProvider
import java.io.File

/** Draws the slip as a PNG-ready bitmap with plain Android graphics (no Compose), the same image on screen and shared. */
fun drawSlip(c: SlipContent, width: Int = 1080): Bitmap {
    val pad = 56
    val inner = width - 2 * pad
    val labelWidth = 330
    fun paint(size: Float, color: Int, bold: Boolean = false) = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = size; this.color = color; typeface = if (bold) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
    }
    fun layout(text: String, p: TextPaint, w: Int) =
        StaticLayout.Builder.obtain(text, 0, text.length, p, w).setAlignment(Layout.Alignment.ALIGN_NORMAL).build()

    val headerPaint = paint(44f, Color.WHITE, bold = true)
    val titlePaint = paint(54f, BRAND, bold = true)
    val labelPaint = paint(34f, Color.rgb(90, 90, 90))
    val valuePaint = paint(42f, Color.BLACK, bold = true)
    val footPaint = paint(32f, Color.rgb(90, 90, 90))

    val header = c.header.map { layout(it, headerPaint, inner) }
    val title = layout("VOTER SLIP", titlePaint, inner)
    val rows = c.rows.map { (label, value) ->
        layout(label, labelPaint, labelWidth - 16) to layout(value, valuePaint, inner - labelWidth)
    }
    val footer = c.footer?.let { layout(it, footPaint, inner) }

    val headerHeight = if (header.isEmpty()) 24 else header.sumOf { it.height + 12 } + 2 * 36
    val rowGap = 28
    val height = headerHeight + 48 + title.height + 36 +
        rows.sumOf { (l, v) -> maxOf(l.height, v.height) + 2 * rowGap } +
        (footer?.let { it.height + 40 } ?: 0) + pad

    val bmp = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
    val canvas = Canvas(bmp)
    canvas.drawColor(Color.WHITE)
    canvas.drawRect(0f, 0f, width.toFloat(), headerHeight.toFloat(), Paint().apply { color = BRAND })

    fun draw(l: StaticLayout, x: Int, y: Int) {
        canvas.save(); canvas.translate(x.toFloat(), y.toFloat()); l.draw(canvas); canvas.restore()
    }
    var y = 36
    header.forEach { draw(it, pad, y); y += it.height + 12 }
    y = headerHeight + 48
    draw(title, pad, y)
    y += title.height + 36
    val line = Paint().apply { color = Color.rgb(220, 220, 220); strokeWidth = 2f }
    rows.forEach { (l, v) ->
        canvas.drawLine(pad.toFloat(), y.toFloat(), (width - pad).toFloat(), y.toFloat(), line)
        y += rowGap
        draw(l, pad, y + 6)
        draw(v, pad + labelWidth, y)
        y += maxOf(l.height, v.height) + rowGap
    }
    canvas.drawLine(pad.toFloat(), y.toFloat(), (width - pad).toFloat(), y.toFloat(), line)
    footer?.let { draw(it, pad, y + 40) }
    return bmp
}

private val BRAND = Color.rgb(11, 85, 99)

/** The slip is written to one cache file (overwritten each time) and handed out through the FileProvider. */
fun slipUri(context: Context, bmp: Bitmap): Uri {
    val dir = File(context.cacheDir, SLIP_DIR).apply { mkdirs() }
    val file = File(dir, "voter-slip.png")
    file.outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    return FileProvider.getUriForFile(context, context.packageName + ".files", file)
}

/** Deleted with the local database on logout or wipe: the image shows a voter's name. */
fun deleteSlipFiles(context: Context) {
    File(context.cacheDir, SLIP_DIR).deleteRecursively()
}

private const val SLIP_DIR = "slips"

private val WHATSAPP = listOf("com.whatsapp", "com.whatsapp.w4b")

/**
 * Opens the phone's own WhatsApp with the slip attached. With a mobile number, WhatsApp is asked to open
 * that chat (the `jid` extra); otherwise the worker picks the chat. Returns false when WhatsApp is not
 * installed (the caller then offers the share sheet).
 */
fun shareSlipOnWhatsApp(context: Context, bmp: Bitmap, mobile: String?): Boolean {
    val send = Intent(Intent.ACTION_SEND).setType("image/png")
        .putExtra(Intent.EXTRA_STREAM, slipUri(context, bmp))
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    if (mobile != null) send.putExtra("jid", "91$mobile@s.whatsapp.net")
    for (pkg in WHATSAPP) {
        try {
            context.startActivity(Intent(send).setPackage(pkg))
            return true
        } catch (e: android.content.ActivityNotFoundException) {
            // try the next one
        }
    }
    return false
}

/** Any app (Files, Drive, Bluetooth, ...), through the phone's share sheet. */
fun shareSlipAnywhere(context: Context, bmp: Bitmap) {
    val send = Intent(Intent.ACTION_SEND).setType("image/png")
        .putExtra(Intent.EXTRA_STREAM, slipUri(context, bmp))
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    context.startActivity(Intent.createChooser(send, "Share voter slip"))
}

/** Android 10+: saved to Pictures/JANSETU without a permission. Older phones: false (use the share sheet). */
fun saveSlipToPictures(context: Context, bmp: Bitmap, name: String): Boolean {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return false
    val resolver = context.contentResolver
    val values = ContentValues().apply {
        put(MediaStore.Images.Media.DISPLAY_NAME, "$name.png")
        put(MediaStore.Images.Media.MIME_TYPE, "image/png")
        put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/JANSETU")
        put(MediaStore.Images.Media.IS_PENDING, 1)
    }
    val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values) ?: return false
    resolver.openOutputStream(uri)?.use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    resolver.update(uri, ContentValues().apply { put(MediaStore.Images.Media.IS_PENDING, 0) }, null, null)
    return true
}
