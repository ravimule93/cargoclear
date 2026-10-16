package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.Destination
import com.cargoclear.japac.core.model.Status
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class BundleRepositoryTest {
    private lateinit var server: MockWebServer
    private lateinit var repository: NetworkBundleRepository

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        val config = ApiConfig(server.url("/api/v1/").toString())
        repository = NetworkBundleRepository(Backend(config, testClient()), BundleStreamClient(config, testClient()))
    }

    @After
    fun tearDown() {
        runCatching { server.close() }
    }

    private fun json(code: Int, body: String) = MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build()

    @Test
    fun `creating a bundle sends the destination and leaves a blank reference out`() = runTest {
        server.enqueue(json(200, TestResources.text("bundle_empty_created.json")))
        val created = repository.create(reference = "   ", destination = Destination.INDIA)
        assertEquals("IN", created.destinationCountry)

        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/api/v1/bundles", request.url.encodedPath)
        assertEquals("""{"destination_country":"IN"}""", request.body?.utf8())
        assertTrue(request.headers["Content-Type"].orEmpty().startsWith("application/json"))
    }

    @Test
    fun `a reference is trimmed and sent`() = runTest {
        server.enqueue(json(200, TestResources.text("bundle_empty_created.json")))
        repository.create(reference = "  SHIP-42 ", destination = Destination.SINGAPORE)
        assertEquals("""{"reference":"SHIP-42","destination_country":"SG"}""", server.takeRequest().body?.utf8())
    }

    @Test
    fun `the demo journeys call their own endpoints`() = runTest {
        server.enqueue(json(200, TestResources.text("case_c_bundle_new.json")))
        server.enqueue(json(200, TestResources.text("case_d_bundle_new.json")))
        assertEquals(3, repository.createDemo(DemoCase.CASE_C).documents.size)
        assertEquals(4, repository.createDemo(DemoCase.CASE_D).documents.size)
        assertEquals("/api/v1/demo/case-c", server.takeRequest().url.encodedPath)
        assertEquals("/api/v1/demo/case-d", server.takeRequest().url.encodedPath)
    }

    @Test
    fun `reads a bundle, its latest assessment and its iterations from the recorded payloads`() = runTest {
        server.enqueue(json(200, TestResources.text("case_c_bundle_final.json")))
        server.enqueue(json(200, TestResources.text("case_c_assessment_compliant.json")))
        server.enqueue(json(200, TestResources.text("case_c_iterations.json")))

        val bundle = repository.bundle("bnd-x")
        val assessment = repository.latestAssessment("bnd-x")
        val iterations = repository.iterations("bnd-x")

        assertEquals(2, bundle.currentIteration)
        assertEquals(Status.COMPLIANT_FOR_SUBMISSION, assessment?.statusKind)
        assertEquals(listOf(1, 2), iterations.map { it.iteration })
        assertEquals("/api/v1/bundles/bnd-x", server.takeRequest().url.encodedPath)
        assertEquals("/api/v1/bundles/bnd-x/assessment", server.takeRequest().url.encodedPath)
        assertEquals("/api/v1/bundles/bnd-x/iterations", server.takeRequest().url.encodedPath)
    }

    @Test
    fun `a bundle that was never analysed has no latest assessment, which is not an error`() = runTest {
        server.enqueue(json(404, TestResources.text("error_assessment_not_found.json")))
        assertNull(repository.latestAssessment("bnd-new"))
    }

    @Test
    fun `any other failure of the assessment call is still an error`() = runTest {
        server.enqueue(json(500, """{"code":"INTERNAL","message":"boom","request_id":"r-9"}"""))
        val failure = runCatching { repository.latestAssessment("bnd-x") }.exceptionOrNull() as ApiException
        assertEquals("INTERNAL", failure.code)
        assertEquals("r-9", failure.requestId)
    }

    @Test
    fun `an unknown bundle is a not-found failure`() = runTest {
        server.enqueue(json(404, TestResources.text("error_bundle_not_found.json")))
        val failure = assertThrows(ApiException::class.java) { kotlinx.coroutines.runBlocking { repository.bundle("bnd-nope") } }
        assertTrue(failure.isNotFound)
        assertNotNull(failure.requestId)
    }
}
