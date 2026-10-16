package com.cargoclear.japac.core.data

import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * The PDFs and page images the viewer shows, kept on this phone so that a document opens again without the network. Files live in the
 * app's private cache (never external storage, never in a backup) and are evicted oldest-first when the cache is over its size.
 */
interface DocumentFiles {
    /** The PDF of a document: from the cache when it is there (a document's id names its content, so it never goes stale), else downloaded first. */
    suspend fun pdf(bundleId: String, documentId: String): File

    /** The page image the extraction of [iteration] was shown, downloaded once. */
    suspend fun processedPage(bundleId: String, documentId: String, page: Int, iteration: Int): File

    /** Total size of everything kept. */
    suspend fun sizeBytes(): Long

    /** Deletes everything kept (for the settings screen). */
    suspend fun clear()
}

class CachedDocumentFiles(
    private val root: File,
    private val maxBytes: Long,
    private val backend: Backend,
    private val now: () -> Long,
) : DocumentFiles {
    constructor(root: File, backend: Backend) : this(root, DEFAULT_MAX_BYTES, backend, System::currentTimeMillis)

    private val lock = Mutex()

    override suspend fun pdf(bundleId: String, documentId: String): File =
        fetch(bundleId, "${safe(documentId)}.pdf") { id, sink -> backend.call { documentFile(id, documentId).use { it.source().readAll(sink) } } }

    override suspend fun processedPage(bundleId: String, documentId: String, page: Int, iteration: Int): File =
        fetch(bundleId, "${safe(documentId)}-p$page-i$iteration.png") { id, sink ->
            backend.call { processedPage(id, documentId, page, iteration).use { it.source().readAll(sink) } }
        }

    private suspend fun fetch(bundleId: String, name: String, download: suspend (String, okio.BufferedSink) -> Unit): File = lock.withLock {
        val dir = File(root, safe(bundleId))
        val target = File(dir, name)
        if (target.isFile && target.length() > 0) {
            withContext(Dispatchers.IO) { target.setLastModified(now()) }
            return@withLock target
        }
        downloadAtomically(dir, name) { sink -> download(bundleId, sink) }
        withContext(Dispatchers.IO) { target.setLastModified(now()) }
        trim(keep = target)
        target
    }

    private suspend fun trim(keep: File) = withContext(Dispatchers.IO) {
        val files = root.walkTopDown().filter { it.isFile && !it.name.endsWith(".part") }.toList()
        var total = files.sumOf { it.length() }
        for (file in files.sortedBy { it.lastModified() }) {
            if (total <= maxBytes) break
            if (file == keep) continue
            total -= file.length()
            file.delete()
        }
        root.listFiles()?.filter { it.isDirectory && it.list().isNullOrEmpty() }?.forEach { it.delete() }
    }

    override suspend fun sizeBytes(): Long = withContext(Dispatchers.IO) { root.walkTopDown().filter { it.isFile }.sumOf { it.length() } }

    override suspend fun clear() {
        lock.withLock { withContext(Dispatchers.IO) { root.deleteRecursively() } }
    }

    /** Ids come from the server and from a person; they become file names, so anything that is not a plain id is refused. */
    private fun safe(id: String): String = requirePlainId(id)

    companion object {
        const val DEFAULT_MAX_BYTES: Long = 200L * 1024 * 1024
    }
}
