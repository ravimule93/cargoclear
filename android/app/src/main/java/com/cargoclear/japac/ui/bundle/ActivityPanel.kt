package com.cargoclear.japac.ui.bundle

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.ActionError
import com.cargoclear.japac.core.model.UploadStatus
import com.cargoclear.japac.core.model.WorkbenchState
import com.cargoclear.japac.ui.assess.RunProgressCard
import com.cargoclear.japac.ui.common.ToneCard
import com.cargoclear.japac.ui.theme.cargo

/**
 * What is happening to the bundle right now, above the tabs so that it is seen from either of them: the last failure (a run that could
 * not start, a run that failed, an upload the server refused), files going up, a run in progress. Draws nothing when none applies.
 */
@Composable
fun ActivityPanel(
    state: WorkbenchState,
    onDismissError: () -> Unit,
    onCancelUploads: () -> Unit,
    modifier: Modifier = Modifier,
    notifyOffer: Boolean = false,
    onNotifyMe: () -> Unit = {},
) {
    val error = state.visibleError
    val upload = state.upload as? UploadStatus.Active
    if (error == null && upload == null && !state.isRunning) return

    Column(modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (error != null) {
            ErrorBanner(
                error = error,
                detail = (state.upload as? UploadStatus.Failed)?.takeIf { error == it.error },
                onDismiss = onDismissError.takeIf { state.canDismissError },
            )
        }
        if (upload != null) UploadProgressRow(upload, onCancelUploads)
        if (state.isRunning) {
            RunProgressCard(state.run)
            // a run takes a while: offered here, where the person is waiting, and only until they have said yes
            if (notifyOffer) TextButton(onClick = onNotifyMe) { Text(stringResource(R.string.run_notify_me), color = MaterialTheme.cargo.focus, fontWeight = FontWeight.SemiBold) }
        }
    }
}

/** A failed run, upload or stream, in the server's own words with the id the server logged it under (port of `ActionErrorBanner`). */
@Composable
fun ErrorBanner(error: ActionError, onDismiss: (() -> Unit)?, modifier: Modifier = Modifier, detail: UploadStatus.Failed? = null) {
    val tokens = MaterialTheme.cargo
    ToneCard(colors = tokens.err, modifier = modifier.semantics { liveRegion = LiveRegionMode.Assertive }) {
        Text("⚠ " + stringResource(R.string.assessment_error_title), color = tokens.err.fg, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium)
        // how far the batch got, when that is known (a batch that died on something unexpected cannot say)
        val uploaded = detail?.uploaded
        if (detail != null && uploaded != null) {
            Text(
                stringResource(if (uploaded > 0) R.string.upload_failed_partial else R.string.upload_failed_none, uploaded, detail.total),
                color = tokens.text,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Text(error.message, color = tokens.textMuted, fontFamily = FontFamily.Monospace, fontSize = 12.sp)
        error.requestId?.let { Text(stringResource(R.string.error_request_id, it), color = tokens.textSubtle, fontFamily = FontFamily.Monospace, fontSize = 11.sp) }
        if (onDismiss != null) {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.action_dismiss), color = tokens.err.fg) }
        }
    }
}

/** Files going up (port of the TopBar's upload chip), with a way to stop. Announced politely to a screen reader. */
@Composable
fun UploadProgressRow(upload: UploadStatus.Active, onCancel: () -> Unit, modifier: Modifier = Modifier) {
    val tokens = MaterialTheme.cargo
    val name = upload.filename
    val text = when {
        upload.waiting -> pluralStringResource(R.plurals.upload_waiting, upload.total, upload.total)
        name != null -> stringResource(R.string.upload_progress, upload.current, upload.total, name)
        else -> stringResource(R.string.upload_progress_unnamed, upload.current, upload.total)
    }
    Row(
        modifier
            .fillMaxWidth()
            .semantics { liveRegion = LiveRegionMode.Polite },
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircularProgressIndicator(Modifier.size(16.dp), color = tokens.focus, strokeWidth = 2.dp)
        Text(text, Modifier.weight(1f), color = tokens.text, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Medium)
        TextButton(onClick = onCancel) { Text(stringResource(R.string.action_cancel_upload), color = tokens.textMuted) }
    }
}
