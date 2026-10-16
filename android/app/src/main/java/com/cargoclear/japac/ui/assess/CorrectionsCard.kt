package com.cargoclear.japac.ui.assess

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.CorrectionKind
import com.cargoclear.japac.core.model.CorrectionRecord
import com.cargoclear.japac.core.model.CorrectionStatus
import com.cargoclear.japac.core.model.CorrectionsResponse
import com.cargoclear.japac.core.model.DocumentRecord
import com.cargoclear.japac.core.model.correctionStatus
import com.cargoclear.japac.core.model.pathLabel
import com.cargoclear.japac.core.model.shownValue
import com.cargoclear.japac.ui.common.PlainCard
import com.cargoclear.japac.ui.common.SectionHeading
import com.cargoclear.japac.ui.common.Tag
import com.cargoclear.japac.ui.theme.cargo

/**
 * The corrections made by the authorised agent, what each replaced, and whether the assessment on screen already includes it (port of
 * components/assess/CorrectionsCard.tsx). A correction changes nothing by itself: "Recompute" re-runs the checks on the stored extraction
 * (no document is read again, no model is called).
 */
@Composable
fun CorrectionsCard(
    corrections: CorrectionsResponse,
    assessment: AssessmentIteration,
    documents: List<DocumentRecord>,
    isRunning: Boolean,
    canRecompute: Boolean,
    canUndo: Boolean,
    revertingId: String?,
    revertError: String?,
    onRevert: (String) -> Unit,
    onRecompute: () -> Unit,
    modifier: Modifier = Modifier,
) {
    if (corrections.effective.isEmpty() && corrections.pending == 0) return
    val tokens = MaterialTheme.cargo
    val docName = { id: String -> documents.firstOrNull { it.documentId == id }?.filename ?: id }

    PlainCard(modifier) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Top) {
            SectionHeading(stringResource(R.string.corrections_title, corrections.effective.size), Modifier.weight(1f).padding(end = 8.dp))
            if (corrections.pending > 0) {
                Tag(stringResource(R.string.corrections_pending_chip, corrections.pending).uppercase(), colors = tokens.warn)
            }
        }

        corrections.effective.forEach { entry ->
            CorrectionEntry(
                entry = entry,
                documentName = docName(entry.documentId),
                status = correctionStatus(entry, assessment),
                undoEnabled = canUndo && revertingId == null,
                onUndo = { onRevert(entry.correctionId) },
            )
        }

        revertError?.let {
            Text(it, Modifier.semantics { liveRegion = LiveRegionMode.Assertive }, color = tokens.err.fg, fontWeight = FontWeight.Medium, style = MaterialTheme.typography.bodySmall)
        }

        if (corrections.pending > 0) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Button(
                    onClick = onRecompute,
                    enabled = canRecompute,
                    modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = 48.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = tokens.focus, contentColor = tokens.onFocus),
                ) {
                    Text(stringResource(if (isRunning) R.string.recompute_busy else R.string.recompute_action), fontWeight = FontWeight.SemiBold)
                }
                Text(stringResource(R.string.recompute_note), color = tokens.textMuted, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun CorrectionEntry(entry: CorrectionRecord, documentName: String, status: CorrectionStatus, undoEnabled: Boolean, onUndo: () -> Unit) {
    val tokens = MaterialTheme.cargo
    val label = pathLabel(entry.path)
    val kind = stringResource(if (entry.kind == CorrectionKind.CONFIRMATION) R.string.correction_kind_confirmation else R.string.correction_kind_correction)
    val undoDescription = stringResource(R.string.correction_undo_description, kind, label, documentName)

    Surface(Modifier.fillMaxWidth(), shape = MaterialTheme.shapes.small, color = tokens.surface, border = BorderStroke(1.dp, tokens.border)) {
        Column(Modifier.padding(start = 10.dp, top = 6.dp, end = 4.dp, bottom = 8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = buildAnnotated(label, documentName),
                    modifier = Modifier.weight(1f).padding(end = 4.dp),
                    style = MaterialTheme.typography.bodySmall,
                )
                TextButton(
                    onClick = onUndo,
                    enabled = undoEnabled,
                    modifier = Modifier.defaultMinSize(minHeight = 48.dp).semantics { contentDescription = undoDescription },
                ) { Text(stringResource(R.string.correction_undo), fontWeight = FontWeight.SemiBold, color = if (undoEnabled) tokens.focus else tokens.textSubtle) }
            }
            Column(Modifier.padding(end = 10.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                if (entry.kind == CorrectionKind.CONFIRMATION) {
                    Text(
                        stringResource(R.string.correction_confirmed, shownValue(entry.value, entry.unit ?: entry.originalUnit)),
                        color = tokens.text, fontFamily = FontFamily.Monospace, fontSize = 12.sp,
                    )
                } else {
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(shownValue(entry.originalValue, entry.originalUnit), color = tokens.textMuted, fontFamily = FontFamily.Monospace, fontSize = 12.sp, textDecoration = TextDecoration.LineThrough)
                        Text("→", color = tokens.text, fontFamily = FontFamily.Monospace, fontSize = 12.sp)
                        Text(shownValue(entry.value, entry.unit ?: entry.originalUnit), color = tokens.text, fontFamily = FontFamily.Monospace, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                    }
                }
                entry.reason?.takeIf { it.isNotBlank() }?.let { Text("“$it”", color = tokens.textMuted, style = MaterialTheme.typography.bodySmall) }
                val (text, ok) = when (status) {
                    CorrectionStatus.InAssessment -> stringResource(R.string.correction_status_in) to true
                    is CorrectionStatus.NotUsed -> stringResource(R.string.correction_status_not_used, status.note ?: stringResource(R.string.correction_status_not_used_default)) to false
                    CorrectionStatus.PendingRecompute -> stringResource(R.string.correction_status_pending) to false
                }
                // never colour alone: the words say what the colour says, and a glyph leads them
                Text((if (ok) "✓ " else "▲ ") + text, color = if (ok) tokens.ok.fg else tokens.warn.fg, fontWeight = FontWeight.Bold, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun buildAnnotated(label: String, documentName: String) = androidx.compose.ui.text.buildAnnotatedString {
    val tokens = MaterialTheme.cargo
    pushStyle(androidx.compose.ui.text.SpanStyle(fontWeight = FontWeight.SemiBold, color = tokens.text))
    append(label)
    pop()
    pushStyle(androidx.compose.ui.text.SpanStyle(color = tokens.textMuted))
    append(" · $documentName")
    pop()
}
