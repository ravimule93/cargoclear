package com.cargoclear.japac.ui.theme

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import kotlin.math.pow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The colour pairs the screens actually draw, against WCAG 2.2's contrast ratios: 4.5:1 for text, 3:1 for the lines and icons that carry
 * meaning. The tokens are the web UI's (its globals.css documents them as audited); this checks that this app puts them only where they pass,
 * in both themes.
 */
class ContrastTest {
    private fun channel(value: Int): Double {
        val c = value / 255.0
        return if (c <= 0.03928) c / 12.92 else ((c + 0.055) / 1.055).pow(2.4)
    }

    private fun luminance(color: Color): Double {
        val argb = color.toArgb()
        return 0.2126 * channel((argb shr 16) and 0xFF) + 0.7152 * channel((argb shr 8) and 0xFF) + 0.0722 * channel(argb and 0xFF)
    }

    private fun ratio(a: Color, b: Color): Double {
        val (hi, lo) = luminance(a).let { la -> luminance(b).let { lb -> if (la > lb) la to lb else lb to la } }
        return (hi + 0.05) / (lo + 0.05)
    }

    private val themes = mapOf("light" to LightTokens, "dark" to DarkTokens)

    private fun atLeast(minimum: Double, name: String, theme: String, a: Color, b: Color, failures: MutableList<String>) {
        val r = ratio(a, b)
        if (r < minimum) failures += "$theme: $name is %.2f:1, needs %.1f:1".format(r, minimum)
    }

    @Test
    fun `the ratio is computed the way WCAG defines it`() {
        assertEquals(21.0, ratio(Color.Black, Color.White), 0.01)
        assertEquals(1.0, ratio(Color.White, Color.White), 0.001)
        assertEquals(4.54, ratio(Color(0xFF767676), Color.White), 0.01) // the usual "just passes" grey
    }

    @Test
    fun `body text passes on every surface it is drawn on`() {
        val failures = mutableListOf<String>()
        for ((theme, t) in themes) for ((surfaceName, surface) in listOf("bg" to t.bg, "surface" to t.surface, "surface2" to t.surface2)) {
            atLeast(4.5, "text on $surfaceName", theme, t.text, surface, failures)
            atLeast(4.5, "textMuted on $surfaceName", theme, t.textMuted, surface, failures)
            atLeast(4.5, "textSubtle on $surfaceName", theme, t.textSubtle, surface, failures)
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    @Test
    fun `status colours pass as text on their own tint and on the page`() {
        val failures = mutableListOf<String>()
        for ((theme, t) in themes) for ((name, status) in listOf("ok" to t.ok, "warn" to t.warn, "err" to t.err, "info" to t.info)) {
            atLeast(4.5, "$name text on its tint", theme, status.fg, status.bg, failures)
            atLeast(4.5, "$name text on the page", theme, status.fg, t.bg, failures)
            atLeast(4.5, "$name text on a card", theme, status.fg, t.surface, failures)
            atLeast(3.0, "$name outline on its tint", theme, status.bd, status.bg, failures)
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    @Test
    fun `links and the focus colour pass as text, and buttons in it carry readable text`() {
        val failures = mutableListOf<String>()
        for ((theme, t) in themes) {
            for ((surfaceName, surface) in listOf("bg" to t.bg, "surface" to t.surface, "surface2" to t.surface2)) atLeast(4.5, "focus-coloured text on $surfaceName", theme, t.focus, surface, failures)
            atLeast(4.5, "text on a button in the focus colour", theme, t.onFocus, t.focus, failures)
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    @Test
    fun `the strong border that outlines controls is visible against what it sits on`() {
        val failures = mutableListOf<String>()
        for ((theme, t) in themes) for ((surfaceName, surface) in listOf("bg" to t.bg, "surface" to t.surface, "surface2" to t.surface2)) {
            atLeast(3.0, "borderStrong on $surfaceName", theme, t.borderStrong, surface, failures)
        }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }

    @Test
    fun `a disabled button is allowed to be dim, but its text is still not lost`() {
        // disabled controls are exempt from WCAG's ratio; this only keeps them from vanishing (the run button draws textMuted on surface2 while it waits)
        val failures = mutableListOf<String>()
        for ((theme, t) in themes) atLeast(3.0, "textMuted on surface2", theme, t.textMuted, t.surface2, failures)
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }
}
