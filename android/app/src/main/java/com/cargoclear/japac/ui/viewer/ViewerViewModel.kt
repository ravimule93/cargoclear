package com.cargoclear.japac.ui.viewer

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.BundleRepository
import com.cargoclear.japac.core.data.DocumentFiles
import com.cargoclear.japac.core.data.DocumentRepository
import com.cargoclear.japac.core.data.RecentBundlesRepository
import com.cargoclear.japac.core.data.SettingsRepository
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.Bundle
import com.cargoclear.japac.core.model.FILE_CACHE_FAILED_MESSAGE
import com.cargoclear.japac.core.model.FetchState
import com.cargoclear.japac.core.model.ViewMode
import com.cargoclear.japac.core.model.ViewerState
import com.cargoclear.japac.core.model.buildHighlights
import com.cargoclear.japac.ui.nav.ViewerRoute
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.File
import java.io.IOException
import javax.inject.Inject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * One document on screen: its PDF (kept on the phone once fetched), how its pages were prepared, and the evidence of the latest assessment
 * to outline on it. Every rule about what is shown lives in [ViewerState] (core:model); this class fetches.
 */
@HiltViewModel
class ViewerViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val bundles: BundleRepository,
    private val recents: RecentBundlesRepository,
    private val documents: DocumentRepository,
    private val files: DocumentFiles,
    private val opener: PdfOpener,
    settings: SettingsRepository,
) : ViewModel() {
    val bundleId: String = checkNotNull(savedStateHandle.get<String>(ViewerRoute::bundleId.name)) { "the viewer route carries no bundle id" }
    val documentId: String = checkNotNull(savedStateHandle.get<String>(ViewerRoute::documentId.name)) { "the viewer route carries no document id" }
    private val requestedPage: Int = savedStateHandle.get<Int>(ViewerRoute::page.name) ?: 1
    private val requestedHighlight: String? = savedStateHandle.get<String>(ViewerRoute::highlightId.name)

    private val mutableState = MutableStateFlow(ViewerState())
    val state: StateFlow<ViewerState> = mutableState.asStateFlow()

    private val mutablePages = MutableStateFlow<PdfPages?>(null)

    /** The open document, once its file is there; the screen draws pages from it. Closed with the view model. */
    val pages: StateFlow<PdfPages?> = mutablePages.asStateFlow()

    private val mutableModelImage = MutableStateFlow<File?>(null)

    /** The page image the model was shown, for the page and mode on screen (null until fetched). */
    val modelImage: StateFlow<File?> = mutableModelImage.asStateFlow()

    /** Whether the window blocks screenshots (FLAG_SECURE). On until the person turns it off in Settings. */
    val secure: StateFlow<Boolean> = settings.viewerSecure.stateIn(viewModelScope, SharingStarted.Eagerly, true)

    private var loadJob: Job? = null
    private var modelJob: Job? = null

    init {
        load()
    }

    fun retry() {
        mutableState.update { ViewerState(page = it.page, selectedBoxId = it.selectedBoxId, mode = ViewMode.ORIGINAL) }
        load()
    }

    // ---- what the person does

    fun nextPage() = move { it.nextPage() }

    fun previousPage() = move { it.previousPage() }

    fun showPage(page: Int) = move { it.showing(page) }

    fun selectBox(id: String?) = mutableState.update { it.selectBox(id) }

    fun focusHandled() = mutableState.update { it.focusHandled() }

    fun showModelView(on: Boolean) {
        mutableState.update { it.modelViewShown(on) }
        refreshModelImage()
    }

    private fun move(transition: (ViewerState) -> ViewerState) {
        mutableState.update(transition)
        refreshModelImage()
    }

    // ---- loading

    private fun load() {
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            val context = try {
                fetchContext()
            } catch (e: ApiException) {
                mutableState.update { it.loadFailed(notFound = e.isNotFound, message = e.message.orEmpty()) }
                return@launch
            }
            val record = context.bundle.documents.firstOrNull { it.documentId == documentId }
            if (record == null) {
                mutableState.update { it.loadFailed(notFound = true, message = "") }
                return@launch
            }
            mutableState.update {
                it.opened(record, buildHighlights(context.assessment), context.assessment?.iteration, context.fromSavedCopy)
                    .focusedOn(requestedPage, requestedHighlight)
            }
            coroutineScope {
                launch { loadGeometry(record.transformMetaUri, offline = context.fromSavedCopy) }
                launch { loadFile() }
            }
        }
    }

    private class Context(val bundle: Bundle, val assessment: AssessmentIteration?, val fromSavedCopy: Boolean)

    /**
     * The bundle and its latest assessment from the server; when the server cannot be reached, the copy saved on this phone. The two calls are
     * made one after the other: a failed `async` would cancel its scope whatever the caller catches, and the fallback would never run.
     */
    private suspend fun fetchContext(): Context =
        try {
            val bundle = bundles.bundle(bundleId)
            Context(bundle, bundles.latestAssessment(bundleId), fromSavedCopy = false)
        } catch (e: ApiException) {
            if (e.isNotFound) throw e
            val saved = recents.savedCopy(bundleId) ?: throw e
            Context(saved.bundle, saved.assessment, fromSavedCopy = true)
        }

    /**
     * How the pages were prepared decides where a box goes on the original. A document with no record of its preparation (the server has none,
     * or never made one) was not transformed, so its boxes are exact; a failure to ask leaves them undrawn rather than possibly misplaced.
     */
    private suspend fun loadGeometry(transformMetaUri: String?, offline: Boolean) {
        if (transformMetaUri.isNullOrEmpty()) {
            mutableState.update { it.geometryKnown(emptyList()) }
            return
        }
        if (offline) {
            mutableState.update { it.geometryUnavailable() }
            return
        }
        try {
            val response = documents.transformMetadata(bundleId, documentId)
            mutableState.update { it.geometryKnown(response?.transformMeta.orEmpty()) }
        } catch (e: ApiException) {
            mutableState.update { it.geometryUnavailable() }
        }
    }

    private suspend fun loadFile() {
        mutableState.update { it.copy(file = FetchState.Loading) }
        try {
            val file = files.pdf(bundleId, documentId)
            val opened = opener.open(file)
            mutablePages.value?.close()
            mutablePages.value = opened
            mutableState.update { it.fileReady(opened.pageCount) }
            refreshModelImage()
        } catch (e: ApiException) {
            mutableState.update { it.fileFailed(e.message.orEmpty()) }
        } catch (e: PdfUnreadableException) {
            mutableState.update { it.fileFailed(e.message.orEmpty()) }
        } catch (e: IOException) {
            // the cache could not be written (the download could not be put in place)
            mutableState.update { it.fileFailed(FILE_CACHE_FAILED_MESSAGE) }
        } catch (e: IllegalArgumentException) {
            // an id the cache will not turn into a file name
            mutableState.update { it.fileFailed(FILE_CACHE_FAILED_MESSAGE) }
        }
    }

    /** Fetches the page image the model was shown while "What the model saw" is on; forgets it when it is off. */
    private fun refreshModelImage() {
        modelJob?.cancel()
        val current = mutableState.value
        val iteration = current.iteration
        if (current.mode != ViewMode.MODEL_VIEW || iteration == null) {
            mutableModelImage.value = null
            mutableState.update { it.modelImage(FetchState.Loading) }
            return
        }
        val page = current.page
        mutableModelImage.value = null
        mutableState.update { it.modelImage(FetchState.Loading) }
        modelJob = viewModelScope.launch {
            try {
                val file = files.processedPage(bundleId, documentId, page, iteration)
                mutableModelImage.value = file
                mutableState.update { it.modelImage(FetchState.Ready) }
            } catch (e: ApiException) {
                val message = if (e.isNotFound) "The page image was not kept for this assessment." else e.message.orEmpty()
                mutableState.update { it.modelImage(FetchState.Failed(message)) }
            } catch (e: IOException) {
                mutableState.update { it.modelImage(FetchState.Failed(FILE_CACHE_FAILED_MESSAGE)) }
            } catch (e: IllegalArgumentException) {
                mutableState.update { it.modelImage(FetchState.Failed(FILE_CACHE_FAILED_MESSAGE)) }
            }
        }
    }

    override fun onCleared() {
        val open = mutablePages.value
        mutablePages.value = null
        // closing waits for a render in flight, so it is not done on the main thread
        if (open != null) CoroutineScope(SupervisorJob() + Dispatchers.IO).launch { open.close() }
    }
}
