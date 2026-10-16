package com.cargoclear.japac.ui.bundle

import androidx.compose.foundation.layout.Box
import androidx.compose.material3.Text
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.cargoclear.japac.Fixtures
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.RunProgress
import com.cargoclear.japac.core.model.RunState
import com.cargoclear.japac.core.model.WorkbenchState
import com.cargoclear.japac.ui.theme.CargoClearTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** The optional extras on the bundle screen: scanning, sharing a link, the notify offer, and the split view. */
class ExtrasContentTest {
    @get:Rule
    val compose = createComposeRule()

    private var adds = 0
    private var scans = 0
    private val links = mutableListOf<String>()
    private var notifyMe = 0

    private fun show(
        state: WorkbenchState = Fixtures.caseCMissingEvidence(),
        scanAvailable: Boolean = false,
        shareLink: String? = null,
        notifyOffer: Boolean = false,
        twoPane: Boolean = false,
        pane: (@androidx.compose.runtime.Composable (androidx.compose.ui.Modifier) -> Unit)? = null,
    ) {
        compose.setContent {
            CargoClearTheme {
                BundleContent(
                    bundleId = "bnd-test",
                    state = state,
                    appMode = AppMode.DEMO,
                    onBack = {},
                    onRetry = {},
                    onSelectDocument = {},
                    onAddDocuments = { adds++ },
                    scanAvailable = scanAvailable,
                    onScan = { scans++ },
                    shareLink = shareLink,
                    onShareLink = { links += it },
                    notifyOffer = notifyOffer,
                    onNotifyMe = { notifyMe++ },
                    twoPane = twoPane,
                    pane = pane,
                )
            }
        }
    }

    // ---- adding a document

    @Test
    fun without_a_scanner_add_opens_the_file_picker_at_once() {
        show(scanAvailable = false)
        compose.onNodeWithContentDescription("Add document").performClick()
        assertEquals(1, adds)
        compose.onNodeWithText("Scan a document").assertDoesNotExist()
    }

    @Test
    fun with_a_scanner_add_asks_whether_to_choose_or_scan() {
        show(scanAvailable = true)
        compose.onNodeWithContentDescription("Add document").performClick()
        compose.onNodeWithText("Add a document").assertIsDisplayed()
        compose.onNodeWithText("Choose PDFs").assertIsDisplayed()
        compose.onNodeWithText("Scan a document").assertIsDisplayed()
        assertEquals("nothing happens until one is chosen", 0, adds + scans)
    }

    @Test
    fun choosing_pdfs_opens_the_picker_and_scanning_starts_the_scanner() {
        show(scanAvailable = true)
        compose.onNodeWithContentDescription("Add document").performClick()
        compose.onNodeWithText("Choose PDFs").performClick()
        assertEquals(1, adds)
        assertEquals(0, scans)

        compose.onNodeWithContentDescription("Add document").performClick()
        compose.onNodeWithText("Scan a document").performClick()
        assertEquals(1, scans)
        assertEquals(1, adds)
        compose.onNodeWithText("Add a document").assertDoesNotExist()
    }

    // ---- sharing a link

    @Test
    fun there_is_no_menu_where_there_is_no_web_address() {
        show(shareLink = null)
        compose.onNodeWithContentDescription("More options").assertDoesNotExist()
    }

    @Test
    fun a_link_is_shared_only_after_the_person_is_told_what_it_gives_access_to() {
        show(shareLink = "https://ui.example.com/workbench/bnd-test")
        compose.onNodeWithContentDescription("More options").performClick()
        compose.onNodeWithText("Share link").performClick()

        compose.onNodeWithText("Share a link to this bundle?").assertIsDisplayed()
        compose.onNodeWithText("there is no sign-in", substring = true).assertIsDisplayed()
        assertEquals("nothing is shared yet", emptyList<String>(), links)

        compose.onNodeWithText("Share").performClick()
        assertEquals(listOf("https://ui.example.com/workbench/bnd-test"), links)
    }

    @Test
    fun cancelling_the_warning_shares_nothing() {
        show(shareLink = "https://ui.example.com/workbench/bnd-test")
        compose.onNodeWithContentDescription("More options").performClick()
        compose.onNodeWithText("Share link").performClick()
        compose.onNodeWithText("Cancel").performClick()
        assertEquals(emptyList<String>(), links)
        compose.onNodeWithText("Share a link to this bundle?").assertDoesNotExist()
    }

    // ---- the notify offer

    private fun running() = Fixtures.caseCMissingEvidence().copy(run = RunProgress("run-1", RunState.RUNNING, "extract", 0.4, null))

    @Test
    fun while_a_run_goes_and_notifications_are_off_the_person_can_ask_for_one() {
        show(state = running(), notifyOffer = true)
        compose.onNodeWithText("Notify me when it finishes").assertIsDisplayed().performClick()
        assertEquals(1, notifyMe)
    }

    @Test
    fun the_offer_is_not_made_when_nothing_is_running_or_it_is_already_on() {
        show(state = Fixtures.caseCMissingEvidence(), notifyOffer = true)
        compose.onNodeWithText("Notify me when it finishes").assertDoesNotExist()
    }

    @Test
    fun the_offer_goes_when_it_is_already_on() {
        show(state = running(), notifyOffer = false)
        compose.onNodeWithText("Notify me when it finishes").assertDoesNotExist()
    }

    // ---- the split view

    @Test
    fun two_panes_put_the_assessment_beside_the_pane_and_fold_the_history_below() {
        show(twoPane = true, pane = { modifier -> Box(modifier) { Text("the right-hand pane") } })
        compose.onNodeWithText("the right-hand pane").assertIsDisplayed()
        compose.onNodeWithText("Missing Evidence").assertExists() // the assessment is on screen at the same time
        compose.onNodeWithText("History").assertIsDisplayed()
        compose.onNodeWithText("▲ Expand").assertIsDisplayed()
        compose.onNodeWithText("Documents").assertDoesNotExist() // no tab bar: nothing to switch between
    }

    @Test
    fun the_history_panel_opens_and_folds_again() {
        show(twoPane = true, pane = { modifier -> Box(modifier) { Text("pane") } })
        compose.onNodeWithText("Reasoning Delta").assertDoesNotExist()
        compose.onNodeWithText("▲ Expand").performClick()
        compose.onNodeWithText("Reasoning Delta").assertIsDisplayed()
        compose.onNodeWithText("▼ Collapse").performClick()
        compose.onNodeWithText("Reasoning Delta").assertDoesNotExist()
    }

    @Test
    fun one_pane_keeps_the_tab_bar() {
        show(twoPane = false, pane = { modifier -> Box(modifier) { Text("pane") } })
        compose.onNodeWithText("Documents").assertIsDisplayed()
        compose.onNodeWithText("pane").assertDoesNotExist()
    }
}
