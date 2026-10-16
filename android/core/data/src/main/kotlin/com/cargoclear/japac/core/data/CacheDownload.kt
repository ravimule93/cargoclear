package com.cargoclear.japac.core.data

import java.io.File
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okio.BufferedSink
import okio.buffer
import okio.sink

/** An id from the server or from a person becomes part of a file name only when it is a plain id (letters, digits, `_` and `-`): never a path. */
private val PLAIN_ID = Regex("[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

internal fun requirePlainId(id: String): String {
    require(PLAIN_ID.matches(id)) { "not a plain id: $id" }
    return id
}

/**
 * Writes what [download] produces into [dir] as [name], through a `.part` file that is renamed into place only when the download has
 * finished, so a failed or cancelled one never leaves half a file under the real name. The body may be read on the thread the download
 * runs on (Retrofit's streaming responses are), so all of it stays off the caller's thread.
 */
internal suspend fun downloadAtomically(dir: File, name: String, download: suspend (BufferedSink) -> Unit): File {
    val target = File(dir, name)
    val partial = File(dir, "$name.part")
    withContext(Dispatchers.IO) { dir.mkdirs() }
    try {
        withContext(Dispatchers.IO) { partial.sink().buffer().use { sink -> download(sink) } }
        withContext(Dispatchers.IO) {
            target.delete()
            if (!partial.renameTo(target)) throw IOException("could not move the download into place")
        }
    } catch (e: Throwable) {
        partial.delete()
        throw e
    }
    return target
}
