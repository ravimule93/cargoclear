package com.cargoclear.japac.core.model

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WindowLayoutTest {
    @Test
    fun `a tablet or an unfolded foldable shows two panes`() {
        assertTrue(isTwoPane(widthDp = 1280, heightDp = 800))
        assertTrue(isTwoPane(widthDp = 840, heightDp = 900))
        assertTrue(isTwoPane(widthDp = 900, heightDp = 600))
    }

    @Test
    fun `a phone keeps one pane, upright or on its side`() {
        assertFalse(isTwoPane(widthDp = 412, heightDp = 915))
        assertFalse("wide but not tall", isTwoPane(widthDp = 915, heightDp = 412))
        assertFalse(isTwoPane(widthDp = 800, heightDp = 360))
    }

    @Test
    fun `a medium window is too narrow to split`() {
        assertFalse(isTwoPane(widthDp = 600, heightDp = 1024))
        assertFalse(isTwoPane(widthDp = 839, heightDp = 900))
    }

    @Test
    fun `the thresholds are inclusive`() {
        assertTrue(isTwoPane(TWO_PANE_MIN_WIDTH_DP, TWO_PANE_MIN_HEIGHT_DP))
        assertFalse(isTwoPane(TWO_PANE_MIN_WIDTH_DP - 1, TWO_PANE_MIN_HEIGHT_DP))
        assertFalse(isTwoPane(TWO_PANE_MIN_WIDTH_DP, TWO_PANE_MIN_HEIGHT_DP - 1))
    }
}
