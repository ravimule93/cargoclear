package com.cargoclear.japac.ui.bundle

import androidx.lifecycle.SavedStateHandle
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.StreamEvent
import com.cargoclear.japac.core.data.UploadBatchRunner
import com.cargoclear.japac.core.model.ActionError
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.BatchOutcome
import com.cargoclear.japac.core.model.BatchPhase
import com.cargoclear.japac.core.model.RunMode
import com.cargoclear.japac.core.model.RunState
import com.cargoclear.japac.core.model.StatusEvent
import com.cargoclear.japac.core.model.UploadBatch
import com.cargoclear.japac.core.model.UploadStatus
import com.cargoclear.japac.ui.FakeBundleRepository
import com.cargoclear.japac.notify.RunTracker
import com.cargoclear.japac.ui.FakeCorrections
import com.cargoclear.japac.ui.FakeFileImporter
import com.cargoclear.japac.ui.FakeDocuments
import com.cargoclear.japac.ui.FakeMeta
import com.cargoclear.japac.ui.FakeRecents
import com.cargoclear.japac.ui.FakeUploadScheduler
import com.cargoclear.japac.ui.apiFailure
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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Starting runs and sending documents from the bundle screen (the action half of `useWorkbench`). */
@OptIn(ExperimentalCoroutinesApi::class)
class BundleRunAndUploadTest {
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

    private fun viewModel(mode: AppMode = AppMode.DEMO) = BundleViewModel(
        SavedStateHandle(mapOf("bundleId" to "bnd-1")), repo, recents, FakeMeta(mode), documents, scheduler, UploadBatchRunner(documents, repo), corrections, FakeFileImporter(), RunTracker(),
    )

    private fun status(state: RunState, runId: String = "run-1", progress: Double = 0.5, message: String? = null) =
        StreamEvent.Status(StatusEvent("status", "bnd-1", runId, state, "extract", progress, message))

    private fun analysedBundle() {
        repo.bundle = bundle(1, "MISSING_EVIDENCE", "d1")
        repo.latest = assessment(1)
        repo.iterations = listOf(assessment(1))
    }

    // ---- runs

    @Test
    fun `a bundle never analysed starts with analyze, and stays running until the stream says that run finished`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING", "d1")
        repo.nextRunId = "run-7"
        val vm = viewModel()
        vm.onScreenStarted()
        runCurrent()
        assertEquals(RunMode.ANALYZE, vm.state.value.runMode)
        assertTrue(vm.state.value.canRun)

        vm.runAnalysis()
        assertTrue("running from the moment of the tap", vm.state.value.isRunning)
        runCurrent()

        assertEquals(listOf("analyze"), repo.runCalls)
        assertEquals("run-7", vm.state.value.pendingRunId)
        assertTrue(vm.state.value.isRunning)
        assertFalse(vm.state.value.canRun)

        repo.events.emit(status(RunState.RUNNING, "run-7"))
        repo.events.emit(status(RunState.COMPLETE, "run-7", 1.0))
        runCurrent()
        assertFalse(vm.state.value.isRunning)
        vm.onScreenStopped()
    }

    @Test
    fun `an analysed bundle asks for a reassessment`() = runTest(dispatcher) {
        analysedBundle()
        val vm = viewModel()
        runCurrent()
        assertEquals(RunMode.REASSESS, vm.state.value.runMode)
        vm.runAnalysis()
        runCurrent()
        assertEquals(listOf("reassess"), repo.runCalls)
    }

    @Test
    fun `a second tap while a run is being asked for does nothing`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING", "d1")
        val vm = viewModel()
        runCurrent()
        vm.runAnalysis()
        vm.runAnalysis()
        runCurrent()
        assertEquals(listOf("analyze"), repo.runCalls)
    }

    @Test
    fun `a refused run shows the web's words with the request id, and can be asked again`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING", "d1")
        repo.runError = ApiException(
            com.cargoclear.japac.core.model.ErrorEnvelope("CONFLICT", "An assessment run is already in progress for bundle 'bnd-1'.", requestId = "req-9"),
            ApiException.Kind.HTTP,
            409,
        )
        val vm = viewModel()
        runCurrent()

        vm.runAnalysis()
        runCurrent()

        val error = vm.state.value.visibleError
        assertEquals("An analysis is already running for this bundle.", error?.message)
        assertEquals("req-9", error?.requestId)
        assertFalse(vm.state.value.isRunning)
        assertTrue(vm.state.value.canRun)

        repo.runError = null
        vm.runAnalysis()
        runCurrent()
        assertNull("asking again forgets the old error", vm.state.value.actionError)
        assertEquals(2, repo.runCalls.size)
    }

    @Test
    fun `a bundle with no documents is told to upload one, in the web's words`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING")
        repo.runError = ApiException(
            com.cargoclear.japac.core.model.ErrorEnvelope("VALIDATION_ERROR", "Cannot analyze an empty bundle. Upload trade documents first."),
            ApiException.Kind.HTTP,
            422,
        )
        val vm = viewModel()
        runCurrent()
        vm.runAnalysis()
        runCurrent()
        assertEquals("Upload at least one document before analyzing.", vm.state.value.visibleError?.message)
    }

    @Test
    fun `a connection that fails says so and leaves the screen usable`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING", "d1")
        repo.runError = apiFailure(ApiException.Kind.NETWORK, ApiException.NETWORK_MESSAGE)
        val vm = viewModel()
        runCurrent()
        vm.runAnalysis()
        runCurrent()
        assertEquals(ApiException.NETWORK_MESSAGE, vm.state.value.visibleError?.message)
        assertTrue(vm.state.value.canRun)
    }

    @Test
    fun `a saved copy cannot start a run`() = runTest(dispatcher) {
        repo.bundleError = apiFailure(ApiException.Kind.NETWORK, ApiException.NETWORK_MESSAGE)
        recents.remember(bundle(1, "MISSING_EVIDENCE", "d1"), assessment(1))
        val vm = viewModel()
        runCurrent()
        assertTrue(vm.state.value.isReadOnly)
        vm.runAnalysis()
        runCurrent()
        assertTrue(repo.runCalls.isEmpty())
    }

    @Test
    fun `recompute goes through the same gate and path`() = runTest(dispatcher) {
        analysedBundle()
        val vm = viewModel()
        runCurrent()
        vm.recompute()
        runCurrent()
        assertEquals(listOf("recompute"), repo.runCalls)
        vm.recompute() // already awaiting that run
        runCurrent()
        assertEquals(1, repo.runCalls.size)
    }

    // ---- uploads

    @Test
    fun `picked files are queued with what the screen knows of the bundle`() = runTest(dispatcher) {
        analysedBundle()
        val vm = viewModel()
        runCurrent()
        vm.onFilesPicked(listOf("content://docs/1", "content://docs/2"))
        assertEquals(listOf(Triple("bnd-1", listOf("content://docs/1", "content://docs/2"), 1)), scheduler.enqueued)
    }

    @Test
    fun `nothing is queued for an empty pick, and nothing while files are already going up`() = runTest(dispatcher) {
        analysedBundle()
        val vm = viewModel()
        vm.onScreenStarted()
        runCurrent()
        vm.onFilesPicked(emptyList())
        assertTrue(scheduler.enqueued.isEmpty())

        scheduler.batches.value = listOf(UploadBatch("w1", BatchPhase.RUNNING, total = 2, current = 1, filename = "a.pdf"))
        runCurrent()
        vm.onFilesPicked(listOf("content://docs/3"))
        assertTrue(scheduler.enqueued.isEmpty())
        vm.onScreenStopped()
    }

    @Test
    fun `adding a file clears the last failure`() = runTest(dispatcher) {
        analysedBundle()
        repo.runError = apiFailure(ApiException.Kind.NETWORK, "x")
        val vm = viewModel()
        runCurrent()
        vm.runAnalysis()
        runCurrent()
        assertTrue(vm.state.value.visibleError != null)
        vm.onFilesPicked(listOf("content://docs/1"))
        assertNull(vm.state.value.visibleError)
    }

    @Test
    fun `progress of the background batch is shown while the screen is visible, and stops with the screen`() = runTest(dispatcher) {
        analysedBundle()
        val vm = viewModel()
        vm.onScreenStarted()
        runCurrent()

        scheduler.batches.value = listOf(UploadBatch("w1", BatchPhase.RUNNING, total = 3, current = 2, filename = "mtc.pdf"))
        runCurrent()
        assertEquals(UploadStatus.Active(2, 3, "mtc.pdf"), vm.state.value.upload)
        assertFalse(vm.state.value.canRun)

        vm.onScreenStopped()
        runCurrent()
        assertEquals(0, scheduler.batches.subscriptionCount.value)
    }

    @Test
    fun `a batch that finishes while watched refreshes the bundle once and puts the screen into the run it started`() = runTest(dispatcher) {
        analysedBundle()
        val vm = viewModel()
        vm.onScreenStarted()
        runCurrent()
        val before = repo.bundleCalls

        scheduler.batches.value = listOf(UploadBatch("w1", BatchPhase.RUNNING, total = 1, current = 1, filename = "a.pdf"))
        runCurrent()
        repo.bundle = bundle(1, "MISSING_EVIDENCE", "d1", "d2")
        scheduler.batches.value = listOf(
            UploadBatch("w1", BatchPhase.SUCCEEDED, total = 1, outcome = BatchOutcome(1, 1, runId = "run-5", finishedAt = 1L)),
        )
        runCurrent()

        assertEquals(before + 1, repo.bundleCalls)
        assertEquals(2, vm.state.value.documents.size)
        assertEquals(UploadStatus.Idle, vm.state.value.upload)
        assertEquals("run-5", vm.state.value.pendingRunId)
        assertTrue(vm.state.value.isRunning)

        scheduler.batches.value = scheduler.batches.value // reported again: handled once
        runCurrent()
        assertEquals(before + 1, repo.bundleCalls)
        vm.onScreenStopped()
    }

    @Test
    fun `a batch that failed shows how far it got and the server's reason, and can be dismissed`() = runTest(dispatcher) {
        analysedBundle()
        val vm = viewModel()
        vm.onScreenStarted()
        runCurrent()
        scheduler.batches.value = listOf(UploadBatch("w1", BatchPhase.RUNNING, total = 2, current = 2, filename = "notes.txt"))
        runCurrent()
        scheduler.batches.value = listOf(
            UploadBatch("w1", BatchPhase.FAILED, total = 2, outcome = BatchOutcome(1, 2, error = ActionError("Only PDF files are accepted.", "req-3"), finishedAt = 1L)),
        )
        runCurrent()

        val failed = vm.state.value.upload as UploadStatus.Failed
        assertEquals(1, failed.uploaded)
        assertEquals(2, failed.total)
        assertEquals("req-3", vm.state.value.visibleError?.requestId)
        assertTrue("one file landed, so the document list was refreshed", repo.bundleCalls >= 2)
        assertTrue(vm.state.value.canDismissError)

        vm.dismissError()
        assertNull(vm.state.value.visibleError)
        vm.onScreenStopped()
    }

    @Test
    fun `cancelling stops the bundle's batches`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.cancelUploads()
        assertEquals(listOf("bnd-1"), scheduler.cancelled)
    }

    // ---- the sample certificate

    @Test
    fun `the sample certificate is uploaded under its own name and the assessed bundle is reassessed once`() = runTest(dispatcher) {
        analysedBundle()
        repo.nextRunId = "run-8"
        val vm = viewModel()
        runCurrent()

        vm.useSampleMtc()
        assertTrue("shown as an upload from the first moment", vm.state.value.isUploading)
        runCurrent()

        assertEquals(listOf("mtc_pipe_test_cert.pdf"), documents.uploaded)
        assertEquals(listOf("reassess"), repo.runCalls)
        assertEquals("run-8", vm.state.value.pendingRunId)
        assertEquals(UploadStatus.Idle, vm.state.value.upload)
        assertTrue(vm.state.value.isRunning)
    }

    @Test
    fun `the sample certificate on a bundle never analysed is uploaded and waits for the person to run`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING", "d1")
        val vm = viewModel()
        runCurrent()
        vm.useSampleMtc()
        runCurrent()
        assertEquals(listOf("mtc_pipe_test_cert.pdf"), documents.uploaded)
        assertTrue(repo.runCalls.isEmpty())
        assertTrue(vm.state.value.canRun)
    }

    @Test
    fun `a sample certificate the server cannot give shows why`() = runTest(dispatcher) {
        analysedBundle()
        documents.sampleError = ApiException(
            com.cargoclear.japac.core.model.ErrorEnvelope("NOT_FOUND", "Demo endpoints are only available when APP_MODE=demo."),
            ApiException.Kind.HTTP,
            404,
        )
        val vm = viewModel()
        runCurrent()
        vm.useSampleMtc()
        runCurrent()
        assertEquals("Demo endpoints are only available when APP_MODE=demo.", vm.state.value.visibleError?.message)
        assertFalse(vm.state.value.isUploading)
    }

    @Test
    fun `a refused sample upload shows the server's reason`() = runTest(dispatcher) {
        analysedBundle()
        documents.uploadError = ApiException(
            com.cargoclear.japac.core.model.ErrorEnvelope("VALIDATION_ERROR", "A bundle can hold at most 20 documents.", requestId = "req-4"),
            ApiException.Kind.HTTP,
            422,
        )
        val vm = viewModel()
        runCurrent()
        vm.useSampleMtc()
        runCurrent()
        assertEquals("A bundle can hold at most 20 documents.", vm.state.value.visibleError?.message)
        assertEquals("req-4", vm.state.value.visibleError?.requestId)
        assertTrue(repo.runCalls.isEmpty())
    }
}
