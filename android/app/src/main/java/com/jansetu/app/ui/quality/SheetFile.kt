package com.jansetu.app.ui.quality

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody

/**
 * A CSV or Excel file picked with the system file picker (mobile number sheets, roll files).
 * File managers name CSV types differently, so the picker offers text and spreadsheet types and
 * the name decides; the server checks the content again.
 */
class SheetFile(val name: String, val bytes: ByteArray) {
    fun part(field: String = "file"): MultipartBody.Part =
        MultipartBody.Part.createFormData(field, name, bytes.toRequestBody(QualityRules.mimeFor(name).toMediaType()))

    companion object {
        val PICK_TYPES = arrayOf(
            "text/*", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel",
            "application/octet-stream",
        )

        /** The file, or a message for the user. Reads on the IO thread. */
        suspend fun read(context: Context, uri: Uri): Pair<SheetFile?, String?> = withContext(Dispatchers.IO) {
            try {
                var name: String? = null
                var size: Long? = null
                context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
                    if (c.moveToFirst()) {
                        name = c.getString(0)
                        size = if (c.isNull(1)) null else c.getLong(1)
                    }
                }
                QualityRules.sheetProblem(name, size)?.let { return@withContext null to it }
                val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                    ?: return@withContext null to "The file could not be opened."
                QualityRules.sheetProblem(name, bytes.size.toLong())?.let { return@withContext null to it }
                SheetFile(name!!, bytes) to null
            } catch (e: java.io.IOException) {
                null to "The file could not be read."
            } catch (e: SecurityException) {
                null to "The file could not be read."
            }
        }
    }
}
