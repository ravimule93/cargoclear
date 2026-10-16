package com.cargoclear.japac.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * The two destinations the rules cover; the checks and the duty estimate depend on where the goods are going.
 * Same list as `DESTINATIONS` in frontend/app/page.tsx.
 */
enum class Destination(val code: String, val label: String) {
    SINGAPORE("SG", "Singapore (SG)"),
    INDIA("IN", "India (IN)"),
}

/** One uploaded document of a bundle (`DocumentResponse` in backend/app/domain/schemas.py). */
@Serializable
data class DocumentRecord(
    @SerialName("document_id") val documentId: String,
    @SerialName("bundle_id") val bundleId: String,
    val filename: String,
    @SerialName("doc_type") val docType: String,
    /** Sent by the backend; the app never uses a storage address (documents are fetched through the API). */
    @SerialName("gcs_uri") val gcsUri: String,
    val sha256: String,
    val bytes: Long,
    @SerialName("uploaded_at") val uploadedAt: String,
    @SerialName("transform_meta_uri") val transformMetaUri: String? = null,
    /** What the uploader said the file is, or null; the assessment flags a file read as another type (T-001). */
    @SerialName("declared_type") val declaredType: String? = null,
)

/**
 * What `DELETE /bundles/{id}/documents/{doc}` answers (`DocumentDeletedResponse`): what was removed, and whether the newest assessment used the
 * document ([inLatestAssessment]; that assessment is not changed by the removal, a reassessment drops the document).
 */
@Serializable
data class DocumentDeleted(
    @SerialName("bundle_id") val bundleId: String,
    @SerialName("document_id") val documentId: String,
    val filename: String,
    @SerialName("files_removed") val filesRemoved: Int,
    @SerialName("cached_answers_removed") val cachedAnswersRemoved: Int,
    @SerialName("latest_iteration") val latestIteration: Int? = null,
    @SerialName("in_latest_assessment") val inLatestAssessment: Boolean,
)

/**
 * A bundle and its documents (`BundleResponse`).
 *
 * [status] is the backend's plain string: a bundle that has never been assessed is `PENDING`, which is not one of the four assessment
 * statuses (the web client's type says otherwise). Read it through [statusKind].
 */
@Serializable
data class Bundle(
    val id: String,
    val reference: String? = null,
    @SerialName("destination_country") val destinationCountry: String,
    val status: String,
    @SerialName("current_iteration") val currentIteration: Int,
    val documents: List<DocumentRecord> = emptyList(),
    @SerialName("created_at") val createdAt: String,
) {
    /** The assessment status, or null when the bundle has none yet (or the backend sent a value this app does not know). */
    val statusKind: Status? get() = Status.fromWire(status)
}

/** Body of `POST /bundles`. A null [reference] is left out of the JSON, as the web client does. */
@Serializable
data class CreateBundleRequest(
    val reference: String? = null,
    @SerialName("destination_country") val destinationCountry: String,
)
