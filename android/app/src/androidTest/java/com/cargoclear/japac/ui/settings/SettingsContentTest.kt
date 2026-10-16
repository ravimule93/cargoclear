package com.cargoclear.japac.ui.settings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.assertIsOff
import com.cargoclear.japac.ui.theme.CargoClearTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class SettingsContentTest {
    @get:Rule
    val compose = createComposeRule()

    private var changed: Boolean? = null
    private var notifyChanged: Boolean? = null
    private var cleared = 0

    private fun show(secure: Boolean, bytes: Long, notify: Boolean = false, notifyDenied: Boolean = false) {
        compose.setContent {
            CargoClearTheme {
                SettingsContent(
                    secure, bytes, onBack = {}, onSecureChange = { changed = it }, onClearCache = { cleared++ },
                    notify = notify, notifyDenied = notifyDenied, onNotifyChange = { notifyChanged = it },
                )
            }
        }
    }

    private val screenshotSwitch get() = isToggleable() and hasText("Block screenshots in the document viewer", substring = true)
    private val notifySwitch get() = isToggleable() and hasText("Tell me when an analysis finishes", substring = true)

    @Test
    fun the_screenshot_switch_is_one_labelled_control_that_reads_on_and_changes_when_tapped() {
        show(secure = true, bytes = 0)
        compose.onNodeWithText("Block screenshots in the document viewer").assertIsDisplayed()
        compose.onNode(screenshotSwitch).assertIsOn().performClick()
        assertEquals(false, changed)
    }

    @Test
    fun the_switch_reads_off_when_screenshots_are_allowed() {
        show(secure = false, bytes = 0)
        compose.onNode(screenshotSwitch).assertIsOff()
    }

    @Test
    fun the_size_of_the_downloaded_documents_is_shown_and_they_can_be_cleared() {
        show(secure = true, bytes = 2_000_000)
        compose.onNode(hasText("Using ", substring = true)).assertIsDisplayed()
        compose.onNodeWithText("Clear downloaded documents").performClick()
        assertEquals(1, cleared)
    }

    @Test
    fun with_nothing_downloaded_there_is_nothing_to_clear() {
        show(secure = true, bytes = 0)
        compose.onNodeWithText("Clear downloaded documents").assertIsNotEnabled()
    }

    @Test
    fun the_settings_say_clearing_touches_nothing_on_the_server() {
        show(secure = true, bytes = 1)
        compose.onNode(hasText("deletes nothing on the server", substring = true)).assertIsDisplayed()
    }

    @Test
    fun the_notify_switch_is_off_until_asked_for_and_turns_on_when_tapped() {
        show(secure = true, bytes = 0, notify = false)
        compose.onNode(notifySwitch).assertIsOff().performClick()
        assertEquals(true, notifyChanged)
    }

    @Test
    fun the_notify_switch_reads_on_and_turns_off_when_tapped() {
        show(secure = true, bytes = 0, notify = true)
        compose.onNode(notifySwitch).assertIsOn().performClick()
        assertEquals(false, notifyChanged)
    }

    @Test
    fun the_notify_text_says_the_lock_screen_shows_no_bundle() {
        show(secure = true, bytes = 0)
        compose.onNode(hasText("The lock screen only says that one did, not which bundle.", substring = true)).assertIsDisplayed()
    }

    @Test
    fun a_refusal_of_the_permission_is_explained_beside_the_switch() {
        show(secure = true, bytes = 0, notify = false, notifyDenied = true)
        compose.onNodeWithText("Notifications are switched off for this app in the system settings, so none can be shown.").assertIsDisplayed()
    }

    @Test
    fun no_refusal_is_shown_when_the_switch_is_on() {
        show(secure = true, bytes = 0, notify = true, notifyDenied = true)
        compose.onNodeWithText("Notifications are switched off for this app in the system settings, so none can be shown.").assertDoesNotExist()
    }
}
