package com.cargoclear.japac.ui.viewer

import android.graphics.Bitmap
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cargoclear.japac.Assets
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.BBox
import com.cargoclear.japac.core.model.Bundle
import com.cargoclear.japac.core.model.NormRect
import com.cargoclear.japac.core.model.PageLayout
import com.cargoclear.japac.core.model.TransformMetadataResponse
import com.cargoclear.japac.core.model.ViewTransform
import com.cargoclear.japac.core.model.boxesOnOriginalPage
import com.cargoclear.japac.core.model.buildHighlights
import com.cargoclear.japac.core.model.initialTransform
import com.cargoclear.japac.core.model.mapProcessedBBoxToOriginal
import com.cargoclear.japac.core.model.pageToView
import com.cargoclear.japac.core.model.visiblePart
import com.cargoclear.japac.core.model.zoomToRect
import java.io.File
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The risky part of the viewer, on a device and with real renderings: Android's PdfRenderer draws the pages, and the boxes the backend gives
 * (carried back through the transform the backend recorded) have to land on what is printed. The scans come from the backend's own
 * preprocessing (android/tools/make_alignment_fixtures.py); the demo cases' PDFs are drawn at their evidence boxes.
 */
@RunWith(AndroidJUnit4::class)
class PdfPagesTest {
    private val open = mutableListOf<PdfPages>()
    private val lenient = Json { ignoreUnknownKeys = true }

    @After
    fun tearDown() = open.forEach { it.close() }

    private fun pages(asset: String): PdfPages = runBlocking { PdfRendererPages.open(Assets.file(asset)) }.also { open += it }

    private fun record(case: String): JsonObject = Json.parseToJsonElement(Assets.text("viewer/$case.json")).jsonObject

    private fun rect(o: JsonObject) = NormRect(
        o.getValue("xmin").jsonPrimitive.content.toDouble(), o.getValue("ymin").jsonPrimitive.content.toDouble(),
        o.getValue("xmax").jsonPrimitive.content.toDouble(), o.getValue("ymax").jsonPrimitive.content.toDouble(),
    )

    private val cases = listOf("clean", "skew5", "skew-8", "sideways90-skew4", "sideways270-skew4", "sideways180", "pdf-rotate90")

    // ---- the page as displayed

    @Test
    fun a_page_is_the_shape_a_viewer_shows_it_including_its_own_rotate() {
        for (case in cases) {
            val shown = record(case).getValue("displayed_pixels_at_72dpi").jsonArray.map { it.jsonPrimitive.content.toInt() }
            val doc = pages("viewer/$case.pdf")
            assertEquals(1, doc.pageCount)
            val aspect = runBlocking { doc.aspect(1) }
            assertEquals("$case: height over width", shown[1].toDouble() / shown[0], aspect.toDouble(), 0.01)
        }
    }

    @Test
    fun the_marker_is_where_the_backend_found_it_on_the_page_as_this_renderer_draws_it() {
        for (case in cases) {
            val doc = pages("viewer/$case.pdf")
            val bitmap = runBlocking { doc.renderPage(1, 900) }
            val seen = Ink.largestBlob(bitmap).rect
            val expected = rect(record(case).getValue("original_marker").jsonObject)
            val agreement = Ink.iou(seen, expected)
            assertTrue("$case: PdfRenderer shows the marker at $seen, the backend measured $expected (IoU $agreement)", agreement >= 0.85)
        }
    }

    // ---- many requests at once

    @Test
    fun windows_asked_for_and_then_given_up_on_are_never_rendered() {
        val doc = pages("viewer/clean.pdf") as PdfRendererPages
        runBlocking { doc.renderPage(1, 600) } // warm up: the page size is known
        val before = doc.renders.get()

        runBlocking {
            // the person pinches on: twenty windows are asked for in a row, and each is given up on as the next is asked for
            val asked = (1..20).map { i ->
                async(start = kotlinx.coroutines.CoroutineStart.UNDISPATCHED) { runCatching { doc.renderRegion(1, 3000 + i, NormRect(0.0, 0.0, 400.0, 400.0)) } }
            }
            asked.dropLast(1).forEach { it.cancel() }
            asked.last().await().getOrThrow()
            asked.forEach { it.join() }
        }

        val ran = doc.renders.get() - before
        assertTrue("at most the one in progress and the last were rendered, not all twenty ($ran)", ran <= 3)
    }

    // ---- the boxes

    private fun mapped(case: String): NormRect {
        val record = record(case)
        val meta = lenient.decodeFromString<TransformMetadataResponse>(record.getValue("transform_metadata").toString()).transformMeta.single()
        val cited = rect(record.getValue("processed_marker").jsonObject)
        val box = mapProcessedBBoxToOriginal(BBox(1, cited.ymin, cited.xmin, cited.ymax, cited.xmax), meta)
        return NormRect(box.xmin, box.ymin, box.xmax, box.ymax)
    }

    @Test
    fun a_box_cited_on_the_processed_page_outlines_the_marker_on_the_rendered_original_for_every_kind_of_scan() {
        for (case in cases) {
            val doc = pages("viewer/$case.pdf")
            val bitmap = runBlocking { doc.renderPage(1, 900) }
            val blob = Ink.largestBlob(bitmap)
            val box = mapped(case)

            val agreement = Ink.iou(box, blob.rect)
            assertTrue("$case: the box $box and the ink ${blob.rect} (IoU $agreement)", agreement >= 0.85)
            // and it is the ink of the marker that is inside, not just the corners that touch: the box is as full of ink as the marker's own bounding box is
            // (a tilted marker leaves paper in the corners of that box, so the comparison is with it, not with 100 %)
            val inkInBox = Ink.inkFraction(bitmap, box)
            val inkInBounds = Ink.inkFraction(bitmap, blob.rect)
            assertTrue("$case: ${(inkInBox * 100).toInt()} % of the box is ink, ${(inkInBounds * 100).toInt()} % of the marker's own bounds", inkInBox >= 0.9 * inkInBounds)
        }
    }

    @Test
    fun the_viewers_own_layout_puts_the_overlay_where_the_ink_is_at_fit_and_zoomed() {
        for (case in cases) {
            val doc = pages("viewer/$case.pdf")
            val aspect = runBlocking { doc.aspect(1) }
            val layout = PageLayout(viewWidth = 900f, viewHeight = 1400f, pageAspect = aspect)
            val box = mapped(case)

            // fit: the bitmap IS the viewport width, so the overlay rectangle can be read straight off the pixels
            val fit = initialTransform(layout)
            val whole = runBlocking { doc.renderPage(1, 900) }
            val blob = Ink.largestBlob(whole)
            val overlay = fit.pageToView(layout, box)
            val pageTop = fit.pageToView(layout, NormRect(0.0, 0.0, 1000.0, 1000.0))[1]
            val overlayAsPage = NormRect(
                overlay[0] / 900.0 * 1000, (overlay[1] - pageTop) / (900f * aspect) * 1000.0,
                overlay[2] / 900.0 * 1000, (overlay[3] - pageTop) / (900f * aspect) * 1000.0,
            )
            assertTrue("$case at fit: overlay $overlayAsPage vs ink ${blob.rect}", Ink.iou(overlayAsPage, blob.rect) >= 0.85)

            // focused on the box, the way tapping its evidence row does: a sharp window rendered the way the screen does it must hold the same ink at the overlay's place
            val zoomed = zoomToRect(layout, box, maxZoom = 3f)
            val visible = zoomed.visiblePart(layout)
            val pageWidthPx = (layout.fitWidth * zoomed.zoom).toInt()
            val window = runBlocking { doc.renderRegion(1, pageWidthPx, visible) }
            val boxInWindow = NormRect(
                (box.xmin - visible.xmin) / visible.width * 1000, (box.ymin - visible.ymin) / visible.height * 1000,
                (box.xmax - visible.xmin) / visible.width * 1000, (box.ymax - visible.ymin) / visible.height * 1000,
            )
            val windowBlob = Ink.largestBlob(window)
            assertTrue("$case focused (zoom ${zoomed.zoom}): box $boxInWindow vs ink ${windowBlob.rect}", Ink.iou(boxInWindow, windowBlob.rect) >= 0.8)
        }
    }

    // ---- the sharp window

    private fun meanAbsDifference(whole: Bitmap, window: Bitmap, region: NormRect): Double {
        val x0 = region.xmin / 1000 * whole.width
        val y0 = region.ymin / 1000 * whole.height
        var sum = 0L
        var n = 0
        for (y in 0 until window.height step 2) for (x in 0 until window.width step 2) {
            val a = whole.getPixel(minOf((x0 + x).toInt(), whole.width - 1), minOf((y0 + y).toInt(), whole.height - 1)) and 0xFF
            sum += kotlin.math.abs(a - (window.getPixel(x, y) and 0xFF))
            n++
        }
        return sum.toDouble() / n
    }

    @Test
    fun a_window_is_the_same_picture_as_that_part_of_the_whole_page() {
        val doc = pages("viewer/skew5.pdf")
        val whole = runBlocking { doc.renderPage(1, 1200) }
        // a region whose top left falls on a whole pixel (x 600, y 0): the two renderings should agree to the pixel
        val aligned = NormRect(500.0, 0.0, 1000.0, 400.0)
        val window = runBlocking { doc.renderRegion(1, 1200, aligned) }
        assertEquals((aligned.width / 1000 * whole.width), window.width.toDouble(), 2.0)
        val exact = meanAbsDifference(whole, window, aligned)
        assertTrue("a window and the page differ by $exact grey levels on average", exact < 4.0)

        // one that falls between pixels differs a little along every edge, but is still the same picture and not a shifted one
        val between = NormRect(500.0, 200.0, 1000.0, 600.0)
        val shifted = runBlocking { doc.renderRegion(1, 1200, between) }
        val fractional = meanAbsDifference(whole, shifted, between)
        val wrong = meanAbsDifference(whole, shifted, NormRect(between.xmin, between.ymin + 40, between.xmax, between.ymax + 40))
        assertTrue("fractional offset $fractional, wrong place $wrong", fractional < 15.0 && wrong > 2 * fractional)
    }

    @Test
    fun however_far_in_a_window_never_exceeds_the_pixel_budget() {
        val doc = pages("viewer/clean.pdf")
        val whole = runBlocking { doc.renderRegion(1, 30_000, NormRect(0.0, 0.0, 1000.0, 1000.0)) } // a page 30,000 pixels wide, asked for whole
        assertTrue("${whole.width}x${whole.height}", whole.width.toLong() * whole.height <= PdfRendererPages.MAX_PIXELS)
        assertEquals(Bitmap.Config.ARGB_8888, whole.config)
    }

    @Test
    fun a_page_that_is_not_in_the_document_is_refused_and_a_closed_document_cannot_be_drawn() {
        val doc = pages("viewer/clean.pdf")
        try {
            runBlocking { doc.renderPage(2, 300) }
            fail("page 2 of 1")
        } catch (_: IllegalArgumentException) {
        }
        doc.close()
        try {
            runBlocking { doc.renderPage(1, 300) }
            fail("closed")
        } catch (_: IllegalStateException) {
        }
    }

    @Test
    fun a_file_that_is_not_a_pdf_is_unreadable_rather_than_a_crash() {
        val junk = File(Assets.file("viewer/clean.json").parentFile, "junk.pdf").apply { writeText("this is not a pdf at all") }
        try {
            runBlocking { PdfRendererPages.open(junk) }
            fail("not a pdf")
        } catch (e: PdfUnreadableException) {
            assertTrue(e.message.orEmpty().isNotEmpty())
        }
    }

    // ---- the demo cases: their sample PDFs are drawn at the boxes of their evidence

    private fun documentFiles(bundleAsset: String, folder: String): Map<String, File> =
        lenient.decodeFromString<Bundle>(Assets.text(bundleAsset)).documents.associate { it.documentId to Assets.file("$folder/${it.filename}") }

    private fun everyEvidenceBoxIsPrintedOn(bundleAsset: String, assessmentAsset: String, folder: String) {
        val files = documentFiles(bundleAsset, folder)
        val assessment = lenient.decodeFromString<AssessmentIteration>(Assets.text(assessmentAsset))
        val highlights = buildHighlights(assessment)
        assertTrue("there is evidence to check", highlights.size >= 20)
        val rendered = HashMap<String, Bitmap>()
        for (h in highlights) {
            val file = files.getValue(h.documentId)
            val bitmap = rendered.getOrPut(h.documentId) { runBlocking { pages("$folder/${file.name}").renderPage(1, 1000) } }
            // demo documents were never transformed: the box is exactly where the model put it
            val box = boxesOnOriginalPage(listOf(h), h.documentId, h.page, emptyList()).single().rect
            val ink = Ink.inkFraction(bitmap, box)
            assertTrue("${file.name}: the box of ${h.value} (${h.id}) at $box holds ${(ink * 100).toInt()} % ink", ink > 0.01)
        }
    }

    @Test
    fun every_evidence_box_of_case_c_lands_on_something_printed() = everyEvidenceBoxIsPrintedOn("case_c_bundle_analyzed.json", "case_c_assessment_missing_evidence.json", "case_c")

    @Test
    fun every_evidence_box_of_case_d_lands_on_something_printed() = everyEvidenceBoxIsPrintedOn("case_d_bundle_analyzed.json", "case_d_assessment_contradiction.json", "case_d")

    @Test
    fun a_box_moved_off_its_value_no_longer_lands_on_ink_so_the_check_above_can_fail() {
        val files = documentFiles("case_d_bundle_analyzed.json", "case_d")
        val assessment = lenient.decodeFromString<AssessmentIteration>(Assets.text("case_d_assessment_contradiction.json"))
        val cert = assessment.checks.first { it.checkId == "M-001" }.evidence.orEmpty().first { it.bbox != null && it.doc != null }
        val bitmap = runBlocking { pages("case_d/${files.getValue(cert.doc!!).name}").renderPage(1, 1000) }
        val box = cert.bbox!!
        val onValue = Ink.inkFraction(bitmap, NormRect(box.xmin, box.ymin, box.xmax, box.ymax))
        val shifted = Ink.inkFraction(bitmap, NormRect(box.xmin, box.ymin - 120, box.xmax, box.ymax - 120)) // a margin above the table: blank
        assertTrue("on the value $onValue, shifted $shifted", onValue > 0.01 && shifted < onValue / 3)
    }
}
