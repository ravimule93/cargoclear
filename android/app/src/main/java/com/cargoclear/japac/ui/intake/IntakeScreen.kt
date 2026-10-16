package com.cargoclear.japac.ui.intake

import android.text.format.Formatter
import androidx.activity.compose.BackHandler
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
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
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.cargoclear.japac.R
import com.cargoclear.japac.core.data.RecentBundle
import com.cargoclear.japac.core.model.Destination
import com.cargoclear.japac.ui.assess.StatusPill
import com.cargoclear.japac.ui.common.SectionHeading
import com.cargoclear.japac.ui.common.Tag
import com.cargoclear.japac.ui.theme.cargo

/** PDFs another app shared with this one: which bundle do they belong to? */
@Composable
fun IntakeScreen(onOpenBundle: (String) -> Unit, onDone: () -> Unit, viewModel: IntakeViewModel = hiltViewModel()) {
    val files by viewModel.files.collectAsStateWithLifecycle()
    val state by viewModel.state.collectAsStateWithLifecycle()
    val recent by viewModel.recent.collectAsStateWithLifecycle()
    LaunchedEffect(viewModel) { viewModel.opens.collect(onOpenBundle) }
    val leave = { if (viewModel.cancel()) onDone() }
    BackHandler(onBack = leave)

    // The files wait in memory only. If this screen comes back after the system ended the process there is nothing to ask about: leave it rather than
    // show a blank page. (Once the files are handed to the uploads they are gone too, but then the open request is already navigating away.)
    val startedEmpty = remember { files == null }
    if (startedEmpty) {
        LaunchedEffect(Unit) { onDone() }
        return
    }
    val waiting = files ?: return
    IntakeContent(
        files = waiting,
        state = state,
        recent = recent,
        onDestination = viewModel::selectDestination,
        onCreate = viewModel::createAndAdd,
        onAddTo = viewModel::addTo,
        onBack = leave,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IntakeContent(
    files: IntakeFiles,
    state: IntakeUi,
    recent: List<RecentBundle>,
    onDestination: (Destination) -> Unit,
    onCreate: () -> Unit,
    onAddTo: (RecentBundle) -> Unit,
    onBack: () -> Unit,
) {
    val tokens = MaterialTheme.cargo
    val canAdd = files.files.isNotEmpty()
    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.intake_title), fontWeight = FontWeight.Bold, color = tokens.text) },
                navigationIcon = { IconButton(onClick = onBack, enabled = !state.busy) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.action_cancel)) } },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = tokens.surface),
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(padding).padding(horizontal = 16.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                if (canAdd) {
                    SectionHeading(pluralStringResource(R.plurals.intake_files, files.files.size, files.files.size))
                    files.files.forEach { file ->
                        Surface(Modifier.fillMaxWidth(), shape = MaterialTheme.shapes.small, color = tokens.surface, border = BorderStroke(1.dp, tokens.border)) {
                            Row(Modifier.padding(horizontal = 10.dp, vertical = 8.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                                Text(file.name, Modifier.weight(1f).padding(end = 8.dp), color = tokens.text, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodySmall)
                                Text(Formatter.formatShortFileSize(LocalContext.current, file.bytes), color = tokens.textSubtle, fontSize = 11.sp)
                            }
                        }
                    }
                }
                if (files.unreadable > 0) {
                    Text(
                        if (canAdd) pluralStringResource(R.plurals.intake_unreadable, files.unreadable, files.unreadable) else stringResource(R.string.intake_none_readable),
                        Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                        color = tokens.warn.fg, fontWeight = FontWeight.Medium, style = MaterialTheme.typography.bodySmall,
                    )
                }
            }

            if (canAdd) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    SectionHeading(stringResource(R.string.intake_new_title))
                    Text(stringResource(R.string.home_destination_label), color = tokens.textMuted, style = MaterialTheme.typography.labelLarge)
                    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
                        Destination.entries.forEachIndexed { index, destination ->
                            SegmentedButton(
                                selected = state.destination == destination,
                                onClick = { onDestination(destination) },
                                enabled = !state.busy,
                                shape = SegmentedButtonDefaults.itemShape(index, Destination.entries.size),
                                modifier = Modifier.defaultMinSize(minHeight = 48.dp).fillMaxHeight(),
                            ) { Text(destination.label) }
                        }
                    }
                    Button(onClick = onCreate, enabled = !state.busy, modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = 48.dp)) {
                        Text(stringResource(if (state.busy) R.string.intake_new_busy else R.string.intake_new_action), fontWeight = FontWeight.SemiBold)
                    }
                    state.error?.let {
                        Text(it, Modifier.semantics { liveRegion = LiveRegionMode.Assertive }, color = tokens.err.fg, fontWeight = FontWeight.Medium, style = MaterialTheme.typography.bodySmall)
                    }
                }

                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    SectionHeading(stringResource(R.string.intake_recent_title))
                    if (recent.isEmpty()) Text(stringResource(R.string.intake_recent_none), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
                    recent.forEach { RecentChoice(it, enabled = !state.busy, onChoose = { onAddTo(it) }) }
                }
                Text(stringResource(R.string.intake_note), color = tokens.textSubtle, fontSize = 11.sp)
            }

            OutlinedButton(onClick = onBack, enabled = !state.busy, modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = 48.dp)) {
                Text(stringResource(R.string.action_cancel), color = tokens.text)
            }
        }
    }
}

@Composable
private fun RecentChoice(recent: RecentBundle, enabled: Boolean, onChoose: () -> Unit) {
    val tokens = MaterialTheme.cargo
    val label = stringResource(R.string.intake_add_to, recent.bundleId)
    Surface(
        modifier = Modifier.fillMaxWidth().clickable(enabled = enabled, onClickLabel = label, role = Role.Button, onClick = onChoose),
        shape = MaterialTheme.shapes.medium, color = tokens.surface, border = BorderStroke(1.dp, tokens.border),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(recent.bundleId, color = tokens.text, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, fontSize = 13.sp)
            recent.reference?.takeIf { it.isNotBlank() }?.let { Text(it, color = tokens.textMuted, style = MaterialTheme.typography.bodySmall) }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp), itemVerticalAlignment = Alignment.CenterVertically) {
                StatusPill(recent.status)
                Tag(stringResource(R.string.home_recent_to, recent.destination))
            }
        }
    }
}
