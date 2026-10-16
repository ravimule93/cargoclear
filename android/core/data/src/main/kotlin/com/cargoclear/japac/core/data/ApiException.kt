package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.ErrorEnvelope

/**
 * Everything that can go wrong in a call to the backend, as one type the screens can branch on.
 *
 * The web client throws the backend's envelope as a plain object and branches on `code`; this keeps the envelope and adds what the
 * browser gets from `fetch` itself: [Kind.NETWORK] (could not reach the server, safe to retry), [Kind.MALFORMED] (the answer could not
 * be read), [Kind.NOT_CONFIGURED] (this build has no backend address) and [Kind.LOCAL_FILE] (an upload could not read the file on this
 * phone: nothing was wrong with the server, and trying again will not help).
 */
class ApiException(
    val envelope: ErrorEnvelope,
    val kind: Kind,
    val httpStatus: Int? = null,
    cause: Throwable? = null,
) : Exception(envelope.message, cause) {
    enum class Kind { HTTP, NETWORK, MALFORMED, NOT_CONFIGURED, LOCAL_FILE }

    val code: String get() = envelope.code
    val requestId: String? get() = envelope.requestId

    /** The backend says the thing asked for does not exist (the envelope code `NOT_FOUND`, which `isNotFound` of the web client checks too). */
    val isNotFound: Boolean get() = kind == Kind.HTTP && code == "NOT_FOUND"

    /** The user may reasonably try again without changing anything. */
    val isRetryable: Boolean get() = kind == Kind.NETWORK || httpStatus in RETRYABLE_STATUSES

    companion object {
        const val NETWORK_MESSAGE = "Can't reach the server. Check your connection and try again."
        const val MALFORMED_MESSAGE = "The server's answer could not be read."
        const val NOT_CONFIGURED_MESSAGE = "This build has no backend address configured."
        private val RETRYABLE_STATUSES = setOf(502, 503, 504)
    }
}
