package com.cargoclear.japac.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** The four assessment verdicts (advisory: never a statement that goods are legal or ready for a government submission). */
enum class Status(val wire: String) {
    COMPLIANT_FOR_SUBMISSION("COMPLIANT_FOR_SUBMISSION"),
    MISSING_EVIDENCE("MISSING_EVIDENCE"),
    MATERIAL_CONTRADICTION("MATERIAL_CONTRADICTION"),
    SPECIALIST_REVIEW_REQUIRED("SPECIALIST_REVIEW_REQUIRED");

    companion object {
        /**
         * Null for anything else (`PENDING`, or a status a newer backend adds). Callers must show that as "not assessed" or "unrecognised",
         * never as one of the four: guessing a verdict is worse than showing none.
         */
        fun fromWire(value: String?): Status? = entries.firstOrNull { it.wire == value }
    }
}

@Serializable
enum class Severity {
    @SerialName("PASS") PASS,
    @SerialName("WARN") WARN,
    @SerialName("MATERIAL") MATERIAL,
}

/** Where the extraction came from; `fixture` is the demo's synthetic extraction (the demo banner applies). */
@Serializable
enum class DataSource {
    @SerialName("live") LIVE,
    @SerialName("fixture") FIXTURE,
}

/** A box on a page: 0-1000 normalised, top-left origin, in the coordinates of the page the model was shown. */
@Serializable
data class BBox(
    val page: Int,
    val ymin: Double,
    val xmin: Double,
    val ymax: Double,
    val xmax: Double,
)

/**
 * One piece of evidence a check cites. The backend sends these as untyped dicts, so everything is optional here and the same entry
 * can be a header field, a line-item field or a row of a list (`row`).
 */
@Serializable
data class EvidenceRef(
    /** document_id of the document the evidence points into */
    val doc: String? = null,
    val field: String? = null,
    @SerialName("line_item") val lineItem: Int? = null,
    val row: Int? = null,
    val page: Int? = null,
    val bbox: BBox? = null,
    /** a string or a number, as the extraction produced it */
    @SerialName("raw_value") val rawValue: JsonPrimitive? = null,
    /** unit as printed, for a weight or a lab value */
    val unit: String? = null,
) {
    /** The value as text, the way the web client shows it (`String(value)`); null when there is none. */
    val rawValueText: String? get() = rawValue?.let(::jsText)?.takeIf { it.isNotBlank() }
}

@Serializable
data class CheckResult(
    @SerialName("check_id") val checkId: String,
    val severity: Severity,
    val message: String,
    val delta: Double? = null,
    val tolerance: Double? = null,
    val evidence: List<EvidenceRef>? = null,
    /** Every assumption the result depends on; a check with assumptions is never PASS or MATERIAL. */
    val assumptions: List<String> = emptyList(),
    /** Which curated rule set the result uses and where it comes from (never "official" unless it is). */
    @SerialName("rule_set") val ruleSet: String? = null,
    @SerialName("regulation_ref") val regulationRef: String? = null,
    /** The document to look at first for this finding; absent on older assessments. */
    @SerialName("focus_document") val focusDocument: String? = null,
)

@Serializable
data class GroundingFinding(
    @SerialName("document_id") val documentId: String,
    @SerialName("declared_hs") val declaredHs: String? = null,
    @SerialName("top_candidate_hs") val topCandidateHs: String? = null,
    @SerialName("top_candidate_description") val topCandidateDescription: String? = null,
    val distance: Double? = null,
    val ambiguous: Boolean,
    @SerialName("hs_mismatch") val hsMismatch: Boolean = false,
    @SerialName("required_documents") val requiredDocuments: List<String> = emptyList(),
    /** exact8 | subheading6 | heading4 | none | not_declared */
    @SerialName("hs_match_level") val hsMatchLevel: String? = null,
    @SerialName("governing_hs") val governingHs: String? = null,
    @SerialName("rule_set") val ruleSet: String? = null,
    @SerialName("regulation_ref") val regulationRef: String? = null,
    @SerialName("better_match_hs") val betterMatchHs: String? = null,
)

@Serializable
data class MissingEvidence(
    val id: String,
    @SerialName("document_label") val documentLabel: String,
    @SerialName("hs_code") val hsCode: String,
    val reason: String,
    @SerialName("regulation_ref") val regulationRef: String? = null,
    @SerialName("rule_set") val ruleSet: String? = null,
)

/** One row of the Reasoning Delta; the backend sends these as untyped dicts (`from`/`to` are usually statuses, always shown as text). */
@Serializable
data class ReasoningDeltaChange(
    val field: String? = null,
    val from: JsonElement? = null,
    val to: JsonElement? = null,
    val because: String? = null,
)

@Serializable
enum class DeltaKind {
    @SerialName("INITIAL") INITIAL,
    @SerialName("REASSESSMENT") REASSESSMENT,
}

@Serializable
data class ReasoningDelta(
    val kind: DeltaKind,
    val changes: List<ReasoningDeltaChange> = emptyList(),
    val narrative: String,
)

@Serializable
enum class ConfidenceAction {
    @SerialName("AUTO_ACCEPT") AUTO_ACCEPT,
    @SerialName("AUTO_FLAG") AUTO_FLAG,
    @SerialName("INTERACTIVE_REVIEW") INTERACTIVE_REVIEW,
    @SerialName("MANUAL_ENTRY") MANUAL_ENTRY,
}

@Serializable
data class ConfidenceResult(
    @SerialName("min_field_confidence") val minFieldConfidence: Double,
    val action: ConfidenceAction,
    @SerialName("min_overall_confidence") val minOverallConfidence: Double? = null,
    @SerialName("min_doc_type_confidence") val minDocTypeConfidence: Double? = null,
    @SerialName("low_confidence_fields") val lowConfidenceFields: List<JsonObject> = emptyList(),
    val reason: String? = null,
)

@Serializable
data class DutyLine(
    val name: String,
    @SerialName("rate_pct") val ratePct: Double? = null,
    val base: Double? = null,
    val amount: Double,
    val note: String? = null,
)

@Serializable
enum class ValuationStatus {
    @SerialName("ESTIMATED") ESTIMATED,
    @SerialName("PARTIAL") PARTIAL,
    @SerialName("NOT_AVAILABLE") NOT_AVAILABLE,
}

/** Indicative assessable value and duty exposure: decision support, never a determination, never the status. */
@Serializable
data class ValuationEstimate(
    @SerialName("destination_country") val destinationCountry: String,
    val status: ValuationStatus,
    val reason: String? = null,
    val incoterm: String? = null,
    @SerialName("invoice_currency") val invoiceCurrency: String? = null,
    @SerialName("destination_currency") val destinationCurrency: String? = null,
    @SerialName("exchange_rate") val exchangeRate: Double? = null,
    @SerialName("exchange_rate_note") val exchangeRateNote: String? = null,
    @SerialName("transaction_value") val transactionValue: Double? = null,
    val freight: Double? = null,
    val insurance: Double? = null,
    @SerialName("assessable_value") val assessableValue: Double? = null,
    @SerialName("hs_code") val hsCode: String? = null,
    val duties: List<DutyLine> = emptyList(),
    @SerialName("total_duty") val totalDuty: Double? = null,
    @SerialName("implied_hs_code") val impliedHsCode: String? = null,
    @SerialName("implied_total_duty") val impliedTotalDuty: Double? = null,
    val assumptions: List<String> = emptyList(),
    @SerialName("rule_set") val ruleSet: String? = null,
    @SerialName("regulation_ref") val regulationRef: String? = null,
    val disclaimer: String,
)

@Serializable
enum class AppliedCorrectionStatus {
    @SerialName("applied") APPLIED,
    @SerialName("skipped") SKIPPED,
}

/** A correction by the authorised agent as one assessment used it. `skipped` means it could not be placed and was NOT used. */
@Serializable
data class AppliedCorrection(
    @SerialName("correction_id") val correctionId: String,
    val seq: Int,
    @SerialName("document_id") val documentId: String,
    val path: String,
    val anchor: String? = null,
    /** the value that replaced the extracted one; null means cleared */
    val value: String? = null,
    val unit: String? = null,
    /** what the model read */
    @SerialName("original_value") val originalValue: String? = null,
    @SerialName("original_unit") val originalUnit: String? = null,
    val reason: String? = null,
    @SerialName("created_at") val createdAt: String,
    val status: AppliedCorrectionStatus,
    val note: String? = null,
)

/**
 * One immutable assessment of a bundle (`AssessmentIteration`). [status] is the backend's plain string (typed `str` there); read it
 * through [statusKind].
 */
@Serializable
data class AssessmentIteration(
    val iteration: Int,
    @SerialName("bundle_id") val bundleId: String,
    val status: String,
    val checks: List<CheckResult> = emptyList(),
    val grounding: List<GroundingFinding> = emptyList(),
    @SerialName("missing_evidence") val missingEvidence: List<MissingEvidence> = emptyList(),
    val confidence: ConfidenceResult? = null,
    @SerialName("reasoning_delta") val reasoningDelta: ReasoningDelta? = null,
    /** document_ids included */
    val documents: List<String> = emptyList(),
    /** null when unknown (iterations stored before the field existed) */
    @SerialName("data_source") val dataSource: DataSource? = null,
    /** null on iterations stored before the estimate existed */
    val valuation: ValuationEstimate? = null,
    /** file name to sha256 prefix of the curated reference data the checks used */
    @SerialName("reference_data") val referenceData: Map<String, String>? = null,
    /** corrections in force when this assessment ran */
    val corrections: List<AppliedCorrection> = emptyList(),
    /** "full" | "reassess" | "recompute"; null on older iterations */
    @SerialName("run_mode") val runMode: String? = null,
    /** what the model calls of the run that produced this cost, per document; null on older iterations. Not shown by the app yet. */
    @SerialName("token_usage") val tokenUsage: JsonObject? = null,
    @SerialName("created_at") val createdAt: String? = null,
) {
    val statusKind: Status? get() = Status.fromWire(status)
}

/**
 * Text of a JSON scalar the way JavaScript's `String(value)` shows it: `1000.0` and `1000` are both "1000", so a value reads the same on
 * the web and here whatever way the backend happened to serialise the number.
 */
internal fun jsText(value: JsonPrimitive): String {
    if (value is kotlinx.serialization.json.JsonNull) return ""
    if (value.isString) return value.content
    val number = value.content.toBigDecimalOrNull() ?: return value.content
    return if (number.signum() == 0) "0" else number.stripTrailingZeros().toPlainString()
}
