package com.cargoclear.japac.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ViewerStateTest {
    private val document = DocumentRecord("d1", "b1", "invoice.pdf", "COMMERCIAL_INVOICE", "gs://x", "sha", 1000, "2026-01-01T00:00:00Z")

    private fun hl(id: String, page: Int = 1, doc: String = "d1", severity: Severity = Severity.MATERIAL) =
        Highlight(id, doc, page, BBox(page, 100.0, 200.0, 160.0, 400.0), severity, "label $id")

    private fun meta(page: Int = 1, rotation: Int = 0, processedUri: String? = "gs://p/page-001.png", deskew: Boolean = false, deg: Double = 0.0) =
        TransformMetadata(page = page, sourcePage = page, rotation = rotation, processedUri = processedUri, deskewApplied = deskew, deskewDeg = deg)

    private fun opened(highlights: List<Highlight> = listOf(hl("a"), hl("b", page = 2), hl("x", doc = "other")), iteration: Int? = 2) =
        ViewerState().opened(document, highlights, iteration, fromSavedCopy = false).geometryKnown(listOf(meta(1), meta(2, processedUri = null))).fileReady(pageCount = 3)

    @Test
    fun `opening shows the document on its first page, with no box chosen`() {
        val s = opened()
        assertEquals(ViewerLoad.Ready, s.load)
        assertEquals(1, s.page)
        assertNull(s.selectedBox)
        assertEquals(listOf("a"), s.boxes.map { it.id })
    }

    @Test
    fun `pages are held to the document's length`() {
        var s = opened()
        assertFalse(s.canGoPrevious)
        s = s.nextPage().nextPage()
        assertEquals(3, s.page)
        assertFalse(s.canGoNext)
        assertEquals(3, s.nextPage().page)
        assertEquals(1, s.showing(-4).page)
        assertEquals(3, s.showing(99).page)
    }

    @Test
    fun `a page asked for before the length is known is kept, then held to it once it is`() {
        val early = ViewerState().opened(document, emptyList(), 1, false).showing(5)
        assertEquals(5, early.page)
        assertEquals(2, early.fileReady(pageCount = 2).page)
    }

    @Test
    fun `focusing on an evidence row opens its page with its box chosen`() {
        val s = opened().focusedOn(page = 2, highlightId = "b")
        assertEquals(2, s.page)
        assertEquals("b", s.selectedBox?.id)
    }

    @Test
    fun `the page of the box is used when the row names none`() {
        val s = opened().focusedOn(page = null, highlightId = "b")
        assertEquals(2, s.page)
        assertEquals("b", s.selectedBoxId)
    }

    @Test
    fun `opening on a box asks for it to be brought into view once`() {
        val s = opened().focusedOn(page = 1, highlightId = "a")
        assertTrue(s.focusRequested)
        assertFalse(s.focusHandled().focusRequested)
        assertFalse("no box, nothing to bring into view", opened().focusedOn(page = 2, highlightId = null).focusRequested)
    }

    @Test
    fun `turning the page before it happened cancels the request`() {
        assertFalse(opened().focusedOn(1, "a").nextPage().focusRequested)
    }

    @Test
    fun `an evidence row without a box opens its page and chooses nothing`() {
        val s = opened().focusedOn(page = 3, highlightId = null)
        assertEquals(3, s.page)
        assertNull(s.selectedBoxId)
    }

    @Test
    fun `a box of another document cannot be chosen`() {
        assertNull(opened().focusedOn(page = 1, highlightId = "x").selectedBoxId)
    }

    @Test
    fun `changing page drops a chosen box that is not on the new page`() {
        val s = opened().focusedOn(1, "a")
        assertEquals("a", s.selectedBoxId)
        assertNull(s.nextPage().selectedBoxId)
        assertEquals("a", s.showing(1).selectedBoxId)
    }

    @Test
    fun `only a box on the page can be chosen`() {
        val s = opened()
        assertEquals("a", s.selectBox("a").selectedBoxId)
        assertNull(s.selectBox("b").selectedBoxId)
        assertNull(s.selectBox("a").selectBox(null).selectedBoxId)
    }

    @Test
    fun `boxes wait for the page geometry, and are hidden, with a reason, when it could not be learnt`() {
        val loading = ViewerState().opened(document, listOf(hl("a")), 1, false).fileReady(2)
        assertTrue(loading.boxes.isEmpty())
        assertFalse(loading.boxesHidden)

        val failed = loading.geometryUnavailable()
        assertTrue(failed.boxes.isEmpty())
        assertTrue(failed.boxesHidden)
        assertEquals("the evidence is still listed", listOf("a"), failed.evidenceOnPage.map { it.id })
    }

    @Test
    fun `nothing is hidden on a page that has no evidence`() {
        val failed = ViewerState().opened(document, listOf(hl("a", page = 2)), 1, false).fileReady(2).geometryUnavailable()
        assertFalse(failed.boxesHidden)
    }

    @Test
    fun `a document with no geometry record is shown with its boxes where the model put them`() {
        val s = ViewerState().opened(document, listOf(hl("a")), 1, false).geometryKnown(emptyList()).fileReady(1)
        assertEquals(NormRect(200.0, 100.0, 400.0, 160.0), s.boxes.single().rect)
    }

    @Test
    fun `the boxes of a turned page are carried back onto the original`() {
        val s = ViewerState().opened(document, listOf(hl("a")), 1, false).geometryKnown(listOf(meta(1, rotation = 90))).fileReady(1)
        assertEquals(NormRect(100.0, 600.0, 160.0, 800.0), s.boxes.single().rect)
    }

    @Test
    fun `what the model saw is offered for a page whose image was kept and shows the boxes as cited`() {
        var s = opened()
        assertTrue(s.canShowModelView)
        s = s.modelViewShown(true)
        assertEquals(ViewMode.MODEL_VIEW, s.mode)
        assertEquals(NormRect(200.0, 100.0, 400.0, 160.0), s.boxes.single().rect)
        assertEquals(ViewMode.ORIGINAL, s.modelViewShown(false).mode)
    }

    @Test
    fun `what the model saw is not offered without a kept image or without an assessment`() {
        val noImage = opened().showing(2)
        assertFalse(noImage.canShowModelView)
        assertEquals(ViewMode.ORIGINAL, noImage.modelViewShown(true).mode)

        assertFalse(opened(iteration = null).canShowModelView)
    }

    @Test
    fun `turning to a page with no image leaves what the model saw`() {
        val s = opened().modelViewShown(true).nextPage()
        assertEquals(2, s.page)
        assertEquals(ViewMode.ORIGINAL, s.mode)
    }

    @Test
    fun `the straightened note follows the page`() {
        val s = ViewerState().opened(document, emptyList(), 1, false).geometryKnown(listOf(meta(1, deskew = true, deg = 4.0), meta(2))).fileReady(2)
        assertEquals("straightened 4.0°", s.deskewNote)
        assertNull(s.nextPage().deskewNote)
    }

    @Test
    fun `a failed load is told apart from a missing document`() {
        assertEquals(ViewerLoad.NotFound, ViewerState().loadFailed(true, "x").load)
        assertEquals(ViewerLoad.Failed("Can't reach the server"), ViewerState().loadFailed(false, "Can't reach the server").load)
    }

    @Test
    fun `a failed file is kept as a message`() {
        assertEquals(FetchState.Failed("no"), ViewerState().fileFailed("no").file)
    }
}
