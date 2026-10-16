package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.AppMode
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class BackendTest {
    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() {
        runCatching { server.close() }
    }

    private fun backend(base: String? = server.url("/api/v1/").toString()) = Backend(
        config = ApiConfig(base.orEmpty()),
        client = OkHttpClient.Builder().addInterceptor(RequestIdInterceptor()).build(),
    )

    private fun json(code: Int, body: String) =
        MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build()

    private suspend fun failureOf(block: suspend () -> Unit): ApiException {
        try {
            block()
        } catch (e: ApiException) {
            return e
        }
        fail("expected an ApiException")
        throw AssertionError()
    }

    @Test
    fun `reads the meta and calls the path under the configured prefix`() = runTest {
        server.enqueue(json(200, """{"app_mode":"demo","data_source_policy":"fixtures","added_later":true}"""))

        val meta = NetworkMetaRepository(backend()).load()

        assertEquals(AppMode.DEMO, meta.appMode)
        val request = server.takeRequest()
        assertEquals("GET", request.method)
        assertEquals("/api/v1/meta", request.url.encodedPath)
    }

    @Test
    fun `sends a request id the proxy accepts and no credentials`() = runTest {
        server.enqueue(json(200, """{"app_mode":"live","data_source_policy":"live-only"}"""))
        server.enqueue(json(200, """{"app_mode":"live","data_source_policy":"live-only"}"""))
        val repository = NetworkMetaRepository(backend())

        repository.load()
        repository.load(forceRefresh = true)

        val first = server.takeRequest().headers[RequestIdInterceptor.HEADER]
        val second = server.takeRequest().headers[RequestIdInterceptor.HEADER]
        val accepted = Regex("^[A-Za-z0-9._-]{1,64}$")
        assertTrue(accepted.matches(first.orEmpty()))
        assertTrue(accepted.matches(second.orEmpty()))
        assertNotEquals(first, second)
    }

    @Test
    fun `carries no authorization or cookie header`() = runTest {
        server.enqueue(json(200, """{"app_mode":"live","data_source_policy":"live-only"}"""))

        NetworkMetaRepository(backend()).load()

        val headers = server.takeRequest().headers
        assertNull(headers["Authorization"])
        assertNull(headers["Cookie"])
    }

    @Test
    fun `a backend error keeps its envelope and request id`() = runTest {
        server.enqueue(json(404, """{"code":"NOT_FOUND","message":"Bundle 'b1' not found.","detail":{"bundle_id":"b1"},"request_id":"abc-1"}"""))

        val failure = failureOf { backend().call { meta() } }

        assertEquals(ApiException.Kind.HTTP, failure.kind)
        assertEquals(404, failure.httpStatus)
        assertEquals("NOT_FOUND", failure.code)
        assertEquals("Bundle 'b1' not found.", failure.message)
        assertEquals("abc-1", failure.requestId)
        assertNotNull(failure.envelope.detail)
        assertFalse(failure.isRetryable)
    }

    @Test
    fun `an error body that is not an envelope becomes HTTP status with the reason phrase`() = runTest {
        server.enqueue(MockResponse.Builder().code(502).status("HTTP/1.1 502 Bad Gateway").body("<html>bad gateway</html>").build())

        val failure = failureOf { backend().call { meta() } }

        assertEquals("HTTP_502", failure.code)
        assertEquals("Bad Gateway", failure.message)
        assertNull(failure.requestId)
        assertTrue(failure.isRetryable)
    }

    @Test
    fun `an unreachable server is a retryable network failure`() = runTest {
        val base = server.url("/api/v1/").toString()
        server.close()

        val failure = failureOf { backend(base).call { meta() } }

        assertEquals(ApiException.Kind.NETWORK, failure.kind)
        assertEquals(ApiException.NETWORK_MESSAGE, failure.message)
        assertTrue(failure.isRetryable)
    }

    @Test
    fun `an answer that cannot be read is reported as such`() = runTest {
        server.enqueue(json(200, """{"app_mode":"staging","data_source_policy":"x"}"""))

        val failure = failureOf { backend().call { meta() } }

        assertEquals(ApiException.Kind.MALFORMED, failure.kind)
        assertEquals("MALFORMED_RESPONSE", failure.code)
    }

    @Test
    fun `a build without a backend address makes no request`() = runTest {
        val failure = failureOf { backend(base = "").call { meta() } }

        assertEquals(ApiException.Kind.NOT_CONFIGURED, failure.kind)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `the base address always ends in a slash`() {
        assertEquals("http://10.0.2.2:8080/api/v1/", ApiConfig("http://10.0.2.2:8080/api/v1").baseUrl)
        assertEquals("https://ui.example/api/proxy/", ApiConfig(" https://ui.example/api/proxy/ ").baseUrl)
        assertNull(ApiConfig("  ").baseUrl)
    }

    @Test
    fun `a good answer is shared and a failure is not remembered`() = runTest {
        server.enqueue(json(503, """{"code":"UNAVAILABLE","message":"warming up"}"""))
        server.enqueue(json(200, """{"app_mode":"demo","data_source_policy":"fixtures"}"""))
        val repository = NetworkMetaRepository(backend())

        failureOf { repository.load() }
        assertEquals(AppMode.DEMO, repository.load().appMode)
        assertEquals(AppMode.DEMO, repository.load().appMode)

        assertEquals(2, server.requestCount)
    }
}
