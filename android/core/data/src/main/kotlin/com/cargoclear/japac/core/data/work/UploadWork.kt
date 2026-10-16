package com.cargoclear.japac.core.data.work

import androidx.work.Data
import androidx.work.WorkInfo
import androidx.work.workDataOf
import com.cargoclear.japac.core.model.ActionError
import com.cargoclear.japac.core.model.BatchOutcome
import com.cargoclear.japac.core.model.BatchPhase
import com.cargoclear.japac.core.model.UploadBatch

/**
 * What goes into and comes out of the upload work, and how WorkManager's states read as [UploadBatch]es. Plain functions of plain
 * values, so they are tested on the JVM; [UploadScheduler] and [UploadWorker] only call them.
 */
internal object UploadWork {
    const val KEY_BUNDLE = "bundle"
    const val KEY_URIS = "uris"
    const val KEY_ITERATION = "iteration"

    // progress, reported while the worker runs
    const val KEY_CURRENT = "current"
    const val KEY_TOTAL = "total"
    const val KEY_NAME = "name"

    // output, set when the worker ends
    const val KEY_UPLOADED = "uploaded"
    const val KEY_ERROR = "error"
    const val KEY_ERROR_ID = "error_id"
    const val KEY_RUN_ID = "run_id"
    const val KEY_RUN_ERROR = "run_error"
    const val KEY_RUN_ERROR_ID = "run_error_id"
    const val KEY_FINISHED_AT = "finished_at"

    const val TAG = "upload"
    private const val TOTAL_TAG_PREFIX = "upload-total:"

    /** One unique chain of work per bundle: batches for the same bundle run one after another, different bundles do not wait for each other. */
    fun uniqueName(bundleId: String) = "upload-$bundleId"

    /** WorkInfo does not expose a request's input, so the number of files rides along as a tag. */
    fun totalTag(total: Int) = "$TOTAL_TAG_PREFIX$total"

    fun input(bundleId: String, uris: List<String>, currentIteration: Int): Data =
        workDataOf(KEY_BUNDLE to bundleId, KEY_URIS to uris.toTypedArray(), KEY_ITERATION to currentIteration)

    fun progress(number: Int, total: Int, name: String): Data = workDataOf(KEY_CURRENT to number, KEY_TOTAL to total, KEY_NAME to name)

    fun output(outcome: BatchOutcome): Data = Data.Builder()
        .putInt(KEY_UPLOADED, outcome.uploaded)
        .putInt(KEY_TOTAL, outcome.total)
        .apply {
            outcome.error?.let { putString(KEY_ERROR, it.message); it.requestId?.let { id -> putString(KEY_ERROR_ID, id) } }
            outcome.runId?.let { putString(KEY_RUN_ID, it) }
            outcome.runError?.let { putString(KEY_RUN_ERROR, it.message); it.requestId?.let { id -> putString(KEY_RUN_ERROR_ID, id) } }
            outcome.finishedAt?.let { putLong(KEY_FINISHED_AT, it) }
        }
        .build()

    /** Null when the work ended without saying how (it was cancelled). */
    fun outcome(output: Data): BatchOutcome? {
        if (!output.keyValueMap.containsKey(KEY_UPLOADED)) return null
        return BatchOutcome(
            uploaded = output.getInt(KEY_UPLOADED, 0),
            total = output.getInt(KEY_TOTAL, 0),
            error = output.getString(KEY_ERROR)?.let { ActionError(it, output.getString(KEY_ERROR_ID)) },
            runId = output.getString(KEY_RUN_ID),
            runError = output.getString(KEY_RUN_ERROR)?.let { ActionError(it, output.getString(KEY_RUN_ERROR_ID)) },
            finishedAt = output.getLong(KEY_FINISHED_AT, -1L).takeIf { it >= 0 },
        )
    }

    fun batch(id: String, state: WorkInfo.State, tags: Set<String>, progress: Data, output: Data): UploadBatch {
        val outcome = outcome(output)
        val total = tags.firstNotNullOfOrNull { it.removePrefix(TOTAL_TAG_PREFIX).takeIf { rest -> rest != it }?.toIntOrNull() }
            ?: outcome?.total
            ?: progress.getInt(KEY_TOTAL, 0)
        val phase = when (state) {
            WorkInfo.State.ENQUEUED, WorkInfo.State.BLOCKED -> BatchPhase.WAITING
            WorkInfo.State.RUNNING -> BatchPhase.RUNNING
            WorkInfo.State.SUCCEEDED -> BatchPhase.SUCCEEDED
            WorkInfo.State.FAILED -> BatchPhase.FAILED
            WorkInfo.State.CANCELLED -> BatchPhase.CANCELLED
        }
        return UploadBatch(
            id = id,
            phase = phase,
            total = total,
            current = progress.getInt(KEY_CURRENT, 0).takeIf { it > 0 },
            filename = progress.getString(KEY_NAME),
            outcome = outcome,
        )
    }
}
