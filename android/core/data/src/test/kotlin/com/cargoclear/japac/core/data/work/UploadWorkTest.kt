package com.cargoclear.japac.core.data.work

import androidx.work.Data
import androidx.work.WorkInfo
import com.cargoclear.japac.core.model.ActionError
import com.cargoclear.japac.core.model.BatchOutcome
import com.cargoclear.japac.core.model.BatchPhase
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UploadWorkTest {
    private val none = Data.EMPTY

    @Test
    fun `an outcome survives the trip through the work's output`() {
        val outcome = BatchOutcome(
            uploaded = 2,
            total = 3,
            error = ActionError("Only PDF files are accepted.", "req-1"),
            runId = null,
            runError = null,
            finishedAt = 1_760_000_000_000L,
        )
        assertEquals(outcome, UploadWork.outcome(UploadWork.output(outcome)))
    }

    @Test
    fun `a batch that ended by starting a run keeps the run's id, one that could not keeps why`() {
        val started = BatchOutcome(1, 1, runId = "run-7", finishedAt = 9L)
        assertEquals(started, UploadWork.outcome(UploadWork.output(started)))
        val refused = BatchOutcome(1, 1, runError = ActionError("An analysis is already running for this bundle.", "req-2"), finishedAt = 9L)
        assertEquals(refused, UploadWork.outcome(UploadWork.output(refused)))
    }

    @Test
    fun `work that ended without an output has no outcome`() {
        assertNull(UploadWork.outcome(none))
    }

    @Test
    fun `the input names the bundle, the files and what the screen knew`() {
        val data = UploadWork.input("bnd-1", listOf("content://a/1", "content://a/2"), currentIteration = 2)
        assertEquals("bnd-1", data.getString(UploadWork.KEY_BUNDLE))
        assertEquals(listOf("content://a/1", "content://a/2"), data.getNullableStringArray(UploadWork.KEY_URIS)?.toList())
        assertEquals(2, data.getInt(UploadWork.KEY_ITERATION, -1))
    }

    @Test
    fun `the states of the work read as the phases of a batch`() {
        fun phase(state: WorkInfo.State) = UploadWork.batch("w", state, setOf("upload", UploadWork.totalTag(2)), none, none).phase
        assertEquals(BatchPhase.WAITING, phase(WorkInfo.State.ENQUEUED))
        assertEquals(BatchPhase.WAITING, phase(WorkInfo.State.BLOCKED))
        assertEquals(BatchPhase.RUNNING, phase(WorkInfo.State.RUNNING))
        assertEquals(BatchPhase.SUCCEEDED, phase(WorkInfo.State.SUCCEEDED))
        assertEquals(BatchPhase.FAILED, phase(WorkInfo.State.FAILED))
        assertEquals(BatchPhase.CANCELLED, phase(WorkInfo.State.CANCELLED))
    }

    @Test
    fun `a running batch reports its file number and name from the progress, and its size from the tag`() {
        val batch = UploadWork.batch("w", WorkInfo.State.RUNNING, setOf("upload", UploadWork.totalTag(3)), UploadWork.progress(2, 3, "mtc.pdf"), none)
        assertEquals(3, batch.total)
        assertEquals(2, batch.current)
        assertEquals("mtc.pdf", batch.filename)
        assertNull(batch.outcome)
    }

    @Test
    fun `a queued batch knows how many files it has before any progress was reported`() {
        val batch = UploadWork.batch("w", WorkInfo.State.ENQUEUED, setOf("upload", UploadWork.totalTag(4)), none, none)
        assertEquals(4, batch.total)
        assertNull(batch.current)
        assertNull(batch.filename)
    }

    @Test
    fun `a finished batch carries its outcome`() {
        val output = UploadWork.output(BatchOutcome(1, 2, error = ActionError("no", "req-3"), finishedAt = 5L))
        val batch = UploadWork.batch("w", WorkInfo.State.FAILED, setOf("upload", UploadWork.totalTag(2)), none, output)
        assertEquals(1, batch.outcome?.uploaded)
        assertEquals("req-3", batch.outcome?.error?.requestId)
    }

    @Test
    fun `without a tag the total comes from the outcome`() {
        val output = UploadWork.output(BatchOutcome(2, 2, finishedAt = 1L))
        assertEquals(2, UploadWork.batch("w", WorkInfo.State.SUCCEEDED, emptySet(), none, output).total)
    }

    @Test
    fun `each bundle has its own chain of work`() {
        assertEquals("upload-bnd-1", UploadWork.uniqueName("bnd-1"))
        assertTrue(UploadWork.uniqueName("bnd-1") != UploadWork.uniqueName("bnd-2"))
    }
}
