package com.cargoclear.japac.ui.scan

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.cargoclear.japac.R
import com.cargoclear.japac.ui.theme.cargo

/** How to add a document when the phone can scan: choose a PDF that is already on it, or scan a paper one. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddDocumentSheet(onChoosePdf: () -> Unit, onScan: () -> Unit, onDismiss: () -> Unit) {
    val tokens = MaterialTheme.cargo
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = tokens.surface) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().padding(bottom = 16.dp)) {
            Text(stringResource(R.string.add_sheet_title), Modifier.padding(horizontal = 24.dp, vertical = 8.dp), color = tokens.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
            Choice(R.string.add_sheet_files, R.string.add_sheet_files_hint, onChoosePdf)
            Choice(R.string.add_sheet_scan, R.string.add_sheet_scan_hint, onScan)
        }
    }
}

@Composable
private fun Choice(title: Int, hint: Int, onClick: () -> Unit) {
    val tokens = MaterialTheme.cargo
    Column(
        Modifier.fillMaxWidth().defaultMinSize(minHeight = 64.dp).clickable(role = Role.Button, onClick = onClick).padding(horizontal = 24.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(stringResource(title), color = tokens.text, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyLarge)
        Text(stringResource(hint), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
    }
}
