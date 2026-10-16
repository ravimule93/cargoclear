package com.cargoclear.japac.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/*
 * Corrections by the authorised agent: how an evidence row names the value it shows (its address), and how to read that value back
 * from an extraction. Port of frontend/lib/corrections.ts.
 *
 * MIRRORS backend/app/domain/corrections.py (the field tables and the path grammar). The backend is the authority and refuses anything
 * outside its tables. backend/tests/unit/test_android_contract.py fails if the lists below drift from the Python ones, so keep their
 * layout (one `"name",` per line inside `listOf(...)`) as it is.
 */

/** Header fields of a document that can be corrected. */
val HEADER_FIELDS: List<String> = listOf(
    "document_number",
    "consignee",
    "consignor",
    "vessel_or_flight",
    "port_of_loading",
    "port_of_discharge",
    "shipment_date",
    "invoice_value",
    "invoice_currency",
    "total_net_weight_kg",
    "total_gross_weight_kg",
    "tare_weight_kg",
    "package_count",
    "hs_code_header",
    "incoterm",
    "country_of_origin",
    "freight_amount",
    "freight_currency",
    "insurance_amount",
    "insurance_currency",
    "specification",
)

/** Fields of one line item that can be corrected. */
val LINE_FIELDS: List<String> = listOf(
    "description",
    "quantity",
    "net_weight_kg",
    "gross_weight_kg",
    "hs_code_declared",
    "unit_price",
    "total_value",
    "currency",
    "unit_price_basis",
)

/** Lists on a document whose entries can be corrected one by one. */
val ROW_LISTS: List<String> = listOf(
    "heat_numbers",
    "test_results",
)

/** Weights carry a printed unit (a lab value does too; see [hasUnit]). */
val WEIGHT_FIELDS: Set<String> = setOf(
    "total_net_weight_kg",
    "total_gross_weight_kg",
    "tare_weight_kg",
    "net_weight_kg",
    "gross_weight_kg",
)

/** An extracted document as the API returns it: loosely typed on purpose (the backend schema is large and this only reads it). */
typealias ExtractedDoc = JsonObject

private val LINE_PATH = Regex("""^line_items\[(\d+)]\.([a-z_]+)$""")
private val ROW_PATH = Regex("""^([a-z_]+)\[(\d+)]$""")

/**
 * The address of the value an evidence entry shows, or null when the entry does not point at exactly one correctable value (for
 * example an HS code stated on several lines, or a derived figure).
 */
fun evidencePath(ev: EvidenceRef): String? {
    val field = ev.field ?: return null
    fun isIndex(n: Int?): Boolean = n != null && n >= 0
    if (field in ROW_LISTS) return if (isIndex(ev.row)) "$field[${ev.row}]" else null
    if (isIndex(ev.lineItem)) return if (field in LINE_FIELDS) "line_items[${ev.lineItem}].$field" else null
    return if (field in HEADER_FIELDS) field else null
}

/** Does the value at this address carry a printed unit (a weight or a certificate cell)? */
fun hasUnit(path: String): Boolean {
    if (path.startsWith("test_results[")) return true
    val field = if ('.' in path) path.substring(path.lastIndexOf('.') + 1) else path
    return field in WEIGHT_FIELDS
}

/** Rows cannot be cleared (a person corrects a certificate cell, they do not delete it). */
fun canClear(path: String): Boolean = !ROW_PATH.matches(path)

data class CellValue(
    val value: String?,
    val unit: String?,
    val corrected: Boolean,
    val originalValue: String?,
    val originalUnit: String?,
)

private fun asText(value: kotlinx.serialization.json.JsonElement?): String? = when (value) {
    null, JsonNull -> null
    is JsonPrimitive -> jsText(value)
    else -> value.toString()
}

private fun asRef(value: kotlinx.serialization.json.JsonElement?): JsonObject? = value as? JsonObject

/** The value (and unit) an extraction has at an address; null when the document or the address does not exist. */
fun readCell(docs: List<ExtractedDoc>, documentId: String, path: String): CellValue? {
    val doc = docs.firstOrNull { (it["document_id"] as? JsonPrimitive)?.content == documentId } ?: return null

    val lineMatch = LINE_PATH.matchEntire(path)
    val rowMatch = ROW_PATH.matchEntire(path)
    val ref: JsonObject? = when {
        lineMatch != null -> {
            val items = doc["line_items"] as? JsonArray
            val item = asRef(items?.getOrNull(lineMatch.groupValues[1].toInt())) ?: return null
            asRef(item[lineMatch.groupValues[2]])
        }
        rowMatch != null -> {
            val list = doc[rowMatch.groupValues[1]] as? JsonArray
            asRef(list?.getOrNull(rowMatch.groupValues[2].toInt())) ?: return null
        }
        else -> asRef(doc[path])
    }

    if (ref == null) return CellValue(null, null, corrected = false, originalValue = null, originalUnit = null)
    return CellValue(
        value = asText(ref["value"]),
        unit = asText(ref["unit"]),
        corrected = (ref["corrected"] as? JsonPrimitive)?.content == "true",
        originalValue = asText(ref["original_value"]),
        originalUnit = asText(ref["original_unit"]),
    )
}

/** A short human label for an address: "Consignee", "Line 2 · HS code declared", "Certificate cell 7". */
fun pathLabel(path: String): String {
    fun words(name: String): String =
        name.removeSuffix("_kg").replace('_', ' ').replaceFirstChar { it.uppercaseChar() }

    LINE_PATH.matchEntire(path)?.let { return "Line ${it.groupValues[1].toInt() + 1} · ${words(it.groupValues[2])}" }
    ROW_PATH.matchEntire(path)?.let {
        val kind = if (it.groupValues[1] == "heat_numbers") "Heat number" else "Certificate cell"
        return "$kind ${it.groupValues[2].toInt() + 1}"
    }
    return words(path)
}

// ---------------------------------------------------------------------------------------------------------------------------------
// The correction history: what the backend sends and what the card and the evidence rows say about it
// ---------------------------------------------------------------------------------------------------------------------------------

/** One correction: what the document actually states at one address of the extraction (`CorrectionRequest` in the backend). */
@Serializable
data class CorrectionRequest(
    @SerialName("document_id") val documentId: String,
    val path: String,
    val value: String? = null,
    val unit: String? = null,
    /** true means the document does not state this value (instead of [value]) */
    val clear: Boolean = false,
    val reason: String? = null,
)

@Serializable
data class RevertCorrectionRequest(val reason: String? = null)

@Serializable
enum class CorrectionKind {
    @SerialName("correction") CORRECTION,
    @SerialName("confirmation") CONFIRMATION,
    @SerialName("revert") REVERT,
}

/** One entry of the correction history, read back from the audit chain. */
@Serializable
data class CorrectionRecord(
    @SerialName("correction_id") val correctionId: String,
    val kind: CorrectionKind,
    val seq: Int,
    @SerialName("created_at") val createdAt: String,
    /** the assessment the agent was looking at when they acted */
    val iteration: Int,
    @SerialName("document_id") val documentId: String,
    val path: String,
    val anchor: String? = null,
    val value: String? = null,
    val unit: String? = null,
    /** what the model read */
    @SerialName("original_value") val originalValue: String? = null,
    @SerialName("original_unit") val originalUnit: String? = null,
    /** the value just before this entry (an earlier correction, or the model's) */
    @SerialName("previous_value") val previousValue: String? = null,
    @SerialName("previous_unit") val previousUnit: String? = null,
    /** for kind `revert`: the id of the correction it undoes */
    val reverts: String? = null,
    val reason: String? = null,
    val actor: String = "user",
)

@Serializable
data class CorrectionsResponse(
    /** every entry, oldest first */
    val corrections: List<CorrectionRecord> = emptyList(),
    /** the overlay in force now: the latest non-reverted entry per address */
    val effective: List<CorrectionRecord> = emptyList(),
    /** changes to the overlay that the latest assessment does not include yet */
    val pending: Int = 0,
    @SerialName("latest_iteration") val latestIteration: Int? = null,
)

/** A value as the card prints it: "(not stated)" when there is none, and the unit unless the value already ends with it. */
fun shownValue(value: String?, unit: String?): String {
    if (value.isNullOrEmpty()) return "(not stated)"
    return if (!unit.isNullOrEmpty() && !value.uppercase().endsWith(unit.uppercase())) "$value $unit" else value
}

/** Where a correction in force stands against the assessment on screen. */
sealed interface CorrectionStatus {
    /** the assessment on screen was computed with it */
    data object InAssessment : CorrectionStatus

    /** the assessment tried to use it and could not place it: it did NOT count */
    data class NotUsed(val note: String?) : CorrectionStatus

    /** made after that assessment: recompute to apply it */
    data object PendingRecompute : CorrectionStatus
}

fun correctionStatus(entry: CorrectionRecord, assessment: AssessmentIteration): CorrectionStatus {
    val used = assessment.corrections.firstOrNull { it.correctionId == entry.correctionId }
    return when (used?.status) {
        AppliedCorrectionStatus.APPLIED -> CorrectionStatus.InAssessment
        AppliedCorrectionStatus.SKIPPED -> CorrectionStatus.NotUsed(used.note)
        null -> CorrectionStatus.PendingRecompute
    }
}

/** What stands on one value an evidence row shows (port of `stateOf` in CheckList.tsx). */
sealed interface EvidenceCorrection {
    /** in force, and the assessment on screen used it */
    data class Used(val entry: AppliedCorrection) : EvidenceCorrection

    /** in force, but made after the assessment on screen */
    data class Pending(val entry: CorrectionRecord) : EvidenceCorrection

    /** the assessment used a correction that has since been undone */
    data class Undone(val entry: AppliedCorrection) : EvidenceCorrection
}

fun evidenceCorrection(
    documentId: String,
    path: String,
    corrections: CorrectionsResponse?,
    applied: List<AppliedCorrection>,
): EvidenceCorrection? {
    val inForce = corrections?.effective?.firstOrNull { it.documentId == documentId && it.path == path }
    val used = applied.firstOrNull { it.documentId == documentId && it.path == path && it.status == AppliedCorrectionStatus.APPLIED }
    return when {
        inForce != null && used?.correctionId == inForce.correctionId -> EvidenceCorrection.Used(used)
        inForce != null -> EvidenceCorrection.Pending(inForce)
        used != null -> EvidenceCorrection.Undone(used)
        else -> null
    }
}

/** What the evidence row of a value can be edited at, and why it cannot: the address of the value, or null when the row does not name exactly one. */
fun editablePath(ev: EvidenceRef): String? = if (ev.doc != null) evidencePath(ev) else null

/**
 * The correction editor's form (port of CorrectionEditor.tsx): the value as printed, its unit when it has one, a reason, and "the document
 * does not state this value". Saving the value as it already is records a confirmation (the model was right, and a person checked); anything
 * else is a correction. Nothing changes the assessment until it is recomputed.
 *
 * The extracted value can still be loading when the editor opens: [loaded] fills the fields once it arrives, unless the person has typed.
 */
data class CorrectionDraft(
    val documentId: String,
    val path: String,
    val value: String = "",
    val unit: String = "",
    val reason: String = "",
    val clear: Boolean = false,
    val touched: Boolean = false,
    val busy: Boolean = false,
    val error: String? = null,
) {
    val showUnit: Boolean get() = hasUnit(path)
    val clearable: Boolean get() = canClear(path)

    fun valueChanged(text: String): CorrectionDraft = copy(value = text.take(MAX_VALUE), touched = true)

    fun unitChanged(text: String): CorrectionDraft = copy(unit = text.take(MAX_UNIT), touched = true)

    fun reasonChanged(text: String): CorrectionDraft = copy(reason = text.take(MAX_VALUE))

    fun clearChanged(checked: Boolean): CorrectionDraft = copy(clear = checked)

    /** The value the extraction has now arrived (or changed): fill the fields, unless the person already typed. */
    fun loaded(current: CellValue?): CorrectionDraft =
        if (touched) this else copy(value = current?.value.orEmpty(), unit = current?.unit.orEmpty())

    /** Saving would change nothing: the value (and unit) are as the extraction has them. */
    fun unchanged(current: CellValue?): Boolean =
        !clear && value.trim() == current?.value.orEmpty() && (!showUnit || unit.trim() == current?.unit.orEmpty())

    /** The button reads "Confirm value" when [unchanged], "Save correction" otherwise. */
    fun canSave(current: CellValue?): Boolean = !busy && current != null && (clear || value.trim().isNotEmpty())

    fun saving(): CorrectionDraft = copy(busy = true, error = null)

    fun failed(message: String): CorrectionDraft = copy(busy = false, error = message)

    fun request(): CorrectionRequest = CorrectionRequest(
        documentId = documentId,
        path = path,
        value = if (clear) null else value,
        unit = if (showUnit && !clear && unit.trim().isNotEmpty()) unit.trim() else null,
        clear = clear,
        reason = reason.trim().ifEmpty { null },
    )

    companion object {
        /** The backend's limits (`CorrectionRequest`): a longer text would be refused with a 422. */
        const val MAX_VALUE = 500
        const val MAX_UNIT = 24
    }
}
