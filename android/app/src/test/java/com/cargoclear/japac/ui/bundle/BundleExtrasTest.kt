package com.cargoclear.japac.ui.bundle

import androidx.lifecycle.SavedStateHandle
import com.cargoclear.japac.core.data.StreamEvent
import com.cargoclear.japac.core.data.UploadBatchRunner
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.RunState
import com.cargoclear.japac.core.model.SCAN_UNAVAILABLE_MESSAGE
import com.cargoclear.japac.core.model.SCAN_UNREADABLE_MESSAGE
import com.cargoclear.japac.core.model.StatusEvent
import com.cargoclear.japac.core.model.WatchedRun
import com.cargoclear.japac.notify.RunTracker
import com.cargoclear.japac.ui.FakeBundleRepository
import com.cargoclear.japac.ui.FakeCorrections
import com.cargoclear.japac.ui.FakeDocuments
import com.cargoclear.japac.ui.FakeFileImporter
import com.cargoclear.japac.ui.FakeMeta
import com.cargoclear.japac.ui.FakeRecents
import com.cargoclear.japac.ui.FakeUploadScheduler
import com.cargoclear.japac.ui.assessment
import com.cargoclear.japac.ui.bundle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Scanned documents, and telling the run watcher what is running when the person might leave the app. */
@OptIn(ExperimentalCoroutinesApi::class)
class BundleExtrasTest {
    private val dispatcher = StandardTestDispatcher()
    private val repo = FakeBundleRepository()
    private val documents = FakeDocuments()
    private val scheduler = FakeUploadScheduler()
    private val importer = FakeFileImporter()
    private var clock = 1_000L
    private val tracker = RunTracker({ clock }, RunTracker.DEFAULT_MAX_AGE_MILLIS)

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
        repo.bundle = bundle(1, "MISSING_EVIDENCE", "d1")
        repo.latest = assessment(1)
        repo.iterations = listOf(assessment(1))
    }

    @After
    fun tearDown() = Dispatchers.resetMain()

    private fun viewModel() = BundleViewModel(
        SavedStateHandle(mapOf("bundleId" to "bnd-1")), repo, FakeRecents(), FakeMeta(AppMode.DEMO), documents, scheduler,
        UploadBatchRunner(documents, repo), FakeCorrections(), importer, tracker,
    )

    private fun status(state: RunState, runId: String = "run-1") = StreamEvent.Status(StatusEvent("status", "bnd-1", runId, state, "extract", 0.5, null))

    // ---- scanning

    @Test
    fun `a scan is copied into the app's cache and queued like any picked file`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()

        vm.onFilesScanned(listOf("file:///data/scanner/SCAN_1.pdf"))
        runCurrent()

        assertEquals(listOf(listOf("file:///data/scanner/SCAN_1.pdf")), importer.imports)
        val (bundleId, uris, iteration) = scheduler.enqueued.single()
        assertEquals("bnd-1", bundleId)
        assertEquals(1, uris.size)
        assertTrue("what is queued is the copy, not the scanner's file", uris.single().startsWith("file:/inbox/"))
        assertEquals(1, iteration)
    }

    @Test
    fun `a scan that cannot be read says so and queues nothing`() = runTest(dispatcher) {
        importer.unreadable += "file:///data/scanner/SCAN_1.pdf"
        val vm = viewModel()
        runCurrent()

        vm.onFilesScanned(listOf("file:///data/scanner/SCAN_1.pdf"))
        runCurrent()

        assertEquals(SCAN_UNREADABLE_MESSAGE, vm.state.value.visibleError?.message)
        assertTrue(scheduler.enqueued.isEmpty())
    }

    @Test
    fun `a scanner that cannot start says so`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()
        vm.scanFailed()
        assertEquals(SCAN_UNAVAILABLE_MESSAGE, vm.state.value.visibleError?.message)
    }

    @Test
    fun `nothing is scanned into a saved copy, which cannot send`() = runTest(dispatcher) {
        repo.bundleError = com.cargoclear.japac.ui.apiFailure(com.cargoclear.japac.core.data.ApiException.Kind.NETWORK)
        val recents = FakeRecents().apply { remember(bundle(1, "MISSING_EVIDENCE", "d1"), assessment(1)) }
        val vm = BundleViewModel(
            SavedStateHandle(mapOf("bundleId" to "bnd-1")), repo, recents, FakeMeta(AppMode.DEMO), documents, scheduler,
            UploadBatchRunner(documents, repo), FakeCorrections(), importer, tracker,
        )
        runCurrent()
        vm.onFilesScanned(listOf("file:///data/scanner/SCAN_1.pdf"))
        runCurrent()
        assertTrue(importer.imports.isEmpty())
    }

    // ---- the run to watch

    @Test
    fun `a run that was asked for is handed to the tracker, and cleared when it ends`() = runTest(dispatcher) {
        repo.nextRunId = "run-7"
        val vm = viewModel()
        runCurrent()
        assertTrue(tracker.active().isEmpty())

        vm.runAnalysis()
        runCurrent()
        assertEquals(listOf(WatchedRun("bnd-1", "run-7")), tracker.active())

        vm.onScreenStarted()
        runCurrent()
        repo.events.tryEmit(status(RunState.COMPLETE, "run-7"))
        runCurrent()
        assertTrue("the run is over", tracker.active().isEmpty())
        vm.onScreenStopped()
    }

    @Test
    fun `a run another device started is watched too`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()
        vm.onScreenStarted()
        runCurrent()

        repo.events.tryEmit(status(RunState.RUNNING, "run-3"))
        runCurrent()

        assertEquals(listOf(WatchedRun("bnd-1", "run-3")), tracker.active())
        vm.onScreenStopped()
    }

    @Test
    fun `leaving the screen mid-run keeps the run tracked`() = runTest(dispatcher) {
        repo.nextRunId = "run-7"
        val vm = viewModel()
        runCurrent()
        vm.runAnalysis()
        runCurrent()
        vm.onScreenStopped()
        runCurrent()
        assertEquals(listOf(WatchedRun("bnd-1", "run-7")), tracker.active())
    }

    @Test
    fun `nothing is tracked while nothing runs`() = runTest(dispatcher) {
        viewModel()
        runCurrent()
        assertNull(tracker.active().firstOrNull())
    }
}
