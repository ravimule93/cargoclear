package com.cargoclear.japac.ui

import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.AuditRepository
import com.cargoclear.japac.core.data.BundleRepository
import com.cargoclear.japac.core.data.CorrectionRepository
import com.cargoclear.japac.core.data.DemoCase
import com.cargoclear.japac.core.data.DocumentFiles
import com.cargoclear.japac.core.data.DocumentRepository
import com.cargoclear.japac.core.data.FileImporter
import com.cargoclear.japac.core.data.InboxFiles
import com.cargoclear.japac.core.data.MetaRepository
import com.cargoclear.japac.core.data.PrefillFiles
import com.cargoclear.japac.core.data.RecentBundle
import com.cargoclear.japac.core.data.RecentBundlesRepository
import com.cargoclear.japac.core.data.SavedCopy
import com.cargoclear.japac.core.data.SettingsRepository
import com.cargoclear.japac.core.data.StreamEvent
import com.cargoclear.japac.core.data.UploadFile
import com.cargoclear.japac.core.data.work.UploadScheduler
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.AuditResponse
import com.cargoclear.japac.core.model.AuditSignature
import com.cargoclear.japac.core.model.CorrectionKind
import com.cargoclear.japac.core.model.CorrectionRecord
import com.cargoclear.japac.core.model.CorrectionRequest
import com.cargoclear.japac.core.model.CorrectionsResponse
import com.cargoclear.japac.core.model.ExtractedDoc
import com.cargoclear.japac.core.model.PrefillFormat
import com.cargoclear.japac.core.model.Bundle
import com.cargoclear.japac.core.model.Destination
import com.cargoclear.japac.core.model.DocumentDeleted
import com.cargoclear.japac.core.model.DocumentRecord
import com.cargoclear.japac.core.model.ErrorEnvelope
import com.cargoclear.japac.core.model.Meta
import com.cargoclear.japac.core.model.RunResponse
import com.cargoclear.japac.core.model.RunState
import com.cargoclear.japac.core.model.SAMPLE_MTC_FILENAME
import com.cargoclear.japac.core.model.Status
import com.cargoclear.japac.core.model.TransformMetadataResponse
import com.cargoclear.japac.core.model.UploadBatch
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map

fun doc(id: String) = DocumentRecord(id, "bnd-1", "$id.pdf", "INVOICE", "gs://x", "sha", 2048, "2026-01-01T00:00:00Z")

fun bundle(iteration: Int = 0, status: String = "PENDING", vararg docs: String) =
    Bundle("bnd-1", "REF-1", "SG", status, iteration, docs.map(::doc), "2026-01-01T00:00:00Z")

fun assessment(n: Int, status: String = "MISSING_EVIDENCE") = AssessmentIteration(iteration = n, bundleId = "bnd-1", status = status)

fun apiFailure(kind: ApiException.Kind, message: String = "boom", code: String = "X", status: Int? = null) =
    ApiException(ErrorEnvelope(code = code, message = message), kind, status)

class FakeBundleRepository : BundleRepository {
    var bundle: Bundle = bundle()
    var bundleError: ApiException? = null
    var latest: AssessmentIteration? = null
    var latestError: ApiException? = null
    var iterations: List<AssessmentIteration> = emptyList()
    var createError: ApiException? = null
    var created: Bundle = bundle()

    val events = MutableSharedFlow<StreamEvent>(extraBufferCapacity = 64)

    var bundleCalls = 0
    var latestCalls = 0
    var iterationCalls = 0
    val creates = mutableListOf<Pair<String?, Destination>>()
    val demos = mutableListOf<DemoCase>()

    override suspend fun create(reference: String?, destination: Destination): Bundle {
        creates += reference to destination
        createError?.let { throw it }
        return created
    }

    override suspend fun createDemo(case: DemoCase): Bundle {
        demos += case
        createError?.let { throw it }
        return created
    }

    /** When set, a read of the bundle waits for it: lets a test have the stream say something while a refetch is under way. */
    var bundleGate: kotlinx.coroutines.CompletableDeferred<Unit>? = null

    override suspend fun bundle(id: String): Bundle {
        bundleCalls++
        bundleGate?.await()
        bundleError?.let { throw it }
        return bundle
    }

    override suspend fun latestAssessment(id: String): AssessmentIteration? {
        latestCalls++
        latestError?.let { throw it }
        return latest
    }

    override suspend fun iterations(id: String): List<AssessmentIteration> {
        iterationCalls++
        return iterations
    }

    /** What a run request answers: a run id, or a failure. Every request is recorded in [runCalls] as "analyze", "reassess" or "recompute". */
    var runError: ApiException? = null
    var nextRunId = "run-1"
    val runCalls = mutableListOf<String>()

    private fun run(kind: String, id: String): RunResponse {
        runCalls += kind
        runError?.let { throw it }
        return RunResponse(nextRunId, id, RunState.RUNNING)
    }

    override suspend fun analyze(id: String): RunResponse = run("analyze", id)

    override suspend fun reassess(id: String): RunResponse = run("reassess", id)

    override suspend fun recompute(id: String): RunResponse = run("recompute", id)

    override fun events(id: String): Flow<StreamEvent> = events
}

class FakeDocuments : DocumentRepository {
    val uploaded = mutableListOf<String>()
    var uploadError: ApiException? = null
    var sampleError: ApiException? = null

    /** What the transform-metadata call answers: a response, null (the server's 404), or a failure. */
    var geometry: TransformMetadataResponse? = null
    var geometryError: ApiException? = null
    var geometryCalls = 0

    override suspend fun transformMetadata(bundleId: String, documentId: String): TransformMetadataResponse? {
        geometryCalls++
        geometryError?.let { throw it }
        return geometry
    }

    override suspend fun upload(bundleId: String, file: UploadFile, declaredType: String?) = run {
        uploadError?.let { throw it }
        uploaded += file.name
        doc(file.name)
    }

    var deleted = mutableListOf<String>()
    var deleteError: ApiException? = null

    override suspend fun deleteDocument(bundleId: String, documentId: String): DocumentDeleted {
        deleteError?.let { throw it }
        deleted += documentId
        return DocumentDeleted(bundleId, documentId, "$documentId.pdf", 2, 0, null, false)
    }

    override suspend fun sampleMtc(): UploadFile {
        sampleError?.let { throw it }
        return UploadFile.of(SAMPLE_MTC_FILENAME, "%PDF".toByteArray())
    }
}

class FakeUploadScheduler : UploadScheduler {
    val batches = MutableStateFlow<List<UploadBatch>>(emptyList())
    val enqueued = mutableListOf<Triple<String, List<String>, Int>>()
    val cancelled = mutableListOf<String>()

    override fun enqueue(bundleId: String, uris: List<String>, currentIteration: Int) {
        enqueued += Triple(bundleId, uris, currentIteration)
    }

    override fun batches(bundleId: String): Flow<List<UploadBatch>> = batches

    override fun cancel(bundleId: String) {
        cancelled += bundleId
    }
}

class FakeRecents : RecentBundlesRepository {
    val rows = MutableStateFlow<Map<String, RecentBundle>>(emptyMap())
    val copies = mutableMapOf<String, SavedCopy>()
    val remembered = mutableListOf<Pair<Bundle, AssessmentIteration?>>()

    override fun observe(): Flow<List<RecentBundle>> = rows.map { it.values.toList() }

    override suspend fun remember(bundle: Bundle, assessment: AssessmentIteration?) {
        remembered += bundle to assessment
        rows.value = rows.value + (bundle.id to RecentBundle(bundle.id, bundle.reference, bundle.destinationCountry, Status.fromWire(assessment?.status ?: bundle.status), assessment?.iteration ?: bundle.currentIteration, bundle.documents.size, 1L))
        copies[bundle.id] = SavedCopy(bundle, assessment, savedAt = 1_000L)
    }

    override suspend fun savedCopy(bundleId: String): SavedCopy? = copies[bundleId]

    override suspend fun forget(bundleId: String) {
        rows.value = rows.value - bundleId
        copies.remove(bundleId)
    }
}

class FakeMeta(var mode: AppMode = AppMode.DEMO) : MetaRepository {
    override suspend fun load(forceRefresh: Boolean): Meta = Meta(mode, "fixtures")
}

class FakeDocumentFiles : DocumentFiles {
    var pdfError: Throwable? = null
    var pageError: Throwable? = null
    val pdfCalls = mutableListOf<Pair<String, String>>()
    val pageCalls = mutableListOf<List<Any>>()
    var cleared = false
    var size = 0L

    override suspend fun pdf(bundleId: String, documentId: String): java.io.File {
        pdfCalls += bundleId to documentId
        pdfError?.let { throw it }
        return java.io.File("/tmp/$documentId.pdf")
    }

    override suspend fun processedPage(bundleId: String, documentId: String, page: Int, iteration: Int): java.io.File {
        pageCalls += listOf(bundleId, documentId, page, iteration)
        pageError?.let { throw it }
        return java.io.File("/tmp/$documentId-p$page-i$iteration.png")
    }

    override suspend fun sizeBytes(): Long = size

    override suspend fun clear() {
        cleared = true
        size = 0
    }
}

class FakeSettings(secure: Boolean = true, notify: Boolean = false) : SettingsRepository {
    private val state = MutableStateFlow(secure)
    override val viewerSecure: Flow<Boolean> = state

    override suspend fun setViewerSecure(secure: Boolean) {
        state.value = secure
    }

    private val notifyState = MutableStateFlow(notify)
    override val notifyRunFinished: Flow<Boolean> = notifyState

    override suspend fun setNotifyRunFinished(notify: Boolean) {
        notifyState.value = notify
    }
}

/** The correction endpoints, held in memory: submitting adds an entry to the overlay (or replaces the one at its address), reverting removes it. */
class FakeCorrections : CorrectionRepository {
    var response = CorrectionsResponse(latestIteration = 1)
    var docs: List<ExtractedDoc> = emptyList()
    var listError: ApiException? = null
    var extractionError: ApiException? = null
    var submitError: ApiException? = null
    var revertError: ApiException? = null

    val submitted = mutableListOf<CorrectionRequest>()
    val reverted = mutableListOf<String>()
    var listCalls = 0
    val extractionCalls = mutableListOf<Int>()

    /** Held back until released: lets a test have two refreshes in flight at once. */
    var gate: kotlinx.coroutines.CompletableDeferred<Unit>? = null

    override suspend fun corrections(bundleId: String): CorrectionsResponse {
        listCalls++
        val snapshot = response
        gate?.await()
        listError?.let { throw it }
        return snapshot
    }

    override suspend fun submit(bundleId: String, request: CorrectionRequest): CorrectionRecord {
        submitted += request
        submitError?.let { throw it }
        val record = CorrectionRecord(
            correctionId = "cor-${10 + submitted.size}", kind = CorrectionKind.CORRECTION, seq = 10 + submitted.size, createdAt = "t", iteration = 1,
            documentId = request.documentId, path = request.path, value = request.value, unit = request.unit, reason = request.reason,
        )
        response = response.copy(effective = response.effective.filterNot { it.documentId == record.documentId && it.path == record.path } + record, pending = response.pending + 1)
        return record
    }

    override suspend fun revert(bundleId: String, correctionId: String): CorrectionRecord {
        reverted += correctionId
        revertError?.let { throw it }
        val gone = response.effective.first { it.correctionId == correctionId }
        response = response.copy(effective = response.effective - gone, pending = response.pending + 1)
        return gone.copy(kind = CorrectionKind.REVERT, reverts = correctionId)
    }

    override suspend fun extractions(bundleId: String, iteration: Int): List<ExtractedDoc> {
        extractionCalls += iteration
        extractionError?.let { throw it }
        return docs
    }
}

class FakeAudit : AuditRepository {
    var chain: AuditResponse = AuditResponse(verified = true)
    var auditError: ApiException? = null
    var signError: ApiException? = null
    var auditCalls = 0
    var signCalls = 0
    var gate: kotlinx.coroutines.CompletableDeferred<Unit>? = null

    override suspend fun audit(bundleId: String): AuditResponse {
        auditCalls++
        val snapshot = chain
        gate?.await()
        auditError?.let { throw it }
        return snapshot
    }

    override suspend fun signHead(bundleId: String): AuditSignature {
        signCalls++
        signError?.let { throw it }
        return checkNotNull(chain.signature)
    }
}

class FakePrefillFiles : PrefillFiles {
    var error: ApiException? = null
    val downloads = mutableListOf<Triple<String, Int, PrefillFormat>>()
    var cleared = false
    var size = 0L

    override suspend fun download(bundleId: String, iteration: Int, format: PrefillFormat): java.io.File {
        downloads += Triple(bundleId, iteration, format)
        error?.let { throw it }
        return java.io.File("/tmp/prefill-$bundleId-$iteration.${format.extension}")
    }

    override suspend fun sizeBytes(): Long = size

    override suspend fun clear() {
        cleared = true
        size = 0
    }
}

/** Files that come in from outside: each uri that is not listed in [unreadable] is "copied" to a `file:` address of its own. */
class FakeFileImporter : FileImporter {
    val unreadable = mutableSetOf<String>()
    val imports = mutableListOf<List<String>>()
    val discarded = mutableListOf<String>()

    override suspend fun import(uris: List<String>): InboxFiles.Result {
        imports += uris
        val (bad, good) = uris.partition { it in unreadable }
        return InboxFiles.Result(good.mapIndexed { i, uri -> InboxFiles.Imported("file:/inbox/$i-${uri.substringAfterLast('/')}", uri.substringAfterLast('/'), 1024) }, bad)
    }

    override fun discard(uri: String) {
        discarded += uri
    }
}
