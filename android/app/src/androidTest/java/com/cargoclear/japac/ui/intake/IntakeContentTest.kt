package com.cargoclear.japac.ui.intake

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import com.cargoclear.japac.core.data.InboxFiles
import com.cargoclear.japac.core.data.RecentBundle
import com.cargoclear.japac.core.model.Destination
import com.cargoclear.japac.core.model.Status
import com.cargoclear.japac.ui.theme.CargoClearTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** PDFs shared to the app: the screen that asks which bundle they belong to. */
class IntakeContentTest {
    @get:Rule
    val compose = createComposeRule()

    private val chosen = mutableListOf<String>()
    private var created = 0
    private var backs = 0
    private val destinations = mutableListOf<Destination>()

    private fun file(name: String, bytes: Long = 12_000) = InboxFiles.Imported("file:/inbox/1-0/$name", name, bytes)

    private fun recent(id: String) = RecentBundle(id, "REF-$id", "SG", Status.MISSING_EVIDENCE, 1, 3, 1L)

    private fun show(files: IntakeFiles, state: IntakeUi = IntakeUi(), recent: List<RecentBundle> = emptyList()) {
        compose.setContent {
            CargoClearTheme {
                IntakeContent(
                    files = files,
                    state = state,
                    recent = recent,
                    onDestination = { destinations += it },
                    onCreate = { created++ },
                    onAddTo = { chosen += it.bundleId },
                    onBack = { backs++ },
                )
            }
        }
    }

    @Test
    fun the_shared_files_are_listed_by_name_and_count() {
        show(IntakeFiles(listOf(file("invoice.pdf"), file("packing_list.pdf")), unreadable = 0))
        compose.onNodeWithText("2 PDFs shared", ignoreCase = true).assertIsDisplayed()
        compose.onNodeWithText("invoice.pdf").assertIsDisplayed()
        compose.onNodeWithText("packing_list.pdf").assertIsDisplayed()
    }

    @Test
    fun a_new_bundle_can_be_made_for_either_destination() {
        show(IntakeFiles(listOf(file("a.pdf")), 0))
        compose.onNodeWithText("India (IN)").performClick()
        assertEquals(listOf(Destination.INDIA), destinations)
        compose.onNodeWithText("Create a bundle with these files").performClick()
        assertEquals(1, created)
    }

    @Test
    fun busy_creation_says_so_and_waits() {
        show(IntakeFiles(listOf(file("a.pdf")), 0), state = IntakeUi(busy = true))
        compose.onNodeWithText("Creating bundle...").assertIsNotEnabled()
    }

    @Test
    fun a_recent_bundle_can_be_chosen_and_the_row_says_what_it_does() {
        show(IntakeFiles(listOf(file("a.pdf")), 0), recent = listOf(recent("bnd-1"), recent("bnd-2")))
        compose.onNodeWithText("bnd-2").performScrollTo().performClick()
        assertEquals(listOf("bnd-2"), chosen)
    }

    @Test
    fun with_no_recent_bundles_that_is_said() {
        show(IntakeFiles(listOf(file("a.pdf")), 0))
        compose.onNodeWithText("No recent bundles on this phone yet.").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun files_that_could_not_be_read_are_counted() {
        show(IntakeFiles(listOf(file("a.pdf")), unreadable = 2))
        compose.onNodeWithText("2 shared files could not be read and were left out.").assertIsDisplayed()
    }

    @Test
    fun when_none_can_be_read_there_is_nothing_to_choose_and_cancel_leaves() {
        show(IntakeFiles(emptyList(), unreadable = 1))
        compose.onNodeWithText("None of the shared files could be read.").assertIsDisplayed()
        compose.onNodeWithText("Create a bundle with these files").assertDoesNotExist()
        compose.onNodeWithText("Cancel").performScrollTo().performClick()
        assertEquals(1, backs)
    }

    @Test
    fun a_failure_to_create_is_said_in_the_servers_words() {
        show(IntakeFiles(listOf(file("a.pdf")), 0), state = IntakeUi(error = "Can't reach the server. Check your connection and try again."))
        compose.onNodeWithText("Can't reach the server. Check your connection and try again.").performScrollTo().assertIsDisplayed()
    }
}
