package com.cargoclear.japac.core.model

/** How far the first load of a bundle got. */
sealed interface LoadState {
    data object Loading : LoadState
    data object Ready : LoadState
    data object NotFound : LoadState
    data class Failed(val message: String) : LoadState
}

enum class StreamConnection { CONNECTING, OPEN, RECONNECTING }

/** The latest run record the stream told us about. */
data class RunProgress(
    val runId: String?,
    val state: RunState?,
    val stage: String?,
    val progress: Double?,
    val message: String?,
)

enum class RunMode { ANALYZE, REASSESS }

/**
 * Everything the bundle screen shows, as one immutable value that changes only through the functions below: a port of the read side of
 * `useWorkbench` (frontend/lib/hooks/useWorkbench.ts), kept free of Android so its rules can be tested on the plain JVM.
 *
 * The rules it keeps (each has a test):
 *  - The assessment on screen is the newest of "what the stream sent" and "what was fetched"; a stale replay never replaces a newer one.
 *  - A stream iteration newer than anything the screen already reflects asks for a refetch of the bundle and the iteration list
 *    ([pendingRefresh]): document types change after classification and the stream only carries the latest iteration.
 *  - The document in view is the person's choice while it exists, else the one the first material finding is about, else the first; once
 *    the finding's document has been shown it stays, so a recompute that clears the finding does not move the page under the reader.
 *  - A failed run (state ERROR) shows its message; any other state clears it.
 *  - After the person asks for a run, the screen stays "running" until the stream reports a terminal state for the run it started
 *    ([pendingRunId]); the stream's own status can lag behind the request by a poll interval. A newer iteration also ends the wait, so a
 *    stream that is down (and replaced by polling, which carries no run status) cannot leave the run button disabled for good.
 *  - One failed action at a time is shown, the newest; a new action, or a new iteration, clears it. The stream's own error comes last.
 */
data class WorkbenchState(
    val load: LoadState = LoadState.Loading,
    val bundle: Bundle? = null,
    val fetchedAssessment: AssessmentIteration? = null,
    val fetchedIterations: List<AssessmentIteration> = emptyList(),
    val streamAssessment: AssessmentIteration? = null,
    val run: RunProgress? = null,
    val connection: StreamConnection = StreamConnection.CONNECTING,
    val streamError: String? = null,
    val selectedDocumentId: String? = null,
    /** Highest iteration number the screen's data already reflects; stream replays at or below it are not "new". */
    val handledIteration: Int? = null,
    /** Epoch millis of the saved copy this state was built from while the server was unreachable; null for live data. */
    val savedCopyAt: Long? = null,
    /** The run this screen asked for and has not yet seen finish (null: none), and the iteration the bundle was at when it asked. */
    val pendingRunId: String? = null,
    val pendingRunBase: Int? = null,
    /** True from the tap on "Run analysis" until the server has accepted or refused the request. */
    val startingRun: Boolean = false,
    val actionError: ActionError? = null,
    val upload: UploadStatus = UploadStatus.Idle,
    /** Corrections by the authorised agent (null until loaded), and the extraction behind the assessment on screen with them laid on. */
    val corrections: CorrectionsResponse? = null,
    val extractions: List<ExtractedDoc> = emptyList(),
) {
    // ---- what the screen reads

    val documents: List<DocumentRecord> get() = bundle?.documents.orEmpty()

    /** The newest assessment: the live one unless a fetched one is newer; null when the bundle has not been analysed yet. */
    val assessment: AssessmentIteration?
        get() {
            val live = streamAssessment
            val fetched = fetchedAssessment
            return if (live != null && (fetched == null || live.iteration >= fetched.iteration)) live else fetched
        }

    val iterations: List<AssessmentIteration>
        get() {
            val byNumber = LinkedHashMap<Int, AssessmentIteration>()
            fetchedIterations.forEach { byNumber[it.iteration] = it }
            assessment?.let { byNumber[it.iteration] = it }
            return byNumber.values.sortedBy { it.iteration }
        }

    val highlights: List<Highlight> get() = buildHighlights(assessment)

    private val findingDocument: String?
        get() = findingDocumentId(assessment?.checks, documents.map { it.documentId })

    val activeDocumentId: String?
        get() {
            val selected = selectedDocumentId
            if (selected != null && documents.any { it.documentId == selected }) return selected
            return findingDocument ?: documents.firstOrNull()?.documentId
        }

    val currentIteration: Int get() = maxOf(bundle?.currentIteration ?: 0, assessment?.iteration ?: 0)

    /** "Run analysis" until the first iteration exists, "Reassess" afterwards. */
    val runMode: RunMode get() = if (currentIteration == 0) RunMode.ANALYZE else RunMode.REASSESS

    /** The run this screen asked for is not known to be over: the stream has not yet said so, and no newer iteration has appeared. */
    private val awaitingRun: Boolean
        get() {
            val pending = pendingRunId ?: return false
            val reported = run
            if (reported != null && reported.runId == pending && reported.state?.isActive == false) return false
            val base = pendingRunBase
            return base == null || currentIteration <= base
        }

    /** A run is going (the stream says so), was just asked for, or is awaited. */
    val isRunning: Boolean get() = run?.state?.isActive == true || awaitingRun || startingRun

    val isUploading: Boolean get() = upload is UploadStatus.Active

    /** A saved copy is read-only: nothing can be sent while the server cannot be reached. */
    val isReadOnly: Boolean get() = savedCopyAt != null

    /**
     * The run to keep an eye on when the person leaves the app: the one they asked for, or the one the stream says is going. Null when no run
     * is on (or when the screen cannot yet tell which one it is).
     */
    val runToWatch: String?
        get() = if (!isRunning) null else pendingRunId ?: run?.takeIf { it.state?.isActive == true }?.runId

    /** Whether "Run analysis" / "Reassess" can be pressed. Not while a run goes, and not while files are going up (a run would read half a batch). */
    val canRun: Boolean get() = load == LoadState.Ready && bundle != null && !isReadOnly && !isRunning && !isUploading

    /**
     * Whether a value can be corrected: not while a run goes (it would be reading the extraction being changed; the web disables its Edit
     * buttons the same way), and not from a saved copy, which cannot send anything.
     */
    val canCorrect: Boolean get() = load == LoadState.Ready && bundle != null && !isReadOnly && !isRunning

    /**
     * Changes whenever the audit chain has grown or may have: a new assessment, a run starting or ending, a document added, a correction
     * recorded. The history view fetches the chain again when it changes (the web's `auditRefreshKey`).
     */
    val auditRefreshKey: String
        get() = "${assessment?.iteration ?: 0}:${run?.runId.orEmpty()}:${run?.state?.name.orEmpty()}:${documents.size}:${corrections?.corrections?.size ?: 0}"

    /** The assessment number whose extraction and corrections the screen should hold; 0 when there is no assessment yet. */
    val shownIteration: Int get() = assessment?.iteration ?: 0

    /** Whether files can be added: one batch at a time, as the web disables its button while uploading. */
    val canAddDocuments: Boolean get() = load == LoadState.Ready && bundle != null && !isReadOnly && !isUploading

    /** The message of the banner: the newest failed action or upload, else what the stream reported (the web's `actionError ?? streamError`). */
    val visibleError: ActionError? get() = actionError ?: (upload as? UploadStatus.Failed)?.error ?: streamError?.let { ActionError(it) }

    /** Action and upload errors can be dismissed; the stream's cannot (it ends with the next status). */
    val canDismissError: Boolean get() = actionError != null || upload is UploadStatus.Failed

    /** Newest iteration number the stream sent, or null. */
    private val streamIteration: Int? get() = streamAssessment?.iteration

    /** The iteration the stream carried that the screen has not caught up with: refetch the bundle and the iteration list for it, then [markHandled]. Null when there is none. */
    fun iterationToRefresh(): Int? {
        val seen = streamIteration ?: return null
        if (load != LoadState.Ready) return null
        val handled = handledIteration
        return seen.takeIf { handled == null || seen > handled }
    }

    /** True when the stream carried an iteration the screen has not caught up with (see [iterationToRefresh]). */
    fun pendingRefresh(): Boolean = iterationToRefresh() != null

    // ---- transitions

    fun markHandled(): WorkbenchState = copy(handledIteration = streamIteration ?: handledIteration)

    /** The refetch for [iteration] worked. A newer iteration that arrived while it ran stays pending; so does one whose refetch failed, which never gets here. */
    fun markHandled(iteration: Int): WorkbenchState = copy(handledIteration = maxOf(handledIteration ?: iteration, iteration))

    fun loaded(bundle: Bundle, assessment: AssessmentIteration?, iterations: List<AssessmentIteration>): WorkbenchState =
        copy(
            load = LoadState.Ready,
            bundle = bundle,
            fetchedAssessment = assessment,
            fetchedIterations = iterations,
            handledIteration = maxOf(assessment?.iteration ?: 0, iterations.maxOfOrNull { it.iteration } ?: 0),
            savedCopyAt = null,
        ).stickToFindingDocument()

    /** The server could not be reached but a saved copy exists: show it, marked as such (read-only). */
    fun loadedFromSavedCopy(bundle: Bundle, assessment: AssessmentIteration?, savedAt: Long): WorkbenchState =
        copy(
            load = LoadState.Ready,
            bundle = bundle,
            fetchedAssessment = assessment,
            fetchedIterations = listOfNotNull(assessment),
            handledIteration = assessment?.iteration ?: 0,
            savedCopyAt = savedAt,
        ).stickToFindingDocument()

    fun loadFailed(notFound: Boolean, message: String): WorkbenchState =
        copy(load = if (notFound) LoadState.NotFound else LoadState.Failed(message))

    /** Retry after a failed load: forget what was loaded (as the web client does) but keep what the stream told us. */
    fun reloading(): WorkbenchState = copy(
        load = LoadState.Loading,
        bundle = null,
        fetchedAssessment = null,
        fetchedIterations = emptyList(),
        selectedDocumentId = null,
        handledIteration = null,
        savedCopyAt = null,
        pendingRunId = null,
        pendingRunBase = null,
        startingRun = false,
        actionError = null,
        corrections = null,
        extractions = emptyList(),
    )

    fun bundleRefreshed(bundle: Bundle): WorkbenchState = copy(bundle = bundle).stickToFindingDocument()

    fun iterationsRefreshed(iterations: List<AssessmentIteration>): WorkbenchState = copy(fetchedIterations = iterations)

    fun streamStatus(event: StatusEvent): WorkbenchState = copy(
        run = RunProgress(event.runId, event.state, event.stage, event.progress, event.message),
        streamError = if (event.state == RunState.ERROR) event.message ?: "Pipeline run failed" else null,
    )

    /** Ignores an iteration older than the one already held (a replay), takes anything else. */
    fun streamIteration(iteration: AssessmentIteration): WorkbenchState {
        val held = streamAssessment
        val next = if (held != null && iteration.iteration < held.iteration) held else iteration
        val grown = copy(streamAssessment = next)
        // a finished run supersedes the error of an earlier action (e.g. a 409 raised while it was running); a replay of what is shown does not
        val superseded = grown.assessment?.iteration != assessment?.iteration
        return grown.copy(actionError = if (superseded) null else actionError).stickToFindingDocument()
    }

    // ---- actions: runs and uploads

    /** The person asked for a run: nothing else can start until the server answers, and the last failure is forgotten. */
    fun runRequested(): WorkbenchState =
        copy(startingRun = true, actionError = null, upload = if (upload is UploadStatus.Failed) UploadStatus.Idle else upload)

    /** The server accepted the run (also: a batch of uploads ended by asking for one). */
    fun runStarted(runId: String): WorkbenchState = copy(startingRun = false, pendingRunId = runId, pendingRunBase = currentIteration)

    fun runRejected(error: ActionError): WorkbenchState = copy(startingRun = false, actionError = error)

    fun actionFailed(error: ActionError): WorkbenchState = copy(actionError = error)

    fun errorDismissed(): WorkbenchState =
        copy(actionError = null, upload = if (upload is UploadStatus.Failed) UploadStatus.Idle else upload)

    /** Applies what the upload scheduler (or one inline upload) reported; see [UploadUpdate]. A batch in progress hides an older failure. */
    fun uploadUpdated(update: UploadUpdate): WorkbenchState {
        var next = when {
            update.active != null -> copy(upload = update.active)
            update.failure != null -> copy(upload = update.failure)
            upload is UploadStatus.Active -> copy(upload = UploadStatus.Idle)
            else -> this
        }
        update.runStarted?.let { next = next.runStarted(it) }
        update.runError?.let { next = next.actionFailed(it) }
        return next
    }

    // ---- corrections

    fun correctionsLoaded(corrections: CorrectionsResponse): WorkbenchState = copy(corrections = corrections)

    fun extractionsLoaded(extractions: List<ExtractedDoc>): WorkbenchState = copy(extractions = extractions)

    /** There is no assessment (or no connection to read one's data over): nothing to correct against. */
    fun correctionDataCleared(): WorkbenchState = copy(corrections = null, extractions = emptyList())

    fun streamFailed(message: String): WorkbenchState = copy(streamError = message)

    fun connection(connection: StreamConnection): WorkbenchState = copy(connection = connection)

    fun selectDocument(documentId: String): WorkbenchState = copy(selectedDocumentId = documentId)

    private fun stickToFindingDocument(): WorkbenchState =
        if (selectedDocumentId == null && findingDocument != null) copy(selectedDocumentId = findingDocument) else this
}
