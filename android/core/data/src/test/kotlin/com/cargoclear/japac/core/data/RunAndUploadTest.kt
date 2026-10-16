package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.RunState
import java.io.IOException
import java.io.InputStream
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.SocketEffect
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Run controls and uploads against a MockWebServer that answers with the payloads recorded from the demo backend. */
class RunAndUploadTest {
    private lateinit var server: MockWebServer
    private lateinit var bundles: NetworkBundleRepository
    private lateinit var documents: NetworkDocumentRepository
    private var clock = 5_000L
    private lateinit var runner: UploadBatchRunner

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        val config = ApiConfig(server.url("/api/v1/").toString())
        val backend = Backend(config, testClient())
        bundles = NetworkBundleRepository(backend, BundleStreamClient(config, testClient()))
        documents = NetworkDocumentRepository(backend)
        runner = UploadBatchRunner(documents, bundles) { clock }
    }

    @After
    fun tearDown() {
        runCatching { server.close() }
    }

    private fun json(code: Int, body: String) = MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build()

    private fun recorded(name: String) = TestResources.text(name)

    private fun pdf(name: String, text: String = "%PDF-1.4 $name") = UploadFile.of(name, text.toByteArray())

    private suspend fun failureOf(block: suspend () -> Unit): ApiException {
        try {
            block()
        } catch (e: ApiException) {
            return e
        }
        throw AssertionError("expected an ApiException")
    }

    // ---- run controls

    @Test
    fun `analyze, reassess and recompute are empty posts to their own paths and read the recorded answer`() = runTest {
        repeat(3) { server.enqueue(json(202, recorded("run_response_analyze.json"))) }

        val first = bundles.analyze("bnd-1")
        bundles.reassess("bnd-1")
        bundles.recompute("bnd-1")

        assertEquals(RunState.RUNNING, first.state)
        assertTrue(first.runId.startsWith("run-"))
        for (path in listOf("analyze", "reassess", "recompute")) {
            val request = server.takeRequest()
            assertEquals("POST", request.method)
            assertEquals("/api/v1/bundles/bnd-1/$path", request.url.encodedPath)
            assertEquals(0, request.body?.size ?: 0)
            assertNotNull(request.headers[RequestIdInterceptor.HEADER])
        }
    }

    @Test
    fun `a second run request is a conflict that carries the request id`() = runTest {
        server.enqueue(json(409, recorded("error_run_already_in_progress.json")))
        val failure = failureOf { bundles.analyze("bnd-1") }
        assertEquals("CONFLICT", failure.code)
        assertEquals(409, failure.httpStatus)
        assertNotNull(failure.requestId)
        assertFalse(failure.isRetryable)
    }

    // ---- one upload

    @Test
    fun `a file goes up as the multipart field file, with its name, a PDF type and a known length`() = runTest {
        server.enqueue(json(201, recorded("document_uploaded.json")))
        val file = pdf("Commercial Invoice.pdf", "%PDF-1.4 the bytes of the file")

        val record = documents.upload("bnd-1", file)

        assertEquals("mtc_pipe_test_cert.pdf", record.filename)
        val request = server.takeRequest()
        assertEquals("/api/v1/bundles/bnd-1/documents", request.url.encodedPath)
        assertTrue(request.headers["Content-Type"].orEmpty().startsWith("multipart/form-data; boundary="))
        assertNotNull("a declared length, not chunked", request.headers["Content-Length"])
        assertNull(request.headers["Transfer-Encoding"])
        val body = request.body!!.utf8()
        assertTrue(body, body.contains("""Content-Disposition: form-data; name="file"; filename="Commercial Invoice.pdf""""))
        assertTrue(body.contains("Content-Type: application/pdf"))
        assertTrue(body.contains("%PDF-1.4 the bytes of the file"))
    }

    @Test
    fun `a declared type goes up as a plain form field beside the file, without quotes`() = runTest {
        server.enqueue(json(201, recorded("document_uploaded_declared.json")))

        val record = documents.upload("bnd-1", pdf("cert.pdf"), "MILL_TEST_CERTIFICATE")

        assertEquals("MILL_TEST_CERTIFICATE", record.declaredType)
        val body = server.takeRequest().body!!.utf8()
        assertTrue(body, body.contains("""Content-Disposition: form-data; name="declared_type""""))
        assertTrue(body, Regex("""name="declared_type"\r\n(Content-[^\r]*\r\n)*\r\nMILL_TEST_CERTIFICATE\r\n""").containsMatchIn(body))
        assertTrue(body.contains("""name="file"; filename="cert.pdf""""))
    }

    @Test
    fun `no declared type, or a blank one, sends no such field`() = runTest {
        repeat(2) { server.enqueue(json(201, recorded("document_uploaded.json"))) }

        documents.upload("bnd-1", pdf("a.pdf"))
        documents.upload("bnd-1", pdf("b.pdf"), "  ")

        repeat(2) { assertFalse(server.takeRequest().body!!.utf8().contains("declared_type")) }
    }

    @Test
    fun `an unknown declared type is the server's 422 with the types it knows`() = runTest {
        server.enqueue(json(422, recorded("error_declared_type_unknown.json")))

        val failure = failureOf { documents.upload("bnd-1", pdf("a.pdf"), "NOT A TYPE") }

        assertEquals(422, failure.httpStatus)
        assertEquals("VALIDATION_ERROR", failure.code)
        assertTrue(failure.message.orEmpty().contains("COMMERCIAL_INVOICE"))
    }

    @Test
    fun `a file without a name is sent as document dot pdf`() = runTest {
        server.enqueue(json(201, recorded("document_uploaded.json")))
        documents.upload("bnd-1", UploadFile.of("  ", "%PDF".toByteArray()))
        assertTrue(server.takeRequest().body!!.utf8().contains("""filename="document.pdf""""))
    }

    @Test
    fun `a large file is read in blocks while it goes out, whole and once`() = runTest {
        server.enqueue(json(201, recorded("document_uploaded.json")))
        var opened = 0
        val size = 3L * 1024 * 1024 + 17
        val file = UploadFile("big.pdf", size) {
            opened += 1
            RepeatingStream(size)
        }

        documents.upload("bnd-1", file)

        assertEquals(1, opened)
        val request = server.takeRequest()
        val sent = request.body!!.size
        assertTrue("the whole file went out (plus the multipart framing)", sent > size && sent < size + 1024)
    }

    @Test
    fun `a file that cannot be opened is a local problem, not a network one`() = runTest {
        val failure = failureOf { documents.upload("bnd-1", UploadFile("gone.pdf", 10) { throw IOException("ENOENT") }) }
        assertEquals(ApiException.Kind.LOCAL_FILE, failure.kind)
        assertEquals("Could not read gone.pdf. The file may have been moved or deleted.", failure.message)
        assertFalse(failure.isRetryable)
    }

    @Test
    fun `a permission that ended is a local problem too`() = runTest {
        val failure = failureOf { documents.upload("bnd-1", UploadFile("x.pdf", 10) { throw SecurityException("grant revoked") }) }
        assertEquals(ApiException.Kind.LOCAL_FILE, failure.kind)
    }

    @Test
    fun `a file that stops being readable halfway is a local problem`() = runTest {
        val failure = failureOf {
            documents.upload("bnd-1", UploadFile("half.pdf", 200_000) {
                object : InputStream() {
                    private var left = 100_000
                    override fun read(): Int = throw IOException("card removed")
                    override fun read(b: ByteArray, off: Int, len: Int): Int {
                        if (left <= 0) throw IOException("card removed")
                        val n = minOf(len, left)
                        left -= n
                        return n
                    }
                }
            })
        }
        assertEquals(ApiException.Kind.LOCAL_FILE, failure.kind)
    }

    @Test
    fun `a source that announces the wrong size is sent again without a declared length`() = runTest {
        server.enqueue(json(201, recorded("document_uploaded.json")))
        var opened = 0
        val real = "%PDF-1.4 twelve".toByteArray()
        val file = UploadFile("drive.pdf", real.size + 500L) { opened += 1; real.inputStream() } // announces 500 bytes too many

        documents.upload("bnd-1", file)

        assertEquals("tried once with the size, once without", 2, opened)
        val request = server.takeRequest()
        assertNull("sent without a Content-Length", request.headers["Content-Length"])
        assertEquals("chunked", request.headers["Transfer-Encoding"])
        assertTrue(request.body!!.utf8().contains("%PDF-1.4 twelve"))
    }

    @Test
    fun `a source that announces too small a size is handled the same way`() = runTest {
        server.enqueue(json(201, recorded("document_uploaded.json")))
        val real = "%PDF-1.4 longer than announced".toByteArray()
        documents.upload("bnd-1", UploadFile("drive.pdf", 5) { real.inputStream() })
        assertTrue(server.takeRequest().body!!.utf8().contains("%PDF-1.4 longer than announced"))
    }

    @Test
    fun `a file whose size really is what it announced is not sent twice`() = runTest {
        server.enqueue(json(201, recorded("document_uploaded.json")))
        documents.upload("bnd-1", pdf("ok.pdf"))
        assertEquals(1, server.requestCount)
    }

    @Test
    fun `removing a document is a delete of that document, and the answer says whether the newest assessment used it`() = runTest {
        server.enqueue(json(200, recorded("document_deleted.json")))

        val removed = documents.deleteDocument("bnd-1", "doc-c9a9529cb1853d8d")

        assertEquals("case_d_packing_list.pdf", removed.filename)
        assertTrue(removed.inLatestAssessment)
        val request = server.takeRequest()
        assertEquals("DELETE", request.method)
        assertEquals("/api/v1/bundles/bnd-1/documents/doc-c9a9529cb1853d8d", request.url.encodedPath)
        assertEquals(0, request.body?.size ?: 0)
        assertNotNull(request.headers[RequestIdInterceptor.HEADER])
    }

    @Test
    fun `a removal during a run is a conflict, and a document that is not there is a 404`() = runTest {
        server.enqueue(json(409, recorded("error_document_delete_run_in_progress.json")))
        server.enqueue(json(404, recorded("error_document_delete_not_found.json")))

        val busy = failureOf { documents.deleteDocument("bnd-1", "doc-1") }
        val missing = failureOf { documents.deleteDocument("bnd-1", "doc-0000000000000000") }

        assertEquals("CONFLICT", busy.code)
        assertEquals(409, busy.httpStatus)
        assertFalse(busy.isRetryable)
        assertEquals("NOT_FOUND", missing.code)
        assertTrue(missing.isNotFound)
    }

    @Test
    fun `the sample certificate is fetched and named the way the demo extraction expects`() = runTest {
        server.enqueue(MockResponse.Builder().code(200).addHeader("Content-Type", "application/pdf").body(Buffer().write("%PDF-1.4 sample".toByteArray())).build())

        val file = documents.sampleMtc()

        assertEquals("mtc_pipe_test_cert.pdf", file.name)
        assertEquals("%PDF-1.4 sample", file.open().bufferedReader().readText())
        assertEquals(15L, file.size)
        assertEquals("/api/v1/demo/case-c/mtc", server.takeRequest().url.encodedPath)
    }

    // ---- a batch

    private fun uploadedOk() = json(201, recorded("document_uploaded.json"))

    @Test
    fun `after an assessment exists, a batch uploads each file once and asks for exactly one reassessment`() = runTest {
        server.enqueue(uploadedOk())
        server.enqueue(uploadedOk())
        server.enqueue(json(200, recorded("case_c_bundle_analyzed.json")))
        server.enqueue(json(202, recorded("run_response_analyze.json")))
        val seen = mutableListOf<Triple<Int, Int, String>>()

        val result = runner.run("bnd-1", listOf(pdf("a.pdf"), pdf("b.pdf")), currentIteration = 0) { n, total, name -> seen += Triple(n, total, name) }

        assertEquals(listOf(Triple(1, 2, "a.pdf"), Triple(2, 2, "b.pdf")), seen)
        assertEquals(2, result.outcome.uploaded)
        assertEquals(2, result.outcome.total)
        assertNotNull(result.outcome.runId)
        assertNull(result.outcome.error)
        assertEquals(5_000L, result.outcome.finishedAt)
        assertFalse(result.retryable)
        assertEquals(
            listOf("/api/v1/bundles/bnd-1/documents", "/api/v1/bundles/bnd-1/documents", "/api/v1/bundles/bnd-1", "/api/v1/bundles/bnd-1/reassess"),
            List(4) { server.takeRequest().url.encodedPath },
        )
    }

    @Test
    fun `before the first assessment a batch only uploads, the first analysis waits for the person`() = runTest {
        server.enqueue(uploadedOk())
        server.enqueue(json(200, recorded("case_c_bundle_new.json")))

        val result = runner.run("bnd-1", listOf(pdf("a.pdf")), currentIteration = 0)

        assertEquals(1, result.outcome.uploaded)
        assertNull(result.outcome.runId)
        assertNull(result.outcome.runError)
        assertEquals(2, server.requestCount)
    }

    @Test
    fun `a batch stops at the first refused file and says how far it got`() = runTest {
        server.enqueue(uploadedOk())
        server.enqueue(json(422, recorded("error_upload_not_pdf.json")))

        val result = runner.run("bnd-1", listOf(pdf("a.pdf"), pdf("notes.txt"), pdf("c.pdf")), currentIteration = 1)

        assertEquals(1, result.outcome.uploaded)
        assertEquals(3, result.outcome.total)
        assertEquals("Only PDF files are accepted. Received: text/plain", result.outcome.error?.message)
        assertNotNull(result.outcome.error?.requestId)
        assertNull("no run after a partial batch", result.outcome.runId)
        assertFalse("a refusal is not worth retrying", result.retryable)
        assertEquals("the third file was never sent", 2, server.requestCount)
    }

    @Test
    fun `a connection that fails is retryable`() = runTest {
        repeat(3) { server.enqueue(MockResponse.Builder().onRequestStart(SocketEffect.CloseSocket()).build()) } // OkHttp itself tries again before giving up
        val result = runner.run("bnd-1", listOf(pdf("a.pdf")), currentIteration = 1)
        assertEquals(0, result.outcome.uploaded)
        assertEquals(ApiException.NETWORK_MESSAGE, result.outcome.error?.message)
        assertTrue(result.retryable)
    }

    @Test
    fun `a busy server or a rate limit is retryable, a validation error is not`() = runTest {
        server.enqueue(json(429, recorded("error_rate_limited.json")))
        assertTrue(runner.run("bnd-1", listOf(pdf("a.pdf")), 1).retryable)

        server.enqueue(json(503, """{"code":"UPSTREAM_ERROR","message":"try later","detail":null}"""))
        assertTrue(runner.run("bnd-1", listOf(pdf("a.pdf")), 1).retryable)

        server.enqueue(json(422, recorded("error_upload_empty.json")))
        assertFalse(runner.run("bnd-1", listOf(pdf("a.pdf")), 1).retryable)
    }

    @Test
    fun `a page the gateway answers with a bare 413 is explained, not shown as a status line`() = runTest {
        server.enqueue(MockResponse.Builder().code(413).addHeader("Content-Type", "text/html").body("<html>Request Entity Too Large</html>").build())
        val result = runner.run("bnd-1", listOf(pdf("big.pdf")), 1)
        assertEquals("The file is too large for the server to accept.", result.outcome.error?.message)
        assertFalse(result.retryable)
    }

    @Test
    fun `a file that cannot be read stops the batch without a retry`() = runTest {
        val result = runner.run("bnd-1", listOf(UploadFile("gone.pdf", 5) { throw IOException("ENOENT") }), 1)
        assertEquals(0, result.outcome.uploaded)
        assertEquals("Could not read gone.pdf. The file may have been moved or deleted.", result.outcome.error?.message)
        assertFalse(result.retryable)
        assertEquals("nothing reached the server", 0, server.requestCount)
    }

    @Test
    fun `a reassessment that cannot start is reported as the run's problem, the files stay uploaded`() = runTest {
        server.enqueue(uploadedOk())
        server.enqueue(json(200, recorded("case_c_bundle_analyzed.json")))
        server.enqueue(json(409, recorded("error_run_already_in_progress.json")))

        val result = runner.run("bnd-1", listOf(pdf("a.pdf")), currentIteration = 1)

        assertEquals(1, result.outcome.uploaded)
        assertNull(result.outcome.error)
        assertNull(result.outcome.runId)
        assertEquals("An analysis is already running for this bundle.", result.outcome.runError?.message)
        assertFalse(result.retryable)
    }

    @Test
    fun `when the bundle cannot be read again the caller's idea of its iteration decides`() = runTest {
        server.enqueue(uploadedOk())
        server.enqueue(json(500, """{"code":"INTERNAL","message":"boom","detail":null}"""))
        server.enqueue(json(202, recorded("run_response_analyze.json")))

        val result = runner.run("bnd-1", listOf(pdf("a.pdf")), currentIteration = 2)

        assertNotNull("known to be assessed, so it reassesses", result.outcome.runId)
    }

    @Test
    fun `an empty batch does nothing`() = runTest {
        val result = runner.run("bnd-1", emptyList(), currentIteration = 3)
        assertEquals(0, result.outcome.total)
        assertEquals(0, server.requestCount)
        assertNull(result.outcome.runId)
    }
}

/** [size] bytes of a repeating pattern, produced on demand so the test never holds the file in memory. */
private class RepeatingStream(private var left: Long) : InputStream() {
    override fun read(): Int = if (left-- > 0) 0x25 else -1

    override fun read(b: ByteArray, off: Int, len: Int): Int {
        if (left <= 0) return -1
        val n = minOf(len.toLong(), left).toInt()
        b.fill(0x25, off, off + n)
        left -= n
        return n
    }
}
