package com.cargoclear.japac.ui.home

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.cargoclear.japac.BuildConfig
import com.cargoclear.japac.R
import com.cargoclear.japac.core.data.DemoCase
import com.cargoclear.japac.core.data.RecentBundle
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.Destination
import com.cargoclear.japac.ui.assess.StatusPill
import com.cargoclear.japac.ui.common.SectionHeading
import com.cargoclear.japac.ui.common.Tag
import com.cargoclear.japac.ui.common.relativeTime
import com.cargoclear.japac.ui.shell.MetaState
import com.cargoclear.japac.ui.shell.MetaViewModel
import com.cargoclear.japac.ui.shell.ModeBadge
import com.cargoclear.japac.ui.theme.cargo
import androidx.compose.foundation.layout.ExperimentalLayoutApi

/** The start screen (port of frontend/app/page.tsx), plus the list of bundles this phone has seen. */
@Composable
fun HomeScreen(
    onOpenBundle: (String) -> Unit,
    onOpenSettings: () -> Unit,
    metaViewModel: MetaViewModel = hiltViewModel(),
    homeViewModel: HomeViewModel = hiltViewModel(),
) {
    val meta by metaViewModel.state.collectAsStateWithLifecycle()
    val state by homeViewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(homeViewModel) { homeViewModel.opens.collect(onOpenBundle) }
    LifecycleStartEffect(metaViewModel) {
        metaViewModel.refreshIfFailed()
        onStopOrDispose { }
    }

    HomeContent(
        meta = meta,
        state = state,
        onRetryMeta = metaViewModel::retry,
        onDestination = homeViewModel::selectDestination,
        onCreateEmpty = homeViewModel::createEmpty,
        onCreateDemo = homeViewModel::createDemo,
        onOpenText = homeViewModel::open,
        onOpenTextChanged = homeViewModel::openTextChanged,
        onOpenRecent = onOpenBundle,
        onForget = homeViewModel::forget,
        onOpenSettings = onOpenSettings,
    )
}

@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
fun HomeContent(
    meta: MetaState,
    state: HomeUiState,
    onRetryMeta: () -> Unit,
    onDestination: (Destination) -> Unit,
    onCreateEmpty: () -> Unit,
    onCreateDemo: (DemoCase) -> Unit,
    onOpenText: (String) -> Unit,
    onOpenTextChanged: () -> Unit,
    onOpenRecent: (String) -> Unit,
    onForget: (String) -> Unit,
    showDevInfo: Boolean = BuildConfig.DEBUG,
    onOpenSettings: () -> Unit = {},
) {
    val tokens = MaterialTheme.cargo
    val busy = state.pending != null
    val showDemo = meta is MetaState.Ready && meta.meta.appMode == AppMode.DEMO
    var openText by rememberSaveable { mutableStateOf("") }
    var forgetTarget by rememberSaveable { mutableStateOf<String?>(null) }

    Scaffold(containerColor = MaterialTheme.colorScheme.background) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(padding)
                .padding(horizontal = 24.dp, vertical = 24.dp)
                .widthIn(max = 560.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                // wraps: at a large system font the badge and the gear drop under the title instead of squeezing it into pieces
                FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp), itemVerticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = stringResource(R.string.home_title),
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold,
                        color = tokens.text,
                    )
                    ModeBadge(meta)
                    IconButton(onClick = onOpenSettings) {
                        Icon(Icons.Filled.Settings, contentDescription = stringResource(R.string.settings_open), tint = tokens.textMuted)
                    }
                }
                Text(stringResource(R.string.home_tagline), style = MaterialTheme.typography.bodyMedium, color = tokens.textMuted)
            }

            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(stringResource(R.string.home_destination_label), color = tokens.textMuted, style = MaterialTheme.typography.labelLarge)
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
                    Destination.entries.forEachIndexed { index, destination ->
                        SegmentedButton(
                            selected = state.destination == destination,
                            onClick = { onDestination(destination) },
                            enabled = !busy,
                            shape = SegmentedButtonDefaults.itemShape(index, Destination.entries.size),
                            modifier = Modifier.fillMaxHeight(),
                        ) { Text(destination.label) }
                    }
                }
                OutlinedButton(onClick = onCreateEmpty, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(if (state.pending == Pending.EMPTY) R.string.home_new_empty_busy else R.string.home_new_empty))
                }
                if (showDemo) {
                    Button(onClick = { onCreateDemo(DemoCase.CASE_C) }, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                        Text(stringResource(if (state.pending == Pending.DEMO_C) R.string.home_demo_busy else R.string.home_demo_c))
                    }
                    OutlinedButton(onClick = { onCreateDemo(DemoCase.CASE_D) }, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                        Text(stringResource(if (state.pending == Pending.DEMO_D) R.string.home_demo_busy else R.string.home_demo_d))
                    }
                }
            }

            if (meta is MetaState.Failed) {
                Column(Modifier.semantics { liveRegion = LiveRegionMode.Assertive }, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        text = if (meta.notConfigured) stringResource(R.string.home_not_configured, meta.message) else stringResource(R.string.home_backend_error, meta.message),
                        style = MaterialTheme.typography.bodySmall,
                        color = tokens.err.fg,
                    )
                    if (!meta.notConfigured) OutlinedButton(onClick = onRetryMeta) { Text(stringResource(R.string.action_retry)) }
                }
            }

            state.error?.let {
                Text(it, Modifier.semantics { liveRegion = LiveRegionMode.Assertive }, color = tokens.err.fg, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Medium)
            }

            if (showDemo) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(stringResource(R.string.demo_note_case_c), style = MaterialTheme.typography.bodySmall, color = tokens.textMuted)
                    Text(stringResource(R.string.demo_note_case_d), style = MaterialTheme.typography.bodySmall, color = tokens.textMuted)
                }
            }

            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                SectionHeading(stringResource(R.string.home_open_title))
                OutlinedTextField(
                    value = openText,
                    onValueChange = {
                        openText = it
                        onOpenTextChanged()
                    },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text(stringResource(R.string.home_open_label)) },
                    singleLine = true,
                    isError = state.openInvalid,
                    supportingText = if (state.openInvalid) ({ Text(stringResource(R.string.home_open_invalid)) }) else null,
                    keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go),
                    keyboardActions = androidx.compose.foundation.text.KeyboardActions(onGo = { onOpenText(openText) }),
                )
                OutlinedButton(onClick = { onOpenText(openText) }, enabled = openText.isNotBlank()) { Text(stringResource(R.string.home_open_action)) }
            }

            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                SectionHeading(stringResource(R.string.home_recents_title))
                if (state.recents.isEmpty()) {
                    Text(stringResource(R.string.home_recents_empty), style = MaterialTheme.typography.bodySmall, color = tokens.textMuted)
                }
                state.recents.forEach { recent ->
                    RecentRow(recent, onOpen = { onOpenRecent(recent.bundleId) }, onForget = { forgetTarget = recent.bundleId })
                }
            }

            if (showDevInfo) {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(
                        stringResource(R.string.dev_backend_line, BuildConfig.API_BASE_URL.ifBlank { "(none)" }),
                        style = MaterialTheme.typography.labelSmall,
                        fontFamily = FontFamily.Monospace,
                        color = tokens.textSubtle,
                    )
                    Text(stringResource(R.string.dev_phase_line), style = MaterialTheme.typography.labelSmall, color = tokens.textSubtle)
                }
            }
        }
    }

    forgetTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { forgetTarget = null },
            title = { Text(stringResource(R.string.home_forget_title)) },
            text = { Text(stringResource(R.string.home_forget_body)) },
            confirmButton = {
                TextButton(onClick = {
                    onForget(target)
                    forgetTarget = null
                }) { Text(stringResource(R.string.home_forget_confirm)) }
            },
            dismissButton = { TextButton(onClick = { forgetTarget = null }) { Text(stringResource(R.string.action_cancel)) } },
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RecentRow(recent: RecentBundle, onOpen: () -> Unit, onForget: () -> Unit) {
    val tokens = MaterialTheme.cargo
    val opened = relativeTime(recent.lastOpenedAt)
    Surface(
        modifier = Modifier.fillMaxWidth().clickable(role = Role.Button, onClick = onOpen),
        shape = MaterialTheme.shapes.medium,
        color = tokens.surface,
        border = BorderStroke(1.dp, tokens.border),
    ) {
        Column(Modifier.padding(start = 12.dp, top = 6.dp, end = 4.dp, bottom = 10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(recent.bundleId, color = tokens.text, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                    recent.reference?.takeIf { it.isNotBlank() }?.let { Text(it, color = tokens.textMuted, style = MaterialTheme.typography.bodySmall) }
                }
                TextButton(onClick = onForget) {
                    Text(stringResource(R.string.home_forget), color = tokens.textMuted)
                }
            }
            Row(Modifier.padding(end = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp), itemVerticalAlignment = Alignment.CenterVertically) {
                    StatusPill(recent.status)
                    Tag(stringResource(R.string.home_recent_to, recent.destination))
                    Tag(pluralStringResource(R.plurals.home_recent_documents, recent.documentCount, recent.documentCount))
                }
            }
            Text(
                stringResource(R.string.home_recent_opened, opened),
                color = tokens.textSubtle,
                fontSize = 11.sp,
                modifier = Modifier.padding(end = 8.dp),
            )
        }
    }
}
