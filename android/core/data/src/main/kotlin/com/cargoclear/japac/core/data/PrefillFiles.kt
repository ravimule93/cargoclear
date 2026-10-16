package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.PrefillFormat
import com.cargoclear.japac.core.model.prefillFileName
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * The declaration pre-fill pack of an assessment as a file on this phone, to hand to the share sheet. Files live in the app's private cache
 * (never external storage) and only the newest few are kept; the share sheet gets a temporary read grant to one file, never a path.
 */
interface PrefillFiles {
    /** Downloads the pack of assessment [iteration] (always fresh: a pack names the audit head it was made at), and returns the file. */
    suspend fun download(bundleId: String, iteration: Int, format: PrefillFormat): File

    /** Total size of what is kept. */
    suspend fun sizeBytes(): Long

    suspend fun clear()
}

class CachedPrefillFiles(private val root: File, private val backend: Backend, private val keep: Int = KEEP_NEWEST) : PrefillFiles {
    private val lock = Mutex()

    override suspend fun download(bundleId: String, iteration: Int, format: PrefillFormat): File = lock.withLock {
        requirePlainId(bundleId)
        val target = downloadAtomically(root, prefillFileName(bundleId, iteration, format)) { sink ->
            backend.call {
                when (format) {
                    PrefillFormat.JSON -> prefillJson(bundleId, iteration)
                    PrefillFormat.PDF -> prefillPdf(bundleId, iteration)
                }.use { it.source().readAll(sink) }
            }
        }
        trim(keepFile = target)
        target
    }

    private suspend fun trim(keepFile: File) = withContext(Dispatchers.IO) {
        val files = root.listFiles { f -> f.isFile && !f.name.endsWith(".part") }.orEmpty().sortedByDescending { it.lastModified() }
        files.filter { it != keepFile }.drop((keep - 1).coerceAtLeast(0)).forEach { it.delete() }
    }

    override suspend fun sizeBytes(): Long = withContext(Dispatchers.IO) { root.walkTopDown().filter { it.isFile }.sumOf { it.length() } }

    override suspend fun clear() {
        lock.withLock { withContext(Dispatchers.IO) { root.deleteRecursively() } }
    }

    private companion object {
        const val KEEP_NEWEST = 10
    }
}
