package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.Bundle
import com.cargoclear.japac.core.model.Destination
import com.cargoclear.japac.core.model.DocumentDeleted
import com.cargoclear.japac.core.model.DocumentRecord
import com.cargoclear.japac.core.model.RunResponse
import com.cargoclear.japac.core.model.TransformMetadataResponse
import com.cargoclear.japac.core.model.UPLOAD_STOPPED_MESSAGE
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

/** What the batch runner does with failures nobody planned for, and with being cancelled. */
class UploadBatchRunnerFailuresTest {
    private class Documents(private val onUpload: (Int) -> Unit) : DocumentRepository {
        var calls = 0

        override suspend fun upload(bundleId: String, file: UploadFile, declaredType: String?): DocumentRecord {
            calls += 1
            onUpload(calls)
            return DocumentRecord("doc-$calls", bundleId, file.name, "UNKNOWN", "gs://x", "sha", 1, "2026-01-01T00:00:00Z")
        }

        override suspend fun deleteDocument(bundleId: String, documentId: String): DocumentDeleted = throw UnsupportedOperationException()
        override suspend fun sampleMtc(): UploadFile = throw UnsupportedOperationException()
        override suspend fun transformMetadata(bundleId: String, documentId: String): TransformMetadataResponse? = null
    }

    private class Bundles(private val onBundle: () -> Unit = {}) : BundleRepository {
        override suspend fun create(reference: String?, destination: Destination): Bundle = throw UnsupportedOperationException()
        override suspend fun createDemo(case: DemoCase): Bundle = throw UnsupportedOperationException()
        override suspend fun bundle(id: String): Bundle {
            onBundle()
            return Bundle(id, null, "SG", "PENDING", 1, emptyList(), "2026-01-01T00:00:00Z")
        }
        override suspend fun latestAssessment(id: String): AssessmentIteration? = null
        override suspend fun iterations(id: String): List<AssessmentIteration> = emptyList()
        override suspend fun analyze(id: String): RunResponse = throw UnsupportedOperationException()
        override suspend fun reassess(id: String): RunResponse = throw UnsupportedOperationException()
        override suspend fun recompute(id: String): RunResponse = throw UnsupportedOperationException()
        override fun events(id: String): Flow<StreamEvent> = emptyFlow()
    }

    private fun pdf(name: String) = UploadFile.of(name, "%PDF $name".toByteArray())

    @Test
    fun `something nobody expected ends the batch and says how far it got`() = runTest {
        val runner = UploadBatchRunner(Documents { if (it == 2) throw IllegalStateException("a bug") }, Bundles()) { 9L }

        val result = runner.run("bnd-1", listOf(pdf("a.pdf"), pdf("b.pdf"), pdf("c.pdf")), currentIteration = 1)

        assertEquals(1, result.outcome.uploaded)
        assertEquals(3, result.outcome.total)
        assertEquals(UPLOAD_STOPPED_MESSAGE, result.outcome.error?.message)
        assertEquals(9L, result.outcome.finishedAt)
        assertNull(result.outcome.runId)
        assertFalse("trying the same thing again would meet the same bug", result.retryable)
    }

    @Test
    fun `a cancellation in the middle of a file goes on, it is not an outcome`() = runTest {
        val runner = UploadBatchRunner(Documents { throw CancellationException("stopped") }, Bundles()) { 9L }
        assertThrows(CancellationException::class.java) { kotlinx.coroutines.runBlocking { runner.run("bnd-1", listOf(pdf("a.pdf")), currentIteration = 1) } }
    }

    @Test
    fun `a cancellation while the bundle is read again goes on, it does not fall back to what the screen knew`() = runTest {
        val docs = Documents { }
        val runner = UploadBatchRunner(docs, Bundles { throw CancellationException("stopped") }) { 9L }
        assertThrows(CancellationException::class.java) { kotlinx.coroutines.runBlocking { runner.run("bnd-1", listOf(pdf("a.pdf")), currentIteration = 1) } }
        assertEquals(1, docs.calls)
    }
}
