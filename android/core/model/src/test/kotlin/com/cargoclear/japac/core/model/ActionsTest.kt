package com.cargoclear.japac.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The wording and the small decisions around running and uploading (frontend/lib/errors.ts and the upload code of useWorkbench). */
class ActionsTest {
    private fun envelope(code: String, message: String) = ErrorEnvelope(code = code, message = message)

    @Test
    fun `a conflict that says a run is going is worded as the web words it`() {
        assertEquals(
            "An analysis is already running for this bundle.",
            runErrorMessage(envelope("CONFLICT", "An analysis is Already In Progress for bundle 'b1'.")),
        )
    }

    @Test
    fun `any other conflict keeps the server's reason, because a recompute uses 409 for nothing to reuse`() {
        val reason = "Documents were added since the last assessment: reassess instead."
        assertEquals(reason, runErrorMessage(envelope("CONFLICT", reason)))
    }

    @Test
    fun `a validation error on a run means there is nothing to analyse`() {
        assertEquals("Upload at least one document before analyzing.", runErrorMessage(envelope("VALIDATION_ERROR", "bundle has no documents")))
    }

    @Test
    fun `other failures show the server's message unchanged`() {
        assertEquals("Slow down", runErrorMessage(envelope("RATE_LIMITED", "Slow down")))
        assertEquals("Can't reach the server.", runErrorMessage(envelope("NETWORK", "Can't reach the server.")))
    }

    @Test
    fun `an upload refusal shows the server's words, and a gateway's bare 413 is explained`() {
        assertEquals("The file is larger than 50 MB.", uploadErrorMessage(envelope("PAYLOAD_TOO_LARGE", "The file is larger than 50 MB."), 413))
        assertEquals("The file is too large for the server to accept.", uploadErrorMessage(envelope("HTTP_413", "Request Entity Too Large"), 413))
        assertEquals("Only PDF files are accepted. Received: text/plain", uploadErrorMessage(envelope("VALIDATION_ERROR", "Only PDF files are accepted. Received: text/plain"), 422))
    }

    private fun assessment(vararg missingIds: String) = AssessmentIteration(
        iteration = 1,
        bundleId = "b1",
        status = "MISSING_EVIDENCE",
        missingEvidence = missingIds.map { MissingEvidence(it, "label", "7304", "reason") },
    )

    @Test
    fun `the sample certificate is offered in demo mode while the certificate is what is missing`() {
        assertTrue(offersSampleMtc(AppMode.DEMO, assessment(MTC_MISSING_ID)))
        assertFalse("live mode never offers it", offersSampleMtc(AppMode.LIVE, assessment(MTC_MISSING_ID)))
        assertFalse("mode not known yet", offersSampleMtc(null, assessment(MTC_MISSING_ID)))
        assertFalse("something else is missing", offersSampleMtc(AppMode.DEMO, assessment("ME-PACKING_LIST")))
        assertFalse("no assessment", offersSampleMtc(AppMode.DEMO, null))
    }

    @Test
    fun `the sample certificate carries the name the demo extraction is keyed on`() {
        assertEquals("mtc_pipe_test_cert.pdf", SAMPLE_MTC_FILENAME)
    }

    @Test
    fun `a batch is followed by a reassessment only when everything landed and an assessment exists`() {
        assertTrue(shouldAutoReassess(allUploaded = true, currentIteration = 1))
        assertFalse("first analysis waits for the person to press Run", shouldAutoReassess(allUploaded = true, currentIteration = 0))
        assertFalse("a partial batch does not run", shouldAutoReassess(allUploaded = false, currentIteration = 3))
    }

    // ---- the words for what the demo backend really answered (android/fixtures, recorded by android/tools/record_fixtures.py)

    private val lenient = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }

    private fun recorded(name: String): ErrorEnvelope = lenient.decodeFromString(Fixtures.text(name))

    @Test
    fun `the real answer to a second run request says a run is going, and the app words it so`() {
        val answer = recorded("error_run_already_in_progress.json")
        assertEquals("CONFLICT", answer.code)
        assertEquals("An analysis is already running for this bundle.", runErrorMessage(answer))
    }

    @Test
    fun `the real answer to a recompute with nothing to reuse keeps the server's reason`() {
        val answer = recorded("error_recompute_nothing_to_reuse.json")
        assertEquals("CONFLICT", answer.code)
        assertEquals("Run the analysis first: there is nothing to recompute yet.", runErrorMessage(answer))
    }

    @Test
    fun `the real answer to analysing an empty bundle is the web's sentence`() {
        assertEquals("Upload at least one document before analyzing.", runErrorMessage(recorded("error_analyze_empty_bundle.json")))
    }

    @Test
    fun `the real rate limit answer reaches the person with the wait the server named`() {
        val answer = recorded("error_rate_limited.json")
        assertEquals("RATE_LIMITED", answer.code)
        assertTrue(runErrorMessage(answer).startsWith("Too many requests. Try again in "))
    }

    @Test
    fun `the real refusals of an upload are shown as the server worded them`() {
        assertEquals("Only PDF files are accepted. Received: text/plain", uploadErrorMessage(recorded("error_upload_not_pdf.json"), 422))
        assertEquals("Uploaded file is empty (0 bytes).", uploadErrorMessage(recorded("error_upload_empty.json"), 422))
    }
}

