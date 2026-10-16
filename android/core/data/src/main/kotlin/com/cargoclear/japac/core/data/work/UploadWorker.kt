package com.cargoclear.japac.core.data.work

import android.content.Context
import android.net.Uri
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.cargoclear.japac.core.data.InboxFiles
import com.cargoclear.japac.core.data.UploadBatchRunner
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlin.coroutines.cancellation.CancellationException

/**
 * Sends one batch of picked files to a bundle (see [UploadBatchRunner] for the rules) in the background, so a large upload survives the
 * app being backgrounded or killed. A connection that fails is tried again a few times with WorkManager's backoff; anything the server
 * refuses ends the batch for good, and the outcome is written to the work's output for the screen to read.
 *
 * The files the batch holds (the read grants the picker gave, made persistable when the batch was queued; the copies of files that came in
 * from outside, see [InboxFiles]) are given back when the batch ENDS, not between attempts and not when it is merely stopped: the system
 * stops work when the connection goes or its time is up and runs it again with the same input, which still needs them. When the person
 * cancels, [UploadScheduler.cancel] gives back what every unfinished batch of the bundle holds (see [BatchFiles]).
 */
@HiltWorker
class UploadWorker @AssistedInject constructor(
    @Assisted private val context: Context,
    @Assisted params: WorkerParameters,
    private val runner: UploadBatchRunner,
    private val batchFiles: BatchFiles,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val bundleId = inputData.getString(UploadWork.KEY_BUNDLE) ?: return Result.failure()
        val uris = inputData.getNullableStringArray(UploadWork.KEY_URIS).orEmpty().filterNotNull()
        val iteration = inputData.getInt(UploadWork.KEY_ITERATION, 0)
        val batchId = id.toString()

        val result = try {
            val resolver = context.contentResolver
            runner.run(bundleId, uris.map { resolver.uploadFile(Uri.parse(it)) }, iteration) { number, total, name ->
                setProgress(UploadWork.progress(number, total, name))
            }
        } catch (e: CancellationException) {
            throw e // stopped, not ended: the files stay (see above)
        } catch (e: Exception) {
            // The runner turns everything it expects into an outcome, so this is something it did not: the batch is over, and WorkManager fails it.
            batchFiles.finished(bundleId, batchId, uris)
            throw e
        }
        if (result.retryable && runAttemptCount < MAX_ATTEMPTS - 1) return Result.retry()

        batchFiles.finished(bundleId, batchId, uris)
        val output = UploadWork.output(result.outcome)
        return if (result.outcome.error != null) Result.failure(output) else Result.success(output)
    }

    companion object {
        /** The first try and two more: enough for a train tunnel, not enough to keep a dead connection busy for an hour. */
        const val MAX_ATTEMPTS = 3
    }
}
