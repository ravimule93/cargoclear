package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.DocumentDeleted
import com.cargoclear.japac.core.model.DocumentRecord
import com.cargoclear.japac.core.model.SAMPLE_MTC_FILENAME
import com.cargoclear.japac.core.model.TransformMetadataResponse
import javax.inject.Inject
import javax.inject.Singleton

/** The documents of a bundle. Every failure is an [ApiException]. */
interface DocumentRepository {
    /**
     * Sends one PDF into the bundle. The server names the document after its content, so sending the same bytes again is safe.
     * [declaredType] (one of the six types the server reads, e.g. `COMMERCIAL_INVOICE`) says what the file is: when the model reads another
     * type the assessment warns (T-001). A value the server does not know is a 422. Null sends no type.
     */
    suspend fun upload(bundleId: String, file: UploadFile, declaredType: String? = null): DocumentRecord

    /**
     * Takes a document out of the bundle. 409 while a run is in progress, 404 when the document is not in the bundle. The newest assessment still
     * counts the document until the bundle is reassessed (see [DocumentDeleted.inLatestAssessment]).
     */
    suspend fun deleteDocument(bundleId: String, documentId: String): DocumentDeleted

    /** Demo mode only: the sample mill test certificate, named the way the demo extraction expects (it is keyed on the file name). */
    suspend fun sampleMtc(): UploadFile

    /** How the pages of a document were prepared for the model, or null when the server has no record (it answers 404 until the document was analysed). */
    suspend fun transformMetadata(bundleId: String, documentId: String): TransformMetadataResponse?
}

@Singleton
class NetworkDocumentRepository @Inject constructor(private val backend: Backend) : DocumentRepository {
    override suspend fun upload(bundleId: String, file: UploadFile, declaredType: String?): DocumentRecord =
        try {
            send(bundleId, file, declaredType)
        } catch (e: ApiException) {
            // some document providers announce a size that is not the file's real length: send it again without announcing one
            if (e.kind == ApiException.Kind.LOCAL_FILE && e.cause is FileSizeChangedException && file.size != null) {
                send(bundleId, UploadFile(file.name, null, file.open), declaredType)
            } else {
                throw e
            }
        }

    override suspend fun deleteDocument(bundleId: String, documentId: String): DocumentDeleted =
        backend.call { deleteDocument(bundleId, documentId) }

    private suspend fun send(bundleId: String, file: UploadFile, declaredType: String?): DocumentRecord = backend.callForUpload {
        // Opened here, before anything is sent, so a file that cannot be read fails at once and for certain: left to the request, OkHttp's own
        // retry of a failed body can end in some other exception. The stream is the one the first send reads; a resend opens the file again.
        val first = openOrThrow(file)
        var firstTaken = false
        val source = UploadFile(file.name, file.size) {
            if (!firstTaken) {
                firstTaken = true
                first
            } else {
                file.open()
            }
        }
        try {
            uploadDocument(
                bundleId,
                okhttp3.MultipartBody.Part.createFormData(FIELD, file.name.ifBlank { DEFAULT_NAME }, StreamingFileBody(source)),
                declaredType?.takeIf { it.isNotBlank() }?.let { okhttp3.MultipartBody.Part.createFormData(DECLARED_TYPE_FIELD, it) },
            )
        } finally {
            if (!firstTaken) runCatching { first.close() }
        }
    }

    private fun openOrThrow(file: UploadFile): java.io.InputStream =
        try {
            file.open()
        } catch (e: java.io.IOException) {
            throw UnreadableFileException(file.name, e)
        } catch (e: SecurityException) {
            throw UnreadableFileException(file.name, e)
        }

    override suspend fun transformMetadata(bundleId: String, documentId: String): TransformMetadataResponse? =
        try {
            backend.call { transformMetadata(bundleId, documentId) }
        } catch (e: ApiException) {
            if (e.isNotFound) null else throw e
        }

    override suspend fun sampleMtc(): UploadFile {
        val bytes = backend.call { sampleMtc().use { it.bytes() } }
        return UploadFile.of(SAMPLE_MTC_FILENAME, bytes)
    }

    private companion object {
        const val FIELD = "file"
        const val DECLARED_TYPE_FIELD = "declared_type"
        const val DEFAULT_NAME = "document.pdf"
    }
}
