package com.cargoclear.japac.core.model

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive

/* Port of frontend/lib/delta-labels.ts: what a person reads in the Reasoning Delta instead of the machine keys. */

private fun title(text: String): String =
    text.replace('_', ' ').lowercase().replace(Regex("(^|\\s)\\S")) { it.value.uppercase() }

private val CORRECTION_FIELD = Regex("""^correction\.[^.]+\.(.+)$""")
private val REQUIREMENT_FIELD = Regex("""^missing_evidence\.(?:ME-)?(?:CORE-)?(.+)$""")
private val SCREAMING_CASE = Regex("""^[A-Z]+(_[A-Z]+)+$""")

/** The Attribute column of a change; check ids (M-001) are cited as they are. */
fun attributeLabel(field: String): String {
    CORRECTION_FIELD.matchEntire(field)?.let { return "Correction: ${pathLabel(it.groupValues[1])}" }
    REQUIREMENT_FIELD.matchEntire(field)?.let { return "Required document: ${title(it.groupValues[1])}" }
    if (field == "status") return "Status"
    return field
}

/** A status or severity as words (MATERIAL_CONTRADICTION becomes Material Contradiction); anything else is shown as it is. */
fun plainValue(value: JsonElement?): String {
    val text = when (value) {
        null, JsonNull -> ""
        is JsonPrimitive -> jsText(value)
        else -> value.toString()
    }
    return if (SCREAMING_CASE.matches(text)) title(text) else text
}
