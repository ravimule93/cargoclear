package com.cargoclear.japac.ui.home

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onLast
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import com.cargoclear.japac.core.data.DemoCase
import com.cargoclear.japac.core.data.RecentBundle
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.Destination
import com.cargoclear.japac.core.model.Meta
import com.cargoclear.japac.core.model.Status
import com.cargoclear.japac.ui.shell.MetaState
import com.cargoclear.japac.ui.theme.CargoClearTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class HomeContentTest {
    @get:Rule
    val compose = createComposeRule()

    private val demo = MetaState.Ready(Meta(AppMode.DEMO, "fixtures"))
    private val live = MetaState.Ready(Meta(AppMode.LIVE, "live-only"))

    private var created = 0
    private var demoRequested: DemoCase? = null
    private var chosen: Destination? = null
    private var openedText: String? = null
    private var openedRecent: String? = null
    private var forgotten: String? = null
    private var retriedMeta = false

    private fun show(meta: MetaState, state: HomeUiState = HomeUiState()) {
        compose.setContent {
            CargoClearTheme {
                HomeContent(
                    meta = meta,
                    state = state,
                    onRetryMeta = { retriedMeta = true },
                    onDestination = { chosen = it },
                    onCreateEmpty = { created++ },
                    onCreateDemo = { demoRequested = it },
                    onOpenText = { openedText = it },
                    onOpenTextChanged = {},
                    onOpenRecent = { openedRecent = it },
                    onForget = { forgotten = it },
                    showDevInfo = false,
                )
            }
        }
    }

    private val recent = RecentBundle("bnd-aaaa11112222", "CASE-C-7304-DEMO", "SG", Status.MISSING_EVIDENCE, 1, 3, System.currentTimeMillis())

    @Test
    fun the_demo_journeys_are_offered_in_demo_mode_with_their_explanations() {
        show(demo)

        compose.onNodeWithText("Start Case C demo").assertIsDisplayed().performClick()
        assertEquals(DemoCase.CASE_C, demoRequested)
        compose.onNodeWithText("Start Case D demo (India import)").assertIsDisplayed().performClick()
        assertEquals(DemoCase.CASE_D, demoRequested)
        compose.onNodeWithText("Extraction uses synthetic fixtures keyed on filename, not a real document reading.", substring = true).assertExists()
    }

    @Test
    fun a_live_backend_offers_no_demo_journeys() {
        show(live)

        compose.onNodeWithText("Start Case C demo").assertDoesNotExist()
        compose.onNodeWithText("Start Case D demo (India import)").assertDoesNotExist()
        compose.onNodeWithText("New empty bundle").assertIsDisplayed()
    }

    @Test
    fun while_the_mode_is_unknown_no_demo_journey_is_offered() {
        show(MetaState.Loading)
        compose.onNodeWithText("Start Case C demo").assertDoesNotExist()
    }

    @Test
    fun the_destination_is_chosen_before_an_empty_bundle_is_created() {
        show(live)

        compose.onNodeWithText("India (IN)").performClick()
        assertEquals(Destination.INDIA, chosen)
        compose.onNodeWithText("New empty bundle").performClick()
        assertEquals(1, created)
    }

    @Test
    fun while_a_bundle_is_being_created_every_start_button_is_disabled_and_says_so() {
        show(demo, HomeUiState(pending = Pending.EMPTY))

        compose.onNodeWithText("Creating bundle...").assertIsNotEnabled()
        compose.onNodeWithText("Start Case C demo").assertIsNotEnabled()
        compose.onNodeWithText("Singapore (SG)").assertIsNotEnabled()
    }

    @Test
    fun a_failure_to_create_is_shown_and_an_unreachable_backend_offers_retry() {
        show(MetaState.Failed("Can't reach the server. Check your connection and try again."), HomeUiState(error = "Bundle limit reached"))

        compose.onNodeWithText("Bundle limit reached").assertIsDisplayed()
        compose.onNodeWithText("Could not reach the backend: Can't reach the server. Check your connection and try again.").assertIsDisplayed()
        compose.onNodeWithText("Retry").performClick()
        assertEquals(true, retriedMeta)
    }

    @Test
    fun a_build_without_a_backend_address_says_so_and_offers_no_retry() {
        show(MetaState.Failed("This build has no backend address configured.", notConfigured = true))

        compose.onNodeWithText("This build has no backend address configured. Set cargoclear.localApiBase or cargoclear.hostedApiBase for this build.").assertIsDisplayed()
        compose.onNodeWithText("Retry").assertDoesNotExist()
    }

    @Test
    fun open_is_only_possible_with_something_typed_and_passes_the_text_on() {
        show(live)

        compose.onNodeWithText("Open").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithText("Bundle id or link").performScrollTo().performTextInput("https://ui.example/workbench/bnd-123")
        compose.onNodeWithText("Open").performScrollTo().assertIsEnabled().performClick()
        assertEquals("https://ui.example/workbench/bnd-123", openedText)
    }

    @Test
    fun text_that_is_no_bundle_id_is_refused_in_words() {
        show(live, HomeUiState(openInvalid = true))
        compose.onNodeWithText("That is not a bundle id or a CargoClear bundle link.").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun recent_bundles_show_their_last_known_status_and_open_on_tap() {
        show(live, HomeUiState(recents = listOf(recent)))

        compose.onNodeWithText("Recent bundles", ignoreCase = true).performScrollTo()
        compose.onNodeWithText("bnd-aaaa11112222").assertIsDisplayed()
        compose.onNodeWithContentDescription("Assessment status: Missing Evidence").assertIsDisplayed()
        compose.onNodeWithText("To SG").assertIsDisplayed()
        compose.onNodeWithText("3 documents").assertIsDisplayed()
        compose.onNodeWithText("Opened just now").assertIsDisplayed()
        compose.onNodeWithText("bnd-aaaa11112222").performClick()
        assertEquals("bnd-aaaa11112222", openedRecent)
    }

    @Test
    fun a_bundle_that_was_never_analysed_is_listed_as_not_assessed() {
        show(live, HomeUiState(recents = listOf(recent.copy(status = null, documentCount = 1, iteration = 0))))

        compose.onNodeWithText("bnd-aaaa11112222").performScrollTo()
        compose.onNodeWithContentDescription("Assessment status: Not assessed yet").assertIsDisplayed()
        compose.onNodeWithText("1 document").assertIsDisplayed()
    }

    @Test
    fun removing_a_bundle_from_the_list_asks_first_and_says_what_it_does_not_do() {
        show(live, HomeUiState(recents = listOf(recent)))

        compose.onNodeWithText("Remove").performScrollTo().performClick()
        compose.onNodeWithText("Remove from this phone?").assertIsDisplayed()
        compose.onNodeWithText("It stays on the server", substring = true).assertIsDisplayed()
        assertEquals(null, forgotten)

        compose.onNodeWithText("Cancel").performClick()
        assertEquals(null, forgotten)

        compose.onNodeWithText("Remove").performScrollTo().performClick()
        // the dialog's confirm button is the last "Remove" on screen (the row's own button is the first)
        compose.onAllNodesWithText("Remove").onLast().performClick()
        assertEquals("bnd-aaaa11112222", forgotten)
    }
}
