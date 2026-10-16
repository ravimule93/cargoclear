package com.cargoclear.japac.ui.bundle

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import com.cargoclear.japac.Fixtures
import com.cargoclear.japac.core.model.ActionError
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.RunProgress
import com.cargoclear.japac.core.model.RunState
import com.cargoclear.japac.core.model.UploadStatus
import com.cargoclear.japac.core.model.UploadUpdate
import com.cargoclear.japac.core.model.WorkbenchState
import com.cargoclear.japac.ui.theme.CargoClearTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** The controls added in Phase 2: running, adding documents, the sample certificate, and what the screen says while they work. */
class RunAndUploadContentTest {
    @get:Rule
    val compose = createComposeRule()

    private var runs = 0
    private var adds = 0
    private var samples = 0
    private var cancels = 0
    private var dismissals = 0

    private fun show(state: WorkbenchState, mode: AppMode? = AppMode.DEMO) {
        compose.setContent {
            CargoClearTheme {
                BundleContent(
                    bundleId = "bnd-test",
                    state = state,
                    appMode = mode,
                    onBack = {},
                    onRetry = {},
                    onSelectDocument = {},
                    onRun = { runs++ },
                    onAddDocuments = { adds++ },
                    onUseSampleMtc = { samples++ },
                    onCancelUploads = { cancels++ },
                    onDismissError = { dismissals++ },
                )
            }
        }
    }

    private fun scrollTo(text: String) = compose.onNode(hasText(text, ignoreCase = true)).performScrollTo()

    // ---- the run button

    @Test
    fun a_bundle_never_analysed_offers_run_analysis_and_asks_to_run_when_tapped() {
        show(Fixtures.neverAnalysed())
        compose.onNodeWithText("Run analysis").assertIsDisplayed().assertIsEnabled().performClick()
        assertEquals(1, runs)
    }

    @Test
    fun an_analysed_bundle_offers_reassess() {
        show(Fixtures.caseCMissingEvidence())
        compose.onNodeWithText("Reassess").assertIsDisplayed().performClick()
        assertEquals(1, runs)
    }

    @Test
    fun while_a_run_goes_the_button_says_so_and_does_nothing() {
        show(Fixtures.caseCMissingEvidence().copy(run = RunProgress("run-1", RunState.RUNNING, "extract", 0.4, null)))
        compose.onNodeWithText("Analysis running…").assertIsDisplayed().assertIsNotEnabled().performClick()
        assertEquals(0, runs)
        compose.onNodeWithText("Stage: Extract").assertIsDisplayed()
    }

    @Test
    fun a_run_just_asked_for_shows_starting_at_zero_not_the_last_runs_hundred_percent() {
        val state = Fixtures.caseCMissingEvidence()
            .copy(run = RunProgress("run-0", RunState.COMPLETE, "finalize", 1.0, null))
            .runRequested()
        show(state)
        compose.onNodeWithText("Stage: Starting").assertIsDisplayed()
        compose.onNodeWithText("0%").assertIsDisplayed()
        compose.onNodeWithText("100%").assertDoesNotExist()
    }

    @Test
    fun a_saved_copy_offers_neither_running_nor_adding() {
        val saved = WorkbenchState().loadedFromSavedCopy(Fixtures.caseCMissingEvidence().bundle!!, Fixtures.caseCMissingEvidence().assessment, savedAt = 1L)
        show(saved)
        compose.onNodeWithText("Reassess").assertDoesNotExist()
        compose.onNodeWithText("Run analysis").assertDoesNotExist()
        compose.onNodeWithContentDescription("Add document").assertIsNotEnabled()
    }

    @Test
    fun files_going_up_disable_running_and_adding() {
        val state = Fixtures.caseCMissingEvidence().uploadUpdated(UploadUpdate(active = UploadStatus.Active(1, 2, "a.pdf")))
        show(state)
        compose.onNodeWithText("Reassess").assertIsNotEnabled()
        compose.onNodeWithContentDescription("Add document").assertIsNotEnabled()
    }

    // ---- adding documents

    @Test
    fun the_top_bar_adds_documents() {
        show(Fixtures.caseCMissingEvidence())
        compose.onNodeWithContentDescription("Add document").assertIsEnabled().performClick()
        assertEquals(1, adds)
    }

    @Test
    fun the_documents_tab_has_its_own_add_button() {
        show(Fixtures.caseCMissingEvidence())
        compose.onNodeWithText("Documents").performClick()
        compose.onNodeWithText("Add document").assertIsDisplayed().performClick()
        assertEquals(1, adds)
    }

    @Test
    fun an_empty_bundle_says_what_to_do() {
        show(WorkbenchState().loaded(Fixtures.neverAnalysed().bundle!!.copy(documents = emptyList()), null, emptyList()))
        compose.onNodeWithText("Documents").performClick()
        compose.onNodeWithText("No documents in this bundle yet.").assertIsDisplayed()
        compose.onNodeWithText("Add the trade PDFs for this shipment, then run the analysis.").assertIsDisplayed()
    }

    // ---- what is missing

    @Test
    fun the_missing_certificate_can_be_uploaded_or_in_demo_mode_taken_from_the_sample() {
        show(Fixtures.caseCMissingEvidence())
        scrollTo("Use sample MTC (demo)").assertIsEnabled().performClick()
        assertEquals(1, samples)
        scrollTo("Upload Missing Certificate (PDF)").assertIsEnabled().performClick()
        assertEquals(1, adds)
        compose.onNodeWithText("Choose PDFs from this phone").assertExists()
    }

    @Test
    fun outside_demo_mode_there_is_no_sample_certificate() {
        show(Fixtures.caseCMissingEvidence(), mode = AppMode.LIVE)
        scrollTo("Upload Missing Certificate (PDF)").assertIsDisplayed()
        compose.onNodeWithText("Use sample MTC (demo)").assertDoesNotExist()
    }

    @Test
    fun the_sample_certificate_button_reads_uploading_while_it_goes_up() {
        val state = Fixtures.caseCMissingEvidence().uploadUpdated(UploadUpdate(active = UploadStatus.Active(1, 1, "mtc_pipe_test_cert.pdf")))
        show(state)
        scrollTo("Uploading sample MTC…").assertIsNotEnabled()
    }

    // ---- what the screen says while it works

    @Test
    fun an_upload_in_progress_names_the_file_and_can_be_cancelled() {
        show(Fixtures.caseCMissingEvidence().uploadUpdated(UploadUpdate(active = UploadStatus.Active(2, 3, "mtc.pdf"))))
        compose.onNodeWithText("Uploading 2/3: mtc.pdf").assertIsDisplayed()
        compose.onNodeWithText("Cancel upload").performClick()
        assertEquals(1, cancels)
    }

    @Test
    fun a_queued_batch_says_it_is_waiting() {
        show(Fixtures.caseCMissingEvidence().uploadUpdated(UploadUpdate(active = UploadStatus.Active(1, 2, null, waiting = true))))
        compose.onNodeWithText("Waiting to upload 2 files…").assertIsDisplayed()
    }

    @Test
    fun a_refused_run_shows_the_servers_words_and_the_request_id_and_can_be_dismissed() {
        show(Fixtures.caseCMissingEvidence().runRejected(ActionError("An analysis is already running for this bundle.", "req-42")))
        compose.onNodeWithText("Analysis Issue Detected", substring = true).assertIsDisplayed()
        compose.onNodeWithText("An analysis is already running for this bundle.").assertIsDisplayed()
        compose.onNodeWithText("Request id: req-42").assertIsDisplayed()
        compose.onNodeWithText("Dismiss").performClick()
        assertEquals(1, dismissals)
    }

    @Test
    fun a_failed_upload_says_how_far_it_got() {
        val failed = UploadStatus.Failed(ActionError("Only PDF files are accepted. Received: text/plain", "req-7"), uploaded = 1, total = 3)
        show(Fixtures.caseCMissingEvidence().uploadUpdated(UploadUpdate(failure = failed)))
        compose.onNodeWithText("Uploaded 1 of 3 files.").assertIsDisplayed()
        compose.onNodeWithText("Only PDF files are accepted. Received: text/plain").assertIsDisplayed()
        compose.onNodeWithText("Dismiss").assertIsDisplayed()
    }

    @Test
    fun a_pipeline_failure_reported_by_the_stream_cannot_be_dismissed() {
        show(Fixtures.neverAnalysed().copy(streamError = "Gemini token limit exceeded"))
        compose.onNodeWithText("Gemini token limit exceeded").assertIsDisplayed()
        compose.onNodeWithText("Dismiss").assertDoesNotExist()
    }
}
