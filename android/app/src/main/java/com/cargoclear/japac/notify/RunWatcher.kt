package com.cargoclear.japac.notify

import com.cargoclear.japac.core.data.SettingsRepository
import com.cargoclear.japac.core.model.WatchedRun
import java.util.concurrent.ConcurrentHashMap
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** Starts and stops the background watch of one run. The screens never touch WorkManager. */
interface RunWatchScheduler {
    fun watch(run: WatchedRun)

    fun cancelAll()
}

/** Whether the system lets this app notify (the permission, and the person not having switched its notifications off). */
fun interface NotificationsEnabled {
    fun check(): Boolean
}

/**
 * The runs somebody is waiting for, as the bundle screens report them. An entry that was not updated for [maxAgeMillis] is forgotten: a
 * screen that went away mid-run cannot say when the run ended, and the watch should not act on a run from long ago.
 */
@Singleton
class RunTracker(private val now: () -> Long, private val maxAgeMillis: Long) {
    @Inject constructor() : this(System::currentTimeMillis, DEFAULT_MAX_AGE_MILLIS)

    private data class Entry(val runId: String, val at: Long)

    private val runs = ConcurrentHashMap<String, Entry>()

    private val mutableStarted = MutableSharedFlow<WatchedRun>(extraBufferCapacity = 16)

    /** Each run the first time it is tracked: a run the server accepts just as the person leaves the app is reported here, not found in [active]. */
    val started: SharedFlow<WatchedRun> = mutableStarted.asSharedFlow()

    fun track(run: WatchedRun) {
        val previous = runs.put(run.bundleId, Entry(run.runId, now()))
        if (previous?.runId != run.runId) mutableStarted.tryEmit(run)
    }

    fun clear(bundleId: String) {
        runs.remove(bundleId)
    }

    /** Forgets [runId] of the bundle, unless a newer run has been tracked for it since (that one is still going). */
    fun clear(bundleId: String, runId: String) {
        runs.computeIfPresent(bundleId) { _, entry -> if (entry.runId == runId) null else entry }
    }

    fun active(): List<WatchedRun> {
        val cutoff = now() - maxAgeMillis
        runs.entries.removeAll { it.value.at < cutoff }
        return runs.map { WatchedRun(it.key, it.value.runId) }
    }

    companion object {
        /** Longer than the watcher ever waits for a run (see RunWatchWorker.MAX_WATCH_MILLIS), so an entry older than this is certainly stale. */
        const val DEFAULT_MAX_AGE_MILLIS: Long = 15L * 60 * 1000
    }
}

/**
 * Keeps an eye on the runs a person started when they leave the app, so a notification can tell them it is done. The app calls
 * [appBackgrounded] when its last screen goes out of sight and [appForegrounded] when one comes back: the watch exists only in between,
 * because with the app in front the screen itself shows the end of the run.
 *
 * Reading the setting takes a moment, and the person may be back by then, or the activity that reported them gone may be gone itself: so
 * the work is done on this class's own scope, and what it decides is checked again, under a lock, against where the person is now.
 */
@Singleton
class RunWatcher(
    private val tracker: RunTracker,
    private val scheduler: RunWatchScheduler,
    private val settings: SettingsRepository,
    private val notifications: NotificationsEnabled,
    private val scope: CoroutineScope,
) {
    @Inject constructor(
        tracker: RunTracker,
        scheduler: RunWatchScheduler,
        settings: SettingsRepository,
        notifications: NotificationsEnabled,
    ) : this(tracker, scheduler, settings, notifications, CoroutineScope(SupervisorJob() + Dispatchers.Default))

    @Volatile
    var appVisible: Boolean = false
        private set

    private val lock = Any()
    private var deciding: Job? = null
    private var late: Job? = null

    fun appBackgrounded() {
        synchronized(lock) {
            appVisible = false
            deciding?.cancel()
            deciding = scope.launch { watchIfWanted() }
        }
    }

    private suspend fun watchIfWanted() {
        if (!settings.notifyRunFinished.first() || !notifications.check()) return
        synchronized(lock) {
            tracker.active().forEach(scheduler::watch)
            // a run the server accepts after the person has gone (they tapped Run and left at once) is watched from the moment it is known
            late?.cancel()
            late = scope.launch { tracker.started.collect { if (!appVisible) scheduler.watch(it) } }
        }
    }

    fun appForegrounded() {
        synchronized(lock) {
            appVisible = true
            deciding?.cancel()
            deciding = null
            late?.cancel()
            late = null
            scheduler.cancelAll()
        }
    }
}
