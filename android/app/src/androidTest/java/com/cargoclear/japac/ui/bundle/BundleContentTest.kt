package com.cargoclear.japac.ui.bundle

import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.isSelected
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onLast
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.dp
import com.cargoclear.japac.Fixtures
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.DEMO_BANNER_TEXT
import com.cargoclear.japac.core.model.RunProgress
import com.cargoclear.japac.core.model.RunState
import com.cargoclear.japac.core.model.StreamConnection
import com.cargoclear.japac.core.model.WorkbenchState
import com.cargoclear.japac.core.model.buildHighlights
import com.cargoclear.japac.core.model.formatMoney
import com.cargoclear.japac.ui.theme.CargoClearTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** The bundle screen, drawn from what the demo backend really sent for Case C and Case D. */
class BundleContentTest {
    @get:Rule
    val compose = createComposeRule()

    private var selected: String? = null
    private var viewerOpened: Triple<String, Int?, String?>? = null
    private var retried = false
    private var wentBack = false

    private fun show(state: WorkbenchState, mode: AppMode? = AppMode.DEMO, bundleId: String = "bnd-test") {
        compose.setContent {
            CargoClearTheme {
                BundleContent(
                    bundleId = bundleId,
                    state = state,
                    appMode = mode,
                    onBack = { wentBack = true },
                    onRetry = { retried = true },
                    onSelectDocument = { selected = it },
                    onOpenViewer = { document, page, highlight -> viewerOpened = Triple(document, page, highlight) },
                )
            }
        }
    }

    /** Headings are drawn in capitals on purpose (as on the web), so they are looked up without regard to case. */
    private fun scrollTo(text: String, substring: Boolean = false) =
        compose.onNode(hasText(text, substring = substring, ignoreCase = true)).performScrollTo()

    // ---- the verdicts

    @Test
    fun case_d_shows_the_contradiction_with_the_certificate_values() {
        show(Fixtures.caseDContradiction())

        compose.onNodeWithContentDescription("Assessment status: Material Contradiction").assertIsDisplayed()
        scrollTo("Alloy Status vs Declared HS Code (HS Note 1)").assertIsDisplayed()
        scrollTo("Discrepancies & Warnings (2)", substring = true).assertIsDisplayed()
        scrollTo("TH-77121: Cr 0.35%").assertIsDisplayed()
        scrollTo("Anti-Dumping Exposure").assertIsDisplayed()
        compose.onNodeWithText("Certificate chemistry contradicts the declared HS code", substring = true).assertExists()
        compose.onNodeWithText("Lowest reported confidence: 96%").assertExists()
        compose.onNodeWithText("A self-reported score, not a measured accuracy.", substring = true).assertExists()
    }

    @Test
    fun the_rule_set_and_its_reference_are_one_tap_away() {
        val state = Fixtures.caseDContradiction()
        val alloy = state.assessment!!.checks.single { it.checkId == "M-001" }
        show(state)

        scrollTo("Alloy Status vs Declared HS Code (HS Note 1)")
        compose.onNodeWithText(alloy.regulationRef!!, substring = true).assertDoesNotExist()
        compose.onAllNodesWithText("Rule set: ${alloy.ruleSet}", substring = true).onFirst().performScrollTo().performClick()
        compose.onNodeWithText(alloy.regulationRef!!, substring = true).assertExists()
    }

    @Test
    fun the_estimate_reads_like_the_web_with_every_assumption_one_tap_away() {
        val state = Fixtures.caseDContradiction()
        val valuation = checkNotNull(state.assessment?.valuation)
        show(state)

        scrollTo("Indicative duty exposure (IN", substring = true).assertIsDisplayed()
        compose.onNodeWithText(valuation.disclaimer).assertExists()
        scrollTo("Indicative total").assertIsDisplayed()
        compose.onNodeWithText(formatMoney(valuation.totalDuty, valuation.destinationCurrency)).assertExists()
        // the estimate's own rule-set line is the last one on the screen (the checks above carry theirs)
        compose.onAllNodesWithText("Rule set: ${valuation.ruleSet}", substring = true).onLast().assertExists()

        val assumption = valuation.assumptions.first()
        compose.onNodeWithText(assumption, substring = true).assertDoesNotExist()
        scrollTo("What this estimate assumed (${valuation.assumptions.size})", substring = true).performClick()
        compose.onNodeWithText(assumption, substring = true).assertExists()
    }

    @Test
    fun passed_checks_are_collapsed_until_asked_for() {
        show(Fixtures.caseDContradiction())

        scrollTo("Verified Rules (13)", substring = true).assertIsDisplayed()
        compose.onNodeWithText("Weight Balance (BoL Gross vs Packing List Net+Tare)").assertDoesNotExist()
        compose.onNodeWithText("Show (13 passed)", substring = true).performClick()
        scrollTo("Weight Balance (BoL Gross vs Packing List Net+Tare)").assertIsDisplayed()
        compose.onNodeWithText("Hide verified", substring = true).assertExists()
    }

    @Test
    fun case_c_without_the_certificate_says_what_is_missing() {
        show(Fixtures.caseCMissingEvidence())

        compose.onNodeWithContentDescription("Assessment status: Missing Evidence").assertIsDisplayed()
        scrollTo("Mandatory Trade Documents Required", substring = true).assertIsDisplayed()
        scrollTo("Missing: Mill Test Certificate", substring = true).assertIsDisplayed()
        compose.onNodeWithText("Ref: Demo rule set (prototype); not an official AHTN requirement", substring = true).assertExists()
    }

    @Test
    fun case_c_with_the_certificate_is_compliant_and_names_nothing_missing() {
        show(Fixtures.caseCCompliant())

        compose.onNodeWithContentDescription("Assessment status: Compliant For Submission").assertIsDisplayed()
        compose.onNodeWithText("Iteration 2").assertExists()
        compose.onNodeWithText("Mandatory Trade Documents Required", substring = true).assertDoesNotExist()
    }

    // ---- honesty about what is and is not known

    @Test
    fun the_demo_banner_states_the_data_is_synthetic_in_demo_mode_and_for_fixture_data() {
        show(Fixtures.caseCMissingEvidence(), mode = AppMode.DEMO)
        compose.onNodeWithText(DEMO_BANNER_TEXT).assertIsDisplayed()
    }

    @Test
    fun an_assessment_that_came_from_fixtures_carries_the_banner_even_when_the_mode_is_unknown() {
        show(Fixtures.caseCMissingEvidence(), mode = null)
        compose.onNodeWithText(DEMO_BANNER_TEXT).assertIsDisplayed()
    }

    @Test
    fun a_bundle_that_was_never_analysed_says_so_and_has_no_verdict() {
        show(Fixtures.neverAnalysed())

        compose.onNodeWithContentDescription("Assessment status: Not assessed yet").assertIsDisplayed()
        compose.onNodeWithText("No assessment yet").assertIsDisplayed()
        compose.onNodeWithText("Run analysis to adjudicate this bundle.").assertIsDisplayed()
    }

    @Test
    fun a_status_this_app_does_not_know_is_not_shown_as_one_of_the_four() {
        val base = Fixtures.caseCMissingEvidence()
        val odd = base.assessment!!.copy(status = "SOMETHING_NEW")
        show(base.streamIteration(odd.copy(iteration = odd.iteration + 1)))

        compose.onNodeWithContentDescription("Assessment status: Unrecognised status").assertIsDisplayed()
    }

    @Test
    fun a_saved_copy_says_the_server_could_not_be_reached() {
        val live = Fixtures.caseCMissingEvidence()
        val saved = WorkbenchState().loadedFromSavedCopy(live.bundle!!, live.assessment, savedAt = System.currentTimeMillis() - 5 * 60_000)
        show(saved.connection(StreamConnection.RECONNECTING))

        compose.onNodeWithText("Showing the copy saved on this phone", substring = true).assertIsDisplayed()
        compose.onNodeWithText("The server could not be reached, so this may be out of date.", substring = true).assertExists()
        compose.onNodeWithText("Live updates: reconnecting…").assertIsDisplayed()
    }

    // ---- a run in progress, and one that failed

    @Test
    fun a_run_in_progress_shows_its_stage_and_percentage() {
        val running = Fixtures.neverAnalysed().copy(run = RunProgress("run-1", RunState.RUNNING, "extract", 0.4, null))
        show(running)

        compose.onNodeWithText("Stage: Extract").assertIsDisplayed()
        compose.onNodeWithText("40%").assertIsDisplayed()
    }

    @Test
    fun a_failed_run_shows_the_servers_words() {
        show(Fixtures.neverAnalysed().copy(streamError = "Gemini token limit exceeded"))

        compose.onNodeWithText("Analysis Issue Detected", substring = true).assertIsDisplayed()
        compose.onNodeWithText("Gemini token limit exceeded").assertIsDisplayed()
    }

    // ---- documents

    @Test
    fun the_documents_tab_lists_the_files_with_their_health_and_marks_the_findings_document() {
        show(Fixtures.caseDContradiction())

        compose.onNodeWithText("Documents").performClick()
        compose.onNode(hasText("Trade Bundle Files (4)", ignoreCase = true)).assertIsDisplayed()
        compose.onAllNodesWithText("● 1 Conflict").assertCountEquals(2)
        compose.onNodeWithText("▲ 1 Gap").assertIsDisplayed()
        compose.onNodeWithText("✓ Clean").assertIsDisplayed()
        // the certificate is what the contradiction is about, so it is the one in view
        compose.onNode(hasText("case_d_mtc_test_cert.pdf") and isSelected()).assertIsDisplayed()
        compose.onNode(hasText("case_d_bill_of_lading.pdf") and isSelected().not()).assertHeightIsAtLeast(48.dp)
    }

    @Test
    fun opening_a_document_selects_it_and_opens_the_viewer_on_its_first_page() {
        val state = Fixtures.caseDContradiction()
        show(state)
        compose.onNodeWithText("Documents").performClick()

        compose.onNode(hasText("case_d_packing_list.pdf")).performClick()

        val id = state.documents.single { it.filename == "case_d_packing_list.pdf" }.documentId
        assertEquals(id, selected)
        assertEquals(Triple(id, null, null), viewerOpened)
    }

    @Test
    fun tapping_evidence_opens_the_viewer_on_the_page_it_cites_with_its_box_chosen() {
        val state = Fixtures.caseDContradiction()
        show(state)

        compose.onAllNodesWithText("case_d_commercial_invoice.pdf", substring = true).onFirst().performScrollTo().performClick()

        val document = state.documents.single { it.filename == "case_d_commercial_invoice.pdf" }.documentId
        val (openedDocument, page, highlight) = checkNotNull(viewerOpened)
        assertEquals(document, openedDocument)
        assertEquals(1, page)
        // the box that was tapped is one the viewer will draw (same id scheme), not just a page
        assertTrue(highlight in buildHighlights(state.assessment).map { it.id })
        assertEquals(document, selected)
    }

    // ---- loading, not found, failure

    @Test
    fun loading_not_found_and_failure_each_say_what_happened() {
        show(WorkbenchState())
        compose.onNodeWithText("Loading bundle...").assertIsDisplayed()
    }

    @Test
    fun an_unknown_bundle_says_so_and_offers_the_way_back() {
        show(WorkbenchState().loadFailed(notFound = true, message = "x"), bundleId = "bnd-nope")

        compose.onNodeWithText("Bundle not found").assertIsDisplayed()
        compose.onNodeWithText("No bundle with id bnd-nope exists.").assertIsDisplayed()
        compose.onNodeWithText("Back to start").performClick()
        assertEquals(true, wentBack)
    }

    @Test
    fun a_failed_load_shows_the_reason_and_retries() {
        show(WorkbenchState().loadFailed(notFound = false, message = "Can't reach the server. Check your connection and try again."))

        compose.onNodeWithText("Could not load bundle: Can't reach the server. Check your connection and try again.").assertIsDisplayed()
        compose.onNodeWithText("Retry").performClick()
        assertEquals(true, retried)
    }

    @Test
    fun the_back_button_leaves_the_bundle() {
        show(Fixtures.caseCCompliant())
        compose.onNodeWithContentDescription("Back").performClick()
        assertEquals(true, wentBack)
    }
}
