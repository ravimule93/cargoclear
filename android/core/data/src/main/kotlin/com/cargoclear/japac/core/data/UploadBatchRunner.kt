package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.ActionError
import com.cargoclear.japac.core.model.BatchOutcome
import com.cargoclear.japac.core.model.UPLOAD_STOPPED_MESSAGE
import com.cargoclear.japac.core.model.runCatchingCancellable
import com.cargoclear.japac.core.model.runErrorMessage
import com.cargoclear.japac.core.model.shouldAutoReassess
import com.cargoclear.japac.core.model.uploadErrorMessage
import javax.inject.Inject
import kotlin.coroutines.cancellation.CancellationException

/** How [UploadBatchRunner.run] ended; [retryable] says a try later could end differently (the connection failed, the server was busy). */
class BatchResult(val outcome: BatchOutcome, val retryable: Boolean)

/**
 * One upload batch, the way the web does it (`uploadFiles` and `handleUploaded` in useWorkbench): the files go up one after another and the
 * batch stops at the first failure; when every file landed and the bundle has already been assessed, it ends by asking for one
 * reassessment, never one per file. The first analysis of a bundle waits for the person to ask for it.
 *
 * Lives here, not in the scheduler's worker, so its rules run on the plain JVM and the same batch can run inline (the demo's sample
 * certificate).
 */
class UploadBatchRunner(
    private val documents: DocumentRepository,
    private val bundles: BundleRepository,
    private val now: () -> Long,
) {
    @Inject
    constructor(documents: DocumentRepository, bundles: BundleRepository) : this(documents, bundles, System::currentTimeMillis)

    /**
     * @param currentIteration what the caller knew of the bundle's iteration; used only when the bundle cannot be read again after the upload
     * @param onFile called before each file goes up, with its number (from 1), the count and its name
     */
    suspend fun run(
        bundleId: String,
        files: List<UploadFile>,
        currentIteration: Int,
        onFile: suspend (number: Int, total: Int, name: String) -> Unit = { _, _, _ -> },
    ): BatchResult {
        var uploaded = 0
        for ((index, file) in files.withIndex()) {
            onFile(index + 1, files.size, file.name)
            try {
                documents.upload(bundleId, file)
                uploaded += 1
            } catch (e: ApiException) {
                val error = ActionError(uploadErrorMessage(e.envelope, e.httpStatus), e.requestId)
                return BatchResult(BatchOutcome(uploaded, files.size, error = error, finishedAt = now()), retryable = e.isRetryable || e.httpStatus == TOO_MANY_REQUESTS)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // nothing the repository is meant to raise: the batch ends here, saying how far it got, rather than failing without a word
                return BatchResult(BatchOutcome(uploaded, files.size, error = ActionError(UPLOAD_STOPPED_MESSAGE), finishedAt = now()), retryable = false)
            }
        }

        if (files.isEmpty()) return BatchResult(BatchOutcome(0, 0, finishedAt = now()), retryable = false)

        // the bundle as it is now decides whether an assessment exists (what the caller knew may be stale, or be all there is if the read fails)
        val iteration = runCatchingCancellable { bundles.bundle(bundleId).currentIteration }.getOrDefault(currentIteration)
        if (!shouldAutoReassess(allUploaded = true, currentIteration = iteration)) {
            return BatchResult(BatchOutcome(uploaded, files.size, finishedAt = now()), retryable = false)
        }
        val outcome = try {
            BatchOutcome(uploaded, files.size, runId = bundles.reassess(bundleId).runId, finishedAt = now())
        } catch (e: ApiException) {
            BatchOutcome(uploaded, files.size, runError = ActionError(runErrorMessage(e.envelope), e.requestId), finishedAt = now())
        }
        return BatchResult(outcome, retryable = false)
    }

    private companion object {
        const val TOO_MANY_REQUESTS = 429
    }
}
