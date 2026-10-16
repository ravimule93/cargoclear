package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.AuditResponse
import com.cargoclear.japac.core.model.AuditSignature
import com.cargoclear.japac.core.model.Bundle
import com.cargoclear.japac.core.model.CorrectionRecord
import com.cargoclear.japac.core.model.CorrectionRequest
import com.cargoclear.japac.core.model.CorrectionsResponse
import com.cargoclear.japac.core.model.CreateBundleRequest
import com.cargoclear.japac.core.model.DocumentDeleted
import com.cargoclear.japac.core.model.DocumentRecord
import com.cargoclear.japac.core.model.ExtractedDoc
import com.cargoclear.japac.core.model.Meta
import com.cargoclear.japac.core.model.RevertCorrectionRequest
import com.cargoclear.japac.core.model.RunResponse
import com.cargoclear.japac.core.model.TransformMetadataResponse
import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.Streaming

/** The backend's HTTP surface (paths are relative to [ApiConfig.baseUrl]). Grows with each phase; see docs/ANDROID_APP_PLAN.md section 8. */
interface CargoClearApi {
    @GET("meta")
    suspend fun meta(): Meta

    @POST("bundles")
    suspend fun createBundle(@Body body: CreateBundleRequest): Bundle

    @GET("bundles/{id}")
    suspend fun getBundle(@Path("id") id: String): Bundle

    @GET("bundles/{id}/assessment")
    suspend fun getAssessment(@Path("id") id: String): AssessmentIteration

    @GET("bundles/{id}/iterations")
    suspend fun listIterations(@Path("id") id: String): List<AssessmentIteration>

    /** Starts the full pipeline (202). Progress arrives on the stream. */
    @POST("bundles/{id}/analyze")
    suspend fun analyze(@Path("id") id: String): RunResponse

    /** Runs the pipeline again over the documents now in the bundle; the Reasoning Delta compares it with the previous assessment. */
    @POST("bundles/{id}/reassess")
    suspend fun reassess(@Path("id") id: String): RunResponse

    /** Re-runs the checks on the stored extraction with the corrections applied: no document is read, no model is called. */
    @POST("bundles/{id}/recompute")
    suspend fun recompute(@Path("id") id: String): RunResponse

    /**
     * One PDF, as the multipart field `file`, and optionally the field `declared_type` (what the uploader says the file is: a null part is left out).
     * Content-addressed on the server: sending the same bytes again is safe. The type is a part built with [MultipartBody.Part.createFormData],
     * not a `String`: the JSON converter would send a string as JSON, with quotes.
     */
    @Multipart
    @POST("bundles/{id}/documents")
    suspend fun uploadDocument(@Path("id") id: String, @Part file: MultipartBody.Part, @Part declaredType: MultipartBody.Part?): DocumentRecord

    /** Takes a document out of the bundle: its file, the model's kept answers and its record. 404 for a document not in the bundle, 409 while a run is in progress. */
    @DELETE("bundles/{id}/documents/{doc}")
    suspend fun deleteDocument(@Path("id") id: String, @Path("doc") documentId: String): DocumentDeleted

    /** How each page of a document was prepared for the model (turned, straightened) and where its page image is kept. 404 until the document was analysed. */
    @GET("bundles/{id}/documents/{doc}/transform-metadata")
    suspend fun transformMetadata(@Path("id") id: String, @Path("doc") documentId: String): TransformMetadataResponse

    /** The PDF as uploaded. Streamed: the caller reads it once and closes it. */
    @Streaming
    @GET("bundles/{id}/documents/{doc}/file")
    suspend fun documentFile(@Path("id") id: String, @Path("doc") documentId: String): ResponseBody

    /** The PNG of one page exactly as the extraction of [iteration] was shown it. 404 when it was not kept. */
    @Streaming
    @GET("bundles/{id}/documents/{doc}/pages/{page}")
    suspend fun processedPage(
        @Path("id") id: String,
        @Path("doc") documentId: String,
        @Path("page") page: Int,
        @Query("iteration") iteration: Int,
    ): ResponseBody

    /** The extraction of an assessment as its checks saw it: corrected values carry `corrected` and `original_value`. Untyped on purpose (the schema is large; the app only reads addresses). */
    @GET("bundles/{id}/extractions")
    suspend fun getExtractions(@Path("id") id: String, @Query("iteration") iteration: Int): List<ExtractedDoc>

    @GET("bundles/{id}/corrections")
    suspend fun getCorrections(@Path("id") id: String): CorrectionsResponse

    /** Records what the document actually states at one address. 409 before the first analysis, 404 for a document or row not in the latest extraction, 422 for a value that cannot be read without guessing. */
    @POST("bundles/{id}/corrections")
    suspend fun createCorrection(@Path("id") id: String, @Body body: CorrectionRequest): CorrectionRecord

    /** Appends an undo entry for a correction in force; the history is never edited. */
    @POST("bundles/{id}/corrections/{correctionId}/revert")
    suspend fun revertCorrection(@Path("id") id: String, @Path("correctionId") correctionId: String, @Body body: RevertCorrectionRequest): CorrectionRecord

    @GET("bundles/{id}/audit")
    suspend fun getAudit(@Path("id") id: String): AuditResponse

    /** Signs the newest event of the chain now. 409 when signing is not configured, or the chain does not verify. */
    @POST("bundles/{id}/audit/sign")
    suspend fun signAuditHead(@Path("id") id: String): AuditSignature

    /** The pre-fill pack as JSON, of assessment [iteration]. Streamed: the caller writes it to a file. */
    @Streaming
    @GET("bundles/{id}/prefill")
    suspend fun prefillJson(@Path("id") id: String, @Query("iteration") iteration: Int, @Query("download") download: Boolean = true): ResponseBody

    /** The pre-fill pack as a printable A4 summary. */
    @Streaming
    @GET("bundles/{id}/prefill.pdf")
    suspend fun prefillPdf(@Path("id") id: String, @Query("iteration") iteration: Int): ResponseBody

    /** Demo mode only: the sample mill test certificate of Case C. */
    @GET("demo/case-c/mtc")
    suspend fun sampleMtc(): ResponseBody

    /** Demo mode only. */
    @POST("demo/case-c")
    suspend fun createCaseCDemo(): Bundle

    /** Demo mode only. */
    @POST("demo/case-d")
    suspend fun createCaseDDemo(): Bundle
}
