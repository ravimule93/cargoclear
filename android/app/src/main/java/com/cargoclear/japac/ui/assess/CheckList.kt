package com.cargoclear.japac.ui.assess

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.AppliedCorrection
import com.cargoclear.japac.core.model.CheckResult
import com.cargoclear.japac.core.model.CorrectionsResponse
import com.cargoclear.japac.core.model.DocumentRecord
import com.cargoclear.japac.core.model.EvidenceCorrection
import com.cargoclear.japac.core.model.EvidenceRef
import com.cargoclear.japac.core.model.EvidenceTarget
import com.cargoclear.japac.core.model.evidenceTarget
import com.cargoclear.japac.core.model.Severity
import com.cargoclear.japac.core.model.checkTitle
import com.cargoclear.japac.core.model.editablePath
import com.cargoclear.japac.core.model.evidenceCorrection
import com.cargoclear.japac.core.model.pathLabel
import com.cargoclear.japac.ui.common.Tag
import com.cargoclear.japac.ui.common.ToneCard
import com.cargoclear.japac.ui.theme.StatusColors
import com.cargoclear.japac.ui.theme.cargo

/** Evidence entries shown before "Show all": a certificate's table can cite dozens of cells. */
private const val EVIDENCE_PREVIEW = 5

/**
 * What the check list needs to offer corrections: what is in force, what the assessment on screen used, whether editing is allowed right
 * now (not during a run, not from a saved copy) and what to do when a value's Edit is tapped. Without one, the list is read-only.
 */
class CorrectionContext(
    val corrections: CorrectionsResponse?,
    val applied: List<AppliedCorrection>,
    val enabled: Boolean,
    val onCorrect: (documentId: String, documentName: String, path: String) -> Unit,
)

/**
 * The checks of an assessment (port of components/assess/CheckList.tsx): issues first, the passed ones behind a toggle, each with the
 * documents and values it compared. Tapping an evidence row opens the viewer on the page it cites, with its box chosen. With a
 * [correction] context, an evidence row that shows one extracted value can be corrected in place (Edit under the row).
 */
@Composable
fun CheckList(
    checks: List<CheckResult>,
    documents: List<DocumentRecord>,
    onOpenEvidence: (EvidenceTarget) -> Unit,
    modifier: Modifier = Modifier,
    correction: CorrectionContext? = null,
) {
    val tokens = MaterialTheme.cargo
    if (checks.isEmpty()) {
        Text(stringResource(R.string.checks_none), modifier, color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
        return
    }
    val docMap = documents.associateBy { it.documentId }
    // each check keeps its place in the assessment: it is part of the id of the boxes the viewer draws for it
    val issues = checks.withIndex().filter { it.value.severity != Severity.PASS }
    val passed = checks.withIndex().filter { it.value.severity == Severity.PASS }
    var showPassed by rememberSaveable { mutableStateOf(false) }

    Column(modifier, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (issues.isNotEmpty()) {
            Text(
                text = "⚠ " + stringResource(R.string.checks_issues, issues.size),
                color = tokens.err.fg,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
            )
            issues.forEachIndexed { i, (index, check) -> CheckCard(check, index, "issue:$i", docMap, onOpenEvidence, correction) }
        }
        if (passed.isNotEmpty()) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .clickable(role = Role.Button) { showPassed = !showPassed }
                    .padding(vertical = 10.dp, horizontal = 6.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "✓ " + stringResource(R.string.checks_verified, passed.size),
                    color = tokens.ok.fg,
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = (if (showPassed) "▲ " else "▼ ") +
                        if (showPassed) stringResource(R.string.checks_verified_hide) else stringResource(R.string.checks_verified_show, passed.size),
                    color = tokens.textMuted,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
            if (showPassed) passed.forEachIndexed { i, (index, check) -> CheckCard(check, index, "pass:$i", docMap, onOpenEvidence, correction) }
        }
    }
}

@Composable
private fun severityColors(severity: Severity): StatusColors = with(MaterialTheme.cargo) {
    when (severity) {
        Severity.PASS -> ok
        Severity.WARN -> warn
        Severity.MATERIAL -> err
    }
}

@Composable
private fun CheckCard(
    check: CheckResult,
    checkIndex: Int,
    key: String,
    docs: Map<String, DocumentRecord>,
    onOpenEvidence: (EvidenceTarget) -> Unit,
    correction: CorrectionContext?,
) {
    val tokens = MaterialTheme.cargo
    val colors = severityColors(check.severity)
    val isPass = check.severity == Severity.PASS
    val evidence = check.evidence.orEmpty()
    var allEvidence by rememberSaveable(key) { mutableStateOf(false) }
    var ruleSetOpen by rememberSaveable(key) { mutableStateOf(false) }
    val shown = if (allEvidence) evidence else evidence.take(EVIDENCE_PREVIEW)

    val body: @Composable () -> Unit = {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f).padding(end = 8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(checkTitle(check.checkId), color = tokens.text, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                Text(check.checkId, color = tokens.textSubtle, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
            }
            Tag(
                text = when (check.severity) {
                    Severity.PASS -> "✓ " + stringResource(R.string.severity_pass)
                    Severity.WARN -> "▲ " + stringResource(R.string.severity_warn)
                    Severity.MATERIAL -> "● " + stringResource(R.string.severity_material)
                },
                colors = colors,
            )
        }

        Text(check.message, color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)

        if (check.assumptions.isNotEmpty()) {
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(stringResource(R.string.check_assumed), color = tokens.text, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
                check.assumptions.forEach { Text("• $it", color = tokens.textMuted, style = MaterialTheme.typography.bodySmall) }
            }
        }

        check.ruleSet?.let { ruleSet ->
            Column(
                Modifier.clickable(role = Role.Button) { ruleSetOpen = !ruleSetOpen },
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                Text(
                    text = (if (ruleSetOpen) "▾ " else "▸ ") + stringResource(R.string.check_rule_set, ruleSet),
                    color = tokens.textSubtle,
                    fontSize = 11.sp,
                )
                if (ruleSetOpen && check.regulationRef != null) {
                    Text(check.regulationRef!!, color = tokens.textSubtle, fontSize = 11.sp)
                }
            }
        }

        if (evidence.isNotEmpty()) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    stringResource(R.string.check_evidence_title).uppercase(),
                    color = tokens.textSubtle,
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Bold,
                )
                shown.forEachIndexed { i, ev -> EvidenceRow(ev, docs, evidenceTarget(check, checkIndex, ev, i), onOpenEvidence, correction) }
                if (evidence.size > EVIDENCE_PREVIEW) {
                    Text(
                        text = if (allEvidence) {
                            stringResource(R.string.check_evidence_show_fewer)
                        } else {
                            stringResource(R.string.check_evidence_show_all, evidence.size, evidence.size - shown.size)
                        },
                        modifier = Modifier.clickable(role = Role.Button) { allEvidence = !allEvidence }.padding(vertical = 8.dp),
                        color = tokens.focus,
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }
        }
    }

    if (isPass) {
        Surface(
            Modifier.fillMaxWidth(),
            shape = MaterialTheme.shapes.medium,
            color = tokens.surface2,
            border = BorderStroke(1.dp, tokens.border),
        ) { Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) { body() } }
    } else {
        ToneCard(colors = colors) { body() }
    }
}

@Composable
private fun EvidenceRow(
    ev: EvidenceRef,
    docs: Map<String, DocumentRecord>,
    target: EvidenceTarget?,
    onOpenEvidence: (EvidenceTarget) -> Unit,
    correction: CorrectionContext?,
) {
    val record = ev.doc?.let(docs::get)
    val name = record?.filename ?: ev.doc ?: stringResource(R.string.check_evidence_unknown_document)
    val path = if (correction != null) editablePath(ev) else null
    Column(verticalArrangement = Arrangement.spacedBy(0.dp)) {
        EvidenceCard(ev, name, record, target, onOpenEvidence)
        // Edit sits outside the tappable card: a clickable card merges what is inside it, so a button in it could not be reached on its own
        if (correction != null && path != null) CorrectionLine(ev.doc.orEmpty(), name, path, correction)
    }
}

@Composable
private fun CorrectionLine(documentId: String, documentName: String, path: String, correction: CorrectionContext) {
    val tokens = MaterialTheme.cargo
    val state = evidenceCorrection(documentId, path, correction.corrections, correction.applied)
    val describe = stringResource(R.string.correct_edit_description, pathLabel(path), documentName)
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        val (text, ok) = when (state) {
            is EvidenceCorrection.Used -> stringResource(R.string.correct_state_used, state.entry.originalValue ?: stringResource(R.string.correct_state_nothing)) to true
            is EvidenceCorrection.Pending -> stringResource(R.string.correct_state_pending, state.entry.value ?: stringResource(R.string.correct_state_cleared)) to false
            is EvidenceCorrection.Undone -> stringResource(R.string.correct_state_undone) to false
            null -> "" to false
        }
        if (state != null) {
            Text((if (ok) "✓ " else "▲ ") + text, Modifier.weight(1f).padding(start = 4.dp, end = 8.dp), color = if (ok) tokens.ok.fg else tokens.warn.fg, fontWeight = FontWeight.Bold, fontSize = 11.sp)
        } else {
            Spacer(Modifier.weight(1f))
        }
        TextButton(
            onClick = { correction.onCorrect(documentId, documentName, path) },
            enabled = correction.enabled,
            modifier = Modifier.defaultMinSize(minHeight = 48.dp).semantics { contentDescription = describe },
        ) { Text(stringResource(R.string.correct_edit), color = if (correction.enabled) tokens.focus else tokens.textSubtle, fontWeight = FontWeight.SemiBold) }
    }
}

@Composable
private fun EvidenceCard(ev: EvidenceRef, name: String, record: DocumentRecord?, target: EvidenceTarget?, onOpenEvidence: (EvidenceTarget) -> Unit) {
    val tokens = MaterialTheme.cargo
    val type = record?.docType?.replace('_', ' ').orEmpty()
    val value = ev.rawValueText
    val isGap = value == null
    val rowColors = if (isGap) tokens.warn else null
    val openLabel = stringResource(R.string.check_evidence_open, name)

    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .let { if (target != null) it.clickable(onClickLabel = openLabel, role = Role.Button) { onOpenEvidence(target) } else it },
        shape = RoundedCornerShape(6.dp),
        color = if (isGap) tokens.warn.bg else tokens.surface,
        border = BorderStroke(1.dp, if (isGap) tokens.warn.bd else tokens.border),
    ) {
        Column(Modifier.padding(horizontal = 10.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp), itemVerticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = (if (isGap) "⚠ " else "") + name,
                    color = rowColors?.fg ?: tokens.text,
                    fontWeight = FontWeight.SemiBold,
                    style = MaterialTheme.typography.bodySmall,
                )
                if (type.isNotEmpty()) Tag(type.uppercase())
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(2.dp), itemVerticalAlignment = Alignment.CenterVertically) {
                if (isGap) {
                    Text(stringResource(R.string.check_evidence_gap), color = tokens.warn.fg, fontStyle = FontStyle.Italic, fontWeight = FontWeight.Medium, fontSize = 12.sp)
                } else {
                    Tag(value, mono = true)
                    ev.unit?.takeIf { it.isNotBlank() }?.let { Text(it, color = tokens.textMuted, fontSize = 12.sp) }
                }
                ev.page?.let { Text(stringResource(R.string.check_evidence_page, it), color = tokens.textSubtle, fontSize = 12.sp) }
            }
        }
    }
}
