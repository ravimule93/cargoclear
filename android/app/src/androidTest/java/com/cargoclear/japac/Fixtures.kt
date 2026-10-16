package com.cargoclear.japac

import androidx.test.platform.app.InstrumentationRegistry
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.Bundle
import com.cargoclear.japac.core.model.CorrectionsResponse
import com.cargoclear.japac.core.model.ExtractedDoc
import com.cargoclear.japac.core.model.WorkbenchState
import kotlinx.serialization.json.Json

/** The backend's recorded payloads (android/fixtures), decoded strictly: a field the DTOs do not know fails the test. */
object Fixtures {
    val json = Json { ignoreUnknownKeys = false }

    fun text(name: String): String =
        InstrumentationRegistry.getInstrumentation().context.assets.open(name).bufferedReader().use { it.readText() }

    inline fun <reified T> decode(name: String): T = json.decodeFromString(text(name))

    private fun state(bundleFile: String, assessmentFile: String?, iterationsFile: String? = null): WorkbenchState {
        val bundle = decode<Bundle>(bundleFile)
        val assessment = assessmentFile?.let { decode<AssessmentIteration>(it) }
        val iterations = iterationsFile?.let { json.decodeFromString<List<AssessmentIteration>>(text(it)) } ?: listOfNotNull(assessment)
        return WorkbenchState().loaded(bundle, assessment, iterations)
    }

    /** Case C after the first analysis: three documents, MISSING_EVIDENCE. */
    fun caseCMissingEvidence() = state("case_c_bundle_analyzed.json", "case_c_assessment_missing_evidence.json")

    /** Case C after the certificate was added: COMPLIANT_FOR_SUBMISSION, two iterations. */
    fun caseCCompliant() = state("case_c_bundle_final.json", "case_c_assessment_compliant.json", "case_c_iterations.json")

    /** Case D: an import into India, MATERIAL_CONTRADICTION with an estimate. */
    fun caseDContradiction() = state("case_d_bundle_analyzed.json", "case_d_assessment_contradiction.json")

    /** A bundle that was created and never analysed. */
    fun neverAnalysed() = WorkbenchState().loaded(decode<Bundle>("case_c_bundle_new.json"), null, emptyList())

    /** Case D with the Cr cell corrected to 0.28 and the consignee confirmed, not yet recomputed: two changes the assessment on screen lacks. */
    fun caseDCorrected() = caseDContradiction()
        .correctionsLoaded(decode<CorrectionsResponse>("case_d_corrections_pending.json"))
        .extractionsLoaded(json.decodeFromString<List<ExtractedDoc>>(text("case_d_extractions.json")))

    /** Case D after the recompute: SPECIALIST_REVIEW_REQUIRED, assessment 2, both corrections in it. */
    fun caseDRecomputed() = caseDContradiction()
        .streamIteration(decode<AssessmentIteration>("case_d_assessment_recomputed.json"))
        .correctionsLoaded(decode<CorrectionsResponse>("case_d_corrections_applied.json"))
        .extractionsLoaded(json.decodeFromString<List<ExtractedDoc>>(text("case_d_extractions_recomputed.json")))
}
