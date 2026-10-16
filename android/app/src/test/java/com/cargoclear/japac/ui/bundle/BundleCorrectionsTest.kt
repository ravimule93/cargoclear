package com.cargoclear.japac.ui.bundle

import androidx.lifecycle.SavedStateHandle
import com.cargoclear.japac.core.data.StreamEvent
import com.cargoclear.japac.core.data.UploadBatchRunner
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.CorrectionKind
import com.cargoclear.japac.core.model.CorrectionRecord
import com.cargoclear.japac.core.model.CorrectionRequest
import com.cargoclear.japac.core.model.CorrectionsResponse
import com.cargoclear.japac.core.model.correctionEditorFromSavedState
import com.cargoclear.japac.ui.FakeBundleRepository
import com.cargoclear.japac.notify.RunTracker
import com.cargoclear.japac.ui.FakeCorrections
import com.cargoclear.japac.ui.FakeFileImporter
import com.cargoclear.japac.ui.FakeDocuments
import com.cargoclear.japac.ui.FakeMeta
import com.cargoclear.japac.ui.FakeRecents
import com.cargoclear.japac.ui.FakeUploadScheduler
import com.cargoclear.japac.ui.apiFailure
import com.cargoclear.japac.ui.assessment
import com.cargoclear.japac.ui.bundle
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Corrections on the bundle screen: what is fetched and when, the editor, undo, and the rules about overlapping requests. */
@OptIn(ExperimentalCoroutinesApi::class)
class BundleCorrectionsTest {
    private val dispatcher = StandardTestDispatcher()
    private val repo = FakeBundleRepository()
    private val corrections = FakeCorrections()
    private val documents = FakeDocuments()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
        repo.bundle = bundle(1, "MATERIAL_CONTRADICTION", "d1")
        repo.latest = assessment(1, "MATERIAL_CONTRADICTION")
        repo.iterations = listOf(assessment(1, "MATERIAL_CONTRADICTION"))
        corrections.docs = listOf(
            buildJsonObject {
                put("document_id", "d1")
                put("doc_type", "MILL_TEST_CERTIFICATE")
                put("consignee", buildJsonObject { put("value", "ACME") })
                put("test_results", buildJsonArray { add(buildJsonObject { put("value", "0.35"); put("unit", "%") }) })
            },
        )
    }

    @After
    fun tearDown() = Dispatchers.resetMain()

    private fun viewModel() = BundleViewModel(
        SavedStateHandle(mapOf("bundleId" to "bnd-1")), repo, FakeRecents(), FakeMeta(AppMode.DEMO), documents, FakeUploadScheduler(),
        UploadBatchRunner(documents, repo), corrections, FakeFileImporter(), RunTracker(),
    )

    private fun record(id: String, path: String = "test_results[0]", value: String = "0.28") =
        CorrectionRecord(id, CorrectionKind.CORRECTION, 9, "t", 1, "d1", path, value = value, unit = "%", originalValue = "0.35", originalUnit = "%")

    // ---- what is fetched, and when

    @Test
    fun `an analysed bundle fetches the extraction and the corrections of the assessment on screen`() = runTest(dispatcher) {
        corrections.response = CorrectionsResponse(effective = listOf(record("cor-9")), pending = 1, latestIteration = 1)
        val vm = viewModel()
        runCurrent()

        assertEquals(listOf(1), corrections.extractionCalls)
        assertEquals(1, vm.state.value.extractions.size)
        assertEquals(1, vm.state.value.corrections?.pending)
    }

    @Test
    fun `a bundle that was never analysed has nothing to correct and fetches nothing`() = runTest(dispatcher) {
        repo.bundle = bundle(0, "PENDING", "d1")
        val vm = viewModel()
        runCurrent()

        assertTrue(corrections.extractionCalls.isEmpty())
        assertEquals(0, corrections.listCalls)
        assertNull(vm.state.value.corrections)
    }

    @Test
    fun `a newer assessment from the stream fetches its own extraction and the corrections again`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()
        vm.onScreenStarted()
        runCurrent()
        val listCalls = corrections.listCalls

        repo.events.tryEmit(StreamEvent.Iteration(assessment(2, "SPECIALIST_REVIEW_REQUIRED")))
        runCurrent()

        assertEquals(listOf(1, 2), corrections.extractionCalls)
        assertEquals(listCalls + 1, corrections.listCalls)
        vm.onScreenStopped()
    }

    @Test
    fun `a replay of the assessment already shown fetches nothing more`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()
        vm.onScreenStarted()
        runCurrent()

        repo.events.tryEmit(StreamEvent.Iteration(assessment(1, "MATERIAL_CONTRADICTION")))
        runCurrent()

        assertEquals(listOf(1), corrections.extractionCalls)
        vm.onScreenStopped()
    }

    @Test
    fun `an extraction that cannot be read leaves the editor unable to save, not the screen broken`() = runTest(dispatcher) {
        corrections.extractionError = apiFailure(com.cargoclear.japac.core.data.ApiException.Kind.NETWORK)
        val vm = viewModel()
        runCurrent()

        assertTrue(vm.state.value.extractions.isEmpty())
        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        vm.editCorrection { it.valueChanged("0.28") }
        vm.saveCorrection()
        runCurrent()

        assertTrue("without the value the model read there is nothing to compare with", corrections.submitted.isEmpty())
    }

    @Test
    fun `a saved copy does not try to fetch what it cannot`() = runTest(dispatcher) {
        repo.bundleError = apiFailure(com.cargoclear.japac.core.data.ApiException.Kind.NETWORK)
        val recents = FakeRecents().apply { remember(bundle(1, "MATERIAL_CONTRADICTION", "d1"), assessment(1, "MATERIAL_CONTRADICTION")) }
        val vm = BundleViewModel(
            SavedStateHandle(mapOf("bundleId" to "bnd-1")), repo, recents, FakeMeta(AppMode.DEMO), documents, FakeUploadScheduler(),
            UploadBatchRunner(documents, repo), corrections, FakeFileImporter(), RunTracker(),
        )
        runCurrent()

        assertTrue(vm.state.value.isReadOnly)
        assertTrue(corrections.extractionCalls.isEmpty())
        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        assertNull("a saved copy cannot send a correction", vm.correctionsUi.value.editor)
    }

    // ---- the editor

    @Test
    fun `opening the editor fills it with what the model read`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()

        vm.openCorrection("d1", "d1.pdf", "test_results[0]")

        val draft = checkNotNull(vm.correctionsUi.value.editor).draft
        assertEquals("0.35", draft.value)
        assertEquals("%", draft.unit)
    }

    @Test
    fun `saving a changed value posts the request, refreshes the list and closes the editor`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()
        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        vm.editCorrection { it.valueChanged("0.28").reasonChanged("prints 0.28") }

        vm.saveCorrection()
        assertTrue("busy at once, so a second tap does nothing", checkNotNull(vm.correctionsUi.value.editor).draft.busy)
        runCurrent()

        assertEquals(listOf(CorrectionRequest("d1", "test_results[0]", value = "0.28", unit = "%", reason = "prints 0.28")), corrections.submitted)
        assertNull(vm.correctionsUi.value.editor)
        assertEquals(1, vm.state.value.corrections?.pending)
        assertEquals(listOf("test_results[0]"), vm.state.value.corrections?.effective?.map { it.path })
    }

    @Test
    fun `a refusal stays in the editor in the server's words, with what was typed`() = runTest(dispatcher) {
        corrections.submitError = com.cargoclear.japac.core.data.ApiException(
            com.cargoclear.japac.core.model.ErrorEnvelope("VALIDATION_ERROR", "'1,2.3' is not a number."),
            com.cargoclear.japac.core.data.ApiException.Kind.HTTP, 422,
        )
        val vm = viewModel()
        runCurrent()
        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        vm.editCorrection { it.valueChanged("1,2.3") }

        vm.saveCorrection()
        runCurrent()

        val draft = checkNotNull(vm.correctionsUi.value.editor).draft
        assertEquals("'1,2.3' is not a number.", draft.error)
        assertEquals("1,2.3", draft.value)
        assertFalse(draft.busy)
        assertEquals("nothing was recorded, so nothing is pending", 0, vm.state.value.corrections?.pending)
    }

    @Test
    fun `typing wins over an extraction that arrives while the editor is open`() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        corrections.docs = emptyList()
        val vm = viewModel()
        runCurrent()
        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        vm.editCorrection { it.valueChanged("0.28") }

        corrections.docs = listOf(buildJsonObject { put("document_id", "d1") })
        vm.correctionValueLoaded()

        assertEquals("0.28", checkNotNull(vm.correctionsUi.value.editor).draft.value)
        gate.complete(Unit)
    }

    @Test
    fun `no editor opens while a run goes`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()
        vm.runAnalysis()
        runCurrent()
        assertTrue(vm.state.value.isRunning)

        vm.openCorrection("d1", "d1.pdf", "test_results[0]")

        assertNull(vm.correctionsUi.value.editor)
    }

    @Test
    fun `an editor left open when a run starts cannot be saved`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()
        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        vm.editCorrection { it.valueChanged("0.28") }
        vm.recompute()
        runCurrent()

        vm.saveCorrection()
        runCurrent()

        assertTrue(corrections.submitted.isEmpty())
    }

    @Test
    fun `closing the editor forgets the draft`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()
        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        vm.editCorrection { it.valueChanged("0.28") }
        vm.closeCorrection()
        assertNull(vm.correctionsUi.value.editor)
        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        assertEquals("a fresh editor starts from what the model read", "0.35", checkNotNull(vm.correctionsUi.value.editor).draft.value)
    }

    // ---- undo

    @Test
    fun `undoing a correction asks the server, refreshes the list and clears the busy mark`() = runTest(dispatcher) {
        corrections.response = CorrectionsResponse(effective = listOf(record("cor-9")), pending = 0, latestIteration = 1)
        val vm = viewModel()
        runCurrent()

        vm.revertCorrection("cor-9")
        assertEquals("cor-9", vm.correctionsUi.value.revertingId)
        runCurrent()

        assertEquals(listOf("cor-9"), corrections.reverted)
        assertNull(vm.correctionsUi.value.revertingId)
        assertTrue(vm.state.value.corrections?.effective?.isEmpty() == true)
        assertEquals("the undo is a change the assessment lacks", 1, vm.state.value.corrections?.pending)
    }

    @Test
    fun `a failed undo is reported and the correction stays`() = runTest(dispatcher) {
        corrections.response = CorrectionsResponse(effective = listOf(record("cor-9")), pending = 0, latestIteration = 1)
        corrections.revertError = apiFailure(com.cargoclear.japac.core.data.ApiException.Kind.NETWORK, message = "Can't reach the server.")
        val vm = viewModel()
        runCurrent()

        vm.revertCorrection("cor-9")
        runCurrent()

        assertEquals("Can't reach the server.", vm.correctionsUi.value.revertError)
        assertNull(vm.correctionsUi.value.revertingId)
        assertEquals(1, vm.state.value.corrections?.effective?.size)
    }

    @Test
    fun `one undo at a time`() = runTest(dispatcher) {
        corrections.response = CorrectionsResponse(effective = listOf(record("cor-9"), record("cor-10", "consignee", "ACME")), pending = 0, latestIteration = 1)
        val vm = viewModel()
        runCurrent()

        vm.revertCorrection("cor-9")
        vm.revertCorrection("cor-10")
        runCurrent()

        assertEquals(listOf("cor-9"), corrections.reverted)
    }

    @Test
    fun `retrying a failed load drops the open editor`() = runTest(dispatcher) {
        val vm = viewModel()
        runCurrent()
        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        assertNotNull(vm.correctionsUi.value.editor)

        vm.retry()

        assertNull(vm.correctionsUi.value.editor)
    }

    // ---- surviving the process being ended

    private fun viewModel(handle: SavedStateHandle) = BundleViewModel(
        handle, repo, FakeRecents(), FakeMeta(AppMode.DEMO), documents, FakeUploadScheduler(),
        UploadBatchRunner(documents, repo), corrections, FakeFileImporter(), RunTracker(),
    )

    @Test
    fun `what is typed in the editor is kept in the screen's saved state`() = runTest(dispatcher) {
        val handle = SavedStateHandle(mapOf("bundleId" to "bnd-1"))
        val vm = viewModel(handle)
        runCurrent()
        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        vm.editCorrection { it.valueChanged("0.28").reasonChanged("prints 0.28") }
        runCurrent()

        val restored = checkNotNull(correctionEditorFromSavedState(handle.get<String>("correctionEditor")))
        assertEquals("0.28", restored.draft.value)
        assertEquals("prints 0.28", restored.draft.reason)
        assertEquals("d1.pdf", restored.documentName)
    }

    @Test
    fun `an editor that was open when the process ended comes back with its text, once the bundle is loaded`() = runTest(dispatcher) {
        val handle = SavedStateHandle(mapOf("bundleId" to "bnd-1"))
        val first = viewModel(handle)
        runCurrent()
        first.openCorrection("d1", "d1.pdf", "test_results[0]")
        first.editCorrection { it.valueChanged("0.28") }
        runCurrent()

        // the system ends the process; the new one is built from the same saved state
        val second = viewModel(SavedStateHandle(mapOf("bundleId" to "bnd-1", "correctionEditor" to handle.get<String>("correctionEditor"))))
        runCurrent()

        val editor = checkNotNull(second.correctionsUi.value.editor)
        assertEquals("0.28", editor.draft.value)
        assertEquals("d1", editor.draft.documentId)
        assertFalse(editor.draft.busy)
        second.correctionValueLoaded()
        assertEquals("what was typed is kept when the extraction arrives", "0.28", checkNotNull(second.correctionsUi.value.editor).draft.value)
    }

    @Test
    fun `closing the editor, saving it, or retrying forgets it in the saved state too`() = runTest(dispatcher) {
        val handle = SavedStateHandle(mapOf("bundleId" to "bnd-1"))
        val vm = viewModel(handle)
        runCurrent()
        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        runCurrent()
        assertNotNull(handle.get<String>("correctionEditor"))

        vm.closeCorrection()
        runCurrent()
        assertNull(handle.get<String>("correctionEditor"))

        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        vm.editCorrection { it.valueChanged("0.28") }
        vm.saveCorrection()
        runCurrent()
        assertNull("saved, so closed, so forgotten", handle.get<String>("correctionEditor"))

        vm.openCorrection("d1", "d1.pdf", "consignee")
        runCurrent()
        vm.retry()
        runCurrent()
        assertNull(handle.get<String>("correctionEditor"))
    }

    @Test
    fun `a damaged saved state is ignored`() = runTest(dispatcher) {
        val vm = viewModel(SavedStateHandle(mapOf("bundleId" to "bnd-1", "correctionEditor" to "{broken")))
        runCurrent()
        assertNull(vm.correctionsUi.value.editor)
    }

    // ---- overlapping refreshes

    @Test
    fun `an older answer that arrives last does not replace a newer one`() = runTest(dispatcher) {
        corrections.response = CorrectionsResponse(effective = emptyList(), pending = 0, latestIteration = 1)
        val vm = viewModel()
        runCurrent()

        // the first refresh is held back after it has read the (old) list; the second reads the newer list and finishes first
        val gate = CompletableDeferred<Unit>()
        corrections.gate = gate
        vm.openCorrection("d1", "d1.pdf", "test_results[0]")
        vm.editCorrection { it.valueChanged("0.28") }
        vm.saveCorrection() // submit adds the correction, then refreshes: this refresh reads the newer list but waits at the gate
        runCurrent()
        corrections.gate = null
        corrections.response = corrections.response.copy(pending = 5) // what a later refresh would read
        vm.revertCorrection(corrections.response.effective.single().correctionId) // its refresh reads pending = 6 and finishes at once
        runCurrent()
        assertEquals("the newer refresh has landed", 6, vm.state.value.corrections?.pending)
        gate.complete(Unit)
        runCurrent()

        assertEquals("the older refresh read pending = 1 and arrived last: it was dropped", 6, vm.state.value.corrections?.pending)
    }
}
