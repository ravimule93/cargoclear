package com.cargoclear.japac.core.data

import java.io.File
import java.io.IOException
import java.net.URI
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * PDFs that came into the app from outside (shared from another app, or scanned), copied into the app's private cache so a background
 * upload can still read them later. The read grant of a shared file lasts only while the app that shared it, and ours, are around;
 * the worker may run hours later. Each file keeps the name it arrived with (a demo extraction is keyed on it) inside a folder of its own,
 * and is deleted when its upload batch ends.
 */
class InboxFiles(private val root: File, private val now: () -> Long = System::currentTimeMillis) {
    /** One copied file: [uri] is a `file:` address inside [root], for the scheduler to hand to the worker. */
    data class Imported(val uri: String, val name: String, val bytes: Long)

    /** What came of a batch of files: the ones copied, and the names of the ones that could not be read (they are skipped, not fatal). */
    data class Result(val imported: List<Imported>, val unreadable: List<String>)

    suspend fun import(files: List<UploadFile>): Result = withContext(Dispatchers.IO) {
        purgeOlderThan(MAX_AGE_MILLIS)
        val stamp = now()
        val imported = mutableListOf<Imported>()
        val unreadable = mutableListOf<String>()
        files.forEachIndexed { index, file ->
            val name = safeName(file.name)
            val folder = File(root, "$stamp-$index")
            val target = File(folder, name)
            try {
                folder.mkdirs()
                file.open().use { input -> target.outputStream().use { input.copyTo(it) } }
                if (target.length() == 0L) throw IOException("empty file")
                imported += Imported(target.toURI().toString(), name, target.length())
            } catch (e: IOException) {
                folder.deleteRecursively()
                unreadable += file.name
            } catch (e: SecurityException) {
                folder.deleteRecursively()
                unreadable += file.name
            }
        }
        Result(imported, unreadable)
    }

    /** Deletes the copy [uri] names (and its folder). Anything that is not inside the inbox is left alone. */
    fun discard(uri: String) {
        val file = fileOf(uri) ?: return
        file.parentFile?.takeIf { it.parentFile?.canonicalPath == root.canonicalPath }?.deleteRecursively()
    }

    suspend fun clear() {
        withContext(Dispatchers.IO) { root.deleteRecursively() }
    }

    private fun purgeOlderThan(ageMillis: Long) {
        val cutoff = now() - ageMillis
        root.listFiles()?.filter { it.isDirectory && it.lastModified() < cutoff }?.forEach { it.deleteRecursively() }
    }

    /** The file a `file:` address inside the inbox names, or null for any other address. */
    private fun fileOf(uri: String): File? = try {
        val parsed = URI(uri)
        if (parsed.scheme != "file") null else File(parsed).canonicalFile.takeIf { it.path.startsWith(root.canonicalPath + File.separator) }
    } catch (e: Exception) {
        null
    }

    companion object {
        /** A copy nobody uploaded or discarded in a day is an abandoned one. */
        const val MAX_AGE_MILLIS: Long = 24L * 60 * 60 * 1000
        private const val MAX_NAME = 100
        private val UNSAFE = Regex("[^\\p{L}\\p{N}._ ()-]")

        fun rootIn(cacheDir: File): File = File(cacheDir, "inbox")

        /** A name that is safe as a file name here and still recognisably the one it arrived with (letters of any script are kept). */
        fun safeName(name: String): String {
            val base = name.substringAfterLast('/').substringAfterLast('\\').replace(UNSAFE, "_").trim().trimStart('.').take(MAX_NAME)
            return base.ifBlank { "document.pdf" }
        }
    }
}
