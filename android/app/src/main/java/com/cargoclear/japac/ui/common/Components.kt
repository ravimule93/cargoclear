package com.cargoclear.japac.ui.common

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.ui.theme.StatusColors
import com.cargoclear.japac.ui.theme.cargo

/** A small bordered label ("To SG", a document type, a reference). */
@Composable
fun Tag(text: String, modifier: Modifier = Modifier, mono: Boolean = false, colors: StatusColors? = null) {
    val tokens = MaterialTheme.cargo
    val fg = colors?.fg ?: tokens.textMuted
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(4.dp),
        color = colors?.bg ?: tokens.surface2,
        border = BorderStroke(1.dp, colors?.bd ?: tokens.border),
    ) {
        Text(
            text = text,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
            color = fg,
            fontSize = 11.sp,
            fontWeight = if (colors != null) FontWeight.Bold else FontWeight.Normal,
            fontFamily = if (mono) FontFamily.Monospace else null,
        )
    }
}

/** A tinted block with a coloured border: the card every message, warning and finding of the assessment sits in. */
@Composable
fun ToneCard(
    colors: StatusColors,
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(12.dp),
    content: @Composable () -> Unit,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.medium,
        color = colors.bg,
        border = BorderStroke(1.dp, colors.bd),
    ) {
        Column(Modifier.padding(contentPadding), verticalArrangement = Arrangement.spacedBy(6.dp)) { content() }
    }
}

/** The neutral card (surface 2 with a hairline border) of the corrections, valuation and pre-fill sections. */
@Composable
fun PlainCard(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val tokens = MaterialTheme.cargo
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.medium,
        color = tokens.surface2,
        border = BorderStroke(1.dp, tokens.border),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) { content() }
    }
}

/** Small upper-case section heading (the web's `text-xs font-bold uppercase`). */
@Composable
fun SectionHeading(text: String, modifier: Modifier = Modifier, color: Color = MaterialTheme.cargo.textSubtle) {
    Text(
        text = text.uppercase(),
        modifier = modifier,
        color = color,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.Bold,
        letterSpacing = 0.6.sp,
    )
}

/** "just now", "5 min. ago", "2 hr. ago", "Oct 12": how long ago something happened, for a person (the platform's own wording, in the phone's language). */
@Composable
fun relativeTime(timestampMillis: Long, nowMillis: Long = System.currentTimeMillis()): String =
    if (nowMillis - timestampMillis < 60_000) {
        androidx.compose.ui.res.stringResource(com.cargoclear.japac.R.string.time_just_now)
    } else {
        android.text.format.DateUtils.getRelativeTimeSpanString(
            timestampMillis,
            nowMillis,
            android.text.format.DateUtils.MINUTE_IN_MILLIS,
            android.text.format.DateUtils.FORMAT_ABBREV_RELATIVE,
        ).toString()
    }
