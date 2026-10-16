package com.cargoclear.japac.core.data.work

import android.content.Context
import android.content.Intent
import android.net.Uri
import com.cargoclear.japac.core.data.InboxFiles
import com.cargoclear.japac.core.model.isValidBundleId
import java.io.File
import java.io.IOException

/**
 * What each upload batch is holding on to, so that it can be given back when the batch ends or is cancelled, including a batch that never
 * started and so never gets to tidy up for itself.
 *
 * A batch holds files of two kinds: the read grant of a file the person picked (the platform limits how many an app may keep), and the
 * copy in the app's cache of a file that came in from outside (see [InboxFiles]). [release] gives one of them back. A small record per
 * batch, under [root] by bundle, remembers the Uris for as long as the batch has not ended: WorkManager does not say what a batch was
 * given, and the Uris must not go into a tag, because WorkManager writes tags to the log.
 */
class BatchFiles(private val root: File, private val release: (String) -> Unit) {
    /** The batch is queued: remember what it holds. A record that cannot be written only means a cancel cannot tidy up after this batch. */
    fun record(bundleId: String, batchId: String, uris: List<String>) {
        val file = recordOf(bundleId, batchId) ?: return
        try {
            file.parentFile?.mkdirs()
            file.writeText(uris.joinToString("\n"))
        } catch (_: IOException) {
        }
    }

    /** The batch ended (done, refused, out of attempts): give its files back and forget it. A batch that is only stopped and will run again does not end. */
    fun finished(bundleId: String, batchId: String, uris: List<String>) {
        uris.forEach(release)
        recordOf(bundleId, batchId)?.delete()
        folderOf(bundleId)?.delete() // goes only when it is empty: the bundle's other batches keep it
    }

    /** The person cancelled the uploads of this bundle: every batch that has not ended, the running one and the ones queued behind it, gives its files back. */
    fun cancelled(bundleId: String) {
        val folder = folderOf(bundleId) ?: return
        for (record in folder.listFiles().orEmpty()) {
            try {
                record.readLines().filter { it.isNotBlank() }.forEach(release)
            } catch (_: IOException) {
            }
            record.delete()
        }
        folder.delete()
    }

    private fun folderOf(bundleId: String): File? = if (isValidBundleId(bundleId)) File(root, bundleId) else null

    private fun recordOf(bundleId: String, batchId: String): File? =
        if (SAFE_BATCH_ID.matches(batchId)) folderOf(bundleId)?.let { File(it, batchId) } else null

    companion object {
        private val SAFE_BATCH_ID = Regex("[A-Za-z0-9-]{1,64}")

        /** The real thing: grants are given back to the system, copies are deleted from the inbox, records live in the app's cache. */
        fun forContext(context: Context): BatchFiles {
            val inbox = InboxFiles(InboxFiles.rootIn(context.cacheDir))
            return BatchFiles(File(context.cacheDir, "upload-batches")) { uri ->
                runCatching { context.contentResolver.releasePersistableUriPermission(Uri.parse(uri), Intent.FLAG_GRANT_READ_URI_PERMISSION) }
                if (uri.startsWith("file:")) inbox.discard(uri)
            }
        }
    }
}
