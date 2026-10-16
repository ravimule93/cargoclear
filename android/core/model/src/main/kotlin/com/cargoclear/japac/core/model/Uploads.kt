package com.cargoclear.japac.core.model

/** What the bundle screen shows about uploading documents. */
sealed interface UploadStatus {
    data object Idle : UploadStatus

    /**
     * File [current] of [total] is going up ([current] counts from 1, as the web's "Uploading 1/3"). [waiting]: the batch is queued or is
     * waiting for a connection, nothing is being sent right now.
     */
    data class Active(val current: Int, val total: Int, val filename: String?, val waiting: Boolean = false) : UploadStatus

    /**
     * The batch stopped at a file the server (or the network) refused; [uploaded] of [total] files landed before that. [uploaded] is null when
     * the batch ended without saying (the background job died on something unexpected): then nobody knows, and the screen says nothing about it.
     */
    data class Failed(val error: ActionError, val uploaded: Int?, val total: Int) : UploadStatus
}

/**
 * How a batch of files ended. Uploading is sequential and stops at the first failure, as in the web client. When every file landed and an
 * assessment already existed, the batch ends by asking for a reassessment ([runId] is that run, [runError] why it could not start).
 */
data class BatchOutcome(
    val uploaded: Int,
    val total: Int,
    val error: ActionError? = null,
    val runId: String? = null,
    val runError: ActionError? = null,
    /** Epoch millis; lets a screen opened later ignore an outcome that is long stale. */
    val finishedAt: Long? = null,
)

enum class BatchPhase {
    /** Queued behind another batch, or waiting for a connection (also between two attempts). */
    WAITING,
    RUNNING,
    SUCCEEDED,
    FAILED,
    CANCELLED;

    val isActive: Boolean get() = this == WAITING || this == RUNNING
}

/** One upload batch as the background scheduler reports it. */
data class UploadBatch(
    val id: String,
    val phase: BatchPhase,
    val total: Int,
    /** File number (from 1) going up right now, once the worker said so. */
    val current: Int? = null,
    val filename: String? = null,
    val outcome: BatchOutcome? = null,
)

/**
 * What a screen should do after hearing about batches (or about one inline upload): [active] is the progress to show, [failure] an upload
 * that went wrong, [bundleChanged] that documents landed (refetch the bundle: one refresh per batch, as the web does), [runStarted] the
 * reassessment the batch ended with, [runError] why that could not start.
 */
data class UploadUpdate(
    val active: UploadStatus.Active? = null,
    val failure: UploadStatus.Failed? = null,
    val bundleChanged: Boolean = false,
    val runStarted: String? = null,
    val runError: ActionError? = null,
)

/** The update for one finished batch (also used for an upload done inline, e.g. the demo's sample certificate). */
fun BatchOutcome.toUpdate(): UploadUpdate = UploadUpdate(
    failure = error?.let { UploadStatus.Failed(it, uploaded, total) },
    bundleChanged = uploaded > 0,
    runStarted = runId,
    runError = runError,
)

/**
 * Turns the scheduler's list of batches into [UploadUpdate]s, one screen at a time. A batch that finished while the screen was watching
 * is acted on in full; one that finished while the screen was away only matters when it went wrong and not long ago (the screen has just
 * loaded the bundle, so the documents are current, and it must not announce an old success or a stale "already running" again). Each
 * finished batch is handled once.
 */
class UploadWatcher(
    private val now: () -> Long = System::currentTimeMillis,
    private val staleAfterMillis: Long = 30 * 60_000L,
) {
    private val seenActive = HashSet<String>()
    private val handled = HashSet<String>()

    fun update(batches: List<UploadBatch>): UploadUpdate {
        batches.filter { it.phase.isActive }.forEach { seenActive += it.id }

        var bundleChanged = false
        var runStarted: String? = null
        var runError: ActionError? = null
        var failure: UploadStatus.Failed? = null
        for (batch in batches) {
            if (batch.phase.isActive || !handled.add(batch.id)) continue
            val outcome = batch.outcome
            val watched = batch.id in seenActive
            if (!watched) {
                val finishedAt = outcome?.finishedAt
                val recent = finishedAt != null && now() - finishedAt <= staleAfterMillis
                val wentWrong = outcome != null && (outcome.error != null || outcome.runError != null)
                if (!recent || !wentWrong) continue
            }
            if (outcome == null) {
                // a batch that ended without saying how may have landed some files: cancelled by the person, or failed on something unexpected
                bundleChanged = bundleChanged || (watched && (batch.phase == BatchPhase.CANCELLED || batch.phase == BatchPhase.FAILED))
                if (watched && batch.phase == BatchPhase.FAILED) failure = UploadStatus.Failed(ActionError(UPLOAD_STOPPED_MESSAGE), uploaded = null, total = batch.total)
                continue
            }
            val update = outcome.toUpdate()
            bundleChanged = bundleChanged || (watched && update.bundleChanged)
            if (watched) runStarted = update.runStarted ?: runStarted
            runError = update.runError ?: runError
            failure = update.failure ?: failure
        }

        val shown = batches.firstOrNull { it.phase == BatchPhase.RUNNING } ?: batches.firstOrNull { it.phase == BatchPhase.WAITING }
        val active = shown?.let {
            UploadStatus.Active(
                current = it.current ?: 1,
                total = it.total,
                filename = it.filename,
                waiting = it.phase == BatchPhase.WAITING,
            )
        }
        return UploadUpdate(active = active, failure = failure, bundleChanged = bundleChanged, runStarted = runStarted, runError = runError)
    }
}
