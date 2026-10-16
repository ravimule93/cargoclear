package com.cargoclear.japac.ui.viewer

import android.graphics.Bitmap
import androidx.lifecycle.SavedStateHandle
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.BBox
import com.cargoclear.japac.core.model.Bundle
import com.cargoclear.japac.core.model.CheckResult
import com.cargoclear.japac.core.model.DocumentRecord
import com.cargoclear.japac.core.model.ErrorEnvelope
import com.cargoclear.japac.core.model.EvidenceRef
import com.cargoclear.japac.core.model.FILE_CACHE_FAILED_MESSAGE
import com.cargoclear.japac.core.model.FetchState
import com.cargoclear.japac.core.model.GeometryState
import com.cargoclear.japac.core.model.NormRect
import com.cargoclear.japac.core.model.Severity
import com.cargoclear.japac.core.model.TransformMetadata
import com.cargoclear.japac.core.model.TransformMetadataResponse
import com.cargoclear.japac.core.model.ViewMode
import com.cargoclear.japac.core.model.ViewerLoad
import com.cargoclear.japac.ui.FakeBundleRepository
import com.cargoclear.japac.ui.FakeDocumentFiles
import com.cargoclear.japac.ui.FakeDocuments
import com.cargoclear.japac.ui.FakeRecents
import com.cargoclear.japac.ui.FakeSettings
import com.cargoclear.japac.ui.apiFailure
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ViewerViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val repo = FakeBundleRepository()
    private val recents = FakeRecents()
    private val documents = FakeDocuments()
    private val files = FakeDocumentFiles()
    private val opened = mutableListOf<File>()
    private var openError: PdfUnreadableException? = null

    private val fakePages = object : PdfPages {
        override val pageCount: Int = 3
        override suspend fun aspect(page: Int): Float = 1.4f
        override suspend fun renderPage(page: Int, widthPx: Int): Bitmap = throw UnsupportedOperationException()
        override suspend fun renderRegion(page: Int, pageWidthPx: Int, region: NormRect): Bitmap = throw UnsupportedOperationException()
        override fun close() = Unit
    }

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
        repo.bundle = bundleWith(transformUri = "gs://x/transform.json")
        repo.latest = assessment()
        documents.geometry = TransformMetadataResponse("d1", listOf(meta(1), meta(2, processedUri = null)))
    }

    @After
    fun tearDown() = Dispatchers.resetMain()

    private fun doc(transformUri: String?) =
        DocumentRecord("d1", "bnd-1", "invoice.pdf", "COMMERCIAL_INVOICE", "gs://x", "sha", 1000, "2026-01-01T00:00:00Z", transformMetaUri = transformUri)

    private fun bundleWith(transformUri: String?) = Bundle("bnd-1", null, "SG", "MISSING_EVIDENCE", 2, listOf(doc(transformUri)), "2026-01-01T00:00:00Z")

    private fun meta(page: Int, processedUri: String? = "gs://p/page.png") = TransformMetadata(page = page, sourcePage = page, processedUri = processedUri)

    private fun evidence(field: String, page: Int, value: String) =
        EvidenceRef(doc = "d1", field = field, page = page, bbox = BBox(page, 100.0, 200.0, 160.0, 400.0), rawValue = JsonPrimitive(value))

    private fun assessment() = AssessmentIteration(
        iteration = 2,
        bundleId = "bnd-1",
        status = "MISSING_EVIDENCE",
        checks = listOf(CheckResult("M-001", Severity.MATERIAL, "contradiction", evidence = listOf(evidence("hs", 1, "7304"), evidence("net", 2, "25000")))),
    )

    private fun viewModel(page: Int? = null, highlight: String? = null, settings: FakeSettings = FakeSettings()): ViewerViewModel {
        val args = mutableMapOf<String, Any?>("bundleId" to "bnd-1", "documentId" to "d1")
        page?.let { args["page"] = it }
        highlight?.let { args["highlightId"] = it }
        val opener = PdfOpener { file ->
            opened += file
            openError?.let { throw it }
            fakePages
        }
        return ViewerViewModel(SavedStateHandle(args), repo, recents, documents, files, opener, settings)
    }

    @Test
    fun `opening shows the document with its evidence, its geometry and its pages`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()

        val s = vm.state.value
        assertEquals(ViewerLoad.Ready, s.load)
        assertEquals("invoice.pdf", s.document?.filename)
        assertEquals(2, s.iteration)
        assertTrue(s.geometry is GeometryState.Known)
        assertEquals(FetchState.Ready, s.file)
        assertEquals(3, s.pageCount)
        assertEquals(listOf("bnd-1" to "d1"), files.pdfCalls)
        assertNotNull(vm.pages.value)
        assertEquals(1, s.evidenceOnPage.size)
    }

    @Test
    fun `an evidence row opens on its page with its box chosen and asks for it to be brought into view`() = runTest(dispatcher) {
        val id = "M-001:0:d1:net:1"
        val vm = viewModel(page = 2, highlight = id)
        runCurrent()

        val s = vm.state.value
        assertEquals(2, s.page)
        assertEquals(id, s.selectedBox?.id)
        assertEquals("25000", s.selectedBox?.value)
        assertTrue(s.focusRequested)
        vm.focusHandled()
        assertFalse(vm.state.value.focusRequested)
    }

    @Test
    fun `a document with no record of its preparation is not asked about, its boxes are exact`() = runTest(dispatcher) {
        repo.bundle = bundleWith(transformUri = null)
        val vm = viewModel()
        runCurrent()
        assertEquals(0, documents.geometryCalls)
        assertEquals(GeometryState.Known(emptyList()), vm.state.value.geometry)
        assertEquals(1, vm.state.value.boxes.size)
    }

    @Test
    fun `the server's 404 for the geometry means it was not transformed`() = runTest(dispatcher) {
        documents.geometry = null
        val vm = viewModel()
        runCurrent()
        assertEquals(GeometryState.Known(emptyList()), vm.state.value.geometry)
    }

    @Test
    fun `when the geometry cannot be fetched no box is drawn and the screen says so`() = runTest(dispatcher) {
        documents.geometryError = apiFailure(ApiException.Kind.NETWORK, "Can't reach the server")
        val vm = viewModel()
        runCurrent()

        val s = vm.state.value
        assertEquals(GeometryState.Unavailable, s.geometry)
        assertTrue(s.boxes.isEmpty())
        assertTrue(s.boxesHidden)
        assertEquals("the document itself still shows", FetchState.Ready, s.file)
    }

    @Test
    fun `a bundle with no assessment yet has a document and no boxes`() = runTest(dispatcher) {
        repo.latest = null
        val vm = viewModel()
        runCurrent()
        assertTrue(vm.state.value.boxes.isEmpty())
        assertNull(vm.state.value.iteration)
        assertFalse(vm.state.value.canShowModelView)
    }

    @Test
    fun `a document the bundle does not have is not found`() = runTest(dispatcher) {
        repo.bundle = bundleWith(null).copy(documents = emptyList())
        val vm = viewModel()
        runCurrent()
        assertEquals(ViewerLoad.NotFound, vm.state.value.load)
        assertTrue(files.pdfCalls.isEmpty())
    }

    @Test
    fun `an unknown bundle is not found, another failure is shown`() = runTest(dispatcher) {
        repo.bundleError = ApiException(ErrorEnvelope("NOT_FOUND", "no"), ApiException.Kind.HTTP, 404)
        assertEquals(ViewerLoad.NotFound, viewModel().also { runCurrent() }.state.value.load)

        repo.bundleError = ApiException(ErrorEnvelope("INTERNAL_ERROR", "boom"), ApiException.Kind.HTTP, 500)
        assertEquals(ViewerLoad.Failed("boom"), viewModel().also { runCurrent() }.state.value.load)
    }

    @Test
    fun `without a connection the document opens from the saved copy and its geometry is unavailable`() = runTest(dispatcher) {
        recents.remember(bundleWith("gs://x/transform.json"), assessment())
        repo.bundleError = apiFailure(ApiException.Kind.NETWORK, "Can't reach the server")
        val vm = viewModel()
        runCurrent()

        val s = vm.state.value
        assertTrue(s.fromSavedCopy)
        assertEquals(ViewerLoad.Ready, s.load)
        assertEquals(GeometryState.Unavailable, s.geometry)
        assertEquals(0, documents.geometryCalls)
        assertEquals(FetchState.Ready, s.file) // a file kept on the phone opens without the server
        assertEquals(1, s.evidenceOnPage.size)
    }

    @Test
    fun `a file that cannot be downloaded is reported and can be tried again`() = runTest(dispatcher) {
        files.pdfError = apiFailure(ApiException.Kind.NETWORK, ApiException.NETWORK_MESSAGE)
        val vm = viewModel()
        runCurrent()
        assertEquals(FetchState.Failed(ApiException.NETWORK_MESSAGE), vm.state.value.file)
        assertNull(vm.pages.value)

        files.pdfError = null
        vm.retry()
        runCurrent()
        assertEquals(FetchState.Ready, vm.state.value.file)
        assertNotNull(vm.pages.value)
    }

    @Test
    fun `a file that is not a readable PDF is reported in words`() = runTest(dispatcher) {
        openError = PdfUnreadableException("The file is not a PDF this phone can read.")
        val vm = viewModel()
        runCurrent()
        assertEquals(FetchState.Failed("The file is not a PDF this phone can read."), vm.state.value.file)
    }

    @Test
    fun `turning pages is held to the document and drops a box left behind`() = runTest(dispatcher) {
        val vm = viewModel(page = 1, highlight = "M-001:0:d1:hs:0")
        runCurrent()
        vm.nextPage()
        assertEquals(2, vm.state.value.page)
        assertNull(vm.state.value.selectedBoxId)
        vm.nextPage()
        vm.nextPage()
        assertEquals(3, vm.state.value.page)
        vm.previousPage()
        assertEquals(2, vm.state.value.page)
        vm.showPage(1)
        assertEquals(1, vm.state.value.page)
    }

    @Test
    fun `tapping a box chooses it, tapping nothing clears it`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()
        vm.selectBox("M-001:0:d1:hs:0")
        assertEquals("M-001:0:d1:hs:0", vm.state.value.selectedBoxId)
        vm.selectBox(null)
        assertNull(vm.state.value.selectedBoxId)
    }

    // ---- what the model saw

    @Test
    fun `what the model saw fetches the page image of the assessment on screen and forgets it when switched off`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()
        assertTrue(vm.state.value.canShowModelView)
        assertTrue("nothing is fetched until asked", files.pageCalls.isEmpty())

        vm.showModelView(true)
        runCurrent()
        assertEquals(ViewMode.MODEL_VIEW, vm.state.value.mode)
        assertEquals(listOf(listOf("bnd-1", "d1", 1, 2)), files.pageCalls)
        assertEquals(FetchState.Ready, vm.state.value.modelImage)
        assertNotNull(vm.modelImage.value)

        vm.showModelView(false)
        runCurrent()
        assertEquals(ViewMode.ORIGINAL, vm.state.value.mode)
        assertNull(vm.modelImage.value)
    }

    @Test
    fun `turning the page while looking at what the model saw fetches that page's image, or leaves it when there is none`() = runTest(dispatcher) {
        documents.geometry = TransformMetadataResponse("d1", listOf(meta(1), meta(2), meta(3, processedUri = null)))
        val vm = viewModel()
        runCurrent()
        vm.showModelView(true)
        runCurrent()
        vm.nextPage()
        runCurrent()
        assertEquals(2, files.pageCalls.last()[2])
        assertEquals(ViewMode.MODEL_VIEW, vm.state.value.mode)

        vm.nextPage() // page 3 has no kept image
        runCurrent()
        assertEquals(ViewMode.ORIGINAL, vm.state.value.mode)
        assertNull(vm.modelImage.value)
    }

    @Test
    fun `a page image the server did not keep is explained`() = runTest(dispatcher) {
        files.pageError = ApiException(ErrorEnvelope("NOT_FOUND", "Processed page not found"), ApiException.Kind.HTTP, 404)
        val vm = viewModel()
        runCurrent()
        vm.showModelView(true)
        runCurrent()
        assertEquals(FetchState.Failed("The page image was not kept for this assessment."), vm.state.value.modelImage)
    }

    @Test
    fun `a document the cache cannot keep says so instead of ending the app`() = runTest(dispatcher) {
        files.pdfError = java.io.IOException("could not move the download into place")
        val vm = viewModel()
        runCurrent()
        assertEquals(FetchState.Failed(FILE_CACHE_FAILED_MESSAGE), vm.state.value.file)
    }

    @Test
    fun `an id the cache will not make a file name says so too`() = runTest(dispatcher) {
        files.pdfError = IllegalArgumentException("not a plain id: a/b")
        val vm = viewModel()
        runCurrent()
        assertEquals(FetchState.Failed(FILE_CACHE_FAILED_MESSAGE), vm.state.value.file)
    }

    @Test
    fun `a page image the cache cannot keep says so`() = runTest(dispatcher) {
        files.pageError = java.io.IOException("disk full")
        val vm = viewModel()
        runCurrent()
        vm.showModelView(true)
        runCurrent()
        assertEquals(FetchState.Failed(FILE_CACHE_FAILED_MESSAGE), vm.state.value.modelImage)
    }

    // ---- privacy

    @Test
    fun `screenshots are blocked unless the person turned that off`() = runTest(dispatcher) {
        val on = viewModel(settings = FakeSettings(secure = true))
        val off = viewModel(settings = FakeSettings(secure = false))
        runCurrent()
        assertTrue(on.secure.value)
        assertFalse(off.secure.value)
    }
}
