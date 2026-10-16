package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.CorrectionKind
import com.cargoclear.japac.core.model.CorrectionRequest
import com.cargoclear.japac.core.model.PrefillFormat
import com.cargoclear.japac.core.model.SignatureStatus
import com.cargoclear.japac.core.model.readCell
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/** Corrections, the audit chain and the pre-fill download against a MockWebServer that answers with what the demo backend really sent. */
class CorrectionsAndAuditTest {
    @get:Rule
    val temp = TemporaryFolder()

    private lateinit var server: MockWebServer
    private lateinit var backend: Backend
    private lateinit var corrections: NetworkCorrectionRepository
    private lateinit var audit: NetworkAuditRepository

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        backend = Backend(ApiConfig(server.url("/api/v1/").toString()), testClient())
        corrections = NetworkCorrectionRepository(backend)
        audit = NetworkAuditRepository(backend)
    }

    @After
    fun tearDown() {
        runCatching { server.close() }
    }

    private fun json(code: Int, body: String) = MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build()

    private fun recorded(name: String) = TestResources.text(name)

    private suspend fun failureOf(block: suspend () -> Unit): ApiException {
        try {
            block()
        } catch (e: ApiException) {
            return e
        }
        throw AssertionError("expected an ApiException")
    }

    // ---- corrections

    @Test
    fun `the correction list and the extraction are read from their own paths`() = runTest {
        server.enqueue(json(200, recorded("case_d_corrections_pending.json")))
        server.enqueue(json(200, recorded("case_d_extractions_recomputed.json")))

        val list = corrections.corrections("bnd-1")
        val docs = corrections.extractions("bnd-1", iteration = 2)

        assertEquals(2, list.pending)
        assertEquals(listOf(CorrectionKind.CORRECTION, CorrectionKind.CONFIRMATION), list.effective.map { it.kind })
        val request = server.takeRequest()
        assertEquals("GET", request.method)
        assertEquals("/api/v1/bundles/bnd-1/corrections", request.url.encodedPath)
        val extraction = server.takeRequest()
        assertEquals("/api/v1/bundles/bnd-1/extractions", extraction.url.encodedPath)
        assertEquals("2", extraction.url.queryParameter("iteration"))

        val cert = docs.single { it["doc_type"]?.jsonPrimitive?.content == "MILL_TEST_CERTIFICATE" }["document_id"]!!.jsonPrimitive.content
        assertEquals("0.28", readCell(docs, cert, "test_results[20]")?.value)
    }

    @Test
    fun `a correction is posted as json under the backend's field names, and the record comes back`() = runTest {
        server.enqueue(json(201, recorded("correction_created.json")))

        val record = corrections.submit("bnd-1", CorrectionRequest("doc-f74c9c3e83f32ccc", "test_results[20]", value = "0.28", unit = "%", reason = "the certificate prints 0.28"))

        assertEquals("cor-9", record.correctionId)
        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/api/v1/bundles/bnd-1/corrections", request.url.encodedPath)
        assertTrue(request.headers["Content-Type"].orEmpty().startsWith("application/json"))
        val body = Json.parseToJsonElement(request.body!!.utf8()).jsonObject
        assertEquals("doc-f74c9c3e83f32ccc", body.getValue("document_id").jsonPrimitive.content)
        assertEquals("test_results[20]", body.getValue("path").jsonPrimitive.content)
        assertEquals("0.28", body.getValue("value").jsonPrimitive.content)
        assertEquals("%", body.getValue("unit").jsonPrimitive.content)
        assertNotNull(request.headers[RequestIdInterceptor.HEADER])
    }

    @Test
    fun `clearing a value sends clear true and no value`() = runTest {
        server.enqueue(json(201, recorded("correction_created.json")))
        corrections.submit("bnd-1", CorrectionRequest("doc-1", "incoterm", clear = true))
        val body = Json.parseToJsonElement(server.takeRequest().body!!.utf8()).jsonObject
        assertEquals("true", body.getValue("clear").jsonPrimitive.content)
        assertFalse("value" in body)
    }

    @Test
    fun `an undo posts to the correction's revert path with an empty reason`() = runTest {
        server.enqueue(json(201, recorded("correction_reverted.json")))

        val record = corrections.revert("bnd-1", "cor-9")

        assertEquals(CorrectionKind.REVERT, record.kind)
        assertEquals("cor-9", record.reverts)
        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/api/v1/bundles/bnd-1/corrections/cor-9/revert", request.url.encodedPath)
        assertTrue("a body is sent: the backend's route reads an optional one", request.body != null)
    }

    @Test
    fun `the backend's refusals reach the editor in the backend's own words`() = runTest {
        server.enqueue(json(409, recorded("error_correction_before_analysis.json")))
        server.enqueue(json(404, recorded("error_correction_unknown_document.json")))
        server.enqueue(json(422, recorded("error_correction_unreadable_value.json")))
        server.enqueue(json(404, recorded("error_revert_not_in_force.json")))

        val before = failureOf { corrections.submit("b", CorrectionRequest("d", "consignee", value = "x")) }
        assertEquals("CONFLICT", before.code)
        assertEquals(409, before.httpStatus)

        val unknown = failureOf { corrections.submit("b", CorrectionRequest("doc-nope", "consignee", value = "x")) }
        assertTrue(unknown.isNotFound)
        assertTrue(unknown.message.orEmpty().contains("not part of the latest assessment"))
        assertNotNull(unknown.requestId)

        val unreadable = failureOf { corrections.submit("b", CorrectionRequest("d", "total_gross_weight_kg", value = "1,234.5.6", unit = "KGS")) }
        assertEquals("VALIDATION_ERROR", unreadable.code)
        assertEquals("'1,234.5.6' is not a number.", unreadable.message)

        val gone = failureOf { corrections.revert("b", "cor-999") }
        assertTrue(gone.isNotFound)
    }

    @Test
    fun `without a connection the failure says so and can be retried`() = runTest {
        server.close()
        val failure = failureOf { corrections.submit("b", CorrectionRequest("d", "consignee", value = "x")) }
        assertEquals(ApiException.Kind.NETWORK, failure.kind)
        assertTrue(failure.isRetryable)
    }

    // ---- the audit chain

    @Test
    fun `the audit chain and the signature come from the audit path`() = runTest {
        server.enqueue(json(200, recorded("case_d_audit_partial.json")))
        val chain = audit.audit("bnd-1")
        assertTrue(chain.verified)
        assertEquals(SignatureStatus.PARTIAL, chain.signature?.statusKind)
        val request = server.takeRequest()
        assertEquals("GET", request.method)
        assertEquals("/api/v1/bundles/bnd-1/audit", request.url.encodedPath)
    }

    @Test
    fun `Sign now is an empty post and answers the new signature`() = runTest {
        server.enqueue(json(200, recorded("audit_sign_response.json")))
        val signature = audit.signHead("bnd-1")
        assertEquals(SignatureStatus.SIGNED, signature.statusKind)
        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/api/v1/bundles/bnd-1/audit/sign", request.url.encodedPath)
        assertEquals(0, request.body?.size ?: 0)
    }

    @Test
    fun `a chain that cannot be signed says why`() = runTest {
        server.enqueue(json(409, """{"code":"CONFLICT","message":"Audit signing is not configured for this service.","detail":{"bundle_id":"bnd-1"},"request_id":"r-1"}"""))
        val failure = failureOf { audit.signHead("bnd-1") }
        assertEquals("Audit signing is not configured for this service.", failure.message)
        assertEquals("r-1", failure.requestId)
    }

    // ---- the pre-fill files

    private fun files(keep: Int = 10) = CachedPrefillFiles(temp.root.resolve("prefill"), backend, keep)

    private fun bytes(content: ByteArray, type: String) = MockResponse.Builder().code(200).addHeader("Content-Type", type).body(Buffer().write(content)).build()

    @Test
    fun `the JSON pack is downloaded to a file named as the web names it`() = runTest {
        val pack = recorded("case_d_prefill.json")
        server.enqueue(bytes(pack.toByteArray(), "application/json"))

        val file = files().download("bnd-ed45cfcc6224", 2, PrefillFormat.JSON)

        assertEquals("cargoclear-prefill-bnd-ed45cfcc6224-assessment2.json", file.name)
        assertEquals(pack, file.readText())
        val request = server.takeRequest()
        assertEquals("/api/v1/bundles/bnd-ed45cfcc6224/prefill", request.url.encodedPath)
        assertEquals("2", request.url.queryParameter("iteration"))
        assertEquals("true", request.url.queryParameter("download"))
        assertTrue(file.startsWith(temp.root))
    }

    @Test
    fun `the PDF summary arrives byte for byte`() = runTest {
        val pdf = checkNotNull(TestResources::class.java.classLoader.getResourceAsStream("case_d_prefill.pdf")).use { it.readBytes() }
        server.enqueue(bytes(pdf, "application/pdf"))

        val file = files().download("bnd-1", 2, PrefillFormat.PDF)

        assertEquals("cargoclear-prefill-bnd-1-assessment2.pdf", file.name)
        assertTrue(file.readBytes().contentEquals(pdf))
        assertEquals("%PDF", String(file.readBytes().copyOf(4)))
        assertEquals("/api/v1/bundles/bnd-1/prefill.pdf", server.takeRequest().url.encodedPath)
    }

    @Test
    fun `a pack is fetched again each time, because it names the audit head it was made at`() = runTest {
        server.enqueue(bytes("one".toByteArray(), "application/json"))
        server.enqueue(bytes("two".toByteArray(), "application/json"))
        val cache = files()
        cache.download("bnd-1", 2, PrefillFormat.JSON)
        val again = cache.download("bnd-1", 2, PrefillFormat.JSON)
        assertEquals("two", again.readText())
        assertEquals(2, server.requestCount)
    }

    @Test
    fun `a failed download leaves no file behind and the error says what the server said`() = runTest {
        server.enqueue(json(404, """{"code":"NOT_FOUND","message":"Bundle 'bnd-1' not found.","detail":null,"request_id":"r-2"}"""))
        val cache = files()
        val failure = failureOf { cache.download("bnd-1", 1, PrefillFormat.PDF) }
        assertTrue(failure.isNotFound)
        assertEquals(0L, cache.sizeBytes())
    }

    @Test
    fun `only the newest files are kept, and clearing removes them all`() = runTest {
        val cache = files(keep = 2)
        var clock = 1_000L
        for (iteration in 1..4) {
            server.enqueue(bytes("pack $iteration".toByteArray(), "application/json"))
            cache.download("bnd-1", iteration, PrefillFormat.JSON).setLastModified(clock++ * 1000)
        }
        val kept = temp.root.resolve("prefill").listFiles().orEmpty().map { it.name }.sorted()
        assertEquals(listOf("cargoclear-prefill-bnd-1-assessment3.json", "cargoclear-prefill-bnd-1-assessment4.json"), kept)

        cache.clear()
        assertEquals(0L, cache.sizeBytes())
        assertNull(temp.root.resolve("prefill").listFiles())
    }

    @Test
    fun `an id that is not a plain id never becomes part of a path`() = runTest {
        val cache = files()
        val refused = runCatching { cache.download("../etc", 1, PrefillFormat.JSON) }.exceptionOrNull()
        assertTrue(refused is IllegalArgumentException)
        assertEquals(0, server.requestCount)
    }
}
