package com.cargoclear.japac.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.ui.graphics.Color

/** One status family: text colour, boundary colour, tinted surface (the `-text`, `-bd`, `-bg` tokens of the web UI). */
@Immutable
class StatusColors(val fg: Color, val bd: Color, val bg: Color)

/**
 * The design tokens of frontend/app/globals.css, value for value. The web file is the WCAG 2.2 AA audit artifact (it documents the
 * contrast ratio of every pair), so these hex values are copied, not re-picked. Status colours are fixed and never taken from the
 * wallpaper: a status must look the same on every device.
 */
@Immutable
class CargoClearColors(
    val bg: Color,
    val surface: Color,
    val surface2: Color,
    val border: Color,
    val borderStrong: Color,
    val text: Color,
    val textMuted: Color,
    val textSubtle: Color,
    val focus: Color,
    /** Text and icons on a [focus]-coloured button: white on the light blue, the page background on the dark theme's lighter blue (white is too thin on it). */
    val onFocus: Color,
    val ok: StatusColors,
    val warn: StatusColors,
    val err: StatusColors,
    val info: StatusColors,
)

val LightTokens = CargoClearColors(
    bg = Color(0xFFF4F6F9),
    surface = Color(0xFFFFFFFF),
    surface2 = Color(0xFFFAFBFC),
    border = Color(0xFFE3E7ED),
    borderStrong = Color(0xFF6B7684),
    text = Color(0xFF12161C),
    textMuted = Color(0xFF4A5462),
    textSubtle = Color(0xFF5F6B7A),
    focus = Color(0xFF1A56DB),
    onFocus = Color(0xFFFFFFFF),
    ok = StatusColors(Color(0xFF146C2E), Color(0xFF1E8E3E), Color(0xFFE6F4EA)),
    warn = StatusColors(Color(0xFF8A5300), Color(0xFFC77700), Color(0xFFFFF4E0)),
    err = StatusColors(Color(0xFFB3261E), Color(0xFFD93025), Color(0xFFFDECEA)),
    info = StatusColors(Color(0xFF5B2DA8), Color(0xFF7C4DFF), Color(0xFFF0EBFF)),
)

val DarkTokens = CargoClearColors(
    bg = Color(0xFF0F1319),
    surface = Color(0xFF161B22),
    surface2 = Color(0xFF1C222B),
    border = Color(0xFF2A313B),
    borderStrong = Color(0xFF8B949E),
    text = Color(0xFFE6EDF3),
    textMuted = Color(0xFFB1BAC4),
    textSubtle = Color(0xFF8B949E),
    focus = Color(0xFF58A6FF),
    onFocus = Color(0xFF0F1319),
    ok = StatusColors(Color(0xFF4ADE80), Color(0xFF4ADE80), Color(0xFF0F2A1A)),
    warn = StatusColors(Color(0xFFFBBF24), Color(0xFFFBBF24), Color(0xFF2E2205)),
    err = StatusColors(Color(0xFFF87171), Color(0xFFF87171), Color(0xFF2E0F0F)),
    info = StatusColors(Color(0xFFA78BFA), Color(0xFFA78BFA), Color(0xFF1E1533)),
)
