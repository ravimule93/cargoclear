package com.cargoclear.japac.core.model

/**
 * The document a person should see first when nothing was chosen: the one the most serious finding is about (port of
 * frontend/lib/finding-document.ts).
 *
 * The check names it itself (`focusDocument`: the alloy check points at the certificate, not at the invoice that carries the HS code).
 * An assessment stored before checks carried one falls back to the first document its evidence cites. Only documents of the bundle on
 * screen count, so a stale id can never select something that is not there.
 */
fun findingDocumentId(checks: List<CheckResult>?, documentIds: List<String>): String? {
    fun known(id: String?): Boolean = id != null && id in documentIds
    val material = checks.orEmpty().firstOrNull { it.severity == Severity.MATERIAL } ?: return null
    if (known(material.focusDocument)) return material.focusDocument
    return material.evidence.orEmpty().map { it.doc }.firstOrNull(::known)
}
