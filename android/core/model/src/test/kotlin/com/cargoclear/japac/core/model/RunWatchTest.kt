package com.cargoclear.japac.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RunWatchTest {
    private fun status(state: RunState, runId: String = "run-2", message: String? = null) = StatusEvent("status", "b1", runId, state, "extract", 0.5, message)

    @Test
    fun `a run that is going is not over`() {
        val watch = RunWatch("run-2")
        assertNull(watch.onStatus(status(RunState.QUEUED)))
        assertNull(watch.onStatus(status(RunState.RUNNING)))
    }

    @Test
    fun `the replay of the run before this one is not this one ending`() {
        val watch = RunWatch("run-2")
        assertNull(watch.onStatus(status(RunState.COMPLETE, runId = "run-1")))
        assertNull(watch.onStatus(status(RunState.ERROR, runId = "run-1", message = "old failure")))
    }

    @Test
    fun `the run finishing is its end`() {
        assertEquals(RunEnd.Finished, RunWatch("run-2").onStatus(status(RunState.COMPLETE)))
    }

    @Test
    fun `the run failing is its end, with its own words`() {
        assertEquals(RunEnd.Failed("model quota exceeded"), RunWatch("run-2").onStatus(status(RunState.ERROR, message = "model quota exceeded")))
        assertEquals(RunEnd.Failed(null), RunWatch("run-2").onStatus(status(RunState.ERROR)))
    }

    private fun doc(id: String) = DocumentRecord(id, "b1", "$id.pdf", "INVOICE", "gs://x", "sha", 2048, "2026-01-01T00:00:00Z")

    private fun analysed() = WorkbenchState().loaded(Bundle("b1", null, "SG", "MISSING_EVIDENCE", 1, listOf(doc("d1")), "t"), AssessmentIteration(iteration = 1, bundleId = "b1", status = "MISSING_EVIDENCE"), emptyList())

    @Test
    fun `the screen knows which run to hand to the watcher when the person leaves`() {
        assertNull("nothing is running", analysed().runToWatch)
        assertNull("asked, but the server has not said which run yet", analysed().runRequested().runToWatch)
        assertEquals("run-7", analysed().runRequested().runStarted("run-7").runToWatch)
        val byStream = analysed().streamStatus(StatusEvent("status", "b1", "run-9", RunState.RUNNING, "extract", 0.2, null))
        assertEquals("a run another device started is watched as well", "run-9", byStream.runToWatch)
        val over = analysed().runRequested().runStarted("run-7").streamStatus(StatusEvent("status", "b1", "run-7", RunState.COMPLETE, null, 1.0, null))
        assertNull(over.runToWatch)
    }
}
