package com.cargoclear.japac.core.data

import java.io.ByteArrayInputStream
import java.io.IOException
import java.io.InputStream
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody
import okio.BufferedSink

/**
 * A file to upload, independent of where it lives. [open] may be called more than once (OkHttp can send a body again) and always reads
 * from the start. [size] is what the source says it has, or null; with it the request carries a Content-Length instead of being chunked,
 * which the UI's proxy and Cloud Run's front end both handle better.
 */
class UploadFile(val name: String, val size: Long?, val open: () -> InputStream) {
    companion object {
        fun of(name: String, bytes: ByteArray): UploadFile = UploadFile(name, bytes.size.toLong()) { ByteArrayInputStream(bytes) }
    }
}

/** The file on this phone could not be read: it was moved or deleted, or the permission to read it ended. Not a network failure. */
class UnreadableFileException(val fileName: String, cause: Throwable) : IOException("could not read $fileName", cause)

/** The file has a different length than its source announced: it changed while it was being sent, or the source reported a wrong size. */
class FileSizeChangedException(val fileName: String, val declared: Long) : IOException("$fileName is not $declared bytes long")

/**
 * Sends a file by reading it in blocks as the request goes out, so a 50 MB scan is never held in memory. A failure to *read* the file is
 * told apart from a failure to *send* it ([UnreadableFileException]), because only the second one is worth retrying.
 */
internal class StreamingFileBody(private val file: UploadFile, private val type: MediaType = PDF) : RequestBody() {
    override fun contentType(): MediaType = type

    override fun contentLength(): Long = file.size ?: -1L

    /** The source can be reopened, so OkHttp may send this body again (a redirect, a retried connection). */
    override fun isOneShot(): Boolean = false

    override fun writeTo(sink: BufferedSink) {
        val input = try {
            file.open()
        } catch (e: IOException) {
            throw UnreadableFileException(file.name, e)
        } catch (e: SecurityException) {
            throw UnreadableFileException(file.name, e)
        }
        input.use { stream ->
            val block = ByteArray(BLOCK_BYTES)
            val declared = file.size
            var sent = 0L
            while (true) {
                val read = try {
                    stream.read(block)
                } catch (e: IOException) {
                    throw UnreadableFileException(file.name, e)
                }
                if (read < 0) break
                // a request with a Content-Length must carry exactly that many bytes; say why it cannot instead of failing inside OkHttp
                if (declared != null && sent + read > declared) throw FileSizeChangedException(file.name, declared)
                sink.write(block, 0, read)
                sent += read
            }
            if (declared != null && sent != declared) throw FileSizeChangedException(file.name, declared)
        }
    }

    companion object {
        private const val BLOCK_BYTES = 64 * 1024
        val PDF: MediaType = "application/pdf".toMediaType()
    }
}
