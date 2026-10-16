package com.cargoclear.japac.core.model

/*
 * The web workbench address of a bundle (`/workbench/{id}`, the page frontend/app/workbench/[bundleId] serves), for continuing on a desktop.
 * The app only knows where the UI is when it talks to the backend through the UI's own proxy; against the backend directly there is no UI to
 * point at, and a cleartext address is a development machine that nobody else can reach.
 */

private const val PROXY_SUFFIX = "/api/proxy"

/** The UI's address (scheme, host and any path prefix, no trailing slash), taken from the API address when that is the UI's HTTPS proxy; otherwise null. */
fun webOriginOf(apiBaseUrl: String?): String? {
    val base = apiBaseUrl?.trim()?.trimEnd('/') ?: return null
    if (!base.startsWith("https://", ignoreCase = true) || !base.endsWith(PROXY_SUFFIX)) return null
    return base.removeSuffix(PROXY_SUFFIX).trimEnd('/').takeIf { it.length > "https://".length }
}

/** The link to a bundle on the web workbench, or null when the UI's address is not known or the id is not shaped like one. */
fun workbenchLink(webOrigin: String?, bundleId: String): String? {
    if (webOrigin == null || !isValidBundleId(bundleId)) return null
    return "$webOrigin/workbench/$bundleId"
}
