package com.cargoclear.japac.core.model

/** How far opening the viewer got: the bundle, its documents and its latest assessment (the boxes come from that). */
sealed interface ViewerLoad {
    data object Loading : ViewerLoad
    data object Ready : ViewerLoad

    /** The bundle answers, but has no such document (or no such bundle). */
    data object NotFound : ViewerLoad
    data class Failed(val message: String) : ViewerLoad
}

/** The PDF of the document, or the page image the model was shown: being fetched, there, or not. */
sealed interface FetchState {
    data object Loading : FetchState
    data object Ready : FetchState
    data class Failed(val message: String) : FetchState
}

enum class ViewMode {
    /** The document as uploaded, with the evidence boxes carried back onto it. */
    ORIGINAL,

    /** The page image exactly as the extraction was shown it ("What the model saw"), with the boxes as it cited them. */
    MODEL_VIEW,
}

/**
 * Everything the document viewer shows besides the pixels, as one immutable value that changes only through the functions below: a port of
 * the state of DocumentViewer.tsx, kept free of Android so its rules run on the plain JVM. The rules:
 *  - Boxes are drawn on the original page only once it is known how the page was transformed; when that could not be learnt none is drawn,
 *    and the screen says so ([boxesHidden]): a box in the wrong place is worse than no box.
 *  - "What the model saw" is offered only for a page whose image was kept and only with an assessment to ask about.
 *  - Changing page keeps a selected box only if it is on that page, and leaves "what the model saw" if that page has no image.
 */
data class ViewerState(
    val load: ViewerLoad = ViewerLoad.Loading,
    val document: DocumentRecord? = null,
    val highlights: List<Highlight> = emptyList(),
    /** The assessment the highlights come from; "what the model saw" is the page of THAT assessment's extraction. */
    val iteration: Int? = null,
    val geometry: GeometryState = GeometryState.Loading,
    val file: FetchState = FetchState.Loading,
    val pageCount: Int = 0,
    val page: Int = 1,
    val mode: ViewMode = ViewMode.ORIGINAL,
    val selectedBoxId: String? = null,
    val modelImage: FetchState = FetchState.Loading,
    /** The bundle was read from the copy saved on this phone because the server could not be reached. */
    val fromSavedCopy: Boolean = false,
    /** The viewer was opened on a box (an evidence row was tapped): bring it into view once, when it can be drawn. */
    val focusRequested: Boolean = false,
) {
    private val documentId: String? get() = document?.documentId

    private val transforms: List<TransformMetadata> get() = (geometry as? GeometryState.Known)?.transforms.orEmpty()

    /** How the shown page was transformed, if it was. */
    val pageTransform: TransformMetadata? get() = transformFor(page, transforms)

    /** The evidence the assessment cites on this page, whether or not it can be drawn now. */
    val evidenceOnPage: List<Highlight> get() = documentId?.let { id -> highlights.filter { it.documentId == id && it.page == page } }.orEmpty()

    /** The boxes drawn on the page being shown. */
    val boxes: List<PageBox>
        get() {
            val id = documentId ?: return emptyList()
            return when (mode) {
                ViewMode.ORIGINAL -> if (geometry.allowsBoxes()) boxesOnOriginalPage(highlights, id, page, transforms) else emptyList()
                ViewMode.MODEL_VIEW -> boxesOnProcessedPage(highlights, id, page)
            }
        }

    /** There is evidence on this page that is not drawn because the page's geometry could not be learnt. */
    val boxesHidden: Boolean get() = mode == ViewMode.ORIGINAL && geometry == GeometryState.Unavailable && evidenceOnPage.isNotEmpty()

    val selectedBox: PageBox? get() = boxes.firstOrNull { it.id == selectedBoxId }

    val deskewNote: String? get() = deskewNote(pageTransform)

    val canShowModelView: Boolean get() = iteration != null && hasModelView(pageTransform)

    val canGoPrevious: Boolean get() = page > 1

    val canGoNext: Boolean get() = page < pageCount

    // ---- transitions

    fun opened(document: DocumentRecord, highlights: List<Highlight>, iteration: Int?, fromSavedCopy: Boolean): ViewerState =
        copy(load = ViewerLoad.Ready, document = document, highlights = highlights, iteration = iteration, fromSavedCopy = fromSavedCopy)

    fun loadFailed(notFound: Boolean, message: String): ViewerState = copy(load = if (notFound) ViewerLoad.NotFound else ViewerLoad.Failed(message))

    fun geometryKnown(transforms: List<TransformMetadata>): ViewerState = copy(geometry = GeometryState.Known(transforms))

    fun geometryUnavailable(): ViewerState = copy(geometry = GeometryState.Unavailable)

    fun fileFailed(message: String): ViewerState = copy(file = FetchState.Failed(message))

    fun fileReady(pageCount: Int): ViewerState = copy(file = FetchState.Ready, pageCount = pageCount).showing(page)

    /** Shows page [target] (1-based); once the page count is known it is held to it. A selected box stays only if it is on that page. */
    fun showing(target: Int): ViewerState {
        val clamped = if (pageCount > 0) target.coerceIn(1, pageCount) else maxOf(1, target)
        val onPage = highlights.any { it.id == selectedBoxId && it.documentId == documentId && it.page == clamped }
        val moved = copy(page = clamped, selectedBoxId = if (onPage) selectedBoxId else null, focusRequested = focusRequested && onPage)
        return if (moved.mode == ViewMode.MODEL_VIEW && !moved.canShowModelView) moved.copy(mode = ViewMode.ORIGINAL) else moved
    }

    fun nextPage(): ViewerState = if (canGoNext) showing(page + 1) else this

    fun previousPage(): ViewerState = if (canGoPrevious) showing(page - 1) else this

    /** Selects a box (null: none). Selecting a box of another page is ignored. */
    fun selectBox(id: String?): ViewerState = when {
        id == null -> copy(selectedBoxId = null)
        boxes.any { it.id == id } -> copy(selectedBoxId = id)
        else -> this
    }

    /** Opens on a page and, if it is one of this document's evidence boxes, selects it (the evidence row that was tapped). */
    fun focusedOn(page: Int?, highlightId: String?): ViewerState {
        val target = highlights.firstOrNull { it.id == highlightId && it.documentId == documentId }
        return copy(selectedBoxId = target?.id, focusRequested = target != null).showing(page ?: target?.page ?: this.page)
    }

    /** The screen has brought the requested box into view; a later change of page or box must not do it again. */
    fun focusHandled(): ViewerState = copy(focusRequested = false)

    fun modelViewShown(on: Boolean): ViewerState = when {
        !on -> copy(mode = ViewMode.ORIGINAL)
        canShowModelView -> copy(mode = ViewMode.MODEL_VIEW)
        else -> this
    }

    fun modelImage(state: FetchState): ViewerState = copy(modelImage = state)
}
