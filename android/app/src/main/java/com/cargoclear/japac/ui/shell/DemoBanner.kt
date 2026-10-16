package com.cargoclear.japac.ui.shell

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.cargoclear.japac.core.model.DEMO_BANNER_TEXT
import com.cargoclear.japac.ui.theme.cargo

/** States on every demo screen that the extraction is synthetic (port of components/shell/DemoBanner.tsx; the text is shared, not retyped). */
@Composable
fun DemoBanner(modifier: Modifier = Modifier) {
    val tokens = MaterialTheme.cargo
    Text(
        text = DEMO_BANNER_TEXT,
        modifier = modifier
            .fillMaxWidth()
            .background(tokens.warn.bg)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        color = tokens.warn.fg,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.SemiBold,
    )
}
