package com.cargoclear.japac.core.model

/**
 * A failed action (starting a run, a recompute, an upload) as the banner shows it: the words, and the id the server logged the request
 * under, so a person can quote it to whoever runs the backend.
 */
data class ActionError(val message: String, val requestId: String? = null)

private val ALREADY_IN_PROGRESS = Regex("already in progress", RegexOption.IGNORE_CASE)

/** User-facing text for run-control (analyze / reassess / recompute) failures. Port of `runErrorMessage` in frontend/lib/errors.ts. */
fun runErrorMessage(envelope: ErrorEnvelope): String = when (envelope.code) {
    // a 409 is also how a recompute says "nothing to reuse" / "documents changed": show that, not "already running"
    "CONFLICT" -> if (ALREADY_IN_PROGRESS.containsMatchIn(envelope.message)) "An analysis is already running for this bundle." else envelope.message
    "VALIDATION_ERROR" -> "Upload at least one document before analyzing."
    else -> envelope.message
}

/**
 * User-facing text for a failed upload: the server's own message (as the web client shows), except when the answer is not the backend's
 * envelope at all. A gateway in front of the API (Cloud Run's request-size limit, for one) answers 413 with a page of its own, which the
 * client can only call `HTTP_413`.
 */
fun uploadErrorMessage(envelope: ErrorEnvelope, httpStatus: Int?): String =
    if (httpStatus == 413 && envelope.code == "HTTP_413") "The file is too large for the server to accept." else envelope.message

/**
 * What the banner says when an upload ended on something the app did not expect (not a refusal by the server, not a lost connection). It
 * does not say how many files landed when that is not known: the document list is read again instead.
 */
const val UPLOAD_STOPPED_MESSAGE: String = "The upload stopped unexpectedly. Check which documents the bundle holds and add the ones that are missing."

/** What the viewer says when a document or a page image could not be kept on this phone (the cache could not be written, or the id is not one it can store). */
const val FILE_CACHE_FAILED_MESSAGE: String = "This could not be saved on the phone, so it cannot be shown."

/** What the banner says when the document scanner produced a file that could not be read back (it is the person's own scan: nothing was sent). */
const val SCAN_UNREADABLE_MESSAGE: String = "The scanned document could not be read. Try scanning it again."

/** What the banner says when the scanner cannot be started (it comes from Google Play services, which may be missing or out of date). */
const val SCAN_UNAVAILABLE_MESSAGE: String = "Scanning is not available on this phone right now. Choose a PDF from the phone instead."

/** The sample mill test certificate of the Case C demo must carry this name: the demo extraction is keyed on the file name. */
const val SAMPLE_MTC_FILENAME: String = "mtc_pipe_test_cert.pdf"

/** Id of the missing-evidence item that asks for the mill test certificate. */
const val MTC_MISSING_ID: String = "ME-MILL_TEST_CERTIFICATE"

/** "Use sample MTC (demo)" is offered in demo mode, and only while the assessment says the certificate is what is missing. */
fun offersSampleMtc(appMode: AppMode?, assessment: AssessmentIteration?): Boolean =
    appMode == AppMode.DEMO && assessment?.missingEvidence?.any { it.id == MTC_MISSING_ID } == true

/** Whether a finished upload batch is followed by a reassessment: only when every file landed and an assessment already exists. */
fun shouldAutoReassess(allUploaded: Boolean, currentIteration: Int): Boolean = allUploaded && currentIteration > 0
