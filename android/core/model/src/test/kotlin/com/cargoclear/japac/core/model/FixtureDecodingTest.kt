package com.cargoclear.japac.core.model

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The DTOs against what the demo backend really sent (android/tools/record_fixtures.py), decoded strictly. */
class FixtureDecodingTest {
    @Test
    fun `meta and the error envelopes`() {
        val meta = Fixtures.decode<Meta>("meta_demo.json")
        assertEquals(AppMode.DEMO, meta.appMode)
        assertEquals("native", meta.pipelineEngine)

        val notFound = Json.parseToJsonElement(Fixtures.text("error_bundle_not_found.json")).jsonObject
        assertEquals("NOT_FOUND", notFound.getValue("code").jsonPrimitive.content)
        val envelope = Json { ignoreUnknownKeys = true }.decodeFromString<ErrorEnvelope>(Fixtures.text("error_bundle_not_found.json"))
        assertEquals("NOT_FOUND", envelope.code)
        assertNotNull(envelope.requestId)
    }

    @Test
    fun `a fresh demo bundle has documents and no assessment`() {
        val bundle = Fixtures.decode<Bundle>("case_c_bundle_new.json")
        assertEquals("PENDING", bundle.status)
        assertNull("PENDING is not one of the four assessment statuses", bundle.statusKind)
        assertEquals(0, bundle.currentIteration)
        assertEquals("SG", bundle.destinationCountry)
        assertEquals(listOf("commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf"), bundle.documents.map { it.filename })
        assertEquals(Destination.INDIA.code, Fixtures.decode<Bundle>("bundle_empty_created.json").destinationCountry)
    }

    @Test
    fun `case C first assessment is MISSING_EVIDENCE and names the certificate`() {
        val a = Fixtures.decode<AssessmentIteration>("case_c_assessment_missing_evidence.json")
        assertEquals(Status.MISSING_EVIDENCE, a.statusKind)
        assertEquals(1, a.iteration)
        assertEquals(DataSource.FIXTURE, a.dataSource)
        assertEquals(listOf("ME-MILL_TEST_CERTIFICATE"), a.missingEvidence.map { it.id })
        assertTrue(a.checks.isNotEmpty())
        assertEquals(DeltaKind.INITIAL, a.reasoningDelta?.kind)
        // every cited value is readable as text, whether the backend sent a string or a number
        a.checks.flatMap { it.evidence.orEmpty() }.forEach { ev -> if (ev.rawValue != null) assertNotNull(ev.rawValueText) }
    }

    @Test
    fun `case C after the certificate is COMPLIANT and the delta says why`() {
        val a = Fixtures.decode<AssessmentIteration>("case_c_assessment_compliant.json")
        assertEquals(Status.COMPLIANT_FOR_SUBMISSION, a.statusKind)
        assertEquals(2, a.iteration)
        assertTrue(a.missingEvidence.isEmpty())
        val delta = checkNotNull(a.reasoningDelta)
        assertEquals(DeltaKind.REASSESSMENT, delta.kind)
        assertTrue(delta.changes.any { it.field == "status" && (it.from as? kotlinx.serialization.json.JsonPrimitive)?.content == "MISSING_EVIDENCE" })

        val iterations = Fixtures.strict.decodeFromString<List<AssessmentIteration>>(Fixtures.text("case_c_iterations.json"))
        assertEquals(listOf(1, 2), iterations.map { it.iteration })
        assertEquals("COMPLIANT_FOR_SUBMISSION", Fixtures.decode<Bundle>("case_c_bundle_final.json").status)
    }

    @Test
    fun `case D is a material contradiction with an estimate and an anti-dumping warning`() {
        val a = Fixtures.decode<AssessmentIteration>("case_d_assessment_contradiction.json")
        assertEquals(Status.MATERIAL_CONTRADICTION, a.statusKind)
        val m001 = a.checks.single { it.checkId == "M-001" }
        assertEquals(Severity.MATERIAL, m001.severity)
        assertNotNull(m001.focusDocument)
        assertEquals(Severity.WARN, a.checks.single { it.checkId == "SEC-002" }.severity)

        val valuation = checkNotNull(a.valuation)
        assertEquals(ValuationStatus.ESTIMATED, valuation.status)
        assertEquals("IN", valuation.destinationCountry)
        assertTrue(valuation.duties.isNotEmpty())
        assertNotNull(valuation.totalDuty)
        assertTrue(valuation.disclaimer.isNotBlank())
        assertNotNull(a.referenceData)
        assertEquals(4, a.documents.size)
    }

    @Test
    fun `the upload answer and the run answer`() {
        val doc = Fixtures.decode<DocumentRecord>("document_uploaded.json")
        assertEquals("mtc_pipe_test_cert.pdf", doc.filename)
        val run = Fixtures.decode<RunResponse>("run_response_analyze.json")
        assertEquals(RunState.RUNNING, run.state)
        assertTrue(run.runId.startsWith("run-"))
        assertEquals(doc.bundleId, run.bundleId)
    }

    @Test
    fun `removing a document answers what was removed, and an upload may carry its declared type`() {
        val removed = Fixtures.decode<DocumentDeleted>("document_deleted.json")
        assertEquals("case_d_packing_list.pdf", removed.filename)
        assertTrue(removed.filesRemoved > 0)
        assertTrue("the newest assessment used it", removed.inLatestAssessment)
        assertEquals(1, removed.latestIteration)

        assertEquals("MILL_TEST_CERTIFICATE", Fixtures.decode<DocumentRecord>("document_uploaded_declared.json").declaredType)
        assertNull("an older answer, recorded before the field existed, decodes with none", Fixtures.decode<DocumentRecord>("document_uploaded.json").declaredType)
    }

    @Test
    fun `the recorded event stream decodes into status and iteration events`() {
        val events = parseSse(Fixtures.text("stream_case_c_first_run.sse"))
        val statuses = events.filter { it.first == "status" }.map { Fixtures.parse<StatusEvent>(it.second) }
        assertEquals(RunState.COMPLETE, statuses.first().state) // the replay of "no run yet"
        assertTrue(statuses.any { it.state == RunState.RUNNING && it.stage != null })
        assertEquals(RunState.COMPLETE, statuses.last().state)
        val iteration = events.single { it.first == "iteration" }.let { Fixtures.parse<AssessmentIteration>(it.second) }
        assertEquals(1, iteration.iteration)
    }

}

/** Minimal SSE reader for the recorded transcript: (event name, data) pairs. The server separates lines with CRLF, as the SSE spec allows. */
internal fun parseSse(text: String): List<Pair<String, String>> =
    text.replace("\r\n", "\n").split("\n\n").mapNotNull { block ->
        val name = block.lines().firstOrNull { it.startsWith("event:") }?.removePrefix("event:")?.trim()
        val data = block.lines().filter { it.startsWith("data:") }.joinToString("\n") { it.removePrefix("data:").trim() }
        if (name != null && data.isNotEmpty()) name to data else null
    }
