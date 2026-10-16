package com.cargoclear.japac.core.model

/*
 * Declaration pre-fill: the values of an assessment, with where each came from, for the person who keys the declaration. It is CargoClear's
 * own documented format (not a government one) and never says a declaration is ready to file. Port of components/assess/PrefillCard.tsx.
 */

enum class PrefillFormat(val extension: String, val mimeType: String) {
    JSON("json", "application/json"),
    PDF("pdf", "application/pdf"),
}

/** The file name the backend gives the download (`_filename` in api/v1/prefill.py), so the share sheet offers the same name the web saves. */
fun prefillFileName(bundleId: String, iteration: Int, format: PrefillFormat): String =
    "cargoclear-prefill-$bundleId-assessment$iteration.${format.extension}"

/** The line under the card's text: whether this pack is of a cleared assessment, and whether corrections are missing from it. */
sealed interface PrefillCaveat {
    /** the pack leads with what blocks it, and flags every value an open finding cites */
    data object NotCleared : PrefillCaveat

    /** cleared, but [count] correction changes were made after this assessment */
    data class Pending(val count: Int) : PrefillCaveat

    data object ClearedWithAllCorrections : PrefillCaveat

    /** only the last one is the reassuring one: it is shown in the "ok" tone, the others as a warning */
    val reassuring: Boolean get() = this is ClearedWithAllCorrections
}

fun prefillCaveat(assessment: AssessmentIteration, pendingCorrections: Int): PrefillCaveat = when {
    assessment.statusKind != Status.COMPLIANT_FOR_SUBMISSION -> PrefillCaveat.NotCleared
    pendingCorrections > 0 -> PrefillCaveat.Pending(pendingCorrections)
    else -> PrefillCaveat.ClearedWithAllCorrections
}
