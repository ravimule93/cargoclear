package com.cargoclear.japac.ui.bundle

import androidx.lifecycle.SavedStateHandle
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.StreamEvent
import com.cargoclear.japac.core.data.UploadBatchRunner
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.LoadState
import com.cargoclear.japac.core.model.RunState
import com.cargoclear.japac.core.model.StatusEvent
import com.cargoclear.japac.core.model.StreamConnection
import com.cargoclear.japac.ui.FakeBundleRepository
import com.cargoclear.japac.notify.RunTracker
import com.cargoclear.japac.ui.FakeCorrections
import com.cargoclear.japac.ui.FakeFileImporter
import com.cargoclear.japac.ui.FakeDocuments
import com.cargoclear.japac.ui.FakeUploadScheduler
import com.cargoclear.japac.ui.FakeMeta
import com.cargoclear.japac.ui.FakeRecents
import com.cargoclear.japac.ui.apiFailure
import com.cargoclear.japac.ui.assessment
import com.cargoclear.japac.ui.bundle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class BundleViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val repo = FakeBundleRepository()
    private val recents = FakeRecents()
    private val documents = FakeDocuments()
    private val scheduler = FakeUploadScheduler()
    private val corrections = FakeCorrections()

    @Before
    fun setUp() = Dispatchers.setMain(dispatcher)

    @After
    fun tearDown() = Dispatchers.resetMain()

    private fun viewModel() = BundleViewModel(
        SavedStateHandle(mapOf("bundleId" to "bnd-1")), repo, recents, FakeMeta(AppMode.DEMO), documents, scheduler, UploadBatchRunner(documents, repo), corrections, FakeFileImporter(), RunTracker(),
    )

    private fun status(state: RunState, progress: Double = 0.5, runId: String = "run-1", message: String? = null) =
        StreamEvent.Status(StatusEvent("status", "bnd-1", runId, state, "extract", progress, message))

    @Test
    fun `a bundle that was never analysed loads without an assessment and is remembered`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING", "d1", "d2")
        val vm = viewModel()
        runCurrent()

        assertEquals("bnd-1", vm.bundleId)
        val state = vm.state.value
        assertEquals(LoadState.Ready, state.load)
        assertNull(state.assessment)
        assertEquals(0, repo.latestCalls)
        assertEquals(0, repo.iterationCalls)
        assertEquals(1, recents.remembered.size)
        assertNull(recents.remembered.single().second)
        assertEquals(AppMode.DEMO, vm.appMode.value)
    }

    @Test
    fun `an analysed bundle loads its latest assessment and its iterations together`() = runTest(dispatcher) {
        repo.bundle = bundle(2, "MISSING_EVIDENCE", "d1")
        repo.latest = assessment(2)
        repo.iterations = listOf(assessment(1), assessment(2))
        val vm = viewModel()
        runCurrent()

        assertEquals(2, vm.state.value.assessment?.iteration)
        assertEquals(listOf(1, 2), vm.state.value.iterations.map { it.iteration })
        assertEquals(2, recents.remembered.single().second?.iteration)
    }

    @Test
    fun `an unknown bundle is not found and never falls back to a saved copy`() = runTest(dispatcher) {
        repo.bundleError = apiFailure(ApiException.Kind.HTTP, code = "NOT_FOUND", status = 404)
        recents.remember(bundle(1, "MISSING_EVIDENCE", "d1"), assessment(1)) // an old copy exists, but the server says the bundle is gone
        val vm = viewModel()
        runCurrent()

        assertEquals(LoadState.NotFound, vm.state.value.load)
    }

    @Test
    fun `when the server cannot be reached the saved copy is shown and marked, and without one the load fails`() = runTest(dispatcher) {
        repo.bundleError = apiFailure(ApiException.Kind.NETWORK, "Can't reach the server.")
        recents.remember(bundle(1, "MISSING_EVIDENCE", "d1"), assessment(1))
        val withCopy = viewModel()
        runCurrent()
        assertEquals(LoadState.Ready, withCopy.state.value.load)
        assertEquals(1_000L, withCopy.state.value.savedCopyAt)
        assertEquals(1, withCopy.state.value.assessment?.iteration)

        recents.forget("bnd-1")
        val without = viewModel()
        runCurrent()
        assertEquals(LoadState.Failed("Can't reach the server."), without.state.value.load)
    }

    @Test
    fun `retry after a failed load tries again`() = runTest(dispatcher) {
        repo.bundleError = apiFailure(ApiException.Kind.NETWORK, "down")
        val vm = viewModel()
        runCurrent()
        assertTrue(vm.state.value.load is LoadState.Failed)

        repo.bundleError = null
        repo.bundle = bundle(0, "PENDING", "d1")
        vm.retry()
        assertEquals(LoadState.Loading, vm.state.value.load)
        runCurrent()
        assertEquals(LoadState.Ready, vm.state.value.load)
    }

    @Test
    fun `the stream is only held while the screen is visible`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()
        assertEquals(0, repo.events.subscriptionCount.value)

        vm.onScreenStarted()
        runCurrent()
        assertEquals(1, repo.events.subscriptionCount.value)

        vm.onScreenStarted() // a second start must not open a second connection
        runCurrent()
        assertEquals(1, repo.events.subscriptionCount.value)

        vm.onScreenStopped()
        runCurrent()
        assertEquals(0, repo.events.subscriptionCount.value)
        assertEquals(StreamConnection.CONNECTING, vm.state.value.connection)
    }

    @Test
    fun `progress and a new iteration arrive over the stream, the bundle is refetched once for it`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING", "d1")
        val vm = viewModel()
        vm.onScreenStarted()
        runCurrent()
        val bundleCallsAfterLoad = repo.bundleCalls

        repo.events.emit(StreamEvent.Opened)
        repo.events.emit(status(RunState.RUNNING, 0.4))
        runCurrent()
        assertEquals(StreamConnection.OPEN, vm.state.value.connection)
        assertTrue(vm.state.value.isRunning)
        assertEquals(0.4, vm.state.value.run?.progress ?: 0.0, 1e-9)

        repo.bundle = bundle(1, "MISSING_EVIDENCE", "d1")
        repo.iterations = listOf(assessment(1))
        repo.events.emit(StreamEvent.Iteration(assessment(1)))
        repo.events.emit(status(RunState.COMPLETE, 1.0))
        runCurrent()

        assertEquals(1, vm.state.value.assessment?.iteration)
        assertFalse(vm.state.value.isRunning)
        assertEquals(bundleCallsAfterLoad + 1, repo.bundleCalls)
        assertEquals(1, vm.state.value.bundle?.currentIteration)
        assertEquals(1, recents.remembered.last().second?.iteration)

        repo.events.emit(StreamEvent.Iteration(assessment(1))) // the replay after a reconnect: nothing new
        runCurrent()
        assertEquals(bundleCallsAfterLoad + 1, repo.bundleCalls)
        vm.onScreenStopped()
    }

    @Test
    fun `a refetch that failed is tried again when the stream says the iteration again`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING", "d1")
        val vm = viewModel()
        vm.onScreenStarted()
        runCurrent()
        val bundleCallsAfterLoad = repo.bundleCalls

        repo.bundleError = apiFailure(ApiException.Kind.NETWORK, "down")
        repo.events.emit(StreamEvent.Iteration(assessment(1)))
        runCurrent()
        assertEquals(bundleCallsAfterLoad + 1, repo.bundleCalls)
        assertTrue("the screen has not caught up: the document list is the old one", vm.state.value.pendingRefresh())

        repo.bundleError = null
        repo.bundle = bundle(1, "MISSING_EVIDENCE", "d1")
        repo.iterations = listOf(assessment(1))
        repo.events.emit(StreamEvent.Iteration(assessment(1))) // a reconnect replays the latest iteration
        runCurrent()

        assertEquals(bundleCallsAfterLoad + 2, repo.bundleCalls)
        assertEquals(1, vm.state.value.bundle?.currentIteration)
        assertFalse(vm.state.value.pendingRefresh())
        vm.onScreenStopped()
    }

    @Test
    fun `an iteration that arrives while a refetch runs is refetched after it, not lost`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING", "d1")
        val vm = viewModel()
        vm.onScreenStarted()
        runCurrent()
        val bundleCallsAfterLoad = repo.bundleCalls

        val gate = kotlinx.coroutines.CompletableDeferred<Unit>()
        repo.bundleGate = gate
        repo.events.emit(StreamEvent.Iteration(assessment(1)))
        runCurrent() // refetching for 1, held
        repo.events.emit(StreamEvent.Iteration(assessment(2)))
        runCurrent()
        assertEquals("one refresh at a time", bundleCallsAfterLoad + 1, repo.bundleCalls)

        repo.bundleGate = null
        repo.bundle = bundle(2, "MISSING_EVIDENCE", "d1")
        repo.iterations = listOf(assessment(1), assessment(2))
        gate.complete(Unit)
        runCurrent()

        assertEquals("a second read for the iteration that came meanwhile", bundleCallsAfterLoad + 2, repo.bundleCalls)
        assertFalse(vm.state.value.pendingRefresh())
        assertEquals(2, vm.state.value.bundle?.currentIteration)
        vm.onScreenStopped()
    }

    @Test
    fun `a failed run shows the server's message`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.onScreenStarted()
        runCurrent()
        repo.events.emit(status(RunState.ERROR, message = "Gemini token limit"))
        runCurrent()
        assertEquals("Gemini token limit", vm.state.value.streamError)
        vm.onScreenStopped()
    }

    @Test
    fun `an update the app cannot read is surfaced, not swallowed`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.onScreenStarted()
        runCurrent()
        repo.events.emit(StreamEvent.Unreadable("iteration"))
        runCurrent()
        assertEquals(BundleViewModel.UNREADABLE_UPDATE, vm.state.value.streamError)
        vm.onScreenStopped()
    }

    @Test
    fun `after repeated failed attempts the latest assessment is polled until the stream is back`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING", "d1")
        val vm = viewModel()
        vm.onScreenStarted()
        runCurrent()

        repo.events.emit(StreamEvent.Disconnected(attempt = 1, retryInMillis = 3_000, httpStatus = null))
        repo.events.emit(StreamEvent.Disconnected(attempt = 2, retryInMillis = 6_000, httpStatus = null))
        runCurrent()
        assertEquals(StreamConnection.RECONNECTING, vm.state.value.connection)
        advanceTimeBy(30_000)
        assertEquals("two failed attempts are not yet a reason to poll", 0, repo.latestCalls)

        repo.events.emit(StreamEvent.Disconnected(attempt = 3, retryInMillis = 12_000, httpStatus = null))
        runCurrent()
        repo.latest = assessment(1)
        repo.bundle = bundle(1, "MISSING_EVIDENCE", "d1")
        repo.iterations = listOf(assessment(1))
        advanceTimeBy(10_001)
        runCurrent()
        assertEquals(1, vm.state.value.assessment?.iteration)
        assertTrue(repo.latestCalls >= 1)

        repo.events.emit(StreamEvent.Opened)
        runCurrent()
        val callsWhenBack = repo.latestCalls
        advanceTimeBy(60_000)
        assertEquals("polling stops once the stream is open again", callsWhenBack, repo.latestCalls)
        vm.onScreenStopped()
    }

    @Test
    fun `when the stream opens while a saved copy is shown the live bundle replaces it`() = runTest(dispatcher) {
        repo.bundleError = apiFailure(ApiException.Kind.NETWORK, "down")
        recents.remember(bundle(1, "MISSING_EVIDENCE", "d1"), assessment(1))
        val vm = viewModel()
        vm.onScreenStarted()
        runCurrent()
        assertEquals(1_000L, vm.state.value.savedCopyAt)

        repo.bundleError = null
        repo.bundle = bundle(2, "COMPLIANT_FOR_SUBMISSION", "d1")
        repo.latest = assessment(2, "COMPLIANT_FOR_SUBMISSION")
        repo.iterations = listOf(assessment(1), assessment(2, "COMPLIANT_FOR_SUBMISSION"))
        repo.events.emit(StreamEvent.Opened)
        runCurrent()

        assertNull(vm.state.value.savedCopyAt)
        assertEquals(2, vm.state.value.assessment?.iteration)
        vm.onScreenStopped()
    }

    @Test
    fun `choosing a document is kept`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING", "d1", "d2")
        val vm = viewModel()
        runCurrent()
        vm.selectDocument("d2")
        assertEquals("d2", vm.state.value.activeDocumentId)
    }

}
