package com.cargoclear.japac.core.model

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The part of the workbench state that holds the corrections and the extraction behind the assessment on screen. */
class WorkbenchCorrectionsTest {
    private fun doc(id: String) = DocumentRecord(id, "b1", "$id.pdf", "INVOICE", "gs://x", "sha", 2048, "2026-01-01T00:00:00Z")

    private fun bundle(iteration: Int) = Bundle("b1", null, "IN", if (iteration == 0) "PENDING" else "MATERIAL_CONTRADICTION", iteration, listOf(doc("d1")), "2026-01-01T00:00:00Z")

    private fun iteration(n: Int) = AssessmentIteration(iteration = n, bundleId = "b1", status = "MATERIAL_CONTRADICTION")

    private fun analysed() = WorkbenchState().loaded(bundle(1), iteration(1), listOf(iteration(1)))

    private val response = CorrectionsResponse(pending = 1, latestIteration = 1)

    private val docs = listOf(buildJsonObject { put("document_id", "d1") })

    @Test
    fun `values can be corrected on a live bundle that is not running`() {
        assertTrue(analysed().canCorrect)
        assertFalse("still loading", WorkbenchState().canCorrect)
        assertFalse("a saved copy cannot send anything", WorkbenchState().loadedFromSavedCopy(bundle(1), iteration(1), savedAt = 1L).canCorrect)
    }

    @Test
    fun `not while a run goes, which would be reading what is being changed`() {
        val running = analysed().runRequested().runStarted("run-1")
        assertFalse(running.canCorrect)
        assertTrue("the run ended", running.streamStatus(StatusEvent("status", "b1", "run-1", RunState.COMPLETE, null, 1.0, null)).canCorrect)
    }

    @Test
    fun `the corrections and the extraction are kept until the bundle is loaded again`() {
        val s = analysed().correctionsLoaded(response).extractionsLoaded(docs)
        assertEquals(response, s.corrections)
        assertEquals(docs, s.extractions)
        val reloaded = s.reloading()
        assertNull("a retry forgets them as it forgets the bundle", reloaded.corrections)
        assertTrue(reloaded.extractions.isEmpty())
    }

    @Test
    fun `with no assessment there is nothing to correct against`() {
        val s = analysed().correctionsLoaded(response).extractionsLoaded(docs).correctionDataCleared()
        assertNull(s.corrections)
        assertTrue(s.extractions.isEmpty())
        assertEquals(0, WorkbenchState().loaded(bundle(0), null, emptyList()).shownIteration)
        assertEquals(1, analysed().shownIteration)
    }

    @Test
    fun `the iteration to fetch for follows the newest assessment, the stream's included`() {
        val s = analysed().streamIteration(iteration(2))
        assertEquals(2, s.shownIteration)
        assertEquals("a stale replay does not move it back", 2, s.streamIteration(iteration(1)).shownIteration)
    }

    @Test
    fun `the audit chain is fetched again when an assessment, a run, a document or a correction changes`() {
        val base = analysed()
        val key = base.auditRefreshKey
        assertEquals(key, base.auditRefreshKey)

        assertTrue("a newer assessment", base.streamIteration(iteration(2)).auditRefreshKey != key)
        assertTrue("a run on the stream", base.streamStatus(StatusEvent("status", "b1", "run-1", RunState.RUNNING, null, 0.1, null)).auditRefreshKey != key)
        assertTrue("a document", base.bundleRefreshed(bundle(1).copy(documents = listOf(doc("d1"), doc("d2")))).auditRefreshKey != key)
        val record = CorrectionRecord("cor-9", CorrectionKind.CORRECTION, 9, "t", 1, "d1", "consignee")
        assertTrue("a correction", base.correctionsLoaded(CorrectionsResponse(corrections = listOf(record))).auditRefreshKey != key)
        assertEquals("pending is not part of it: nothing was added to the chain", key, base.correctionsLoaded(CorrectionsResponse(pending = 3)).auditRefreshKey)
    }
}
