package com.cargoclear.japac.ui.assess

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.CellValue
import com.cargoclear.japac.core.model.CorrectionDraft
import com.cargoclear.japac.core.model.CorrectionEditor
import com.cargoclear.japac.core.model.pathLabel
import com.cargoclear.japac.ui.theme.cargo

/**
 * Edit-in-place for one extracted value (port of components/assess/CorrectionEditor.tsx), as a bottom sheet: the authorised agent states
 * what the document actually says. Saving the value as it already is records a confirmation (the model was right, and a person checked);
 * anything else is a correction. Nothing changes the assessment until it is recomputed.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CorrectionSheet(
    editor: CorrectionEditor,
    current: CellValue?,
    onEdit: ((CorrectionDraft) -> CorrectionDraft) -> Unit,
    onValueLoaded: () -> Unit,
    onSave: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val tokens = MaterialTheme.cargo
    val draft = editor.draft
    val label = pathLabel(draft.path)
    val focus = remember { FocusRequester() }
    // the extraction can still be loading when the sheet opens: fill the fields once it arrives, unless the person has typed
    LaunchedEffect(current) { onValueLoaded() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }

    ModalBottomSheet(
        onDismissRequest = { if (!draft.busy) onDismiss() },
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = tokens.surface,
        modifier = modifier,
    ) {
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).imePadding().navigationBarsPadding().padding(start = 16.dp, end = 16.dp, bottom = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(stringResource(R.string.editor_heading, label, editor.documentName), color = tokens.text, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.titleSmall)
                if (current == null) {
                    Text(stringResource(R.string.editor_loading), Modifier.semantics { liveRegion = LiveRegionMode.Polite }, color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
                } else {
                    val read = (if (current.corrected) current.originalValue else current.value) ?: stringResource(R.string.editor_not_stated)
                    val readUnit = if (current.corrected) current.originalUnit else current.unit
                    Text(
                        stringResource(R.string.editor_model_read, read + (readUnit?.takeIf { it.isNotEmpty() }?.let { " $it" } ?: "")),
                        color = tokens.textMuted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
                OutlinedTextField(
                    value = if (draft.clear) "" else draft.value,
                    onValueChange = { text -> onEdit { it.valueChanged(text) } },
                    modifier = Modifier.weight(1f).focusRequester(focus),
                    label = { Text(stringResource(R.string.editor_value_label)) },
                    enabled = !draft.clear && !draft.busy,
                    singleLine = true,
                    textStyle = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 15.sp),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                )
                if (draft.showUnit) {
                    OutlinedTextField(
                        value = if (draft.clear) "" else draft.unit,
                        onValueChange = { text -> onEdit { it.unitChanged(text) } },
                        modifier = Modifier.weight(0.45f),
                        label = { Text(stringResource(R.string.editor_unit_label)) },
                        placeholder = { Text(stringResource(R.string.editor_unit_placeholder), color = tokens.textSubtle) },
                        enabled = !draft.clear && !draft.busy,
                        singleLine = true,
                        textStyle = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 15.sp),
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                    )
                }
            }

            OutlinedTextField(
                value = draft.reason,
                onValueChange = { text -> onEdit { it.reasonChanged(text) } },
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.editor_reason_label)) },
                enabled = !draft.busy,
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { if (draft.canSave(current)) onSave() }),
            )

            if (draft.clearable) {
                Row(
                    // the row, not the box, is the target: one 48 dp button announced as a checkbox with its state
                    Modifier.fillMaxWidth().defaultMinSize(minHeight = 48.dp).toggleable(
                        value = draft.clear,
                        enabled = !draft.busy,
                        role = Role.Checkbox,
                        onValueChange = { checked -> onEdit { it.clearChanged(checked) } },
                    ),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Checkbox(checked = draft.clear, onCheckedChange = null, enabled = !draft.busy)
                    Text(stringResource(R.string.editor_clear_label), color = tokens.textMuted, style = MaterialTheme.typography.bodyMedium)
                }
            }

            draft.error?.let {
                Text(it, Modifier.semantics { liveRegion = LiveRegionMode.Assertive }, color = tokens.err.fg, fontWeight = FontWeight.Medium, style = MaterialTheme.typography.bodyMedium)
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = onSave,
                    enabled = draft.canSave(current),
                    modifier = Modifier.defaultMinSize(minHeight = 48.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = tokens.focus, contentColor = tokens.onFocus),
                ) {
                    Text(
                        stringResource(
                            when {
                                draft.busy -> R.string.editor_saving
                                draft.unchanged(current) -> R.string.editor_confirm
                                else -> R.string.editor_save
                            },
                        ),
                        fontWeight = FontWeight.SemiBold,
                    )
                }
                OutlinedButton(onClick = onDismiss, enabled = !draft.busy, modifier = Modifier.defaultMinSize(minHeight = 48.dp)) {
                    Text(stringResource(R.string.action_cancel), color = tokens.text, fontWeight = FontWeight.Medium)
                }
            }
        }
    }
}
