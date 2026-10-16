package com.cargoclear.japac.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UploadWatcherTest {
    private var clock = 1_000_000_000L
    private val watcher = UploadWatcher(now = { clock }, staleAfterMillis = 30 * 60_000L)

    private fun running(id: String = "w1", current: Int? = 1, total: Int = 2, name: String? = "a.pdf") =
        UploadBatch(id, BatchPhase.RUNNING, total, current, name)

    private fun waiting(id: String = "w1", total: Int = 2) = UploadBatch(id, BatchPhase.WAITING, total)

    private fun done(id: String = "w1", outcome: BatchOutcome, phase: BatchPhase = BatchPhase.SUCCEEDED) =
        UploadBatch(id, phase, outcome.total, outcome = outcome)

    @Test
    fun `a running batch is shown with its file number and name`() {
        val update = watcher.update(listOf(running(current = 2, total = 3, name = "mtc.pdf")))
        assertEquals(UploadStatus.Active(2, 3, "mtc.pdf", waiting = false), update.active)
        assertFalse(update.bundleChanged)
    }

    @Test
    fun `a queued batch, or one waiting for a connection, is shown as waiting and counted from the first file`() {
        assertEquals(UploadStatus.Active(1, 2, null, waiting = true), watcher.update(listOf(waiting())).active)
    }

    @Test
    fun `the running batch is shown in preference to one queued behind it`() {
        val update = watcher.update(listOf(waiting("w2"), running("w1", current = 1, total = 1, name = "x.pdf")))
        assertEquals("x.pdf", update.active?.filename)
    }

    @Test
    fun `a batch that finishes while watched asks for one refresh and the run it started`() {
        watcher.update(listOf(running()))
        val update = watcher.update(listOf(done(outcome = BatchOutcome(uploaded = 2, total = 2, runId = "run-9", finishedAt = clock))))
        assertNull(update.active)
        assertTrue(update.bundleChanged)
        assertEquals("run-9", update.runStarted)
        assertNull(update.failure)
        assertNull(update.runError)
    }

    @Test
    fun `a batch is handled once however often the list is reported`() {
        watcher.update(listOf(running()))
        val finished = listOf(done(outcome = BatchOutcome(2, 2, runId = "run-9", finishedAt = clock)))
        assertTrue(watcher.update(finished).bundleChanged)
        val again = watcher.update(finished)
        assertFalse(again.bundleChanged)
        assertNull(again.runStarted)
    }

    @Test
    fun `a failed batch reports how far it got and why`() {
        watcher.update(listOf(running(total = 3)))
        val error = ActionError("Only PDF files are accepted.", requestId = "req-1")
        val update = watcher.update(listOf(done(outcome = BatchOutcome(1, 3, error = error, finishedAt = clock), phase = BatchPhase.FAILED)))
        assertEquals(UploadStatus.Failed(error, uploaded = 1, total = 3), update.failure)
        assertTrue("the one file that landed makes the document list stale", update.bundleChanged)
    }

    @Test
    fun `a failure with nothing uploaded does not ask for a refresh`() {
        watcher.update(listOf(running(total = 1)))
        val update = watcher.update(listOf(done(outcome = BatchOutcome(0, 1, error = ActionError("no"), finishedAt = clock), phase = BatchPhase.FAILED)))
        assertFalse(update.bundleChanged)
        assertEquals(0, update.failure?.uploaded)
    }

    @Test
    fun `files that landed but a run that could not start report the run's reason, not an upload failure`() {
        watcher.update(listOf(running()))
        val reason = ActionError("An analysis is already running for this bundle.")
        val update = watcher.update(listOf(done(outcome = BatchOutcome(2, 2, runError = reason, finishedAt = clock))))
        assertEquals(reason, update.runError)
        assertNull(update.failure)
        assertTrue(update.bundleChanged)
    }

    @Test
    fun `a cancelled batch may have landed files, so the bundle is refetched`() {
        watcher.update(listOf(running()))
        val update = watcher.update(listOf(UploadBatch("w1", BatchPhase.CANCELLED, total = 2)))
        assertTrue(update.bundleChanged)
        assertNull(update.failure)
        assertNull(update.active)
    }

    @Test
    fun `a failure that happened while the screen was away is reported if it is recent`() {
        val error = ActionError("Server said no")
        val update = watcher.update(listOf(done(outcome = BatchOutcome(0, 1, error = error, finishedAt = clock - 5 * 60_000L), phase = BatchPhase.FAILED)))
        assertEquals(error, update.failure?.error)
        assertFalse("the screen has just loaded the bundle", update.bundleChanged)
    }

    @Test
    fun `a failure from long ago is not announced again`() {
        val update = watcher.update(listOf(done(outcome = BatchOutcome(0, 1, error = ActionError("old"), finishedAt = clock - 31 * 60_000L), phase = BatchPhase.FAILED)))
        assertNull(update.failure)
    }

    @Test
    fun `a batch that succeeded while the screen was away says nothing, even if it started a run`() {
        val update = watcher.update(listOf(done(outcome = BatchOutcome(2, 2, runId = "run-1", finishedAt = clock - 60_000L))))
        assertNull(update.runStarted)
        assertFalse(update.bundleChanged)
        assertNull(update.failure)
    }

    @Test
    fun `a failure with no time stamp is treated as stale`() {
        val update = watcher.update(listOf(done(outcome = BatchOutcome(0, 1, error = ActionError("x")), phase = BatchPhase.FAILED)))
        assertNull(update.failure)
    }

    @Test
    fun `one inline upload is turned into the same update as a batch`() {
        val ok = BatchOutcome(1, 1, runId = "run-2").toUpdate()
        assertTrue(ok.bundleChanged)
        assertEquals("run-2", ok.runStarted)
        val bad = BatchOutcome(0, 1, error = ActionError("nope")).toUpdate()
        assertEquals(UploadStatus.Failed(ActionError("nope"), 0, 1), bad.failure)
        assertFalse(bad.bundleChanged)
    }

    @Test
    fun `a batch that failed without saying how is reported when it was watched, with no count`() {
        watcher.update(listOf(running(total = 3)))
        val update = watcher.update(listOf(UploadBatch("w1", BatchPhase.FAILED, total = 3)))
        assertEquals(UploadStatus.Failed(ActionError(UPLOAD_STOPPED_MESSAGE), uploaded = null, total = 3), update.failure)
        assertTrue("some files may have landed: the documents are read again", update.bundleChanged)
    }

    @Test
    fun `a batch that failed without saying how, which the screen never saw run, is not announced`() {
        val update = watcher.update(listOf(UploadBatch("old", BatchPhase.FAILED, total = 2)))
        assertNull(update.failure)
        assertFalse(update.bundleChanged)
    }
}
