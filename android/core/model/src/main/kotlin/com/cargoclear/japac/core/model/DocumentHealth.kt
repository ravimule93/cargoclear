package com.cargoclear.japac.core.model

/** How many evidence entries of each severity cite a document (the Conflict / Gap / Clean chips of the document rail). */
data class DocumentHealth(val material: Int = 0, val warn: Int = 0, val pass: Int = 0)

enum class HealthBadge { CONFLICT, GAP, CLEAN }

/** Port of the counting in components/rail/DocumentRail.tsx: every evidence entry of every check counts once for its document. */
fun documentHealth(documents: List<DocumentRecord>, checks: List<CheckResult>): Map<String, DocumentHealth> {
    val counts = LinkedHashMap<String, DocumentHealth>()
    for (doc in documents) counts[doc.documentId] = DocumentHealth()
    for (check in checks) {
        for (ev in check.evidence.orEmpty()) {
            val doc = ev.doc?.takeIf { it.isNotEmpty() } ?: continue
            val current = counts[doc] ?: DocumentHealth()
            counts[doc] = when (check.severity) {
                Severity.MATERIAL -> current.copy(material = current.material + 1)
                Severity.WARN -> current.copy(warn = current.warn + 1)
                Severity.PASS -> current.copy(pass = current.pass + 1)
            }
        }
    }
    return counts
}

/** The chip a document gets: conflicts beat gaps, gaps beat clean, and a document no check cites gets none. */
fun DocumentHealth.badge(): HealthBadge? = when {
    material > 0 -> HealthBadge.CONFLICT
    warn > 0 -> HealthBadge.GAP
    pass > 0 -> HealthBadge.CLEAN
    else -> null
}
