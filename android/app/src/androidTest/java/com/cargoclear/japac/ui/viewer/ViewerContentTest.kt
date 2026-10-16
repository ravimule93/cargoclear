package com.cargoclear.japac.ui.viewer

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.test.doubleClick
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.runtime.mutableStateOf
import com.cargoclear.japac.Assets
import com.cargoclear.japac.core.model.BBox
import com.cargoclear.japac.core.model.DocumentRecord
import com.cargoclear.japac.core.model.FetchState
import com.cargoclear.japac.core.model.Highlight
import com.cargoclear.japac.core.model.Severity
import com.cargoclear.japac.core.model.TransformMetadata
import com.cargoclear.japac.core.model.ViewerState
import com.cargoclear.japac.ui.theme.CargoClearTheme
import java.io.File
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** The viewer screen on a real PDF: what it offers, what it says when things go wrong, and that boxes really are drawn on the page. */
class ViewerContentTest {
    @get:Rule
    val compose = createComposeRule()

    private val opened = mutableListOf<PdfPages>()
    private var retried = 0
    private var previous = 0
    private var next = 0
    private var selectedBox: String? = "unset"
    private var modelView: Boolean? = null
    private var focusHandled = 0
    private var wentBack = false

    @After
    fun tearDown() = opened.forEach { it.close() }

    private val document = DocumentRecord("d1", "b1", "scan.pdf", "COMMERCIAL_INVOICE", "gs://x", "sha", 1000, "2026-01-01T00:00:00Z", transformMetaUri = "gs://x/t.json")

    // the marker block of the alignment pages (x 0.84-0.93, y 0.30-0.36 of an upright page)
    private val marker = Highlight("H-1", "d1", 1, BBox(1, 300.0, 840.0, 360.0, 930.0), Severity.MATERIAL, "Certificate chemistry contradicts the declared HS code", value = "TH-77121: Cr 0.35%")
    private val second = Highlight("H-2", "d1", 1, BBox(1, 100.0, 100.0, 140.0, 400.0), Severity.WARN, "Weights differ by 3 %", value = "14,280.50 KGS")

    private fun meta(processedUri: String? = "gs://p/page-001.png", deskew: Boolean = false, deg: Double = 0.0) =
        TransformMetadata(page = 1, sourcePage = 1, processedUri = processedUri, deskewApplied = deskew, deskewDeg = deg)

    private fun state(
        highlights: List<Highlight> = listOf(marker, second),
        transforms: List<TransformMetadata>? = listOf(meta()),
        iteration: Int? = 2,
        pageCount: Int = 1,
    ): ViewerState {
        val base = ViewerState().opened(document, highlights, iteration, fromSavedCopy = false)
        val withGeometry = if (transforms == null) base.geometryUnavailable() else base.geometryKnown(transforms)
        return withGeometry.fileReady(pageCount)
    }

    private fun pages(asset: String = "viewer/clean.pdf"): PdfPages = runBlocking { PdfRendererPages.open(Assets.file(asset)) }.also { opened += it }

    /** The state on screen; a test can change it after showing it, as the view model does. */
    private val current = mutableStateOf(ViewerState())

    private fun show(state: ViewerState, pages: PdfPages? = pages(), modelImage: File? = null) {
        current.value = state
        compose.setContent {
            CargoClearTheme {
                ViewerContent(
                    documentId = "d1",
                    state = current.value,
                    pages = pages,
                    modelImage = modelImage,
                    onBack = { wentBack = true },
                    onRetry = { retried++ },
                    onPrevious = { previous++ },
                    onNext = { next++ },
                    onSelectBox = { selectedBox = it },
                    onShowModelView = { modelView = it },
                    onFocusHandled = { focusHandled++ },
                )
            }
        }
    }

    // ---- what it offers

    @Test
    fun the_file_name_the_page_and_the_controls_are_there_and_a_single_page_cannot_be_turned() {
        show(state())

        compose.onNodeWithText("scan.pdf").assertIsDisplayed()
        compose.onNodeWithText("COMMERCIAL INVOICE").assertIsDisplayed()
        compose.onNodeWithText("Page 1 of 1").assertIsDisplayed()
        compose.onNodeWithText("Previous").assertIsNotEnabled()
        compose.onNodeWithText("Next").assertIsNotEnabled()
        compose.onNodeWithContentDescription("Zoom in").assertIsEnabled()
        compose.onNodeWithContentDescription("Zoom out").assertIsEnabled()
        compose.onNodeWithText("Fit").assertIsEnabled()
    }

    @Test
    fun pages_are_turned_with_the_buttons_when_there_are_more() {
        show(state(pageCount = 3))
        compose.onNodeWithText("Page 1 of 3").assertIsDisplayed()
        compose.onNodeWithText("Previous").assertIsNotEnabled()
        compose.onNodeWithText("Next").assertIsEnabled().performClick()
        assertEquals(1, next)
    }

    @Test
    fun the_page_tells_a_screen_reader_how_many_highlights_it_carries() {
        show(state())
        compose.onNode(hasContentDescription("Page 1 of 1: scan.pdf. 2 evidence highlights on this page", substring = true)).assertExists()
    }

    @Test
    fun a_straightened_page_says_so_and_why_boxes_still_fit() {
        show(state(transforms = listOf(meta(deskew = true, deg = 5.0))))
        compose.onNodeWithText("straightened 5.0°").assertIsDisplayed()
        compose.onNodeWithText("The page was straightened before the model read it; evidence boxes are mapped back onto this original page.").assertIsDisplayed()
    }

    @Test
    fun an_unstraightened_page_has_no_such_note() {
        show(state())
        compose.onNode(hasText("straightened", substring = true)).assertDoesNotExist()
    }

    // ---- the evidence list

    @Test
    fun the_evidence_of_the_page_is_a_list_whose_rows_choose_a_box() {
        show(state())

        compose.onNodeWithText("Evidence (2)").performClick()
        compose.onNodeWithText("Evidence on this page (2)").assertIsDisplayed()
        compose.onNodeWithText("TH-77121: Cr 0.35%").assertIsDisplayed()
        compose.onNodeWithText("14,280.50 KGS").assertIsDisplayed()
        compose.onNodeWithText("Weights differ by 3 %").assertIsDisplayed()

        compose.onNodeWithText("14,280.50 KGS").performClick()
        assertEquals("H-2", selectedBox)
    }

    @Test
    fun a_page_with_no_evidence_says_so() {
        show(state(highlights = emptyList()))
        compose.onNodeWithText("Evidence (0)").performClick()
        compose.onNodeWithText("No evidence is cited on this page.").assertIsDisplayed()
    }

    @Test
    fun a_chosen_box_is_described_with_its_severity_its_value_and_the_finding() {
        show(state().selectBox("H-1"))
        compose.onNodeWithText("MATERIAL").assertIsDisplayed()
        compose.onNodeWithText("CITED EVIDENCE").assertIsDisplayed()
        compose.onNodeWithText("TH-77121: Cr 0.35%").assertIsDisplayed()
        compose.onNodeWithText("Certificate chemistry contradicts the declared HS code").assertIsDisplayed()
    }

    // ---- what is not drawn, and why

    @Test
    fun without_the_pages_geometry_no_box_is_drawn_and_the_screen_says_why_and_offers_a_retry() {
        show(state(transforms = null))
        compose.onNode(hasText("Evidence boxes are hidden", substring = true)).assertIsDisplayed()
        compose.onNodeWithText("Retry").performClick()
        assertEquals(1, retried)
        // the evidence is still listed
        compose.onNodeWithText("Evidence (2)").assertIsDisplayed()
    }

    @Test
    fun a_page_with_no_evidence_has_no_such_notice_even_without_geometry() {
        show(state(highlights = emptyList(), transforms = null))
        compose.onNode(hasText("Evidence boxes are hidden", substring = true)).assertDoesNotExist()
    }

    // ---- what the model saw

    @Test
    fun what_the_model_saw_is_offered_for_a_page_whose_image_was_kept() {
        show(state())
        compose.onNodeWithText("What the model saw").assertIsDisplayed().performClick()
        assertEquals(true, modelView)
    }

    @Test
    fun what_the_model_saw_is_not_offered_when_the_image_was_not_kept_or_there_is_no_assessment() {
        show(state(transforms = listOf(meta(processedUri = null))))
        compose.onNodeWithText("What the model saw").assertDoesNotExist()
    }

    @Test
    fun looking_at_what_the_model_saw_explains_what_the_boxes_are() {
        show(state().modelViewShown(true).modelImage(FetchState.Loading))
        compose.onNode(hasText("The page image exactly as the extraction saw it", substring = true)).assertIsDisplayed()
        compose.onNodeWithText("Loading the page image…").assertIsDisplayed()
    }

    @Test
    fun a_page_image_that_cannot_be_loaded_says_so_with_a_retry() {
        show(state().modelViewShown(true).modelImage(FetchState.Failed("The page image was not kept for this assessment.")))
        compose.onNodeWithText("Could not load the page image the model saw: The page image was not kept for this assessment.").assertIsDisplayed()
        compose.onNodeWithText("Retry").performClick()
        assertEquals(1, retried)
    }

    // ---- loading and failing

    @Test
    fun a_document_still_being_fetched_says_so() {
        show(state().copy(file = FetchState.Loading), pages = null)
        compose.onNodeWithText("Loading document...").assertIsDisplayed()
        compose.onNodeWithText("Page - of -").assertIsDisplayed()
        compose.onNodeWithText("Next").assertIsNotEnabled()
    }

    @Test
    fun a_document_that_cannot_be_shown_names_the_file_and_the_reason() {
        show(state().fileFailed("Can't reach the server. Check your connection and try again."), pages = null)
        compose.onNodeWithText("Could not display scan.pdf: Can't reach the server. Check your connection and try again.").assertIsDisplayed()
        compose.onNodeWithText("Retry").performClick()
        assertEquals(1, retried)
    }

    @Test
    fun a_document_the_bundle_does_not_have_is_not_found() {
        show(ViewerState().loadFailed(notFound = true, message = ""), pages = null)
        compose.onNodeWithText("Document not found").assertIsDisplayed()
        compose.onNodeWithText("This bundle has no document with id d1.").assertIsDisplayed()
    }

    @Test
    fun a_bundle_that_could_not_be_read_says_why_with_a_retry() {
        show(ViewerState().loadFailed(notFound = false, message = "boom"), pages = null)
        compose.onNodeWithText("Could not open the document: boom").assertIsDisplayed()
        compose.onNodeWithText("Retry").performClick()
        assertEquals(1, retried)
    }

    @Test
    fun a_copy_read_from_the_phone_is_marked_as_one() {
        show(ViewerState().opened(document, listOf(marker), 2, fromSavedCopy = true).geometryUnavailable().fileReady(1))
        compose.onNodeWithText("Read from the copy saved on this phone: the server could not be reached.").assertIsDisplayed()
    }

    // ---- the page is really drawn

    private fun pagePixels(): Triple<Int, Int, androidx.compose.ui.graphics.ImageBitmap> {
        val image = compose.onNode(hasContentDescription("Page 1 of 1", substring = true)).captureToImage()
        return Triple(image.width, image.height, image)
    }

    private fun countNear(image: androidx.compose.ui.graphics.ImageBitmap, argb: Int, tolerance: Int): Int {
        val pixels = IntArray(image.width * image.height).also { image.readPixels(it) }
        return pixels.count { p ->
            kotlin.math.abs((p shr 16 and 0xFF) - (argb shr 16 and 0xFF)) <= tolerance &&
                kotlin.math.abs((p shr 8 and 0xFF) - (argb shr 8 and 0xFF)) <= tolerance &&
                kotlin.math.abs((p and 0xFF) - (argb and 0xFF)) <= tolerance
        }
    }

    @Test
    fun the_page_and_its_boxes_are_painted_on_the_canvas() {
        show(state())
        // the marker block of the page is solid black: wait until the render has arrived
        compose.waitUntil(10_000) { countNear(pagePixels().third, 0xFF000000.toInt(), 8) > 2_000 }
        // the material box is drawn in the error colour of the theme, the warning box in the warning colour
        val tokens = com.cargoclear.japac.ui.theme.LightTokens
        compose.waitUntil(5_000) { countNear(pagePixels().third, tokens.err.bd.toArgb(), 12) > 200 }
        assertTrue(countNear(pagePixels().third, tokens.warn.bd.toArgb(), 12) > 100)
    }

    @Test
    fun a_chosen_box_is_filled_so_it_stands_out_from_the_others() {
        show(state())
        compose.waitUntil(10_000) { countNear(pagePixels().third, 0xFF000000.toInt(), 8) > 2_000 }
        val black = countNear(pagePixels().third, 0xFF000000.toInt(), 8)

        // the material box sits on the solid marker: tinted red, the black under it is no longer black
        current.value = current.value.selectBox("H-1")
        compose.waitUntil(5_000) { countNear(pagePixels().third, 0xFF000000.toInt(), 8) < black - 1_000 }
    }

    @Test
    fun a_box_asked_for_is_brought_into_view_once_it_can_be_placed() {
        show(state().focusedOn(page = 1, highlightId = "H-1"))
        compose.waitUntil(10_000) { focusHandled >= 1 }
        compose.waitForIdle()
        assertEquals(1, focusHandled)
    }

    @Test
    fun a_double_tap_zooms_the_page_in_and_a_second_one_back() {
        show(state())
        compose.waitUntil(10_000) { countNear(pagePixels().third, 0xFF000000.toInt(), 8) > 2_000 }
        val before = countNear(pagePixels().third, 0xFF000000.toInt(), 8)

        compose.onNode(hasContentDescription("Page 1 of 1", substring = true)).performTouchInput { doubleClick(center) }
        compose.waitForIdle()
        compose.waitUntil(5_000) { countNear(pagePixels().third, 0xFF000000.toInt(), 8) != before }
        val zoomed = countNear(pagePixels().third, 0xFF000000.toInt(), 8)
        assertTrue("zoomed in the page shows more black ($zoomed) than fitted ($before) over the same area, or less of the page", zoomed != before)

        compose.onNode(hasContentDescription("Page 1 of 1", substring = true)).performTouchInput { doubleClick(center) }
        compose.waitUntil(5_000) { countNear(pagePixels().third, 0xFF000000.toInt(), 8) == before }
    }

    @Test
    fun the_back_arrow_leaves() {
        show(state())
        compose.onNodeWithContentDescription("Back").performClick()
        assertTrue(wentBack)
    }
}
