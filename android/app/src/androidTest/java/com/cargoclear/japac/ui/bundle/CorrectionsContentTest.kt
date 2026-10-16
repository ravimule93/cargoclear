package com.cargoclear.japac.ui.bundle

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import com.cargoclear.japac.Fixtures
import com.cargoclear.japac.core.model.CorrectionsUi
import com.cargoclear.japac.core.model.PrefillFormat
import com.cargoclear.japac.core.model.RunProgress
import com.cargoclear.japac.core.model.RunState
import com.cargoclear.japac.core.model.WorkbenchState
import com.cargoclear.japac.ui.assess.PrefillUi
import com.cargoclear.japac.ui.theme.CargoClearTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** The Phase 4 controls on the bundle screen: Edit on an evidence row, the corrections card, the editor sheet, undo, recompute and the pre-fill card. */
class CorrectionsContentTest {
    @get:Rule
    val compose = createComposeRule()

    private val opened = mutableListOf<Triple<String, String, String>>()
    private val reverted = mutableListOf<String>()
    private var recomputes = 0
    private val shared = mutableListOf<PrefillFormat>()
    private var ui by mutableStateOf(CorrectionsUi())
    private var saves = 0
    private var closes = 0

    private val certName = "case_d_mtc_test_cert.pdf"

    private fun show(state: WorkbenchState, prefill: PrefillUi = PrefillUi(), correctionsUi: CorrectionsUi = CorrectionsUi()) {
        ui = correctionsUi
        compose.setContent {
            CargoClearTheme {
                BundleContent(
                    bundleId = "bnd-test",
                    state = state,
                    appMode = com.cargoclear.japac.core.model.AppMode.DEMO,
                    onBack = {},
                    onRetry = {},
                    onSelectDocument = {},
                    correctionsUi = ui,
                    onCorrect = { doc, name, path -> opened += Triple(doc, name, path) },
                    onEditCorrection = { change -> ui = ui.edited(change) },
                    onSaveCorrection = { saves++ },
                    onCloseCorrection = { closes++; ui = ui.closed() },
                    onRevert = { reverted += it },
                    onRecompute = { recomputes++ },
                    prefill = prefill,
                    onSharePrefill = { shared += it },
                )
            }
        }
    }

    /** Texts that lead with a glyph ("▲ ", "✓ ") are found by what follows it. */
    private fun scrollTo(text: String) = compose.onNode(hasText(text, substring = true, ignoreCase = true)).performScrollTo()

    /** Clicks through the semantics: a button scrolled under the floating Run button cannot be hit by a touch, and that is not what these tests are about. */
    private fun androidx.compose.ui.test.SemanticsNodeInteraction.activate() =
        performScrollTo().performSemanticsAction(androidx.compose.ui.semantics.SemanticsActions.OnClick)

    private fun certId(state: WorkbenchState) = state.documents.first { it.filename == certName }.documentId

    // ---- Edit on an evidence row

    @Test
    fun a_value_the_check_cites_can_be_edited_and_edit_names_the_value_and_the_document() {
        val state = Fixtures.caseDCorrected()
        show(state)
        val edit = compose.onNodeWithContentDescription("Correct Certificate cell 21 in $certName")
        edit.performScrollTo().assertIsEnabled()
        edit.activate()
        assertEquals(listOf(Triple(certId(state), certName, "test_results[20]")), opened)
    }

    @Test
    fun no_edit_while_a_run_goes() {
        show(Fixtures.caseDCorrected().copy(run = RunProgress("run-1", RunState.RUNNING, "extract", 0.4, null)))
        compose.onNodeWithContentDescription("Correct Certificate cell 21 in $certName").performScrollTo().assertIsNotEnabled()
    }

    @Test
    fun a_saved_copy_offers_no_edit_and_no_pre_fill() {
        val live = Fixtures.caseDContradiction()
        show(WorkbenchState().loadedFromSavedCopy(live.bundle!!, live.assessment, savedAt = 1L))
        compose.onNodeWithContentDescription("Correct Certificate cell 21 in $certName").assertDoesNotExist()
        compose.onNodeWithText("Share PDF summary").assertDoesNotExist()
    }

    @Test
    fun a_pending_correction_is_said_on_its_evidence_row() {
        show(Fixtures.caseDCorrected())
        scrollTo("Correction pending: 0.28. Recompute to apply it.").assertIsDisplayed()
    }

    @Test
    fun once_recomputed_the_row_says_what_the_model_read() {
        show(Fixtures.caseDRecomputed())
        scrollTo("Corrected by the agent (model read 0.35)")
    }

    // ---- the corrections card

    @Test
    fun the_card_counts_corrections_names_what_changed_and_offers_recompute() {
        show(Fixtures.caseDCorrected())
        scrollTo("Corrections (2)").assertIsDisplayed()
        compose.onNodeWithText("2 not in this assessment yet", ignoreCase = true).assertIsDisplayed()
        compose.onNodeWithText("0.35 %").assertIsDisplayed()
        compose.onNodeWithText("0.28 %").assertIsDisplayed()
        compose.onNodeWithText("“the certificate prints 0.28”").assertIsDisplayed()
        compose.onNodeWithText("Confirmed: MUMBAI INFRA PIPING PVT LTD").assertIsDisplayed()
        compose.onAllNodes(hasText("Pending recompute", substring = true)).assertCountEquals(2) // one line per correction in force
        compose.onNodeWithText("Re-runs every check on the stored extraction. No document is read again and no model is called.").assertIsDisplayed()

        compose.onNodeWithText("Recompute with corrections").assertIsEnabled().activate()
        assertEquals(1, recomputes)
    }

    @Test
    fun undo_names_the_correction_and_asks_for_that_one() {
        val state = Fixtures.caseDCorrected()
        show(state)
        compose.onNodeWithContentDescription("Undo the correction of Certificate cell 21 in $certName").activate()
        assertEquals(listOf("cor-9"), reverted)
        compose.onNodeWithContentDescription("Undo the confirmation of Consignee in case_d_commercial_invoice.pdf").assertExists()
    }

    @Test
    fun a_recompute_in_progress_reads_so_and_blocks_undo() {
        show(Fixtures.caseDCorrected().copy(run = RunProgress("run-1", RunState.RUNNING, "extract", 0.4, null)))
        scrollTo("Recomputing...").assertIsNotEnabled()
        compose.onNodeWithContentDescription("Undo the correction of Certificate cell 21 in $certName").assertIsNotEnabled()
    }

    @Test
    fun a_card_for_an_assessment_that_includes_everything_has_no_recompute() {
        show(Fixtures.caseDRecomputed())
        scrollTo("Corrections (2)")
        compose.onAllNodes(hasText("In this assessment", substring = true)).assertCountEquals(2)
        compose.onNodeWithText("Recompute with corrections").assertDoesNotExist()
    }

    @Test
    fun an_undo_that_failed_says_why() {
        show(Fixtures.caseDCorrected(), correctionsUi = CorrectionsUi().reverting("cor-9").revertFailed("Can't reach the server. Check your connection and try again."))
        scrollTo("Can't reach the server. Check your connection and try again.").assertIsDisplayed()
    }

    // ---- the editor sheet

    private fun editorFor(state: WorkbenchState, path: String, documentId: String, name: String): CorrectionsUi {
        val current = com.cargoclear.japac.core.model.readCell(state.extractions, documentId, path)
        return CorrectionsUi().opened(documentId, name, path, current)
    }

    @Test
    fun the_sheet_shows_what_the_model_read_and_confirms_an_unchanged_value() {
        val state = Fixtures.caseDCorrected()
        show(state, correctionsUi = editorFor(state, "test_results[20]", certId(state), certName))
        // the corrections card names the same value, so the heading is found twice: once in the card, once in the sheet
        compose.onAllNodes(hasText("Certificate cell 21 · $certName")).assertCountEquals(2)
        compose.onNodeWithText("Model read: 0.35 %. State what the document actually says.").assertIsDisplayed()
        compose.onNodeWithText("Unit").assertIsDisplayed()
        compose.onNodeWithText("Confirm value").assertIsEnabled()
        compose.onNodeWithText("The document does not state this value").assertDoesNotExist() // a certificate cell cannot be cleared
    }

    @Test
    fun changing_the_value_turns_confirm_into_save_and_save_asks_to_record_it() {
        val state = Fixtures.caseDCorrected()
        show(state, correctionsUi = editorFor(state, "test_results[20]", certId(state), certName))
        val value = compose.onAllNodes(hasSetTextAction())[0] // the first field is the value; the unit and the reason follow
        value.performTextClearance()
        compose.onNodeWithText("Save correction").assertIsNotEnabled() // an emptied field: a value is needed

        value.performTextInput("0.28")
        compose.onNodeWithText("Save correction").assertIsEnabled().performClick()
        assertEquals(1, saves)
        assertEquals("0.28", ui.editor?.draft?.value)
    }

    @Test
    fun a_header_field_can_be_declared_not_stated_and_then_needs_no_value() {
        val state = Fixtures.caseDCorrected()
        show(state, correctionsUi = editorFor(state, "consignee", certId(state), certName))
        compose.onNodeWithText("The document does not state this value").assertIsDisplayed().performClick()
        compose.onNodeWithText("Save correction").assertIsEnabled()
        compose.onNodeWithText("Unit").assertDoesNotExist() // a consignee has no unit
    }

    @Test
    fun a_refusal_is_shown_in_the_sheet_in_the_servers_words() {
        val state = Fixtures.caseDCorrected()
        val failed = editorFor(state, "test_results[20]", certId(state), certName).edited { it.valueChanged("1,2.3").saving().failed("'1,2.3' is not a number.") }
        show(state, correctionsUi = failed)
        compose.onNodeWithText("'1,2.3' is not a number.").assertIsDisplayed()
        compose.onNodeWithText("Save correction").assertIsEnabled()
    }

    @Test
    fun while_the_value_is_loading_the_sheet_says_so_and_cannot_save() {
        val state = Fixtures.caseDCorrected().extractionsLoaded(emptyList())
        show(state, correctionsUi = CorrectionsUi().opened(certId(state), certName, "test_results[20]", null))
        compose.onNodeWithText("Loading the extracted value...").assertIsDisplayed()
        compose.onNodeWithText("Confirm value").assertIsNotEnabled()
    }

    @Test
    fun cancel_closes_the_sheet() {
        val state = Fixtures.caseDCorrected()
        show(state, correctionsUi = editorFor(state, "test_results[20]", certId(state), certName))
        compose.onNodeWithText("Cancel").performClick()
        assertEquals(1, closes)
    }

    // ---- the pre-fill card

    @Test
    fun a_pack_that_is_not_cleared_says_it_leads_with_what_blocks_it() {
        show(Fixtures.caseDContradiction())
        scrollTo("Declaration pre-fill").assertIsDisplayed()
        compose.onNodeWithText("Not cleared: the pack leads with what blocks it, and flags every value an open finding cites.").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("The values read from your documents (with your corrections)", substring = true).assertIsDisplayed()
    }

    @Test
    fun the_share_buttons_ask_for_their_own_format() {
        show(Fixtures.caseDContradiction())
        compose.onNodeWithText("Share JSON").performScrollTo().performClick()
        compose.onNodeWithText("Share PDF summary").performClick()
        assertEquals(listOf(PrefillFormat.JSON, PrefillFormat.PDF), shared)
    }

    @Test
    fun while_a_pack_is_prepared_the_buttons_wait_and_a_failure_is_said() {
        show(Fixtures.caseDContradiction(), prefill = PrefillUi(busy = PrefillFormat.PDF))
        compose.onNodeWithText("Share JSON").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithText("Preparing…").assertIsNotEnabled()
    }

    @Test
    fun a_failed_download_is_reported_under_the_buttons() {
        show(Fixtures.caseDContradiction(), prefill = PrefillUi(error = "Can't reach the server. Check your connection and try again."))
        scrollTo("Can't reach the server. Check your connection and try again.").assertIsDisplayed()
    }
}
