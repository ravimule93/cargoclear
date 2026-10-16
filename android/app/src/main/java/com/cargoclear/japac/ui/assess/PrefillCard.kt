package com.cargoclear.japac.ui.assess

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.PrefillCaveat
import com.cargoclear.japac.core.model.PrefillFormat
import com.cargoclear.japac.core.model.prefillCaveat
import com.cargoclear.japac.ui.common.PlainCard
import com.cargoclear.japac.ui.common.SectionHeading
import com.cargoclear.japac.ui.theme.cargo

/**
 * Declaration pre-fill: the values of this assessment, with where each came from, for the person who keys the declaration (port of
 * components/assess/PrefillCard.tsx). It is CargoClear's own documented format (not a government one) and never says a declaration is
 * ready to file. The web offers downloads; here the pack is prepared on the phone and handed to the system share sheet.
 */
@Composable
fun PrefillCard(
    assessment: AssessmentIteration,
    pendingCorrections: Int,
    state: PrefillUi,
    onShare: (PrefillFormat) -> Unit,
    modifier: Modifier = Modifier,
) {
    val tokens = MaterialTheme.cargo
    val caveat = prefillCaveat(assessment, pendingCorrections)
    val busy = state.busy != null

    PlainCard(modifier) {
        SectionHeading(stringResource(R.string.prefill_title))
        Text(stringResource(R.string.prefill_body), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
        Text(
            text = when (caveat) {
                PrefillCaveat.NotCleared -> stringResource(R.string.prefill_caveat_not_cleared)
                is PrefillCaveat.Pending -> stringResource(R.string.prefill_caveat_pending, caveat.count)
                PrefillCaveat.ClearedWithAllCorrections -> stringResource(R.string.prefill_caveat_cleared)
            },
            color = if (caveat.reassuring) tokens.ok.fg else tokens.warn.fg,
            fontWeight = FontWeight.SemiBold,
            style = MaterialTheme.typography.bodySmall,
        )
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            for ((format, label) in listOf(PrefillFormat.JSON to R.string.prefill_share_json, PrefillFormat.PDF to R.string.prefill_share_pdf)) {
                OutlinedButton(
                    onClick = { onShare(format) },
                    enabled = !busy,
                    modifier = Modifier.defaultMinSize(minHeight = 48.dp),
                    border = BorderStroke(1.dp, tokens.borderStrong),
                ) {
                    Text(stringResource(if (state.busy == format) R.string.prefill_busy else label), color = if (busy) tokens.textSubtle else tokens.focus, fontWeight = FontWeight.SemiBold)
                }
            }
        }
        Text(stringResource(R.string.prefill_note), color = tokens.textSubtle, fontSize = 11.sp)
        state.error?.let {
            Text(it, Modifier.semantics { liveRegion = LiveRegionMode.Assertive }, color = tokens.err.fg, fontWeight = FontWeight.Medium, style = MaterialTheme.typography.bodySmall)
        }
    }
}
