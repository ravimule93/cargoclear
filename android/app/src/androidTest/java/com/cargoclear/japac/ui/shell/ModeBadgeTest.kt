package com.cargoclear.japac.ui.shell

import androidx.compose.ui.test.assertContentDescriptionContains
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.Meta
import com.cargoclear.japac.ui.theme.CargoClearTheme
import org.junit.Rule
import org.junit.Test

class ModeBadgeTest {
    @get:Rule
    val compose = createComposeRule()

    private fun show(state: MetaState) = compose.setContent { CargoClearTheme { ModeBadge(state) } }

    @Test
    fun demo_mode_is_labelled_in_words() {
        show(MetaState.Ready(Meta(AppMode.DEMO, "fixtures")))
        compose.onNodeWithText("DEMO MODE").assertIsDisplayed().assertContentDescriptionContains("demo", substring = true, ignoreCase = true)
    }

    @Test
    fun live_mode_is_labelled_in_words() {
        show(MetaState.Ready(Meta(AppMode.LIVE, "live-only")))
        compose.onNodeWithText("LIVE GCP").assertIsDisplayed().assertContentDescriptionContains("live", substring = true, ignoreCase = true)
    }

    @Test
    fun an_unreachable_backend_says_offline_and_why() {
        show(MetaState.Failed("Can't reach the server."))
        compose.onNodeWithText("OFFLINE").assertIsDisplayed().assertContentDescriptionContains("Can't reach the server.", substring = true)
    }
}
