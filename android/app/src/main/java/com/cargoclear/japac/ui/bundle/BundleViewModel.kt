package com.cargoclear.japac.ui.bundle

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.BundleRepository
import com.cargoclear.japac.core.data.CorrectionRepository
import com.cargoclear.japac.core.data.DocumentRepository
import com.cargoclear.japac.core.data.FileImporter
import com.cargoclear.japac.core.data.MetaRepository
import com.cargoclear.japac.core.data.RecentBundlesRepository
import com.cargoclear.japac.core.data.StreamEvent
import com.cargoclear.japac.core.data.UploadBatchRunner
import com.cargoclear.japac.core.data.work.UploadScheduler
import com.cargoclear.japac.core.model.ActionError
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.CellValue
import com.cargoclear.japac.core.model.CorrectionDraft
import com.cargoclear.japac.core.model.CorrectionsUi
import com.cargoclear.japac.core.model.correctionEditorFromSavedState
import com.cargoclear.japac.core.model.toSavedState
import com.cargoclear.japac.core.model.LoadState
import com.cargoclear.japac.core.model.RunMode
import com.cargoclear.japac.core.model.RunResponse
import com.cargoclear.japac.core.model.SCAN_UNAVAILABLE_MESSAGE
import com.cargoclear.japac.core.model.SCAN_UNREADABLE_MESSAGE
import com.cargoclear.japac.core.model.SAMPLE_MTC_FILENAME
import com.cargoclear.japac.core.model.StreamConnection
import com.cargoclear.japac.core.model.UploadStatus
import com.cargoclear.japac.core.model.UploadUpdate
import com.cargoclear.japac.core.model.UploadWatcher
import com.cargoclear.japac.core.model.WatchedRun
import com.cargoclear.japac.core.model.WorkbenchState
import com.cargoclear.japac.core.model.readCell
import com.cargoclear.japac.core.model.runCatchingCancellable
import com.cargoclear.japac.core.model.runErrorMessage
import com.cargoclear.japac.core.model.toUpdate
import com.cargoclear.japac.notify.RunTracker
import com.cargoclear.japac.ui.nav.BundleRoute
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * One bundle on screen: loads it, keeps it live over the stream, remembers it on this device, and starts runs and uploads. Port of
 * `useWorkbench`; every rule about what the screen shows lives in [WorkbenchState] (core:model), this class only does the fetching and
 * the asking.
 */
@HiltViewModel
class BundleViewModel @Inject constructor(
    private val savedStateHandle: SavedStateHandle,
    private val bundles: BundleRepository,
    private val recents: RecentBundlesRepository,
    private val meta: MetaRepository,
    private val documents: DocumentRepository,
    private val uploads: UploadScheduler,
    private val uploadRunner: UploadBatchRunner,
    private val corrections: CorrectionRepository,
    private val importer: FileImporter,
    private val tracker: RunTracker,
) : ViewModel() {
    /** The route's argument, by the name of its property (that is the key type-safe navigation stores it under). */
    val bundleId: String = checkNotNull(savedStateHandle.get<String>(BundleRoute::bundleId.name)) { "the bundle route carries no bundle id" }

    private val mutableState = MutableStateFlow(WorkbenchState())
    val state: StateFlow<WorkbenchState> = mutableState.asStateFlow()

    /** The correction editor and the undo in flight (what the person is doing, apart from what the server holds). */
    // an editor that was open when the system ended the process comes back with what was typed in it
    private val mutableCorrectionsUi = MutableStateFlow(CorrectionsUi(editor = correctionEditorFromSavedState(savedStateHandle.get<String>(EDITOR_KEY))))
    val correctionsUi: StateFlow<CorrectionsUi> = mutableCorrectionsUi.asStateFlow()

    /** The backend's mode, for the demo banner; null until known (or if it could not be read). */
    private val mutableMode = MutableStateFlow<AppMode?>(null)
    val appMode: StateFlow<AppMode?> = mutableMode.asStateFlow()

    private var streamJob: Job? = null
    private var pollJob: Job? = null
    private var loadJob: Job? = null
    private var uploadsJob: Job? = null
    private var refreshJob: Job? = null

    /** Refreshes of the correction list can overlap (a new assessment arrives while an undo is recorded): only the newest request may set the state. */
    private var correctionsRequest = 0

    /** Remembers which batches this screen has seen finish, across the screen being stopped and started again. */
    private val uploadWatcher = UploadWatcher()

    init {
        load()
        viewModelScope.launch { mutableMode.value = runCatchingCancellable { meta.load().appMode }.getOrNull() }
        observeShownAssessment()
        observeRunToWatch()
        rememberEditor()
    }

    // ---- the screen's lifecycle: the stream is held only while the screen is visible

    fun onScreenStarted() {
        if (streamJob?.isActive == true) return
        streamJob = viewModelScope.launch { bundles.events(bundleId).collect(::onStreamEvent) }
        uploadsJob = viewModelScope.launch { uploads.batches(bundleId).collect { onUploadBatches(it) } }
    }

    fun onScreenStopped() {
        streamJob?.cancel()
        streamJob = null
        uploadsJob?.cancel()
        uploadsJob = null
        pollJob?.cancel()
        pollJob = null
        mutableState.update { it.connection(StreamConnection.CONNECTING) }
    }

    fun retry() {
        mutableState.update { it.reloading() }
        mutableCorrectionsUi.update { it.reset() }
        load()
    }

    fun selectDocument(documentId: String) = mutableState.update { it.selectDocument(documentId) }

    // ---- runs

    /** "Run analysis" until the first assessment exists, "Reassess" afterwards. */
    fun runAnalysis() = startRun { mode -> if (mode == RunMode.ANALYZE) bundles.analyze(bundleId) else bundles.reassess(bundleId) }

    /** Re-runs the checks on the stored extraction with the corrections applied. */
    fun recompute() = startRun { bundles.recompute(bundleId) }

    private fun startRun(request: suspend (RunMode) -> RunResponse) {
        val current = mutableState.value
        if (!current.canRun) return
        val mode = current.runMode
        mutableState.update { it.runRequested() }
        viewModelScope.launch {
            try {
                val started = request(mode)
                mutableState.update { it.runStarted(started.runId) }
            } catch (e: ApiException) {
                mutableState.update { it.runRejected(ActionError(runErrorMessage(e.envelope), e.requestId)) }
            }
        }
    }

    fun dismissError() = mutableState.update { it.errorDismissed() }

    /** Keeps the open editor in the screen's saved state (null when none is open), so a half-typed correction survives the process being ended. */
    private fun rememberEditor() {
        viewModelScope.launch {
            mutableCorrectionsUi.map { it.editor?.toSavedState() }.distinctUntilChanged().collect { savedStateHandle[EDITOR_KEY] = it }
        }
    }

    // ---- leaving the app mid-run

    /**
     * Tells the run tracker which run to keep an eye on if the person leaves the app, and when there is none. The tracker's entry is not
     * cleared when this screen goes away mid-run (nobody could say when the run ended); it expires on its own.
     */
    private fun observeRunToWatch() {
        viewModelScope.launch {
            mutableState.map { it.runToWatch }.distinctUntilChanged().collect { runId ->
                if (runId == null) tracker.clear(bundleId) else tracker.track(WatchedRun(bundleId, runId))
            }
        }
    }

    // ---- corrections

    /**
     * The extraction behind the assessment on screen (what its checks saw, corrections laid on) and the correction list follow it: fetched
     * when the bundle is ready and whenever a newer assessment arrives. Not from a saved copy (nothing can be fetched), and a newer
     * assessment replaces a fetch that is still going.
     */
    private fun observeShownAssessment() {
        viewModelScope.launch {
            mutableState
                .map { if (it.load == LoadState.Ready && !it.isReadOnly) it.shownIteration else null }
                .distinctUntilChanged()
                .collectLatest { iteration ->
                    when (iteration) {
                        null -> Unit
                        0 -> mutableState.update { it.correctionDataCleared() }
                        else -> loadCorrectionData(iteration)
                    }
                }
        }
    }

    private suspend fun loadCorrectionData(iteration: Int) = coroutineScope {
        launch {
            val docs = try {
                corrections.extractions(bundleId, iteration)
            } catch (_: ApiException) {
                emptyList() // the editor then says it cannot read the value yet, and Save stays off
            }
            mutableState.update { it.extractionsLoaded(docs) }
        }
        launch { refreshCorrections() }
    }

    private suspend fun refreshCorrections() {
        val mine = ++correctionsRequest
        try {
            val next = corrections.corrections(bundleId)
            if (mine == correctionsRequest) mutableState.update { it.correctionsLoaded(next) }
        } catch (_: ApiException) {
            // the list on screen stays as it was; the next refresh replaces it
        }
    }

    fun openCorrection(documentId: String, documentName: String, path: String) {
        val current = mutableState.value
        if (!current.canCorrect) return
        mutableCorrectionsUi.update { it.opened(documentId, documentName, path, readCell(current.extractions, documentId, path)) }
    }

    fun closeCorrection() = mutableCorrectionsUi.update { it.closed() }

    fun editCorrection(change: (CorrectionDraft) -> CorrectionDraft) = mutableCorrectionsUi.update { it.edited(change) }

    /** The extraction arrived (or changed) while the editor was open: fill the fields, unless the person has typed. */
    fun correctionValueLoaded() {
        val editor = mutableCorrectionsUi.value.editor ?: return
        val cell = readCell(mutableState.value.extractions, editor.draft.documentId, editor.draft.path)
        mutableCorrectionsUi.update { it.edited { draft -> draft.loaded(cell) } }
    }

    /** Records the open editor's value. A refusal stays in the editor in the server's words; success closes it. */
    fun saveCorrection() {
        val editor = mutableCorrectionsUi.value.editor ?: return
        val current = readCell(mutableState.value.extractions, editor.draft.documentId, editor.draft.path)
        if (!mutableState.value.canCorrect || !editor.draft.canSave(current)) return
        mutableCorrectionsUi.update { it.saving() }
        viewModelScope.launch {
            try {
                corrections.submit(bundleId, editor.draft.request())
                refreshCorrections()
                mutableCorrectionsUi.update { it.closed() }
            } catch (e: ApiException) {
                mutableCorrectionsUi.update { it.saveFailed(e.message.orEmpty()) }
            }
        }
    }

    /** Undoes a correction that is in force. The failure shows on the corrections card. */
    fun revertCorrection(correctionId: String) {
        if (!mutableState.value.canCorrect || mutableCorrectionsUi.value.revertingId != null) return
        mutableCorrectionsUi.update { it.reverting(correctionId) }
        viewModelScope.launch {
            try {
                corrections.revert(bundleId, correctionId)
                refreshCorrections()
                mutableCorrectionsUi.update { it.reverted() }
            } catch (e: ApiException) {
                mutableCorrectionsUi.update { it.revertFailed(e.message.orEmpty()) }
            }
        }
    }

    // ---- uploads

    /** The files the person picked (content Uris as text). They go up in the background, one after another, and the screen follows along. */
    fun onFilesPicked(uris: List<String>) {
        val current = mutableState.value
        if (uris.isEmpty() || !current.canAddDocuments) return
        mutableState.update { it.errorDismissed() }
        uploads.enqueue(bundleId, uris, current.currentIteration)
    }

    fun cancelUploads() = uploads.cancel(bundleId)

    /** The document scanner produced these files (in its own storage): copy them into the app's cache, where the background upload can read them later, and send them. */
    fun onFilesScanned(uris: List<String>) {
        if (uris.isEmpty() || !mutableState.value.canAddDocuments) return
        viewModelScope.launch {
            val result = importer.import(uris)
            if (result.imported.isEmpty()) {
                mutableState.update { it.actionFailed(ActionError(SCAN_UNREADABLE_MESSAGE)) }
            } else {
                onFilesPicked(result.imported.map { it.uri })
            }
        }
    }

    fun scanFailed() = mutableState.update { it.actionFailed(ActionError(SCAN_UNAVAILABLE_MESSAGE)) }

    /** Demo mode only: uploads the sample mill test certificate (small, so it goes up right here rather than through the scheduler). */
    fun useSampleMtc() {
        val current = mutableState.value
        if (!current.canAddDocuments) return
        mutableState.update { it.errorDismissed().uploadUpdated(UploadUpdate(active = UploadStatus.Active(1, 1, SAMPLE_MTC_FILENAME))) }
        viewModelScope.launch {
            val update = try {
                uploadRunner.run(bundleId, listOf(documents.sampleMtc()), current.currentIteration).outcome.toUpdate()
            } catch (e: ApiException) {
                UploadUpdate(failure = UploadStatus.Failed(ActionError(e.message.orEmpty(), e.requestId), uploaded = 0, total = 1))
            }
            applyUploadUpdate(update)
        }
    }

    private fun onUploadBatches(batches: List<com.cargoclear.japac.core.model.UploadBatch>) = applyUploadUpdate(uploadWatcher.update(batches))

    private fun applyUploadUpdate(update: UploadUpdate) {
        mutableState.update { it.uploadUpdated(update) }
        if (update.bundleChanged) viewModelScope.launch { refreshBundle() }
    }

    /** One refresh of the bundle after documents landed (the web's `refreshBundle`); a failure leaves what is shown as it was. */
    private suspend fun refreshBundle() {
        runCatchingCancellable { bundles.bundle(bundleId) }.onSuccess { fresh ->
            mutableState.update { it.bundleRefreshed(fresh) }
            recents.remember(fresh, mutableState.value.assessment)
        }
    }

    // ---- loading

    private fun load() {
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            try {
                val (bundle, assessment, iterations) = fetchAll()
                mutableState.update { it.loaded(bundle, assessment, iterations) }
                recents.remember(bundle, assessment)
                refreshIfNeeded()
            } catch (e: ApiException) {
                val saved = if (e.isNotFound) null else recents.savedCopy(bundleId)
                if (saved != null) {
                    mutableState.update { it.loadedFromSavedCopy(saved.bundle, saved.assessment, saved.savedAt) }
                } else {
                    mutableState.update { it.loadFailed(notFound = e.isNotFound, message = e.message.orEmpty()) }
                }
            }
        }
    }

    private suspend fun fetchAll(): Triple<com.cargoclear.japac.core.model.Bundle, AssessmentIteration?, List<AssessmentIteration>> = coroutineScope {
        val bundle = bundles.bundle(bundleId)
        if (bundle.currentIteration > 0) {
            val assessment = async { bundles.latestAssessment(bundleId) }
            val iterations = async { runCatchingCancellable { bundles.iterations(bundleId) }.getOrDefault(emptyList()) }
            Triple(bundle, assessment.await(), iterations.await())
        } else {
            Triple(bundle, null, emptyList())
        }
    }

    // ---- the stream

    private fun onStreamEvent(event: StreamEvent) {
        when (event) {
            StreamEvent.Opened -> {
                pollJob?.cancel()
                pollJob = null
                val wasSavedCopy = mutableState.value.savedCopyAt != null
                mutableState.update { it.connection(StreamConnection.OPEN) }
                if (wasSavedCopy) retry() // the server is reachable again: replace the saved copy with the live bundle
            }
            is StreamEvent.Status -> mutableState.update { it.streamStatus(event.event) }
            is StreamEvent.Iteration -> {
                mutableState.update { it.streamIteration(event.iteration) }
                refreshIfNeeded()
            }
            is StreamEvent.ServerError -> mutableState.update { it.streamFailed(event.event.message) }
            is StreamEvent.Unreadable -> mutableState.update { it.streamFailed(UNREADABLE_UPDATE) }
            is StreamEvent.Disconnected -> {
                mutableState.update { it.connection(StreamConnection.RECONNECTING) }
                if (event.attempt >= POLL_AFTER_ATTEMPTS) startPolling()
            }
            is StreamEvent.Rejected -> Unit // no such bundle: the load already says so
        }
    }

    /**
     * The stream carried an iteration the screen has not caught up with: refetch the bundle (document types change after classification) and
     * the iteration list, and remember the new state on this device. The iteration counts as caught up only once both reads worked, so one that
     * failed is tried again by the next thing the stream says (a reconnect replays the latest iteration). One refresh runs at a time; an
     * iteration that arrives while it runs gets its own as soon as it ends.
     */
    private fun refreshIfNeeded() {
        if (refreshJob?.isActive == true) return
        refreshJob = viewModelScope.launch {
            while (true) {
                val iteration = mutableState.value.iterationToRefresh() ?: return@launch
                val fresh = runCatchingCancellable { bundles.bundle(bundleId) }.getOrNull()
                val list = runCatchingCancellable { bundles.iterations(bundleId) }.getOrNull()
                mutableState.update { state ->
                    var next = state
                    if (fresh != null) next = next.bundleRefreshed(fresh)
                    if (list != null) next = next.iterationsRefreshed(list)
                    if (fresh != null && list != null) next.markHandled(iteration) else next
                }
                val current = mutableState.value
                current.bundle?.let { recents.remember(it, current.assessment) }
                if (fresh == null || list == null) return@launch
            }
        }
    }

    /** Fallback while the stream cannot connect: ask for the latest assessment every few seconds. Progress is not available this way. */
    private fun startPolling() {
        if (pollJob?.isActive == true) return
        pollJob = viewModelScope.launch { poll() }
    }

    private suspend fun CoroutineScope.poll() {
        while (isActive) {
            delay(POLL_INTERVAL_MILLIS)
            val latest = try {
                bundles.latestAssessment(bundleId)
            } catch (_: ApiException) {
                null
            }
            if (latest != null) {
                mutableState.update { it.streamIteration(latest) }
                refreshIfNeeded()
            }
        }
    }

    companion object {
        private const val EDITOR_KEY = "correctionEditor"
        private const val POLL_AFTER_ATTEMPTS = 3
        private const val POLL_INTERVAL_MILLIS = 10_000L
        const val UNREADABLE_UPDATE = "An update from the server could not be read. This app may need updating."
    }
}
