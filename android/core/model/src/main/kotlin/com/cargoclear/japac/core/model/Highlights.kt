package com.cargoclear.japac.core.model

/** A box to draw on a page, with the finding it belongs to. */
data class Highlight(
    val id: String,
    val documentId: String,
    val page: Int,
    val bbox: BBox,
    val severity: Severity,
    val label: String,
    /** The value the box outlines, as the evidence states it (null for a field the document omits). Tells apart the boxes of one finding. */
    val value: String? = null,
)

/** Check evidence is not unique by check id alone, so the check's position, the document, the field and the evidence's position are all in the id. */
fun highlightId(checkId: String, checkIndex: Int, doc: String, field: String?, evidenceIndex: Int): String = "$checkId:$checkIndex:$doc:$field:$evidenceIndex"

/** Where tapping an evidence row should take the viewer: the document, the page the evidence cites, and the box to emphasise (null when the evidence has none). */
data class EvidenceTarget(val documentId: String, val page: Int?, val highlightId: String?)

/** The viewer target of one piece of evidence of the check at [checkIndex]; null when it names no document. */
fun evidenceTarget(check: CheckResult, checkIndex: Int, evidence: EvidenceRef, evidenceIndex: Int): EvidenceTarget? {
    val doc = evidence.doc ?: return null
    val drawn = evidence.page != null && evidence.bbox != null
    return EvidenceTarget(doc, evidence.page, if (drawn) highlightId(check.checkId, checkIndex, doc, evidence.field, evidenceIndex) else null)
}

/**
 * Viewer highlights come only from check evidence that carries a document, a page and a box (port of frontend/lib/highlights.ts).
 * Evidence without a box is simply not drawn.
 */
fun buildHighlights(assessment: AssessmentIteration?): List<Highlight> {
    if (assessment == null) return emptyList()
    return buildList {
        assessment.checks.forEachIndexed { checkIndex, check ->
            check.evidence.orEmpty().forEachIndexed { index, evidence ->
                val doc = evidence.doc ?: return@forEachIndexed
                val page = evidence.page ?: return@forEachIndexed
                val bbox = evidence.bbox ?: return@forEachIndexed
                add(
                    Highlight(
                        id = highlightId(check.checkId, checkIndex, doc, evidence.field, index),
                        documentId = doc,
                        page = page,
                        bbox = bbox,
                        severity = check.severity,
                        label = check.message,
                        value = evidence.rawValueText,
                    ),
                )
            }
        }
    }
}
