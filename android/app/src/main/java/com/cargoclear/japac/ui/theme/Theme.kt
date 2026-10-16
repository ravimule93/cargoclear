package com.cargoclear.japac.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp

val LocalCargoClearColors = staticCompositionLocalOf { LightTokens }

/** The CargoClear-specific tokens (status families, subtle text, borders) next to Material's own: `MaterialTheme.cargo.warn.bg`. */
val MaterialTheme.cargo: CargoClearColors
    @Composable
    @ReadOnlyComposable
    get() = LocalCargoClearColors.current

private fun CargoClearColors.toMaterial(dark: Boolean): ColorScheme {
    // Text on the primary (focus) colour: see [CargoClearColors.onFocus] (the web UI puts white on #58A6FF, which is thin there).
    val onPrimary = onFocus
    val base = if (dark) darkColorScheme() else lightColorScheme()
    return base.copy(
        primary = focus,
        onPrimary = onPrimary,
        background = bg,
        onBackground = text,
        surface = surface,
        onSurface = text,
        surfaceVariant = surface2,
        onSurfaceVariant = textMuted,
        outline = borderStrong,
        outlineVariant = border,
        error = err.fg,
        onError = if (dark) bg else Color.White,
        errorContainer = err.bg,
        onErrorContainer = err.fg,
    )
}

@Composable
fun CargoClearTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val tokens = if (darkTheme) DarkTokens else LightTokens
    CompositionLocalProvider(LocalCargoClearColors provides tokens) {
        MaterialTheme(
            colorScheme = tokens.toMaterial(darkTheme),
            // --cc-radius: 8px
            shapes = Shapes(
                extraSmall = RoundedCornerShape(4.dp),
                small = RoundedCornerShape(8.dp),
                medium = RoundedCornerShape(8.dp),
                large = RoundedCornerShape(12.dp),
                extraLarge = RoundedCornerShape(16.dp),
            ),
            content = content,
        )
    }
}
