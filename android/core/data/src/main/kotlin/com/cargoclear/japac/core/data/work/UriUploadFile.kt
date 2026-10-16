package com.cargoclear.japac.core.data.work

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import com.cargoclear.japac.core.data.UploadFile
import java.io.File
import java.io.FileInputStream
import java.io.FileNotFoundException

/**
 * The file a content Uri (from the system file picker) points at. Nothing is read here: the name and size come from the provider's
 * metadata, and the bytes are read only when the request goes out. A size the provider does not give, or gives as zero or less, is left
 * out, so the upload is sent without a declared length rather than with a wrong one.
 */
fun ContentResolver.uploadFile(uri: Uri): UploadFile {
    // a copy in the app's own cache (a shared or scanned file, see InboxFiles): the provider machinery below answers only for content Uris
    if (uri.scheme == "file") uri.path?.let { return uploadFileOf(File(it)) }
    var name: String? = null
    var size: Long? = null
    runCatching {
        query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME).takeIf { it >= 0 && !cursor.isNull(it) }?.let { name = cursor.getString(it) }
                cursor.getColumnIndex(OpenableColumns.SIZE).takeIf { it >= 0 && !cursor.isNull(it) }?.let { size = cursor.getLong(it) }
            }
        }
    }
    val fallback = uri.lastPathSegment?.substringAfterLast('/')?.takeIf { it.isNotBlank() } ?: "document.pdf"
    return UploadFile(
        name = name?.takeIf { it.isNotBlank() } ?: fallback,
        size = size?.takeIf { it > 0 },
        open = { openInputStream(uri) ?: throw FileNotFoundException(uri.toString()) },
    )
}

/** A file on this phone's own storage: its name and length are the file's, and it is read when the request goes out. */
fun uploadFileOf(file: File): UploadFile = UploadFile(file.name, file.length().takeIf { it > 0 }) { FileInputStream(file) }
