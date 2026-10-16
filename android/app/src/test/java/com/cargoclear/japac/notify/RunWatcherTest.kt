package com.cargoclear.japac.notify

import com.cargoclear.japac.core.data.SettingsRepository
import com.cargoclear.japac.core.model.WatchedRun
import com.cargoclear.japac.ui.FakeSettings
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RunWatcherTest {
    private class RecordingScheduler : RunWatchScheduler {
        val watched = mutableListOf<WatchedRun>()
        var cancels = 0

        override fun watch(run: WatchedRun) {
            watched += run
        }

        override fun cancelAll() {
            cancels++
        }
    }

    private var clock = 10_000L
    private val tracker = RunTracker({ clock }, maxAgeMillis = 60_000)
    private val scheduler = RecordingScheduler()
    private var allowed = true

    private val scope = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.Unconfined)

    private fun watcher(notify: Boolean = true) = RunWatcher(tracker, scheduler, FakeSettings(notify = notify), { allowed }, scope)

    @Test
    fun `leaving the app watches every run that is going`() = runTest {
        tracker.track(WatchedRun("bnd-1", "run-1"))
        tracker.track(WatchedRun("bnd-2", "run-5"))

        watcher().appBackgrounded()

        assertEquals(setOf(WatchedRun("bnd-1", "run-1"), WatchedRun("bnd-2", "run-5")), scheduler.watched.toSet())
    }

    @Test
    fun `without the person's say-so nothing is watched`() = runTest {
        tracker.track(WatchedRun("bnd-1", "run-1"))
        watcher(notify = false).appBackgrounded()
        assertTrue(scheduler.watched.isEmpty())
    }

    @Test
    fun `without the system's permission to notify nothing is watched`() = runTest {
        tracker.track(WatchedRun("bnd-1", "run-1"))
        allowed = false
        watcher().appBackgrounded()
        assertTrue("a connection would be held for a notification that cannot be shown", scheduler.watched.isEmpty())
    }

    @Test
    fun `with no run going there is nothing to watch`() = runTest {
        watcher().appBackgrounded()
        assertTrue(scheduler.watched.isEmpty())
    }

    @Test
    fun `coming back stops the watch and says the app is in front`() = runTest {
        val watcher = watcher()
        watcher.appBackgrounded()
        assertFalse(watcher.appVisible)
        watcher.appForegrounded()
        assertTrue(watcher.appVisible)
        assertEquals(1, scheduler.cancels)
    }

    @Test
    fun `a run nobody has reported on for a while is forgotten`() = runTest {
        tracker.track(WatchedRun("bnd-1", "run-1"))
        clock += 60_001
        watcher().appBackgrounded()
        assertTrue(scheduler.watched.isEmpty())
    }

    @Test
    fun `a newer run of the same bundle replaces the older one, and a finished one is cleared`() {
        tracker.track(WatchedRun("bnd-1", "run-1"))
        tracker.track(WatchedRun("bnd-1", "run-2"))
        assertEquals(listOf(WatchedRun("bnd-1", "run-2")), tracker.active())
        tracker.clear("bnd-1")
        assertTrue(tracker.active().isEmpty())
    }

    @Test
    fun `reporting again keeps a long run alive`() {
        tracker.track(WatchedRun("bnd-1", "run-1"))
        clock += 50_000
        tracker.track(WatchedRun("bnd-1", "run-1"))
        clock += 50_000
        assertEquals(1, tracker.active().size)
    }

    @Test
    fun `a run the server accepts after the person left is watched from the moment it is known`() = runTest {
        val watcher = watcher()
        watcher.appBackgrounded()
        assertTrue(scheduler.watched.isEmpty())

        tracker.track(WatchedRun("bnd-1", "run-1"))

        assertEquals(listOf(WatchedRun("bnd-1", "run-1")), scheduler.watched)
        watcher.appForegrounded()
    }

    @Test
    fun `the same run reported again is not watched twice`() = runTest {
        val watcher = watcher()
        watcher.appBackgrounded()
        tracker.track(WatchedRun("bnd-1", "run-1"))
        tracker.track(WatchedRun("bnd-1", "run-1"))
        assertEquals(1, scheduler.watched.size)
        watcher.appForegrounded()
    }

    @Test
    fun `back in front a run that becomes known is not watched`() = runTest {
        val watcher = watcher()
        watcher.appBackgrounded()
        watcher.appForegrounded()
        tracker.track(WatchedRun("bnd-1", "run-1"))
        assertTrue(scheduler.watched.isEmpty())
    }

    @Test
    fun `no late watch when the person does not want notifications`() = runTest {
        val watcher = watcher(notify = false)
        watcher.appBackgrounded()
        tracker.track(WatchedRun("bnd-1", "run-1"))
        assertTrue(scheduler.watched.isEmpty())
    }

    /** The setting arrives only when the test lets it: the moment between "the person left" and "the app knows they want to be told". */
    private class SlowSettings : SettingsRepository {
        val arrives = CompletableDeferred<Unit>()
        override val viewerSecure: Flow<Boolean> = flow { emit(true) }
        override val notifyRunFinished: Flow<Boolean> = flow {
            arrives.await()
            emit(true)
        }

        override suspend fun setViewerSecure(secure: Boolean) = Unit
        override suspend fun setNotifyRunFinished(notify: Boolean) = Unit
    }

    @Test
    fun `coming back while the setting is still being read leaves nothing watched, then or later`() = runTest {
        tracker.track(WatchedRun("bnd-1", "run-1"))
        val settings = SlowSettings()
        val watcher = RunWatcher(tracker, scheduler, settings, { allowed }, scope)

        watcher.appBackgrounded()
        watcher.appForegrounded()
        settings.arrives.complete(Unit)
        tracker.track(WatchedRun("bnd-1", "run-2"))

        assertTrue(watcher.appVisible)
        assertTrue("the app is in front: nothing to hold a connection for", scheduler.watched.isEmpty())
    }

    @Test
    fun `leaving is acted on once the setting is read, however long that takes`() = runTest {
        tracker.track(WatchedRun("bnd-1", "run-1"))
        val settings = SlowSettings()
        val watcher = RunWatcher(tracker, scheduler, settings, { allowed }, scope)

        watcher.appBackgrounded()
        assertTrue(scheduler.watched.isEmpty())
        settings.arrives.complete(Unit)

        assertEquals(listOf(WatchedRun("bnd-1", "run-1")), scheduler.watched)
    }

    @Test
    fun `a run that ended is forgotten, but only that run`() {
        tracker.track(WatchedRun("bnd-1", "run-1"))
        tracker.clear("bnd-1", "run-1")
        assertTrue(tracker.active().isEmpty())

        tracker.track(WatchedRun("bnd-1", "run-2"))
        tracker.clear("bnd-1", "run-1") // the watch of the first run ended after the second had been asked for
        assertEquals(listOf(WatchedRun("bnd-1", "run-2")), tracker.active())
    }
}
