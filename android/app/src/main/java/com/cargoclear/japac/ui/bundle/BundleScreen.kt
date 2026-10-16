package com.cargoclear.japac.ui.bundle

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FabPosition
import androidx.compose.material3.VerticalDivider
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Surface
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import android.net.Uri
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.cargoclear.japac.BuildConfig
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.CorrectionDraft
import com.cargoclear.japac.core.model.CorrectionsUi
import com.cargoclear.japac.core.model.LoadState
import com.cargoclear.japac.core.model.PrefillFormat
import com.cargoclear.japac.core.model.RunMode
import com.cargoclear.japac.core.model.Status
import com.cargoclear.japac.core.model.StreamConnection
import com.cargoclear.japac.core.model.WorkbenchState
import com.cargoclear.japac.core.model.isDemoData
import com.cargoclear.japac.core.model.isTwoPane
import com.cargoclear.japac.core.model.readCell
import com.cargoclear.japac.core.model.webOriginOf
import com.cargoclear.japac.core.model.workbenchLink
import com.cargoclear.japac.notify.NotifyViewModel
import com.cargoclear.japac.notify.rememberNotifyEnabler
import com.cargoclear.japac.ui.assess.AssessmentTab
import com.cargoclear.japac.ui.assess.CorrectionSheet
import com.cargoclear.japac.ui.assess.PrefillUi
import com.cargoclear.japac.ui.assess.PrefillViewModel
import com.cargoclear.japac.ui.assess.StatusPill
import com.cargoclear.japac.ui.common.HistoryIcon
import com.cargoclear.japac.ui.common.Tag
import com.cargoclear.japac.ui.history.AuditUi
import com.cargoclear.japac.ui.nav.ViewerRoute
import com.cargoclear.japac.ui.history.AuditViewModel
import com.cargoclear.japac.ui.history.HistoryTab
import com.cargoclear.japac.ui.scan.AddDocumentSheet
import com.cargoclear.japac.ui.scan.rememberDocumentScanner
import com.cargoclear.japac.ui.common.relativeTime
import com.cargoclear.japac.ui.shell.DemoBanner
import com.cargoclear.japac.ui.theme.cargo

private enum class BundleTab { ASSESSMENT, DOCUMENTS, HISTORY }

/** One bundle: its status, the assessment and its documents, with the controls to run it and add documents (port of app/workbench/[bundleId]/page.tsx). */
@Composable
fun BundleScreen(
    onBack: () -> Unit,
    onOpenViewer: (documentId: String, page: Int?, highlightId: String?) -> Unit,
    viewModel: BundleViewModel = hiltViewModel(),
    auditViewModel: AuditViewModel = hiltViewModel(),
    prefillViewModel: PrefillViewModel = hiltViewModel(),
    notifyViewModel: NotifyViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val appMode by viewModel.appMode.collectAsStateWithLifecycle()
    val correctionsUi by viewModel.correctionsUi.collectAsStateWithLifecycle()
    val audit by auditViewModel.state.collectAsStateWithLifecycle()
    val prefill by prefillViewModel.state.collectAsStateWithLifecycle()
    val notifyOn by notifyViewModel.enabled.collectAsStateWithLifecycle()
    val enableNotify = rememberNotifyEnabler { on, _ -> notifyViewModel.set(on) }
    val scanner = rememberDocumentScanner(onScanned = viewModel::onFilesScanned, onFailed = viewModel::scanFailed)
    val webOrigin = remember { webOriginOf(BuildConfig.API_BASE_URL) }
    val context = androidx.compose.ui.platform.LocalContext.current
    val configuration = androidx.compose.ui.platform.LocalConfiguration.current
    val twoPane = isTwoPane(configuration.screenWidthDp, configuration.screenHeightDp)
    val paneNav = androidx.navigation.compose.rememberNavController()

    // A downloaded pre-fill pack is handed to the system share sheet (the file provider gives it a temporary read grant, no storage permission).
    val chooserTitle = stringResource(R.string.prefill_chooser)
    val shareChooserTitle = stringResource(R.string.share_link_chooser)
    androidx.compose.runtime.LaunchedEffect(prefillViewModel) {
        prefillViewModel.shares.collect { share -> sharePrefill(context, share.file, share.format.mimeType, chooserTitle) }
    }

    // The system file picker (ACTION_OPEN_DOCUMENT): its Uris can be kept readable for the background upload.
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        viewModel.onFilesPicked(uris.map(Uri::toString))
    }

    // The live stream is held only while the screen is visible.
    LifecycleStartEffect(viewModel) {
        viewModel.onScreenStarted()
        onStopOrDispose { viewModel.onScreenStopped() }
    }

    BundleContent(
        bundleId = viewModel.bundleId,
        state = state,
        appMode = appMode,
        onBack = onBack,
        onRetry = viewModel::retry,
        onSelectDocument = viewModel::selectDocument,
        // two panes: the document opens beside the assessment instead of replacing the screen
        onOpenViewer = { documentId, page, highlightId ->
            if (twoPane) paneNav.openInPane(ViewerRoute(viewModel.bundleId, documentId, page ?: 1, highlightId)) else onOpenViewer(documentId, page, highlightId)
        },
        onRun = viewModel::runAnalysis,
        onAddDocuments = { picker.launch(arrayOf("application/pdf")) },
        onUseSampleMtc = viewModel::useSampleMtc,
        onCancelUploads = viewModel::cancelUploads,
        onDismissError = viewModel::dismissError,
        correctionsUi = correctionsUi,
        onCorrect = viewModel::openCorrection,
        onEditCorrection = viewModel::editCorrection,
        onCorrectionValueLoaded = viewModel::correctionValueLoaded,
        onSaveCorrection = viewModel::saveCorrection,
        onCloseCorrection = viewModel::closeCorrection,
        onRevert = viewModel::revertCorrection,
        onRecompute = viewModel::recompute,
        audit = audit,
        onLoadAudit = auditViewModel::load,
        onSignNow = auditViewModel::signNow,
        prefill = prefill,
        onSharePrefill = { format -> state.assessment?.let { prefillViewModel.share(it.iteration, format) } },
        notifyOffer = !notifyOn,
        onNotifyMe = { enableNotify(true) },
        scanAvailable = scanner.available,
        onScan = scanner.start,
        shareLink = workbenchLink(webOrigin, viewModel.bundleId),
        onShareLink = { link -> shareLink(context, link, shareChooserTitle) },
        twoPane = twoPane,
        pane = { paneModifier ->
            BundlePane(paneNav, viewModel.bundleId, state, onSelectDocument = viewModel::selectDocument, onAddDocuments = { picker.launch(arrayOf("application/pdf")) }, modifier = paneModifier)
        },
    )
}

/** Hands the web link of a bundle to the share sheet as plain text. */
private fun shareLink(context: android.content.Context, link: String, title: String) {
    val send = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(android.content.Intent.EXTRA_TEXT, link)
    }
    context.startActivity(android.content.Intent.createChooser(send, title))
}

/** Hands a downloaded pre-fill file to the share sheet through the app's file provider. */
private fun sharePrefill(context: android.content.Context, file: java.io.File, mimeType: String, title: String) {
    val uri = androidx.core.content.FileProvider.getUriForFile(context, "${context.packageName}.files", file)
    val send = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
        type = mimeType
        putExtra(android.content.Intent.EXTRA_STREAM, uri)
        clipData = android.content.ClipData.newRawUri(file.name, uri)
        addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    context.startActivity(android.content.Intent.createChooser(send, title))
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BundleContent(
    bundleId: String,
    state: WorkbenchState,
    appMode: AppMode?,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    onSelectDocument: (String) -> Unit,
    modifier: Modifier = Modifier,
    onOpenViewer: (documentId: String, page: Int?, highlightId: String?) -> Unit = { _, _, _ -> },
    onRun: () -> Unit = {},
    onAddDocuments: () -> Unit = {},
    onUseSampleMtc: () -> Unit = {},
    onCancelUploads: () -> Unit = {},
    onDismissError: () -> Unit = {},
    correctionsUi: CorrectionsUi = CorrectionsUi(),
    onCorrect: (documentId: String, documentName: String, path: String) -> Unit = { _, _, _ -> },
    onEditCorrection: ((CorrectionDraft) -> CorrectionDraft) -> Unit = {},
    onCorrectionValueLoaded: () -> Unit = {},
    onSaveCorrection: () -> Unit = {},
    onCloseCorrection: () -> Unit = {},
    onRevert: (correctionId: String) -> Unit = {},
    onRecompute: () -> Unit = {},
    audit: AuditUi = AuditUi(),
    onLoadAudit: () -> Unit = {},
    onSignNow: () -> Unit = {},
    prefill: PrefillUi = PrefillUi(),
    onSharePrefill: (PrefillFormat) -> Unit = {},
    notifyOffer: Boolean = false,
    onNotifyMe: () -> Unit = {},
    scanAvailable: Boolean = false,
    onScan: () -> Unit = {},
    shareLink: String? = null,
    onShareLink: (String) -> Unit = {},
    twoPane: Boolean = false,
    pane: (@Composable (Modifier) -> Unit)? = null,
) {
    val tokens = MaterialTheme.cargo
    var tab by rememberSaveable { mutableIntStateOf(BundleTab.ASSESSMENT.ordinal) }
    val ready = state.load == LoadState.Ready && state.bundle != null
    var addChooserOpen by rememberSaveable { mutableStateOf(false) }
    var menuOpen by remember { mutableStateOf(false) }
    var shareConfirmOpen by rememberSaveable { mutableStateOf(false) }
    var historyOpen by rememberSaveable { mutableStateOf(false) }
    val splitView = twoPane && pane != null
    val historyTab: @Composable (Modifier) -> Unit = { historyModifier ->
        HistoryTab(
            latest = state.assessment,
            audit = audit,
            auditRefreshKey = state.auditRefreshKey,
            onLoadAudit = onLoadAudit,
            onSignNow = onSignNow,
            modifier = historyModifier,
        )
    }
    // with a scanner there are two ways to add a document, so the person is asked; without one the file picker opens straight away
    val requestAdd: () -> Unit = { if (scanAvailable) addChooserOpen = true else onAddDocuments() }

    Scaffold(
        modifier = modifier,
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                // The id and one line under it (where it goes, and its reference), each on a single line that is cut with an ellipsis rather than broken
                // mid-word; the bar is as tall as the text needs, so a large system font does not squeeze it.
                title = {
                    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(
                            bundleId, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, fontSize = 14.sp, color = tokens.text,
                            maxLines = 1, overflow = TextOverflow.Ellipsis,
                        )
                        state.bundle?.let { bundle ->
                            Text(
                                text = listOfNotNull(stringResource(R.string.bundle_destination, bundle.destinationCountry), bundle.reference?.takeIf { it.isNotBlank() }).joinToString(" · "),
                                color = tokens.textMuted, style = MaterialTheme.typography.labelSmall, maxLines = 1, overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                },
                expandedHeight = TopAppBarDefaults.TopAppBarExpandedHeight * LocalDensity.current.fontScale.coerceIn(1f, 2f),
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.action_back))
                    }
                },
                actions = {
                    if (ready) {
                        IconButton(onClick = requestAdd, enabled = state.canAddDocuments) {
                            Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.action_add_document))
                        }
                        // only when there is something to put in it: a link to the web workbench exists only where the app reaches the UI's own proxy
                        if (shareLink != null) {
                            Box {
                                IconButton(onClick = { menuOpen = true }) {
                                    Icon(Icons.Filled.MoreVert, contentDescription = stringResource(R.string.more_options))
                                }
                                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                                    DropdownMenuItem(
                                        text = { Text(stringResource(R.string.share_link_action)) },
                                        onClick = {
                                            menuOpen = false
                                            shareConfirmOpen = true
                                        },
                                    )
                                }
                            }
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = tokens.surface),
            )
        },
        floatingActionButton = {
            if (ready) RunButton(state, onRun)
        },
        // beside the viewer the button would sit on its controls: it keeps to the assessment's side
        floatingActionButtonPosition = if (splitView) FabPosition.Start else FabPosition.End,
        bottomBar = {
            // two panes show the assessment and the documents together; the history folds up under them (and the Run button sits above it)
            if (ready && splitView) HistoryPanel(open = historyOpen, onToggle = { historyOpen = !historyOpen }) { historyTab(Modifier) }
            if (ready && !splitView) {
                NavigationBar(containerColor = tokens.surface) {
                    NavigationBarItem(
                        selected = tab == BundleTab.ASSESSMENT.ordinal,
                        onClick = { tab = BundleTab.ASSESSMENT.ordinal },
                        icon = { Icon(Icons.Filled.CheckCircle, contentDescription = null) },
                        label = { TabLabel(stringResource(R.string.tab_assessment)) },
                        colors = NavigationBarItemDefaults.colors(indicatorColor = tokens.surface2),
                    )
                    NavigationBarItem(
                        selected = tab == BundleTab.DOCUMENTS.ordinal,
                        onClick = { tab = BundleTab.DOCUMENTS.ordinal },
                        icon = { Icon(Icons.AutoMirrored.Filled.List, contentDescription = null) },
                        label = { TabLabel(stringResource(R.string.tab_documents)) },
                        colors = NavigationBarItemDefaults.colors(indicatorColor = tokens.surface2),
                    )
                    NavigationBarItem(
                        selected = tab == BundleTab.HISTORY.ordinal,
                        onClick = { tab = BundleTab.HISTORY.ordinal },
                        icon = { Icon(HistoryIcon, contentDescription = null) },
                        label = { TabLabel(stringResource(R.string.tab_history)) },
                        colors = NavigationBarItemDefaults.colors(indicatorColor = tokens.surface2),
                    )
                }
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            when (val load = state.load) {
                LoadState.Loading -> Centered {
                    CircularProgressIndicator(color = tokens.focus)
                    Text(
                        stringResource(R.string.bundle_loading),
                        Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                        color = tokens.textMuted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                LoadState.NotFound -> Centered {
                    Text(stringResource(R.string.bundle_not_found_title), color = tokens.text, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(stringResource(R.string.bundle_not_found_body, bundleId), color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)
                    OutlinedButton(onClick = onBack) { Text(stringResource(R.string.bundle_back_to_start)) }
                }
                is LoadState.Failed -> Centered {
                    Text(
                        stringResource(R.string.bundle_load_failed, load.message),
                        Modifier.semantics { liveRegion = LiveRegionMode.Assertive },
                        color = tokens.err.fg,
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium,
                    )
                    OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.action_retry)) }
                }
                LoadState.Ready -> {
                    if (isDemoData(appMode, state.assessment?.dataSource)) DemoBanner()
                    state.savedCopyAt?.let { SavedCopyBanner(it) }
                    BundleStatusRow(state)
                    ActivityPanel(state, onDismissError = onDismissError, onCancelUploads = onCancelUploads, notifyOffer = notifyOffer, onNotifyMe = onNotifyMe)
                    val assessmentTab: @Composable () -> Unit = {
                        AssessmentTab(
                            state = state,
                            appMode = appMode,
                            onOpenEvidence = { target ->
                                onSelectDocument(target.documentId)
                                onOpenViewer(target.documentId, target.page, target.highlightId)
                            },
                            onAddDocuments = requestAdd,
                            onUseSampleMtc = onUseSampleMtc,
                            correctionsUi = correctionsUi,
                            prefill = prefill,
                            onCorrect = onCorrect,
                            onRevert = onRevert,
                            onRecompute = onRecompute,
                            onSharePrefill = onSharePrefill,
                        )
                    }
                    if (splitView && pane != null) {
                        Row(Modifier.fillMaxSize()) {
                            Box(Modifier.weight(SPLIT_ASSESSMENT_SHARE).fillMaxSize()) { assessmentTab() }
                            VerticalDivider(color = tokens.border)
                            pane(Modifier.weight(1f - SPLIT_ASSESSMENT_SHARE).fillMaxSize())
                        }
                    } else {
                        Box(Modifier.fillMaxSize()) {
                            when (BundleTab.entries[tab]) {
                                BundleTab.ASSESSMENT -> assessmentTab()
                                BundleTab.HISTORY -> historyTab(Modifier)
                                BundleTab.DOCUMENTS -> DocumentsTab(
                                    state,
                                    onOpen = { id ->
                                        onSelectDocument(id)
                                        onOpenViewer(id, null, null)
                                    },
                                    onAddDocuments = requestAdd,
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    // the correction editor sits over whichever tab is showing
    correctionsUi.editor?.takeIf { ready }?.let { editor ->
        CorrectionSheet(
            editor = editor,
            current = readCell(state.extractions, editor.draft.documentId, editor.draft.path),
            onEdit = onEditCorrection,
            onValueLoaded = onCorrectionValueLoaded,
            onSave = onSaveCorrection,
            onDismiss = onCloseCorrection,
        )
    }

    if (addChooserOpen) {
        AddDocumentSheet(
            onChoosePdf = {
                addChooserOpen = false
                onAddDocuments()
            },
            onScan = {
                addChooserOpen = false
                onScan()
            },
            onDismiss = { addChooserOpen = false },
        )
    }

    // a bundle id is the only access control the backend has, so a link to it is a key: say so before it is handed out
    if (shareConfirmOpen && shareLink != null) {
        AlertDialog(
            onDismissRequest = { shareConfirmOpen = false },
            title = { Text(stringResource(R.string.share_link_title)) },
            text = { Text(stringResource(R.string.share_link_body)) },
            confirmButton = {
                TextButton(onClick = {
                    shareConfirmOpen = false
                    onShareLink(shareLink)
                }) { Text(stringResource(R.string.share_link_confirm)) }
            },
            dismissButton = { TextButton(onClick = { shareConfirmOpen = false }) { Text(stringResource(R.string.action_cancel)) } },
        )
    }
}

/** How much of the width the assessment takes beside the document. */
private const val SPLIT_ASSESSMENT_SHARE = 0.42f

/** History under the two panes, folded to its header until asked for (the web's collapsible drawer). */
@Composable
private fun HistoryPanel(open: Boolean, onToggle: () -> Unit, content: @Composable () -> Unit) {
    val tokens = MaterialTheme.cargo
    Column(Modifier.fillMaxWidth().background(tokens.surface).navigationBarsPadding()) {
        androidx.compose.material3.HorizontalDivider(color = tokens.border)
        Row(
            Modifier.fillMaxWidth().defaultMinSize(minHeight = 48.dp).clickable(role = Role.Button, onClick = onToggle).padding(horizontal = 16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(stringResource(R.string.tab_history), color = tokens.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.labelLarge)
            Text(stringResource(if (open) R.string.history_collapse else R.string.history_expand), color = tokens.textMuted, style = MaterialTheme.typography.labelMedium)
        }
        if (open) {
            // never more than 40% of the window: the two panes above it are what the screen is for
            val windowHeight = androidx.compose.ui.platform.LocalConfiguration.current.screenHeightDp.dp
            Box(Modifier.fillMaxWidth().height(minOf(HISTORY_PANEL_HEIGHT, windowHeight * 0.4f))) { content() }
        }
    }
}

private val HISTORY_PANEL_HEIGHT = 320.dp

/**
 * "Run analysis" until the first assessment exists, "Reassess" afterwards (the web's primary button). While a run goes it reads
 * "Analysis running…" and does nothing; on a saved copy it is not offered, because nothing can be sent from one.
 *
 * Built from a clickable [Surface] rather than `ExtendedFloatingActionButton`: the latter leaves its label out of the merged
 * semantics, so a screen reader would announce "button" and nothing else. Here the label and the disabled state belong to the button.
 */
@Composable
private fun RunButton(state: WorkbenchState, onRun: () -> Unit) {
    val tokens = MaterialTheme.cargo
    if (state.isReadOnly) return
    val enabled = state.canRun
    val label = when {
        state.isRunning -> R.string.action_running
        state.runMode == RunMode.ANALYZE -> R.string.action_run_analysis
        else -> R.string.action_reassess
    }
    val content = if (enabled) tokens.onFocus else tokens.textMuted
    Surface(
        onClick = onRun,
        enabled = enabled,
        modifier = Modifier.semantics { role = Role.Button },
        shape = RoundedCornerShape(16.dp),
        color = if (enabled) tokens.focus else tokens.surface2,
        contentColor = content,
        shadowElevation = 6.dp,
    ) {
        Row(
            Modifier.defaultMinSize(minHeight = 56.dp).padding(horizontal = 20.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (state.isRunning) {
                CircularProgressIndicator(Modifier.size(18.dp), color = content, strokeWidth = 2.dp)
            } else {
                Icon(Icons.Filled.PlayArrow, contentDescription = null)
            }
            Text(stringResource(label), fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.labelLarge)
        }
    }
}

/** A bottom-bar label on one line that shrinks to fit its third of the width rather than breaking in the middle of a word at a large system font. */
@Composable
private fun TabLabel(text: String) {
    Text(text, maxLines = 1, softWrap = false, overflow = TextOverflow.Ellipsis, autoSize = androidx.compose.foundation.text.TextAutoSize.StepBased(minFontSize = 9.sp, maxFontSize = 12.sp))
}

@Composable
private fun BundleStatusRow(state: WorkbenchState) {
    val tokens = MaterialTheme.cargo
    // One source for both: an assessment whose status this app does not know must not fall back to the bundle's older status.
    val raw = state.assessment?.status ?: state.bundle?.status
    val kind = Status.fromWire(raw)
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        StatusPill(kind, unrecognised = kind == null && raw != null && raw != "PENDING")
        if (state.connection != StreamConnection.OPEN) {
            Text(
                text = stringResource(if (state.connection == StreamConnection.RECONNECTING) R.string.bundle_live_reconnecting else R.string.bundle_live_connecting),
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                color = tokens.textMuted,
                fontSize = 11.sp,
            )
        }
    }
}

@Composable
private fun SavedCopyBanner(savedAt: Long) {
    val tokens = MaterialTheme.cargo
    val whenSaved = relativeTime(savedAt)
    Text(
        text = stringResource(R.string.bundle_saved_copy, whenSaved),
        modifier = Modifier
            .fillMaxWidth()
            .semantics { liveRegion = LiveRegionMode.Polite }
            .background(tokens.warn.bg)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        color = tokens.warn.fg,
        style = MaterialTheme.typography.labelMedium,
    )
}

@Composable
private fun Centered(content: @Composable () -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) { content() }
}
