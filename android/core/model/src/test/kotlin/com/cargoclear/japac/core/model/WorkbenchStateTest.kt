package com.cargoclear.japac.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The read-side rules of `useWorkbench` (frontend/lib/hooks/useWorkbench.ts), one scenario each. */
class WorkbenchStateTest {
    private fun doc(id: String) = DocumentRecord(id, "b1", "$id.pdf", "INVOICE", "gs://x", "sha", 2048, "2026-01-01T00:00:00Z")

    private fun bundle(vararg docs: String, iteration: Int = 0, status: String = "PENDING") =
        Bundle("b1", null, "SG", status, iteration, docs.map(::doc), "2026-01-01T00:00:00Z")

    private fun iteration(n: Int, status: String = "MISSING_EVIDENCE", vararg checks: CheckResult) =
        AssessmentIteration(iteration = n, bundleId = "b1", status = status, checks = checks.toList())

    private fun material(focus: String?) = CheckResult("M-001", Severity.MATERIAL, "m", focusDocument = focus)

    private fun status(state: RunState, runId: String = "run-1", message: String? = null, progress: Double = 0.5) =
        StatusEvent("status", "b1", runId, state, "extract", progress, message)

    @Test
    fun `a bundle that was never analysed has no assessment and offers to analyse`() {
        val s = WorkbenchState().loaded(bundle("d1", "d2"), null, emptyList())
        assertEquals(LoadState.Ready, s.load)
        assertNull(s.assessment)
        assertEquals(RunMode.ANALYZE, s.runMode)
        assertEquals(0, s.currentIteration)
        assertEquals("d1", s.activeDocumentId)
    }

    @Test
    fun `after the first iteration the action is reassess`() {
        val s = WorkbenchState().loaded(bundle("d1", iteration = 1), iteration(1), listOf(iteration(1)))
        assertEquals(RunMode.REASSESS, s.runMode)
        assertEquals(1, s.currentIteration)
    }

    @Test
    fun `the live assessment wins unless the fetched one is newer, and a stale replay is dropped`() {
        var s = WorkbenchState().loaded(bundle("d1", iteration = 2), iteration(2), listOf(iteration(1), iteration(2)))
        s = s.streamIteration(iteration(1)) // a replay older than what was fetched
        assertEquals(2, s.assessment?.iteration)
        s = s.streamIteration(iteration(3, "COMPLIANT_FOR_SUBMISSION"))
        assertEquals(3, s.assessment?.iteration)
        s = s.streamIteration(iteration(2)) // a later replay of an older one must not replace the held live one
        assertEquals(3, s.assessment?.iteration)
        assertEquals(listOf(1, 2, 3), s.iterations.map { it.iteration })
    }

    @Test
    fun `an iteration the screen has already reflected is not new, a newer one asks for a refetch exactly once`() {
        var s = WorkbenchState().loaded(bundle("d1", iteration = 1), iteration(1), listOf(iteration(1)))
        s = s.streamIteration(iteration(1)) // the replay on connect
        assertFalse(s.pendingRefresh())

        s = s.streamIteration(iteration(2))
        assertTrue(s.pendingRefresh())
        s = s.markHandled()
        assertFalse(s.pendingRefresh())
    }

    @Test
    fun `a refetch is for one iteration, and one that arrived while it ran stays pending`() {
        var s = WorkbenchState().loaded(bundle("d1", iteration = 1), iteration(1), listOf(iteration(1)))
        s = s.streamIteration(iteration(2))
        assertEquals(2, s.iterationToRefresh())

        s = s.streamIteration(iteration(3)) // arrives while the refetch for 2 is running
        s = s.markHandled(2)
        assertEquals("3 was not part of that refetch", 3, s.iterationToRefresh())
        assertEquals(null, s.markHandled(3).iterationToRefresh())
    }

    @Test
    fun `an iteration whose refetch failed is still pending`() {
        val s = WorkbenchState().loaded(bundle("d1", iteration = 1), iteration(1), listOf(iteration(1))).streamIteration(iteration(2))
        // the refetch failed: markHandled is never called, so the next thing the stream says asks again
        assertEquals(2, s.iterationToRefresh())
        assertEquals(2, s.iterationToRefresh())
    }

    @Test
    fun `nothing is refetched before the first load has finished`() {
        val s = WorkbenchState().streamIteration(iteration(1))
        assertFalse(s.pendingRefresh())
        // once loaded with an older fetch, the stream's newer iteration is then caught up with
        val loaded = s.loaded(bundle("d1"), null, emptyList())
        assertTrue(loaded.pendingRefresh())
    }

    @Test
    fun `a run in progress is shown, a failed run keeps its message until another state replaces it`() {
        var s = WorkbenchState().loaded(bundle("d1"), null, emptyList())
        s = s.streamStatus(status(RunState.RUNNING))
        assertTrue(s.isRunning)
        assertNull(s.streamError)

        s = s.streamStatus(status(RunState.ERROR, message = "Gemini token limit"))
        assertFalse(s.isRunning)
        assertEquals("Gemini token limit", s.streamError)

        s = s.streamStatus(status(RunState.ERROR, message = null))
        assertEquals("Pipeline run failed", s.streamError)

        s = s.streamStatus(status(RunState.COMPLETE))
        assertNull(s.streamError)
        assertFalse(s.isRunning)
        assertTrue(WorkbenchState().streamStatus(status(RunState.QUEUED)).isRunning)
    }

    @Test
    fun `the document in view is the finding's document, then the person's choice while it exists, else the first`() {
        val checks = arrayOf(material(focus = "mtc"))
        val analysed = iteration(1, "MATERIAL_CONTRADICTION", *checks)
        var s = WorkbenchState().loaded(bundle("inv", "mtc", "bl", iteration = 1), analysed, listOf(analysed))
        assertEquals("mtc", s.activeDocumentId)

        s = s.selectDocument("bl")
        assertEquals("bl", s.activeDocumentId)

        s = s.selectDocument("gone")
        assertEquals("mtc", s.activeDocumentId.also { assertTrue("a stale choice falls back to the finding", true) })
    }

    @Test
    fun `once the finding's document was shown it stays when a recompute clears the finding`() {
        val analysed = iteration(1, "MATERIAL_CONTRADICTION", material(focus = "mtc"))
        var s = WorkbenchState().loaded(bundle("inv", "mtc", iteration = 1), analysed, listOf(analysed))
        assertEquals("mtc", s.selectedDocumentId)

        s = s.streamIteration(iteration(2, "SPECIALIST_REVIEW_REQUIRED")) // the contradiction is gone
        assertEquals("mtc", s.activeDocumentId)
    }

    @Test
    fun `without a finding the first document is shown but not stuck to`() {
        var s = WorkbenchState().loaded(bundle("inv", "bl"), null, emptyList())
        assertEquals("inv", s.activeDocumentId)
        assertNull(s.selectedDocumentId)
        s = s.bundleRefreshed(bundle("bl", "inv"))
        assertEquals("bl", s.activeDocumentId)
    }

    @Test
    fun `a failed load is told apart from a bundle that does not exist, and retry starts over`() {
        val failed = WorkbenchState().loadFailed(notFound = false, message = "Can't reach the server")
        assertEquals(LoadState.Failed("Can't reach the server"), failed.load)
        assertEquals(LoadState.NotFound, WorkbenchState().loadFailed(notFound = true, message = "x").load)

        val retrying = failed.streamStatus(status(RunState.RUNNING)).reloading()
        assertEquals(LoadState.Loading, retrying.load)
        assertTrue("what the stream said is kept", retrying.isRunning)
        assertNull(retrying.bundle)
    }

    @Test
    fun `a saved copy is marked as one and replaced by live data`() {
        val saved = WorkbenchState().loadedFromSavedCopy(bundle("d1", iteration = 1), iteration(1), savedAt = 1234L)
        assertEquals(1234L, saved.savedCopyAt)
        assertEquals(LoadState.Ready, saved.load)
        assertEquals(1, saved.assessment?.iteration)

        val live = saved.loaded(bundle("d1", iteration = 2), iteration(2), listOf(iteration(1), iteration(2)))
        assertNull(live.savedCopyAt)
        assertEquals(2, live.assessment?.iteration)
    }

    @Test
    fun `the connection state and a stream failure are carried`() {
        var s = WorkbenchState()
        assertEquals(StreamConnection.CONNECTING, s.connection)
        s = s.connection(StreamConnection.OPEN)
        assertEquals(StreamConnection.OPEN, s.connection)
        s = s.streamFailed("The event stream failed unexpectedly")
        assertEquals("The event stream failed unexpectedly", s.streamError)
    }
}
