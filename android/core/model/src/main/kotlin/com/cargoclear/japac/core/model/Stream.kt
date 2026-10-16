package com.cargoclear.japac.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
enum class RunState {
    @SerialName("QUEUED") QUEUED,
    @SerialName("RUNNING") RUNNING,
    @SerialName("COMPLETE") COMPLETE,
    @SerialName("ERROR") ERROR;

    val isActive: Boolean get() = this == QUEUED || this == RUNNING
}

/** Payload of the SSE `status` event: the run record of a bundle. */
@Serializable
data class StatusEvent(
    val kind: String? = null,
    @SerialName("bundle_id") val bundleId: String,
    @SerialName("run_id") val runId: String,
    val state: RunState,
    val stage: String? = null,
    val progress: Double = 0.0,
    val message: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)

/** Payload of the SSE `error` event (a server-side stream failure with a fixed message). */
@Serializable
data class StreamErrorEvent(
    val kind: String? = null,
    @SerialName("bundle_id") val bundleId: String,
    val code: String,
    val message: String,
)

/** Answer of `POST /bundles/{id}/analyze|reassess|recompute` (202): the run was accepted; progress arrives on the stream. */
@Serializable
data class RunResponse(
    @SerialName("run_id") val runId: String,
    @SerialName("bundle_id") val bundleId: String,
    val state: RunState,
    val message: String? = null,
)
