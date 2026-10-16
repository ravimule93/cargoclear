package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.StatusEvent
import com.cargoclear.japac.core.model.StreamErrorEvent
import com.cargoclear.japac.core.model.isValidBundleId
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.buffer
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.firstOrNull
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.merge
import kotlinx.coroutines.flow.onCompletion
import kotlinx.coroutines.flow.takeWhile
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources

/** How long to wait before the next attempt: 3 s, doubling to 30 s (the web client reopens a closed stream after 3 s). */
fun interface Backoff {
    fun delayMillis(attempt: Int): Long

    companion object {
        val Default = Backoff { attempt -> minOf(30_000L, 3_000L shl (attempt - 1).coerceIn(0, 4)) }
    }
}

/**
 * The live stream of one bundle (`GET /bundles/{id}/stream`, Server-Sent Events): `status` (run progress), `iteration` (a full new
 * assessment) and `error`. Port of `useBundleStream` (frontend/lib/hooks/useBundleStream.ts) with what a phone adds: the connection is
 * only held while somebody collects the flow, and a lost connection is retried with a growing delay.
 *
 * Reconnecting is normal, not an error: Cloud Run ends every request after its timeout (300 s here), and the server replays the
 * current status and the latest iteration on every connect, so nothing needs to be "caught up" by hand.
 *
 * The read timeout must be longer than the server's keep-alive (a comment line every 15 s), or a quiet but healthy stream would be cut. That is
 * also how long a connection that broke without telling anyone (the radio went off and came back) would sit dead, so [reconnectSignals] (the
 * phone saying a network is available again) cuts the connection at once and opens a new one, whose replay brings the screen up to date.
 * The same signal ends the wait between two attempts, and either way the count of failed attempts starts over: a network that has just come
 * back is the reason the wait was for.
 */
class BundleStreamClient(
    private val config: ApiConfig,
    client: OkHttpClient,
    private val json: Json = Backend.defaultJson,
    private val backoff: Backoff = Backoff.Default,
    private val reconnectSignals: Flow<Unit> = emptyFlow(),
) {
    private val sseClient: OkHttpClient = client.newBuilder().readTimeout(READ_TIMEOUT_SECONDS, TimeUnit.SECONDS).build()

    fun events(bundleId: String): Flow<StreamEvent> = flow {
        val url = config.baseUrl?.let { "${it}bundles/$bundleId/stream".toHttpUrlOrNull() }
        if (url == null || !isValidBundleId(bundleId)) {
            emit(StreamEvent.Rejected(httpStatus = 404))
            return@flow
        }
        val request = Request.Builder().url(url).header("Accept", "text/event-stream").build()

        var attempt = 0
        while (true) {
            var opened = false
            var failureStatus: Int? = null
            var fatal = false
            var cutBySignal = false
            connect(request).untilReconnectSignal { cutBySignal = true }.collect { raw ->
                when (raw) {
                    Raw.Opened -> {
                        opened = true
                        attempt = 0
                        emit(StreamEvent.Opened)
                    }
                    is Raw.Event -> if (raw.type in KNOWN_EVENTS) emit(decode(raw) ?: StreamEvent.Unreadable(raw.type))
                    Raw.Closed -> Unit
                    is Raw.Failure -> {
                        failureStatus = raw.httpStatus
                        fatal = raw.httpStatus != null && raw.httpStatus in 400..499 && raw.httpStatus != 408 && raw.httpStatus != 429
                    }
                }
            }
            if (fatal) {
                emit(StreamEvent.Rejected(checkNotNull(failureStatus)))
                return@flow
            }
            if (cutBySignal) {
                // a network is there again: nothing to back off from, and the count of failed attempts starts over
                attempt = 0
                emit(StreamEvent.Disconnected(attempt = 1, retryInMillis = 0, httpStatus = null))
                continue
            }
            attempt += 1
            val wait = backoff.delayMillis(attempt)
            emit(StreamEvent.Disconnected(attempt = if (opened) 1 else attempt, retryInMillis = wait, httpStatus = failureStatus))
            if (sleepUnlessSignalled(wait)) attempt = 0
        }
    }

    /** Waits [millis] before the next attempt, or less when the phone says a network is available again (then the wait was for that). True when it did. */
    private suspend fun sleepUnlessSignalled(millis: Long): Boolean {
        var signalled = false
        withTimeoutOrNull(millis) {
            signalled = reconnectSignals.firstOrNull() != null
            if (!signalled) awaitCancellation() // the signals ended without one (there are none to wait for): wait out the time
        }
        return signalled
    }

    /**
     * The events of one connection, ending when it ends or when [reconnectSignals] fires, whichever is first (the first ends the collect,
     * which cancels the other). [onSignal] is told when it was the signal.
     */
    private fun Flow<Raw>.untilReconnectSignal(onSignal: () -> Unit): Flow<Raw> {
        val connection = map<Raw, Step> { Step.Item(it) }.onCompletion { emit(Step.End) }
        return merge(connection, reconnectSignals.map { onSignal(); Step.End }).takeWhile { it !is Step.End }.map { (it as Step.Item).raw }
    }

    private sealed interface Step {
        data class Item(val raw: Raw) : Step
        data object End : Step
    }

    /** Null when the payload could not be read; an event name this app does not know never gets here (it is ignored). */
    private fun decode(event: Raw.Event): StreamEvent? = try {
        when (event.type) {
            "status" -> StreamEvent.Status(json.decodeFromString<StatusEvent>(event.data))
            "iteration" -> StreamEvent.Iteration(json.decodeFromString<AssessmentIteration>(event.data))
            else -> StreamEvent.ServerError(json.decodeFromString<StreamErrorEvent>(event.data))
        }
    } catch (_: kotlinx.serialization.SerializationException) {
        null
    }

    private sealed interface Raw {
        data object Opened : Raw
        data class Event(val type: String, val data: String) : Raw
        data object Closed : Raw
        data class Failure(val httpStatus: Int?) : Raw
    }

    /** One connection: its events until it closes or fails. Cancelling the collector cancels the call. */
    private fun connect(request: Request): Flow<Raw> = callbackFlow {
        val listener = object : EventSourceListener() {
            override fun onOpen(eventSource: EventSource, response: Response) {
                trySend(Raw.Opened)
            }

            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                trySend(Raw.Event(type ?: "message", data))
            }

            override fun onClosed(eventSource: EventSource) {
                trySend(Raw.Closed)
                close()
            }

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                trySend(Raw.Failure(response?.code))
                close()
            }
        }
        val source = EventSources.createFactory(sseClient).newEventSource(request, listener)
        awaitClose { source.cancel() }
    }.buffer(Channel.UNLIMITED)

    companion object {
        /** Longer than the server's 15 s keep-alive. */
        const val READ_TIMEOUT_SECONDS = 45L

        private val KNOWN_EVENTS = setOf("status", "iteration", "error")
    }
}
