package com.cargoclear.japac.core.data

/**
 * Where the backend is. [baseUrl] is the full prefix every path hangs off (`.../api/v1/` against the backend directly, `.../api/proxy/`
 * through the deployed UI), always ending in a slash because Retrofit requires it. Null when the build was given none: the app then
 * says so instead of calling a host nobody chose.
 */
class ApiConfig(configured: String) {
    val baseUrl: String? = configured.trim().takeIf { it.isNotEmpty() }?.let { if (it.endsWith("/")) it else "$it/" }

    val isConfigured: Boolean get() = baseUrl != null
}
