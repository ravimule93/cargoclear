package com.cargoclear.japac.core.data.work

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.cargoclear.japac.core.model.UploadBatch
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Queues the files a person picked for a bundle and reports how the batches are doing. The screen never touches WorkManager. */
interface UploadScheduler {
    /**
     * Queues one batch. [uris] are content Uris from the system file picker; [currentIteration] is what the screen knows of the bundle's
     * assessment count, used only if the bundle cannot be read after the upload.
     */
    fun enqueue(bundleId: String, uris: List<String>, currentIteration: Int)

    /** The batches of a bundle, newest information first as WorkManager keeps them (finished ones stay for about a day). */
    fun batches(bundleId: String): Flow<List<UploadBatch>>

    /** Stops the batch in progress and the ones queued behind it, and gives back the files they hold. Files already uploaded stay in the bundle. */
    fun cancel(bundleId: String)
}

@Singleton
class WorkManagerUploadScheduler @Inject constructor(
    @ApplicationContext private val context: Context,
    private val batchFiles: BatchFiles,
) : UploadScheduler {
    private val workManager: WorkManager get() = WorkManager.getInstance(context)

    override fun enqueue(bundleId: String, uris: List<String>, currentIteration: Int) {
        if (uris.isEmpty()) return
        // The picker's grant lasts only while the app's task does; the worker may run later (no connection now, or the process was killed).
        for (uri in uris) {
            runCatching { context.contentResolver.takePersistableUriPermission(Uri.parse(uri), Intent.FLAG_GRANT_READ_URI_PERMISSION) }
        }
        val request = OneTimeWorkRequestBuilder<UploadWorker>()
            .setInputData(UploadWork.input(bundleId, uris, currentIteration))
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, BACKOFF_SECONDS, TimeUnit.SECONDS)
            .addTag(UploadWork.TAG)
            .addTag(UploadWork.totalTag(uris.size))
            .build()
        batchFiles.record(bundleId, request.id.toString(), uris)
        // A batch for a bundle waits for the one before it; a failed one does not stop the next from running.
        workManager.enqueueUniqueWork(UploadWork.uniqueName(bundleId), ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }

    override fun batches(bundleId: String): Flow<List<UploadBatch>> =
        workManager.getWorkInfosForUniqueWorkFlow(UploadWork.uniqueName(bundleId)).map { infos ->
            infos.map { UploadWork.batch(it.id.toString(), it.state, it.tags, it.progress, it.outputData) }
        }

    override fun cancel(bundleId: String) {
        workManager.cancelUniqueWork(UploadWork.uniqueName(bundleId))
        // a batch that was queued behind the running one never starts, so it cannot tidy up after itself
        batchFiles.cancelled(bundleId)
    }

    private companion object {
        const val BACKOFF_SECONDS = 10L
    }
}
