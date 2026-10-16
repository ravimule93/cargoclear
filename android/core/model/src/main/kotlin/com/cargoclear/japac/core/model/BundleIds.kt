package com.cargoclear.japac.core.model

/** The shape the backend accepts for a bundle id in a URL (`ID_PATTERN` in backend/app/gateway/ids.py). Anything else answers 404 there. */
private val BUNDLE_ID = Regex("[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

fun isValidBundleId(candidate: String): Boolean = BUNDLE_ID.matches(candidate)

/**
 * What a person typed or pasted in "open a bundle": a bundle id, or the address of the web workbench for one
 * (`https://host/workbench/bnd-1234abcd5678`, with or without a trailing slash, query or fragment). Returns the id, or null when the
 * text holds none. Never returns something that is not shaped like an id, so it is safe to put in a URL path.
 */
fun extractBundleId(input: String): String? {
    val text = input.trim()
    if (text.isEmpty()) return null
    if (isValidBundleId(text)) return text
    val afterWorkbench = text.substringAfter("/workbench/", missingDelimiterValue = "")
    if (afterWorkbench.isEmpty()) return null
    val segment = afterWorkbench.takeWhile { it != '/' && it != '?' && it != '#' }
    return segment.takeIf(::isValidBundleId)
}
