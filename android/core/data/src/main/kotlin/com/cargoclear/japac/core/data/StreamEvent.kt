package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.StatusEvent
import com.cargoclear.japac.core.model.StreamErrorEvent

/** What a bundle's live stream tells the app. The stream never ends by itself: it reconnects until the collector stops. */
sealed interface StreamEvent {
    /** A connection is open (the server now replays the current status and the latest iteration). */
    data object Opened : StreamEvent

    data class Status(val event: StatusEvent) : StreamEvent

    data class Iteration(val iteration: AssessmentIteration) : StreamEvent

    /** The server's own `error` event (a fixed message, never exception text). */
    data class ServerError(val event: StreamErrorEvent) : StreamEvent

    /** An event the app could not read (the backend and the app disagree about its shape). Surfaced, not swallowed. */
    data class Unreadable(val type: String) : StreamEvent

    /**
     * The connection ended, cleanly (Cloud Run closes every stream after its request timeout) or by failure, and the next attempt
     * starts after [retryInMillis]. [attempt] counts consecutive attempts that never opened; it is 1 for a connection that was open.
     */
    data class Disconnected(val attempt: Int, val retryInMillis: Long, val httpStatus: Int?) : StreamEvent

    /** The server refused the stream in a way retrying cannot fix (for example 404: no such bundle). The flow ends after this. */
    data class Rejected(val httpStatus: Int) : StreamEvent
}
