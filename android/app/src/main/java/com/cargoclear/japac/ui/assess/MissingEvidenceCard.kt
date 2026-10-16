package com.cargoclear.japac.ui.assess

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.MissingEvidence
import com.cargoclear.japac.ui.common.ToneCard
import com.cargoclear.japac.ui.theme.cargo

/** A document the declared HS code requires and the bundle lacks (port of components/assess/MissingEvidenceCard.tsx). */
@Composable
fun MissingEvidenceCard(item: MissingEvidence, modifier: Modifier = Modifier) {
    val tokens = MaterialTheme.cargo
    ToneCard(colors = tokens.warn, modifier = modifier) {
        Text(
            text = "⚠ " + stringResource(R.string.missing_card_title, item.documentLabel),
            color = tokens.warn.fg,
            fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.bodyMedium,
        )
        Text(
            text = stringResource(R.string.missing_card_body, item.hsCode, item.reason),
            color = tokens.text,
            style = MaterialTheme.typography.bodySmall,
        )
        item.regulationRef?.takeIf { it.isNotEmpty() }?.let {
            Text(stringResource(R.string.missing_card_ref, it), color = tokens.warn.fg, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
        }
    }
}
