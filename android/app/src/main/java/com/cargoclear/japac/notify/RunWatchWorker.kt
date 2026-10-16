package com.cargoclear.japac.notify

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.BundleRepository
import com.cargoclear.japac.core.data.RecentBundlesRepository
import com.cargoclear.japac.core.data.StreamEvent
import com.cargoclear.japac.core.model.RunEnd
import com.cargoclear.japac.core.model.RunWatch
import com.cargoclear.japac.core.model.runCatchingCancellable
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.flow.firstOrNull
import kotlinx.coroutines.flow.mapNotNull
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Holds a bundle's live stream while the app is in the background and posts one notification when the run the person started is over.
 * It runs as an expedited job with a foreground notification, so the system lets it keep the connection while the app is away; it stops
 * as soon as the run ends, after [MAX_WATCH_MILLIS], or when the app comes back to the front (the watcher cancels it then).
 *
 * The end of the run is whatever the stream says about that run id (see [RunWatch]); the verdict for the notification is read from the
 * server afterwards, so the text never rests on a stale copy.
 */
@HiltWorker
class RunWatchWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val bundles: BundleRepository,
    private val recents: RecentBundlesRepository,
    private val notifier: RunNotifier,
    private val watcher: RunWatcher,
    private val tracker: RunTracker,
) : CoroutineWorker(context, params) {

    override suspend fun getForegroundInfo(): ForegroundInfo = notifier.foregroundInfo(inputData.getString(KEY_BUNDLE).orEmpty())

    override suspend fun doWork(): Result {
        val bundleId = inputData.getString(KEY_BUNDLE) ?: return Result.failure()
        val runId = inputData.getString(KEY_RUN) ?: return Result.failure()
        // best effort: where the system refuses a foreground service the watch still runs, for as long as it is allowed to
        runCatchingCancellable { setForeground(getForegroundInfo()) }

        val watch = RunWatch(runId)
        val end = withTimeoutOrNull(MAX_WATCH_MILLIS) {
            bundles.events(bundleId).mapNotNull { (it as? StreamEvent.Status)?.let { status -> watch.onStatus(status.event) } }.firstOrNull()
        } ?: return Result.success()
        // over: if the run stayed tracked, every later trip out of the app would watch it again and post the same notification again
        tracker.clear(bundleId, runId)
        if (watcher.appVisible) return Result.success() // the person is looking at the app: the screen says it

        val title = recents.savedCopy(bundleId)?.bundle?.reference?.takeIf { it.isNotBlank() } ?: bundleId
        when (end) {
            RunEnd.Finished -> {
                val status = try {
                    bundles.latestAssessment(bundleId)?.statusKind
                } catch (_: ApiException) {
                    null
                }
                notifier.finished(bundleId, title, status)
            }
            is RunEnd.Failed -> notifier.failed(bundleId, title, end.message)
        }
        return Result.success()
    }

    companion object {
        const val KEY_BUNDLE = "bundle_id"
        const val KEY_RUN = "run_id"

        /** How long the watcher waits at most (a number chosen here, not a measurement of runs): short enough that a run that never reports does not keep a connection open for hours. */
        const val MAX_WATCH_MILLIS: Long = 8L * 60 * 1000
    }
}
