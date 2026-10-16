package com.cargoclear.japac.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The action side of `useWorkbench`: runs asked for, runs awaited, errors, uploads. */
class WorkbenchRunTest {
    private fun doc(id: String) = DocumentRecord(id, "b1", "$id.pdf", "INVOICE", "gs://x", "sha", 2048, "2026-01-01T00:00:00Z")

    private fun bundle(iteration: Int = 0) = Bundle("b1", null, "SG", if (iteration == 0) "PENDING" else "MISSING_EVIDENCE", iteration, listOf(doc("d1")), "2026-01-01T00:00:00Z")

    private fun iteration(n: Int, status: String = "MISSING_EVIDENCE") = AssessmentIteration(iteration = n, bundleId = "b1", status = status)

    private fun status(state: RunState, runId: String = "run-1", message: String? = null) = StatusEvent("status", "b1", runId, state, "extract", 0.5, message)

    private fun fresh() = WorkbenchState().loaded(bundle(), null, emptyList())

    private fun analysed() = WorkbenchState().loaded(bundle(1), iteration(1), listOf(iteration(1)))

    @Test
    fun `a ready bundle can be run, a loading one or a saved copy cannot`() {
        assertTrue(fresh().canRun)
        assertFalse(WorkbenchState().canRun)
        assertFalse(WorkbenchState().loadFailed(notFound = false, message = "x").canRun)
        val saved = WorkbenchState().loadedFromSavedCopy(bundle(1), iteration(1), savedAt = 1L)
        assertFalse(saved.canRun)
        assertFalse(saved.canAddDocuments)
        assertTrue(saved.isReadOnly)
    }

    @Test
    fun `asking for a run disables running until the server answers, and forgets the last error`() {
        var s = fresh().actionFailed(ActionError("old failure"))
        s = s.runRequested()
        assertTrue(s.isRunning)
        assertFalse(s.canRun)
        assertNull(s.actionError)

        s = s.runRejected(ActionError("An analysis is already running for this bundle.", "req-7"))
        assertFalse(s.isRunning)
        assertEquals("req-7", s.visibleError?.requestId)
        assertTrue(s.canRun)
    }

    @Test
    fun `an accepted run keeps the screen running until the stream reports that run finished`() {
        var s = fresh().runRequested().runStarted("run-1")
        assertTrue("the stream has said nothing yet", s.isRunning)

        s = s.streamStatus(status(RunState.COMPLETE, runId = "run-0")) // the replay of an older run
        assertTrue("another run's end is not ours", s.isRunning)

        s = s.streamStatus(status(RunState.RUNNING, runId = "run-1"))
        assertTrue(s.isRunning)

        s = s.streamStatus(status(RunState.COMPLETE, runId = "run-1"))
        assertFalse(s.isRunning)
        assertTrue(s.canRun)
    }

    @Test
    fun `a run that failed ends the wait and shows the stream's message`() {
        val s = fresh().runStarted("run-1").streamStatus(status(RunState.ERROR, "run-1", "Gemini token limit"))
        assertFalse(s.isRunning)
        assertEquals("Gemini token limit", s.visibleError?.message)
        assertFalse("the stream's own error cannot be dismissed, it ends with the next status", s.canDismissError)
    }

    @Test
    fun `a newer iteration ends the wait even when the stream never reports the run, as with polling`() {
        var s = analysed().runStarted("run-2")
        assertTrue(s.isRunning)
        s = s.streamIteration(iteration(1)) // the same iteration again: nothing new
        assertTrue(s.isRunning)
        s = s.streamIteration(iteration(2, "COMPLIANT_FOR_SUBMISSION"))
        assertFalse(s.isRunning)
    }

    @Test
    fun `the wait is measured from where the bundle was when the run was asked for`() {
        val s = fresh().runStarted("run-1")
        assertEquals(0, s.pendingRunBase)
        assertTrue(s.streamIteration(iteration(1)).also { assertEquals(1, it.currentIteration) }.isRunning.not())
    }

    @Test
    fun `an action error is superseded by a new iteration but not by a replay of the one shown`() {
        var s = analysed().actionFailed(ActionError("409"))
        s = s.streamIteration(iteration(1))
        assertEquals("a replay of what is shown changes nothing", "409", s.actionError?.message)
        s = s.streamIteration(iteration(2))
        assertNull("a finished run supersedes it", s.actionError)
    }

    @Test
    fun `the banner shows the newest action error, then a failed upload, then the stream's error`() {
        val upload = UploadStatus.Failed(ActionError("upload failed"), uploaded = 0, total = 1)
        var s = fresh().streamStatus(status(RunState.ERROR, message = "pipeline"))
        assertEquals("pipeline", s.visibleError?.message)

        s = s.uploadUpdated(UploadUpdate(failure = upload))
        assertEquals("upload failed", s.visibleError?.message)
        assertTrue(s.canDismissError)

        s = s.actionFailed(ActionError("run failed"))
        assertEquals("run failed", s.visibleError?.message)

        s = s.errorDismissed()
        assertEquals("both are cleared, the stream's remains", "pipeline", s.visibleError?.message)
        assertEquals(UploadStatus.Idle, s.upload)
    }

    @Test
    fun `starting a run forgets a failed upload, an upload in progress hides it`() {
        val failed = UploadStatus.Failed(ActionError("upload failed"), 1, 2)
        assertEquals(UploadStatus.Idle, fresh().uploadUpdated(UploadUpdate(failure = failed)).runRequested().upload)

        val active = UploadStatus.Active(1, 2, "a.pdf")
        val s = fresh().uploadUpdated(UploadUpdate(failure = failed)).uploadUpdated(UploadUpdate(active = active))
        assertEquals(active, s.upload)
        assertTrue(s.isUploading)
    }

    @Test
    fun `files going up block running and adding, as the web disables its buttons`() {
        val s = fresh().uploadUpdated(UploadUpdate(active = UploadStatus.Active(1, 1, "a.pdf")))
        assertFalse(s.canRun)
        assertFalse(s.canAddDocuments)
        assertTrue(s.uploadUpdated(UploadUpdate()).canRun)
        assertEquals("progress ends when the scheduler reports no active batch", UploadStatus.Idle, s.uploadUpdated(UploadUpdate()).upload)
    }

    @Test
    fun `a finished batch that started a run puts the screen into the running state at once`() {
        val s = analysed().uploadUpdated(BatchOutcome(1, 1, runId = "run-5").toUpdate())
        assertTrue(s.isRunning)
        assertEquals("run-5", s.pendingRunId)
        assertEquals(1, s.pendingRunBase)
    }

    @Test
    fun `a finished batch whose run could not start shows why`() {
        val s = analysed().uploadUpdated(BatchOutcome(1, 1, runError = ActionError("An analysis is already running for this bundle.")).toUpdate())
        assertEquals("An analysis is already running for this bundle.", s.actionError?.message)
        assertFalse(s.isRunning)
    }

    @Test
    fun `retry after a failed load forgets what the screen was waiting for`() {
        val s = fresh().runStarted("run-1").actionFailed(ActionError("x")).reloading()
        assertNull(s.pendingRunId)
        assertNull(s.actionError)
        assertFalse(s.startingRun)
    }
}
