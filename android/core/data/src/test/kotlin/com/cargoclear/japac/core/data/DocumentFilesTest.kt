package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.hasModelView
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
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class DocumentFilesTest {
    @get:Rule
    val temp = TemporaryFolder()

    private lateinit var server: MockWebServer
    private lateinit var backend: Backend
    private var clock = 1_000L

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        backend = Backend(ApiConfig(server.url("/api/v1/").toString()), testClient())
    }

    @After
    fun tearDown() {
        runCatching { server.close() }
    }

    private fun files(maxBytes: Long = 1_000_000) = CachedDocumentFiles(temp.root.resolve("documents"), maxBytes, backend) { clock }

    private fun bytes(size: Int, fill: Char = 'x') = MockResponse.Builder().code(200).addHeader("Content-Type", "application/pdf").body(Buffer().write(ByteArray(size) { fill.code.toByte() })).build()

    private fun json(code: Int, body: String) = MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build()

    // ---- the PDF

    @Test
    fun `a document is downloaded once and then read from the phone`() = runTest {
        server.enqueue(bytes(2048))
        val cache = files()

        val first = cache.pdf("bnd-1", "doc-1")
        val second = cache.pdf("bnd-1", "doc-1")

        assertEquals(first, second)
        assertEquals(2048L, first.length())
        assertEquals("/api/v1/bundles/bnd-1/documents/doc-1/file", server.takeRequest().url.encodedPath)
        assertEquals("the second reading needs no network", 1, server.requestCount)
        assertTrue(first.startsWith(temp.root))
    }

    @Test
    fun `a refused download leaves nothing behind and says why`() = runTest {
        server.enqueue(json(404, """{"code":"NOT_FOUND","message":"Document 'doc-1' not found in bundle 'bnd-1'.","detail":null}"""))
        val cache = files()

        val failure = runCatching { cache.pdf("bnd-1", "doc-1") }.exceptionOrNull() as ApiException

        assertTrue(failure.isNotFound)
        assertEquals(0L, cache.sizeBytes())
        assertEquals(emptyList<String>(), temp.root.walkTopDown().filter { it.isFile }.map { it.name }.toList())
    }

    @Test
    fun `a download cut off halfway is not mistaken for the document`() = runTest {
        server.enqueue(
            // body() sets the true length, so the announced one is set after it: the connection ends 4900 bytes short
            MockResponse.Builder().code(200).body(Buffer().write(ByteArray(100) { 1 })).setHeader("Content-Length", "5000")
                .onResponseEnd(SocketEffect.CloseSocket()).build(),
        )
        val cache = files()

        val failure = runCatching { cache.pdf("bnd-1", "doc-1") }.exceptionOrNull() as ApiException

        assertEquals(ApiException.Kind.NETWORK, failure.kind)
        assertEquals("no partial file stays", emptyList<String>(), temp.root.walkTopDown().filter { it.isFile }.map { it.name }.toList())

        server.enqueue(bytes(5000)) // and trying again works
        assertEquals(5000L, cache.pdf("bnd-1", "doc-1").length())
    }

    @Test
    fun `the oldest files go first when the cache is over its size, never the one just fetched`() = runTest {
        val cache = files(maxBytes = 2500)
        repeat(3) { server.enqueue(bytes(1000, 'a' + it)) }

        clock = 1_000
        val a = cache.pdf("bnd-1", "doc-a")
        clock = 2_000
        val b = cache.pdf("bnd-1", "doc-b")
        clock = 3_000
        val c = cache.pdf("bnd-1", "doc-c")

        assertFalse("the oldest was evicted", a.exists())
        assertTrue(b.exists())
        assertTrue(c.exists())
        assertEquals(2000L, cache.sizeBytes())
    }

    @Test
    fun `reading a file again makes it the newest, so a document in use is not the one that goes`() = runTest {
        val cache = files(maxBytes = 2500)
        repeat(3) { server.enqueue(bytes(1000)) }

        clock = 1_000
        val a = cache.pdf("bnd-1", "doc-a")
        clock = 2_000
        val b = cache.pdf("bnd-1", "doc-b")
        clock = 3_000
        cache.pdf("bnd-1", "doc-a") // read again: now newer than b
        clock = 4_000
        cache.pdf("bnd-1", "doc-c")

        assertTrue(a.exists())
        assertFalse(b.exists())
    }

    @Test
    fun `clearing removes everything and reports zero`() = runTest {
        val cache = files()
        server.enqueue(bytes(10))
        server.enqueue(bytes(20))
        cache.pdf("bnd-1", "doc-1")
        cache.pdf("bnd-2", "doc-2")
        assertEquals(30L, cache.sizeBytes())

        cache.clear()

        assertEquals(0L, cache.sizeBytes())
        server.enqueue(bytes(10))
        cache.pdf("bnd-1", "doc-1") // fetched again after clearing
        assertEquals(3, server.requestCount)
    }

    @Test
    fun `an id that is not a plain id never becomes a path`() = runTest {
        val cache = files()
        assertThrows(IllegalArgumentException::class.java) { kotlinx.coroutines.runBlocking { cache.pdf("bnd-1", "../../escape") } }
        assertThrows(IllegalArgumentException::class.java) { kotlinx.coroutines.runBlocking { cache.pdf("..", "doc-1") } }
        assertThrows(IllegalArgumentException::class.java) { kotlinx.coroutines.runBlocking { cache.pdf("bnd-1", "a/b") } }
        assertEquals(0, server.requestCount)
    }

    // ---- the model's page image

    @Test
    fun `a page image is kept per document, page and assessment`() = runTest {
        server.enqueue(bytes(300))
        server.enqueue(bytes(400))
        val cache = files()

        val one = cache.processedPage("bnd-1", "doc-1", page = 2, iteration = 1)
        val two = cache.processedPage("bnd-1", "doc-1", page = 2, iteration = 2)
        cache.processedPage("bnd-1", "doc-1", page = 2, iteration = 2)

        assertTrue(one != two)
        assertEquals(2, server.requestCount)
        val request = server.takeRequest()
        assertEquals("/api/v1/bundles/bnd-1/documents/doc-1/pages/2", request.url.encodedPath)
        assertEquals("1", request.url.queryParameter("iteration"))
        assertEquals("2", server.takeRequest().url.queryParameter("iteration"))
    }

    // ---- the transform metadata

    @Test
    fun `the page geometry of an analysed document is read from the recorded answer`() = runTest {
        server.enqueue(json(200, TestResources.text("transform_metadata_demo.json")))
        val repository = NetworkDocumentRepository(backend)

        val response = repository.transformMetadata("bnd-1", "doc-1")

        assertNotNull(response)
        assertTrue(hasModelView(response!!.transformMeta.single()))
        assertEquals("/api/v1/bundles/bnd-1/documents/doc-1/transform-metadata", server.takeRequest().url.encodedPath)
    }

    @Test
    fun `a document with no record of its pages has no geometry, which is not an error`() = runTest {
        server.enqueue(json(404, TestResources.text("error_transform_metadata_not_found.json")))
        assertNull(NetworkDocumentRepository(backend).transformMetadata("bnd-1", "doc-1"))
    }

    @Test
    fun `any other failure reading the geometry is raised`() = runTest {
        server.enqueue(json(500, """{"code":"INTERNAL_ERROR","message":"boom","detail":null}"""))
        val failure = runCatching { NetworkDocumentRepository(backend).transformMetadata("bnd-1", "doc-1") }.exceptionOrNull()
        assertTrue(failure is ApiException)
    }

    @Test
    fun `a download that cannot be put in place is an IO failure with no half file left`() = runTest {
        server.enqueue(bytes(512))
        val cache = files()
        // something that is not a file is in the way, so the finished download cannot take its name
        val blocker = temp.root.resolve("documents/bnd-1/doc-1.pdf").apply { mkdirs() }
        blocker.resolve("inside").writeText("x")

        assertThrows(java.io.IOException::class.java) { kotlinx.coroutines.runBlocking { cache.pdf("bnd-1", "doc-1") } }

        assertFalse(temp.root.resolve("documents/bnd-1/doc-1.pdf.part").exists())
    }
}
