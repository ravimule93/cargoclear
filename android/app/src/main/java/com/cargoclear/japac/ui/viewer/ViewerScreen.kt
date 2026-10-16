package com.cargoclear.japac.ui.viewer

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.view.WindowManager
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.clickable
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.FetchState
import com.cargoclear.japac.core.model.Highlight
import com.cargoclear.japac.core.model.Severity
import com.cargoclear.japac.core.model.ViewMode
import com.cargoclear.japac.core.model.ViewerLoad
import com.cargoclear.japac.core.model.ViewerState
import com.cargoclear.japac.core.model.sampleSizeFor
import com.cargoclear.japac.ui.common.Tag
import com.cargoclear.japac.ui.common.ToneCard
import com.cargoclear.japac.ui.theme.cargo
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** One document of a bundle: the PDF page by page, with the evidence boxes of the latest assessment laid over it (port of components/viewer/DocumentViewer.tsx). */
@Composable
fun ViewerScreen(onBack: () -> Unit, viewModel: ViewerViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val pages by viewModel.pages.collectAsStateWithLifecycle()
    val modelImage by viewModel.modelImage.collectAsStateWithLifecycle()
    val secure by viewModel.secure.collectAsStateWithLifecycle()

    SecureWindow(secure)

    ViewerContent(
        documentId = viewModel.documentId,
        state = state,
        pages = pages,
        modelImage = modelImage,
        onBack = onBack,
        onRetry = viewModel::retry,
        onPrevious = viewModel::previousPage,
        onNext = viewModel::nextPage,
        onSelectBox = viewModel::selectBox,
        onShowModelView = viewModel::showModelView,
        onFocusHandled = viewModel::focusHandled,
    )
}

/** Keeps the window out of screenshots, screen recordings and the recent-apps thumbnail while [secure] (FLAG_SECURE). */
@Composable
fun SecureWindow(secure: Boolean) {
    val window = LocalContext.current.findActivity()?.window
    DisposableEffect(window, secure) {
        if (secure) window?.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        onDispose { if (secure) window?.clearFlags(WindowManager.LayoutParams.FLAG_SECURE) }
    }
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ViewerContent(
    documentId: String,
    state: ViewerState,
    pages: PdfPages?,
    modelImage: File?,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    onSelectBox: (String?) -> Unit,
    onShowModelView: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    onFocusHandled: () -> Unit = {},
) {
    val tokens = MaterialTheme.cargo
    val filename = state.document?.filename ?: documentId
    // a new viewport for every page and view, so each opens fitted
    val viewport = remember(state.page, state.mode) { ViewportState() }
    var sheetOpen by rememberSaveable { mutableStateOf(false) }

    // Opened from an evidence row: bring its box into view once the page and the geometry that places it are known
    val selectedBox = state.selectedBox
    LaunchedEffect(state.focusRequested, viewport.layout != null, selectedBox?.id) {
        if (state.focusRequested && viewport.layout != null && selectedBox != null) {
            viewport.focusOn(selectedBox.rect)
            onFocusHandled()
        }
    }

    val budget = LocalContext.current.bitmapBudget()
    val modelBitmap by produceState<Bitmap?>(null, modelImage) { value = modelImage?.let { decodeBounded(it, budget) } }

    Scaffold(
        modifier = modifier,
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = {
                    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(filename, maxLines = 1, overflow = TextOverflow.Ellipsis, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, fontSize = 14.sp, color = tokens.text)
                        state.document?.docType?.let { Tag(it.replace('_', ' ').uppercase(), mono = true) }
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.action_back)) }
                },
                actions = {
                    if (state.load == ViewerLoad.Ready) {
                        TextButton(onClick = { sheetOpen = true }) {
                            Text(stringResource(R.string.viewer_evidence_button, state.evidenceOnPage.size), color = tokens.focus, fontWeight = FontWeight.SemiBold)
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = tokens.surface),
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            when (val load = state.load) {
                ViewerLoad.Loading -> Centered { CircularProgressIndicator(color = tokens.focus) }
                ViewerLoad.NotFound -> Centered {
                    Text(stringResource(R.string.viewer_not_found_title), color = tokens.text, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(stringResource(R.string.viewer_not_found_body, documentId), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
                    OutlinedButton(onClick = onBack) { Text(stringResource(R.string.action_back)) }
                }
                is ViewerLoad.Failed -> Centered {
                    Text(stringResource(R.string.viewer_load_failed, load.message), Modifier.semantics { liveRegion = LiveRegionMode.Assertive }, color = tokens.err.fg, fontWeight = FontWeight.Medium)
                    OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.action_retry)) }
                }
                ViewerLoad.Ready -> {
                    if (state.fromSavedCopy) {
                        Text(
                            stringResource(R.string.viewer_saved_copy),
                            Modifier.fillMaxWidth().background(tokens.warn.bg).padding(horizontal = 16.dp, vertical = 6.dp),
                            color = tokens.warn.fg,
                            style = MaterialTheme.typography.labelMedium,
                        )
                    }
                    Controls(state, viewport, onPrevious, onNext, onShowModelView)
                    if (state.boxesHidden) {
                        ToneCard(tokens.warn, Modifier.padding(horizontal = 12.dp, vertical = 4.dp)) {
                            Text(stringResource(R.string.viewer_boxes_hidden), color = tokens.warn.fg, style = MaterialTheme.typography.bodySmall)
                            TextButton(onClick = onRetry) { Text(stringResource(R.string.action_retry), color = tokens.warn.fg) }
                        }
                    }
                    Box(Modifier.weight(1f).fillMaxWidth()) {
                        Pane(state, pages, modelBitmap, viewport, filename, onRetry, onSelectBox)
                    }
                    state.selectedBox?.let { SelectedBoxCard(it.severity, it.label, it.value) }
                }
            }
        }
    }

    if (sheetOpen) {
        EvidenceSheet(
            evidence = state.evidenceOnPage,
            selectedId = state.selectedBoxId,
            onDismiss = { sheetOpen = false },
            onChoose = { highlight ->
                sheetOpen = false
                onSelectBox(highlight.id)
                state.boxes.firstOrNull { it.id == highlight.id }?.let { viewport.focusOn(it.rect) }
            },
        )
    }
}

@Composable
private fun Pane(
    state: ViewerState,
    pages: PdfPages?,
    modelBitmap: Bitmap?,
    viewport: ViewportState,
    filename: String,
    onRetry: () -> Unit,
    onSelectBox: (String?) -> Unit,
) {
    val tokens = MaterialTheme.cargo
    val modelView = state.mode == ViewMode.MODEL_VIEW
    val status = if (modelView) state.modelImage else state.file
    when {
        status is FetchState.Failed -> Centered {
            val text = if (modelView) stringResource(R.string.viewer_model_view_failed, status.message) else stringResource(R.string.viewer_error, filename, status.message)
            Text(text, Modifier.semantics { liveRegion = LiveRegionMode.Assertive }, color = tokens.err.fg, fontWeight = FontWeight.Medium, style = MaterialTheme.typography.bodyMedium)
            OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.action_retry)) }
        }
        status is FetchState.Loading -> Centered {
            CircularProgressIndicator(color = tokens.focus)
            Text(
                stringResource(if (modelView) R.string.viewer_model_view_loading else R.string.viewer_loading),
                Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                color = tokens.textMuted,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        else -> {
            val description = stringResource(R.string.viewer_canvas_description, state.page, state.pageCount.coerceAtLeast(1), filename) + ". " +
                pluralStringResource(R.plurals.viewer_highlights_on_page, state.evidenceOnPage.size, state.evidenceOnPage.size)
            PageSurface(
                pages = pages,
                modelImage = modelBitmap,
                state = state,
                viewport = viewport,
                description = description,
                onTapBox = onSelectBox,
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Controls(
    state: ViewerState,
    viewport: ViewportState,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    onShowModelView: (Boolean) -> Unit,
) {
    val tokens = MaterialTheme.cargo
    val ready = state.file is FetchState.Ready
    Column(Modifier.fillMaxWidth().background(tokens.surface).padding(horizontal = 12.dp, vertical = 6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = onPrevious, enabled = ready && state.canGoPrevious) { Text(stringResource(R.string.viewer_previous)) }
            Text(
                text = if (ready) stringResource(R.string.viewer_page_of, state.page, state.pageCount) else stringResource(R.string.viewer_page_unknown),
                modifier = Modifier.weight(1f).semantics { liveRegion = LiveRegionMode.Polite },
                color = tokens.textMuted,
                style = MaterialTheme.typography.bodySmall,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
            OutlinedButton(onClick = onNext, enabled = ready && state.canGoNext) { Text(stringResource(R.string.viewer_next)) }
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(0.dp), itemVerticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = viewport::zoomOut, enabled = ready) { Text("−", fontSize = 20.sp, modifier = Modifier.semantics { contentDescription = "Zoom out" }) }
            TextButton(onClick = viewport::zoomIn, enabled = ready) { Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.viewer_zoom_in)) }
            TextButton(onClick = viewport::fit, enabled = ready) { Text(stringResource(R.string.viewer_fit)) }
            state.deskewNote?.let { Tag(it, mono = true) }
            if (state.canShowModelView) {
                val model = state.mode == ViewMode.MODEL_VIEW
                FilterChip(
                    selected = model,
                    onClick = { onShowModelView(!model) },
                    label = { Text(stringResource(R.string.viewer_model_view)) },
                )
            }
        }
        if (state.deskewNote != null) Text(stringResource(R.string.viewer_deskew_note), color = tokens.textSubtle, fontSize = 11.sp)
        if (state.mode == ViewMode.MODEL_VIEW) Text(stringResource(R.string.viewer_model_view_note), color = tokens.textSubtle, fontSize = 11.sp)
    }
}

@Composable
private fun SelectedBoxCard(severity: Severity, label: String, value: String?) {
    val tokens = MaterialTheme.cargo
    val colors = when (severity) {
        Severity.PASS -> tokens.ok
        Severity.WARN -> tokens.warn
        Severity.MATERIAL -> tokens.err
    }
    ToneCard(colors, Modifier.padding(12.dp).semantics { liveRegion = LiveRegionMode.Polite }) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Tag(severityText(severity), mono = true, colors = colors)
            Text(stringResource(R.string.viewer_selected_title).uppercase(), color = tokens.textMuted, fontSize = 10.sp, fontWeight = FontWeight.Bold)
            value?.let { Tag(it, mono = true) }
        }
        // a long finding is cut to three lines; a tap shows all of it
        var expanded by remember(label) { mutableStateOf(false) }
        Text(
            label,
            Modifier.clickable(role = Role.Button) { expanded = !expanded },
            color = tokens.text,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium,
            maxLines = if (expanded) Int.MAX_VALUE else 3,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun severityText(severity: Severity): String = when (severity) {
    Severity.PASS -> stringResource(R.string.severity_pass)
    Severity.WARN -> stringResource(R.string.severity_warn)
    Severity.MATERIAL -> stringResource(R.string.severity_material)
}

/** The evidence the assessment cites on this page, as a list: the way to reach a box for someone who cannot see or tap the canvas, and a way to jump to one. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun EvidenceSheet(evidence: List<Highlight>, selectedId: String?, onDismiss: () -> Unit, onChoose: (Highlight) -> Unit) {
    val tokens = MaterialTheme.cargo
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = tokens.surface) {
        Text(
            stringResource(R.string.viewer_evidence_title, evidence.size),
            Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            color = tokens.text,
            fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.titleSmall,
        )
        if (evidence.isEmpty()) {
            Text(stringResource(R.string.viewer_evidence_none), Modifier.padding(16.dp), color = tokens.textMuted, style = MaterialTheme.typography.bodyMedium)
        } else {
            LazyColumn(Modifier.fillMaxWidth(), contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 24.dp)) {
                items(evidence, key = { it.id }) { highlight ->
                    val colors = when (highlight.severity) {
                        Severity.PASS -> tokens.ok
                        Severity.WARN -> tokens.warn
                        Severity.MATERIAL -> tokens.err
                    }
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable(role = Role.Button) { onChoose(highlight) }
                            .padding(horizontal = 16.dp, vertical = 12.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Tag(severityText(highlight.severity), mono = true, colors = colors)
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            // the value tells apart the boxes of one finding, whose message is the same for all of them
                            highlight.value?.let { Text(it, color = tokens.text, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyMedium) }
                            Text(
                                highlight.label,
                                color = if (highlight.value != null) tokens.textMuted else tokens.text,
                                fontWeight = if (highlight.id == selectedId) FontWeight.Bold else FontWeight.Normal,
                                style = if (highlight.value != null) MaterialTheme.typography.bodySmall else MaterialTheme.typography.bodyMedium,
                                maxLines = 3,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Centered(content: @Composable () -> Unit) {
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically), horizontalAlignment = Alignment.CenterHorizontally) { content() }
}

/** Decodes a PNG into no more than [maxPixels] pixels, by sub-sampling (a scan can be bigger than this phone has room for), and again at half the size if even that runs out of memory. */
private suspend fun decodeBounded(file: File, maxPixels: Long): Bitmap? = withContext(Dispatchers.IO) {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(file.path, bounds)
    var sample = sampleSizeFor(bounds.outWidth, bounds.outHeight, maxPixels)
    var decoded: Bitmap? = null
    var finished = false
    while (!finished) {
        try {
            decoded = BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
            finished = true
        } catch (e: OutOfMemoryError) {
            if (sample >= MAX_SAMPLE) finished = true else sample *= 2
        }
    }
    decoded
}

private const val MAX_SAMPLE = 16
