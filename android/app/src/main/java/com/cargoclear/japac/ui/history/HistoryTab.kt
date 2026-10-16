package com.cargoclear.japac.ui.history

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.AuditEvent
import com.cargoclear.japac.core.model.AuditResponse
import com.cargoclear.japac.core.model.AuditSignature
import com.cargoclear.japac.core.model.DeltaKind
import com.cargoclear.japac.core.model.ReasoningDelta
import com.cargoclear.japac.core.model.Tone
import com.cargoclear.japac.core.model.attributeLabel
import com.cargoclear.japac.core.model.canSignNow
import com.cargoclear.japac.core.model.chainBadge
import com.cargoclear.japac.core.model.describeEvent
import com.cargoclear.japac.core.model.describeSignature
import com.cargoclear.japac.core.model.plainValue
import com.cargoclear.japac.core.model.shortHash
import com.cargoclear.japac.ui.common.PlainCard
import com.cargoclear.japac.ui.common.Tag
import com.cargoclear.japac.ui.theme.StatusColors
import com.cargoclear.japac.ui.theme.cargo

private enum class HistorySegment { DELTA, AUDIT }

/**
 * What changed between assessments, and the tamper-evident record of everything that happened to the bundle (port of
 * components/delta/DeltaDrawer.tsx: the web's drawer becomes a tab, its two tabs a segmented control).
 *
 * The audit chain is read only while its segment is showing, and again whenever [auditRefreshKey] changes.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryTab(
    latest: AssessmentIteration?,
    audit: AuditUi,
    auditRefreshKey: String,
    onLoadAudit: () -> Unit,
    onSignNow: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var segment by rememberSaveable { mutableIntStateOf(HistorySegment.DELTA.ordinal) }
    val tokens = MaterialTheme.cargo
    val entries = HistorySegment.entries

    Column(modifier.fillMaxSize()) {
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().height(IntrinsicSize.Min).padding(horizontal = 16.dp, vertical = 12.dp)) {
            entries.forEachIndexed { index, entry ->
                SegmentedButton(
                    selected = segment == index,
                    onClick = { segment = index },
                    shape = SegmentedButtonDefaults.itemShape(index, entries.size),
                    modifier = Modifier.defaultMinSize(minHeight = 48.dp).fillMaxHeight(),
                    colors = SegmentedButtonDefaults.colors(activeContainerColor = tokens.surface2, activeContentColor = tokens.focus, inactiveContentColor = tokens.textMuted),
                ) {
                    Text(
                        stringResource(if (entry == HistorySegment.DELTA) R.string.history_delta else R.string.history_audit),
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 12.sp,
                    )
                }
            }
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(start = 16.dp, end = 16.dp, bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            when (entries[segment]) {
                HistorySegment.DELTA -> ReasoningDeltaView(latest?.reasoningDelta)
                HistorySegment.AUDIT -> {
                    LaunchedEffect(auditRefreshKey) { onLoadAudit() }
                    AuditView(audit, onRetry = onLoadAudit, onSignNow = onSignNow)
                }
            }
        }
    }
}

/** The Reasoning Delta (port of components/delta/ReasoningDelta.tsx). The web's four-column table becomes one card per change. */
@Composable
fun ReasoningDeltaView(delta: ReasoningDelta?, modifier: Modifier = Modifier) {
    val tokens = MaterialTheme.cargo
    if (delta == null) {
        Text(stringResource(R.string.delta_none), modifier, color = tokens.textMuted, style = MaterialTheme.typography.bodySmall, fontStyle = androidx.compose.ui.text.font.FontStyle.Italic)
        return
    }
    if (delta.kind == DeltaKind.INITIAL) {
        Column(modifier, verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.delta_baseline), color = tokens.text, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyMedium)
            Text(delta.narrative, color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
        }
        return
    }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        PlainCard { Text(delta.narrative, color = tokens.text, fontWeight = FontWeight.Medium, style = MaterialTheme.typography.bodySmall) }
        delta.changes.forEach { change ->
            val attribute = attributeLabel(change.field.orEmpty())
            val from = plainValue(change.from)
            val to = plainValue(change.to)
            val because = change.because.orEmpty()
            val description = stringResource(R.string.delta_change_description, attribute, from, to, because)
            Surface(
                Modifier.fillMaxWidth().semantics(mergeDescendants = true) { contentDescription = description },
                shape = MaterialTheme.shapes.small, color = tokens.surface, border = BorderStroke(1.dp, tokens.border),
            ) {
                Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(attribute, color = tokens.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodySmall)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
                        DeltaState(stringResource(R.string.delta_previous), from, tokens.err.fg, Modifier.weight(1f))
                        DeltaState(stringResource(R.string.delta_current), to, tokens.ok.fg, Modifier.weight(1f))
                    }
                    if (because.isNotBlank()) {
                        Text(because, color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
    }
}

@Composable
private fun DeltaState(label: String, value: String, color: androidx.compose.ui.graphics.Color, modifier: Modifier = Modifier) {
    val tokens = MaterialTheme.cargo
    Column(modifier, verticalArrangement = Arrangement.spacedBy(1.dp)) {
        Text(label.uppercase(), color = tokens.textSubtle, fontSize = 10.sp, fontWeight = FontWeight.Bold)
        Text(value.ifEmpty { "—" }, color = color, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
    }
}

private fun Tone.colors(tokens: com.cargoclear.japac.ui.theme.CargoClearColors): StatusColors = when (this) {
    Tone.OK -> tokens.ok
    Tone.WARN -> tokens.warn
    Tone.ERR -> tokens.err
}

private fun Tone.glyph(): String = when (this) {
    Tone.OK -> "✓ "
    Tone.WARN -> "▲ "
    Tone.ERR -> "● "
}

/** The audit chain of the bundle: whether it verifies, what its signature says, and every event (port of components/audit/AuditTimeline.tsx). */
@Composable
fun AuditView(state: AuditUi, onRetry: () -> Unit, onSignNow: () -> Unit, modifier: Modifier = Modifier) {
    val tokens = MaterialTheme.cargo
    state.error?.let {
        Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(R.string.audit_load_failed, it), Modifier.semantics { liveRegion = LiveRegionMode.Assertive }, color = tokens.err.fg, style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = onRetry, modifier = Modifier.defaultMinSize(minHeight = 48.dp)) { Text(stringResource(R.string.action_retry), color = tokens.text) }
        }
        return
    }
    val audit = state.audit
    if (audit == null) {
        Text(stringResource(R.string.audit_loading), modifier.semantics { liveRegion = LiveRegionMode.Polite }, color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
        return
    }
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        ChainHeader(audit, state, onSignNow)
        if (audit.events.isEmpty()) {
            Text(stringResource(R.string.audit_none), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall, fontStyle = androidx.compose.ui.text.font.FontStyle.Italic)
        } else {
            audit.events.forEach { AuditEventCard(it) }
        }
    }
}

@Composable
private fun ChainHeader(audit: AuditResponse, state: AuditUi, onSignNow: () -> Unit) {
    val tokens = MaterialTheme.cargo
    val badge = chainBadge(audit)
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Tag(badge.tone.glyph() + badge.text, colors = badge.tone.colors(tokens))
        audit.signature?.let { signature ->
            val summary = describeSignature(signature)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp), itemVerticalAlignment = Alignment.CenterVertically) {
                Tag(summary.tone.glyph() + summary.text, colors = summary.tone.colors(tokens))
                if (canSignNow(signature)) {
                    OutlinedButton(onClick = onSignNow, enabled = !state.signing, modifier = Modifier.defaultMinSize(minHeight = 48.dp), border = BorderStroke(1.dp, tokens.borderStrong)) {
                        Text(stringResource(if (state.signing) R.string.audit_signing else R.string.audit_sign_now), color = tokens.focus, fontWeight = FontWeight.SemiBold)
                    }
                }
            }
            if (signature.failures > 0) {
                Text(
                    pluralStringResource(R.plurals.audit_signing_failures, signature.failures, signature.failures),
                    Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                    color = tokens.warn.fg, style = MaterialTheme.typography.bodySmall,
                )
            }
            state.signError?.let {
                Text(it, Modifier.semantics { liveRegion = LiveRegionMode.Assertive }, color = tokens.err.fg, style = MaterialTheme.typography.bodySmall)
            }
            SignatureMeaning(signature)
        }
    }
}

@Composable
private fun SignatureMeaning(signature: AuditSignature) {
    val tokens = MaterialTheme.cargo
    var open by rememberSaveable { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            text = (if (open) "▾ " else "▸ ") + stringResource(R.string.audit_meaning_title),
            modifier = Modifier
                .defaultMinSize(minHeight = 48.dp)
                .clickable(role = Role.Button) { open = !open }
                .padding(vertical = 12.dp),
            color = tokens.textMuted,
            style = MaterialTheme.typography.bodySmall,
        )
        if (open) {
            Text(signature.meaning, color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
            signature.key?.takeIf { it.isNotBlank() }?.let { Text(stringResource(R.string.audit_key, it), color = tokens.textMuted, fontFamily = FontFamily.Monospace, fontSize = 11.sp) }
        }
    }
}

@Composable
private fun AuditEventCard(event: AuditEvent) {
    val tokens = MaterialTheme.cargo
    val detail = describeEvent(event)
    Surface(Modifier.fillMaxWidth(), shape = MaterialTheme.shapes.small, color = tokens.surface2, border = BorderStroke(1.dp, tokens.border)) {
        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(stringResource(R.string.audit_event_title, event.seq, event.eventType), color = tokens.focus, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
            Text(event.ts, color = tokens.textMuted, fontFamily = FontFamily.Monospace, fontSize = 10.sp)
            detail?.let { Text(it, color = tokens.text, style = MaterialTheme.typography.bodySmall) }
            Column(verticalArrangement = Arrangement.spacedBy(1.dp)) {
                Text(stringResource(R.string.audit_actor, event.actor), color = tokens.textMuted, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
                Text(stringResource(R.string.audit_prev, shortHash(event.prevHash)), color = tokens.textMuted, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
                Text(stringResource(R.string.audit_hash, shortHash(event.hash)), color = tokens.textMuted, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
            }
        }
    }
}
