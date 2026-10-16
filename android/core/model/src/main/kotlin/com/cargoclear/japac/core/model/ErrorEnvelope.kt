package com.cargoclear.japac.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/**
 * The error body every backend failure carries (`{code, message, detail, request_id}`); the UI's proxy uses the same shape for its own
 * failures. Mirrors `ErrorEnvelope` in frontend/lib/types.ts.
 */
@Serializable
data class ErrorEnvelope(
    val code: String,
    val message: String,
    val detail: JsonElement? = null,
    @SerialName("request_id") val requestId: String? = null,
)
