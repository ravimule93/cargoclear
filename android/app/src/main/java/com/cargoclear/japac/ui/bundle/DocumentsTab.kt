package com.cargoclear.japac.ui.bundle

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.DocumentHealth
import com.cargoclear.japac.core.model.DocumentRecord
import com.cargoclear.japac.core.model.HealthBadge
import com.cargoclear.japac.core.model.WorkbenchState
import com.cargoclear.japac.core.model.badge
import com.cargoclear.japac.core.model.documentHealth
import com.cargoclear.japac.ui.common.SectionHeading
import com.cargoclear.japac.ui.common.Tag
import com.cargoclear.japac.ui.theme.cargo
import kotlin.math.roundToInt

/** The files of the bundle with the Conflict / Gap / Clean chip of each (port of components/rail/DocumentRail.tsx). */
@Composable
fun DocumentsTab(state: WorkbenchState, onOpen: (String) -> Unit, onAddDocuments: () -> Unit, modifier: Modifier = Modifier) {
    val tokens = MaterialTheme.cargo
    val documents = state.documents
    val health = documentHealth(documents, state.assessment?.checks.orEmpty())
    val active = state.activeDocumentId

    LazyColumn(
        modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(start = 16.dp, top = 16.dp, end = 16.dp, bottom = 96.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item { SectionHeading(stringResource(R.string.documents_title, documents.size)) }
        if (documents.isEmpty()) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(stringResource(R.string.documents_none), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
                    Text(stringResource(R.string.documents_none_hint), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        item {
            OutlinedButton(onClick = onAddDocuments, enabled = state.canAddDocuments, modifier = Modifier.fillMaxWidth(), border = BorderStroke(1.dp, tokens.borderStrong)) {
                Text(stringResource(R.string.action_add_document), color = tokens.text, fontWeight = FontWeight.SemiBold)
            }
        }
        items(documents, key = { it.documentId }) { doc ->
            DocumentRow(doc, health[doc.documentId], selected = doc.documentId == active, onClick = { onOpen(doc.documentId) })
        }
    }
}

@Composable
private fun DocumentRow(doc: DocumentRecord, health: DocumentHealth?, selected: Boolean, onClick: () -> Unit) {
    val tokens = MaterialTheme.cargo
    // no contentDescription: it would replace what a screen reader reads (the file name, its type, its Conflict / Gap / Clean chip) with a name alone
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .semantics { this.selected = selected }
            .clickable(onClickLabel = stringResource(R.string.viewer_open_document, doc.filename), role = Role.Button, onClick = onClick),
        shape = MaterialTheme.shapes.medium,
        color = if (selected) tokens.surface2 else tokens.surface,
        border = BorderStroke(if (selected) 2.dp else 1.dp, if (selected) tokens.focus else tokens.border),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
                Text(
                    text = doc.filename,
                    modifier = Modifier.weight(1f),
                    color = tokens.text,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodyMedium,
                )
                when (health?.badge()) {
                    HealthBadge.CONFLICT -> Tag(pluralStringResource(R.plurals.health_conflicts, health.material, health.material), colors = tokens.err)
                    HealthBadge.GAP -> Tag(stringResource(R.string.health_gap, health.warn), colors = tokens.warn)
                    HealthBadge.CLEAN -> Tag(stringResource(R.string.health_clean), colors = tokens.ok)
                    null -> Unit
                }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Tag(doc.docType.replace('_', ' ').uppercase(), mono = true)
                Text(stringResource(R.string.document_size_kb, (doc.bytes / 1024.0).roundToInt()), color = tokens.textMuted, fontSize = 12.sp)
            }
        }
    }
}
