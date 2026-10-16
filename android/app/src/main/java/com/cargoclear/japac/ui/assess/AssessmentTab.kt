package com.cargoclear.japac.ui.assess

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.CorrectionsUi
import com.cargoclear.japac.core.model.EvidenceTarget
import com.cargoclear.japac.core.model.PrefillFormat
import com.cargoclear.japac.core.model.RunProgress
import com.cargoclear.japac.core.model.SAMPLE_MTC_FILENAME
import com.cargoclear.japac.core.model.Severity
import com.cargoclear.japac.core.model.Status
import com.cargoclear.japac.core.model.UploadStatus
import com.cargoclear.japac.core.model.WorkbenchState
import com.cargoclear.japac.core.model.offersSampleMtc
import com.cargoclear.japac.ui.common.SectionHeading
import com.cargoclear.japac.ui.common.Tag
import com.cargoclear.japac.ui.theme.cargo
import kotlin.math.roundToInt

/**
 * The assessment of the bundle on screen (port of components/assess/AssessmentPanel.tsx). The run's progress and the failure banner are
 * shown above the tabs by [com.cargoclear.japac.ui.bundle.ActivityPanel], so they are seen from either tab.
 */
@Composable
fun AssessmentTab(
    state: WorkbenchState,
    appMode: AppMode?,
    onOpenEvidence: (EvidenceTarget) -> Unit,
    onAddDocuments: () -> Unit,
    onUseSampleMtc: () -> Unit,
    modifier: Modifier = Modifier,
    correctionsUi: CorrectionsUi = CorrectionsUi(),
    prefill: PrefillUi = PrefillUi(),
    onCorrect: (documentId: String, documentName: String, path: String) -> Unit = { _, _, _ -> },
    onRevert: (correctionId: String) -> Unit = {},
    onRecompute: () -> Unit = {},
    onSharePrefill: (PrefillFormat) -> Unit = {},
) {
    val tokens = MaterialTheme.cargo
    val assessment = state.assessment
    AnnounceStatusChanges(assessment)

    Column(
        modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(start = 16.dp, top = 16.dp, end = 16.dp, bottom = FAB_CLEARANCE),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        if (assessment == null) {
            Text(stringResource(R.string.assessment_none_title), color = tokens.text, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            Text(stringResource(R.string.assessment_none_body), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
            return@Column
        }

        AssessmentHeader(assessment)

        // Corrections by the authorised agent: what they replaced, and whether this assessment includes them
        state.corrections?.let { corrections ->
            CorrectionsCard(
                corrections = corrections,
                assessment = assessment,
                documents = state.documents,
                isRunning = state.isRunning,
                canRecompute = state.canRun,
                canUndo = state.canCorrect,
                revertingId = correctionsUi.revertingId,
                revertError = correctionsUi.revertError,
                onRevert = onRevert,
                onRecompute = onRecompute,
            )
        }

        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            SectionHeading(stringResource(R.string.checks_title))
            CheckList(
                assessment.checks,
                state.documents,
                onOpenEvidence,
                // a saved copy cannot send a correction, so it offers none
                correction = if (state.isReadOnly) null else CorrectionContext(state.corrections, assessment.corrections, state.canCorrect, onCorrect),
            )
        }

        assessment.valuation?.let { ValuationCard(it) }

        // The values of this assessment for the person who keys the declaration
        if (!state.isReadOnly) PrefillCard(assessment, state.corrections?.pending ?: 0, prefill, onShare = onSharePrefill)

        if (assessment.missingEvidence.isNotEmpty()) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                SectionHeading(stringResource(R.string.missing_title), color = tokens.warn.fg)
                assessment.missingEvidence.forEach { MissingEvidenceCard(it) }
                if (offersSampleMtc(appMode, assessment)) {
                    val busy = state.upload.let { it is UploadStatus.Active && it.filename == SAMPLE_MTC_FILENAME }
                    OutlinedButton(
                        onClick = onUseSampleMtc,
                        enabled = state.canAddDocuments && !state.isRunning,
                        modifier = Modifier.fillMaxWidth(),
                        border = BorderStroke(1.dp, tokens.focus),
                    ) { Text(stringResource(if (busy) R.string.sample_mtc_busy else R.string.sample_mtc_action), color = tokens.focus, fontWeight = FontWeight.SemiBold) }
                }
                UploadMissingButton(enabled = state.canAddDocuments, onClick = onAddDocuments)
            }
        }
    }
}

@Composable
private fun AssessmentHeader(assessment: AssessmentIteration) {
    val tokens = MaterialTheme.cargo
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        SectionHeading(stringResource(R.string.assessment_title))
        // a row that wraps: at a large system font the confidence line goes under the iteration instead of being squeezed letter by letter
        FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp), itemVerticalAlignment = Alignment.CenterVertically) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.assessment_iteration, assessment.iteration), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
                if (assessment.runMode == "recompute") Tag(stringResource(R.string.assessment_recomputed))
            }
            Text(
                text = stringResource(
                    R.string.assessment_confidence,
                    assessment.confidence?.let { "${(it.minFieldConfidence * 100).roundToInt()}%" } ?: stringResource(R.string.assessment_confidence_na),
                ),
                color = tokens.textMuted,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        // The web shows this as a tooltip; a phone has no hover, so the caveat is simply printed.
        Text(stringResource(R.string.assessment_confidence_note), color = tokens.textSubtle, fontSize = 11.sp)
    }
}

/**
 * Progress of the run the stream reports (port of `RunProgress` in AssessmentPanel.tsx). Only a run that is going counts: between asking
 * for a run and the stream reporting it, the last run on record is a finished one, and its 100% must not show.
 */
@Composable
fun RunProgressCard(run: RunProgress?, modifier: Modifier = Modifier) {
    val tokens = MaterialTheme.cargo
    val live = run?.takeIf { it.state?.isActive == true }
    val progress = (live?.progress ?: 0.0).coerceIn(0.0, 1.0)
    val stage = (live?.stage?.takeIf { it.isNotBlank() } ?: stringResource(R.string.run_stage_starting)).replaceFirstChar { it.uppercaseChar() }
    Column(
        modifier
            .fillMaxWidth()
            .clip(MaterialTheme.shapes.medium)
            .background(tokens.surface2)
            .padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(
                stringResource(R.string.run_stage, stage),
                Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                color = tokens.text,
                fontWeight = FontWeight.SemiBold,
                style = MaterialTheme.typography.bodySmall,
            )
            Text(stringResource(R.string.run_progress_percent, (progress * 100).roundToInt()), color = tokens.text, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
        }
        LinearProgressIndicator(
            progress = { progress.toFloat() },
            modifier = Modifier.fillMaxWidth().height(6.dp).clip(CircleShape),
            color = tokens.focus,
            trackColor = tokens.border,
        )
    }
}

/** The choice of files for a missing document: the system picker (port of `UploadDropzone`, which a phone has no drag and drop for). */
@Composable
private fun UploadMissingButton(enabled: Boolean, onClick: () -> Unit) {
    val tokens = MaterialTheme.cargo
    OutlinedButton(onClick = onClick, enabled = enabled, modifier = Modifier.fillMaxWidth(), border = BorderStroke(1.dp, tokens.borderStrong)) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(stringResource(R.string.missing_upload_action), color = tokens.text, fontWeight = FontWeight.SemiBold)
            Text(stringResource(R.string.upload_picker_hint), color = tokens.textMuted, fontSize = 11.sp)
        }
    }
}

/** Room under the last card for the floating Run button. */
private val FAB_CLEARANCE = 96.dp

/**
 * Tells a screen reader when the verdict changes (as the web's live region does), but not about the verdict that was there when the
 * screen opened. A contradiction is announced assertively, in the web client's words. Done with a live-region node, the supported
 * way: the node is one dp wide and carries the sentence as its description.
 */
@Composable
private fun AnnounceStatusChanges(assessment: AssessmentIteration?) {
    val material = stringResource(R.string.announce_material, assessment?.checks?.firstOrNull { it.severity == Severity.MATERIAL }?.message.orEmpty())
    val compliant = stringResource(R.string.announce_compliant)
    val missing = stringResource(R.string.announce_missing, assessment?.missingEvidence?.firstOrNull()?.documentLabel.orEmpty())
    val status = assessment?.statusKind
    var previous by remember { mutableStateOf(status) }
    var announcement by remember { mutableStateOf<String?>(null) }
    var assertive by remember { mutableStateOf(false) }
    LaunchedEffect(status) {
        if (status == previous) return@LaunchedEffect
        previous = status
        assertive = status == Status.MATERIAL_CONTRADICTION
        announcement = when (status) {
            Status.MATERIAL_CONTRADICTION -> material
            Status.COMPLIANT_FOR_SUBMISSION -> compliant
            Status.MISSING_EVIDENCE -> missing
            else -> null
        }
    }
    announcement?.let { text ->
        Box(
            Modifier
                .size(1.dp)
                .semantics {
                    contentDescription = text
                    liveRegion = if (assertive) LiveRegionMode.Assertive else LiveRegionMode.Polite
                },
        )
    }
}
