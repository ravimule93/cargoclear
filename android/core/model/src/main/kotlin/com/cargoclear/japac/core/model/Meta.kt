package com.cargoclear.japac.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Mirrors `AppMode` in frontend/lib/types.ts (backend: `GET /api/v1/meta`).
 *
 * Deliberately strict: a mode this app does not know is a decoding error, never a guess. Guessing "live" would hide the demo
 * banner and guessing "demo" would claim synthetic data where there may be none.
 */
@Serializable
enum class AppMode {
    @SerialName("demo")
    DEMO,

    @SerialName("live")
    LIVE,
}

/** `GET /api/v1/meta`: which mode the backend runs in. Mirrors `Meta` in frontend/lib/types.ts. */
@Serializable
data class Meta(
    @SerialName("app_mode") val appMode: AppMode,
    @SerialName("data_source_policy") val dataSourcePolicy: String,
    /** Sent by the backend, unused by the app (the web client does not model it either). */
    @SerialName("pipeline_engine") val pipelineEngine: String? = null,
)
