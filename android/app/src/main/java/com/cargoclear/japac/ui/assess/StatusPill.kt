package com.cargoclear.japac.ui.assess

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.Status
import com.cargoclear.japac.ui.theme.StatusColors
import com.cargoclear.japac.ui.theme.cargo

/**
 * The assessment status (port of components/assess/StatusPill.tsx). The words carry the meaning; the dot and tint repeat it.
 * [status] is null when there is no assessment yet, or the backend sent a status this app does not know ([unrecognised]): that is
 * shown as such and never as one of the four verdicts.
 */
@Composable
fun StatusPill(status: Status?, modifier: Modifier = Modifier, unrecognised: Boolean = false) {
    val tokens = MaterialTheme.cargo
    val (label, colors) = when {
        status == Status.COMPLIANT_FOR_SUBMISSION -> stringResource(R.string.status_compliant) to tokens.ok
        status == Status.MISSING_EVIDENCE -> stringResource(R.string.status_missing_evidence) to tokens.warn
        status == Status.MATERIAL_CONTRADICTION -> stringResource(R.string.status_material_contradiction) to tokens.err
        status == Status.SPECIALIST_REVIEW_REQUIRED -> stringResource(R.string.status_specialist_review) to tokens.info
        unrecognised -> stringResource(R.string.status_unrecognised) to StatusColors(tokens.textMuted, tokens.borderStrong, tokens.surface2)
        else -> stringResource(R.string.status_not_assessed) to StatusColors(tokens.textMuted, tokens.borderStrong, tokens.surface2)
    }
    val description = stringResource(R.string.status_description, label)
    Surface(
        modifier = modifier.semantics { contentDescription = description },
        shape = CircleShape,
        color = colors.bg,
        border = BorderStroke(1.dp, colors.bd),
    ) {
        Row(Modifier.padding(horizontal = 10.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Spacer(Modifier.size(8.dp).background(colors.bd, CircleShape))
            Spacer(Modifier.width(6.dp))
            Text(text = label, color = colors.fg, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}
