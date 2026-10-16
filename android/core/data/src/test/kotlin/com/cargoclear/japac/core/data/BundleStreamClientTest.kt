package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.RunState
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The stream client against a real (local) HTTP server speaking Server-Sent Events, including the CRLF line endings the backend uses. */
class BundleStreamClientTest {
    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() {
        runCatching { server.close() }
    }

    private fun client(base: String? = server.url("/api/v1/").toString(), backoffMillis: Long = 10) =
        BundleStreamClient(ApiConfig(base.orEmpty()), testClient(), backoff = Backoff { backoffMillis })

    private fun sse(body: String, code: Int = 200) = MockResponse.Builder().code(code).addHeader("Content-Type", "text/event-stream").body(body).build()

    private fun <T> Flow<T>.firstN(n: Int): List<T> = runBlocking { withTimeout(10_000) { take(n).toList() } }

    private val statusRunning = """{"bundle_id":"bnd-x","kind":"status","progress":0.15,"run_id":"run-1","stage":"preprocess","state":"RUNNING"}"""

    @Test
    fun `the recorded run replays as opened, four statuses and the iteration, then a reconnect is scheduled`() {
        server.enqueue(sse(TestResources.text("stream_case_c_first_run.sse")))

        val events = client().events("bnd-x").firstN(7)

        assertEquals(StreamEvent.Opened, events[0])
        val statuses = events.filterIsInstance<StreamEvent.Status>().map { it.event }
        assertEquals(listOf(RunState.COMPLETE, RunState.RUNNING, RunState.RUNNING, RunState.COMPLETE), statuses.map { it.state })
        assertEquals(listOf("default", "run-55e106bc7a55", "run-55e106bc7a55", "run-55e106bc7a55"), statuses.map { it.runId })
        assertEquals(1, events.filterIsInstance<StreamEvent.Iteration>().single().iteration.iteration)
        val disconnected = events[6] as StreamEvent.Disconnected
        assertEquals(1, disconnected.attempt)
        assertNull(disconnected.httpStatus)

        val request = server.takeRequest()
        assertEquals("/api/v1/bundles/bnd-x/stream", request.url.encodedPath)
        assertEquals("text/event-stream", request.headers["Accept"])
        assertTrue(request.headers[RequestIdInterceptor.HEADER].orEmpty().isNotEmpty())
    }

    @Test
    fun `a closed stream is reopened and the next connection's events arrive`() {
        server.enqueue(sse("event: status\r\ndata: $statusRunning\r\n\r\n"))
        server.enqueue(sse("event: status\r\ndata: ${statusRunning.replace("0.15", "0.75")}\r\n\r\n"))

        val events = client().events("bnd-x").firstN(6)

        val progress = events.filterIsInstance<StreamEvent.Status>().map { it.event.progress }
        assertEquals(listOf(0.15, 0.75), progress)
        assertEquals(2, events.count { it == StreamEvent.Opened })
        assertEquals(2, server.requestCount)
    }

    @Test
    fun `a connection that went silent is replaced at once when the network comes back, and the new one replays`() {
        // the first connection opens and then says nothing for a minute (the radio went off and on; the socket does not know)
        server.enqueue(MockResponse.Builder().code(200).addHeader("Content-Type", "text/event-stream").body("event: status\r\ndata: $statusRunning\r\n\r\n").bodyDelay(60, java.util.concurrent.TimeUnit.SECONDS).build())
        server.enqueue(sse("event: status\r\ndata: ${statusRunning.replace("RUNNING", "COMPLETE")}\r\n\r\n"))
        val network = kotlinx.coroutines.flow.MutableSharedFlow<Unit>(extraBufferCapacity = 1)
        // a backoff far longer than the test: only the signal can have started the second connection
        val stream = BundleStreamClient(ApiConfig(server.url("/api/v1/").toString()), testClient(), backoff = Backoff { 60_000 }, reconnectSignals = network)

        val events = runBlocking {
            withTimeout(10_000) {
                val received = mutableListOf<StreamEvent>()
                kotlinx.coroutines.coroutineScope {
                    val job = launch { stream.events("bnd-x").collect { received += it } }
                    while (received.none { it == StreamEvent.Opened }) delay(20)
                    network.emit(Unit) // the network is available again
                    while (received.none { it is StreamEvent.Status }) delay(20)
                    job.cancel()
                }
                received
            }
        }

        assertEquals("two connections were made, the second without waiting out the silence", 2, server.requestCount)
        assertEquals(StreamEvent.Opened, events.first())
        assertEquals(RunState.COMPLETE, (events.filterIsInstance<StreamEvent.Status>().single().event).state)
        assertEquals("a cut by the network starts over rather than counting a failed attempt", StreamEvent.Disconnected(attempt = 1, retryInMillis = 0, httpStatus = null), events.filterIsInstance<StreamEvent.Disconnected>().first())
    }

    @Test
    fun `the network coming back while the client waits to try again ends the wait`() {
        server.enqueue(MockResponse.Builder().code(503).body("busy").build())
        server.enqueue(sse("event: status\r\ndata: $statusRunning\r\n\r\n"))
        val network = kotlinx.coroutines.flow.MutableSharedFlow<Unit>(extraBufferCapacity = 1)
        val stream = BundleStreamClient(ApiConfig(server.url("/api/v1/").toString()), testClient(), backoff = Backoff { 60_000 }, reconnectSignals = network)

        val events = runBlocking {
            withTimeout(10_000) {
                val received = mutableListOf<StreamEvent>()
                kotlinx.coroutines.coroutineScope {
                    val job = launch { stream.events("bnd-x").collect { received += it } }
                    while (received.none { it is StreamEvent.Disconnected }) delay(20) // the first attempt failed: a minute to wait
                    network.subscriptionCount.first { it > 0 } // the client is waiting for the signal
                    network.emit(Unit)
                    while (received.none { it == StreamEvent.Opened }) delay(20)
                    job.cancel()
                }
                received
            }
        }

        assertEquals(StreamEvent.Disconnected(attempt = 1, retryInMillis = 60_000, httpStatus = 503), events[0])
        assertEquals(StreamEvent.Opened, events[1])
        assertEquals(2, server.requestCount)
    }

    @Test
    fun `a failed attempt after the network signalled starts the count again`() {
        // two failures, then a signal during the second wait, then a failure again: that one is attempt 1, not 3
        server.enqueue(MockResponse.Builder().code(503).body("busy").build())
        server.enqueue(MockResponse.Builder().code(503).body("busy").build())
        server.enqueue(MockResponse.Builder().code(503).body("busy").build())
        val network = kotlinx.coroutines.flow.MutableSharedFlow<Unit>(extraBufferCapacity = 1)
        val stream = BundleStreamClient(ApiConfig(server.url("/api/v1/").toString()), testClient(), backoff = Backoff { attempt -> if (attempt == 1) 10L else 60_000L }, reconnectSignals = network)

        val events = runBlocking {
            withTimeout(10_000) {
                val received = mutableListOf<StreamEvent>()
                kotlinx.coroutines.coroutineScope {
                    val job = launch { stream.events("bnd-x").collect { received += it } }
                    while (received.count { it is StreamEvent.Disconnected } < 2) delay(20) // attempt 1 (10 ms), then attempt 2 (a minute)
                    network.subscriptionCount.first { it > 0 }
                    network.emit(Unit)
                    while (received.count { it is StreamEvent.Disconnected } < 3) delay(20)
                    job.cancel()
                }
                received
            }
        }

        assertEquals(listOf(1, 2, 1), events.filterIsInstance<StreamEvent.Disconnected>().map { it.attempt })
    }

    @Test
    fun `without a signal a healthy connection is left alone`() {
        server.enqueue(sse("event: status\r\ndata: $statusRunning\r\n\r\n"))
        val events = BundleStreamClient(ApiConfig(server.url("/api/v1/").toString()), testClient(), backoff = Backoff { 10 }).events("bnd-x").firstN(3)
        assertEquals(StreamEvent.Opened, events[0])
        assertEquals(1, server.requestCount)
    }

    @Test
    fun `a server error is retried with the attempt counted until a connection opens`() {
        server.enqueue(MockResponse.Builder().code(503).body("busy").build())
        server.enqueue(MockResponse.Builder().code(502).body("bad gateway").build())
        server.enqueue(sse("event: status\r\ndata: $statusRunning\r\n\r\n"))

        val events = client().events("bnd-x").firstN(4)

        assertEquals(StreamEvent.Disconnected(attempt = 1, retryInMillis = 10, httpStatus = 503), events[0])
        assertEquals(StreamEvent.Disconnected(attempt = 2, retryInMillis = 10, httpStatus = 502), events[1])
        assertEquals(StreamEvent.Opened, events[2])
        assertTrue(events[3] is StreamEvent.Status)
    }

    @Test
    fun `no such bundle ends the stream instead of retrying forever`() {
        server.enqueue(MockResponse.Builder().code(404).addHeader("Content-Type", "application/json").body(TestResources.text("error_bundle_not_found.json")).build())

        val events = runBlocking { withTimeout(10_000) { client().events("bnd-nope").toList() } }

        assertEquals(listOf(StreamEvent.Rejected(404)), events)
        assertEquals(1, server.requestCount)
    }

    @Test
    fun `an id that is not an id, or a build without a backend address, never makes a request`() {
        val bad = runBlocking { withTimeout(5_000) { client().events("../secret").toList() } }
        val unconfigured = runBlocking { withTimeout(5_000) { client(base = "").events("bnd-x").toList() } }
        assertEquals(listOf(StreamEvent.Rejected(404)), bad)
        assertEquals(listOf(StreamEvent.Rejected(404)), unconfigured)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `keep-alive comments and event names it does not know are ignored, and a payload it cannot read is reported`() {
        server.enqueue(
            sse(
                ": ping - 2026-10-14\r\n\r\n" +
                    "event: something-new\r\ndata: {}\r\n\r\n" +
                    "event: status\r\ndata: {\"this\":\"is not a status\"}\r\n\r\n" +
                    "event: error\r\ndata: {\"bundle_id\":\"bnd-x\",\"code\":\"STREAM_EXCEPTION\",\"message\":\"The event stream failed unexpectedly\"}\r\n\r\n",
            ),
        )

        val events = client().events("bnd-x").firstN(4)

        assertEquals(StreamEvent.Opened, events[0])
        assertEquals(StreamEvent.Unreadable("status"), events[1])
        assertEquals("The event stream failed unexpectedly", (events[2] as StreamEvent.ServerError).event.message)
    }

    @Test
    fun `the delay grows from 3 seconds and stops at 30`() {
        val delays = (1..8).map { Backoff.Default.delayMillis(it) }
        assertEquals(listOf(3_000L, 6_000L, 12_000L, 24_000L, 30_000L, 30_000L, 30_000L, 30_000L), delays)
    }
}
