package com.cargoclear.japac.core.data.work

import android.content.Context
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import androidx.work.ListenableWorker
import androidx.work.WorkerFactory
import androidx.work.WorkerParameters
import androidx.work.testing.TestListenableWorkerBuilder
import com.cargoclear.japac.core.data.ApiConfig
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.Backend
import com.cargoclear.japac.core.data.BundleRepository
import com.cargoclear.japac.core.data.DemoCase
import com.cargoclear.japac.core.data.DocumentRepository
import com.cargoclear.japac.core.data.InboxFiles
import com.cargoclear.japac.core.data.NetworkDocumentRepository
import com.cargoclear.japac.core.data.StreamEvent
import com.cargoclear.japac.core.data.UploadBatchRunner
import com.cargoclear.japac.core.data.UploadFile
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.Bundle
import com.cargoclear.japac.core.model.Destination
import com.cargoclear.japac.core.model.DocumentDeleted
import com.cargoclear.japac.core.model.DocumentRecord
import com.cargoclear.japac.core.model.ErrorEnvelope
import com.cargoclear.japac.core.model.RunResponse
import com.cargoclear.japac.core.model.RunState
import com.cargoclear.japac.core.model.TransformMetadataResponse
import com.cargoclear.japac.core.model.UPLOAD_STOPPED_MESSAGE
import java.io.File
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The worker's glue on a device: content Uris become files, the batch runs, the outcome is written to the work's output. */
class UploadWorkerTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private val files = mutableListOf<File>()
    private lateinit var documents: RecordingDocuments
    private lateinit var bundles: RecordingBundles

    @Before
    fun setUp() {
        documents = RecordingDocuments()
        bundles = RecordingBundles()
    }

    @After
    fun tearDown() {
        files.forEach { it.delete() }
    }

    private fun pdf(name: String, text: String): String {
        val file = File(context.cacheDir, name).apply { writeText(text) }
        files += file
        return Uri.fromFile(file).toString()
    }

    private fun worker(uris: List<String>, iteration: Int, attempt: Int = 0): UploadWorker =
        TestListenableWorkerBuilder<UploadWorker>(context)
            .setInputData(UploadWork.input("bnd-1", uris, iteration))
            .setRunAttemptCount(attempt)
            .setWorkerFactory(object : WorkerFactory() {
                override fun createWorker(appContext: Context, workerClassName: String, workerParameters: WorkerParameters): ListenableWorker =
                    UploadWorker(appContext, workerParameters, UploadBatchRunner(documents, bundles) { 42L }, BatchFiles.forContext(appContext))
            })
            .build()

    @Test
    fun files_are_read_from_their_uris_uploaded_in_order_and_one_reassessment_follows() = runBlocking {
        bundles.iteration = 1
        val result = worker(listOf(pdf("first.pdf", "%PDF one"), pdf("second.pdf", "%PDF two")), iteration = 0).doWork()

        assertTrue(result is ListenableWorker.Result.Success)
        assertEquals(listOf("first.pdf" to "%PDF one", "second.pdf" to "%PDF two"), documents.uploaded)
        assertEquals(listOf("reassess"), bundles.runs)
        val outcome = UploadWork.outcome((result as ListenableWorker.Result.Success).outputData)
        assertNotNull(outcome)
        assertEquals(2, outcome!!.uploaded)
        assertEquals("run-9", outcome.runId)
        assertEquals(42L, outcome.finishedAt)
    }

    /** A copy of a file that came in from outside (shared, scanned), as the intake leaves it: in the inbox, in a folder of its own. */
    private fun inboxCopy(name: String, text: String): String = runBlocking {
        InboxFiles(InboxFiles.rootIn(context.cacheDir)).import(listOf(UploadFile.of(name, text.toByteArray()))).imported.single().uri
    }

    private fun inboxFolders() = InboxFiles.rootIn(context.cacheDir).listFiles().orEmpty().toList()

    @Test
    fun a_copy_that_came_in_from_outside_is_uploaded_under_its_name_and_deleted_when_the_batch_ends() = runBlocking {
        InboxFiles.rootIn(context.cacheDir).deleteRecursively()
        val copy = inboxCopy("shared_invoice.pdf", "%PDF shared")
        assertEquals(1, inboxFolders().size)

        val result = worker(listOf(copy), iteration = 0).doWork()

        assertTrue(result is ListenableWorker.Result.Success)
        assertEquals(listOf("shared_invoice.pdf" to "%PDF shared"), documents.uploaded)
        assertTrue("the copy is gone", inboxFolders().isEmpty())
    }

    @Test
    fun a_copy_is_deleted_when_the_batch_fails_for_good_too() = runBlocking {
        InboxFiles.rootIn(context.cacheDir).deleteRecursively()
        documents.failure = ApiException(ErrorEnvelope("VALIDATION_ERROR", "The file is not a PDF.", requestId = "req-1"), ApiException.Kind.HTTP, 422)
        val result = worker(listOf(inboxCopy("x.pdf", "nope")), iteration = 1).doWork()
        assertTrue(result is ListenableWorker.Result.Failure)
        assertTrue(inboxFolders().isEmpty())
    }

    @Test
    fun a_copy_that_came_in_from_outside_is_uploaded_with_its_length_declared() = runBlocking {
        InboxFiles.rootIn(context.cacheDir).deleteRecursively()
        worker(listOf(inboxCopy("shared_invoice.pdf", "%PDF shared")), iteration = 0).doWork()
        assertEquals(listOf<Long?>("%PDF shared".length.toLong()), documents.declaredSizes)
    }

    @Test
    fun a_batch_the_system_stops_keeps_its_copies_for_the_run_that_follows() = runBlocking {
        InboxFiles.rootIn(context.cacheDir).deleteRecursively()
        val copy = inboxCopy("x.pdf", "%PDF kept")
        documents.failure = kotlinx.coroutines.CancellationException("the connection went")

        try {
            worker(listOf(copy), iteration = 1).doWork()
            org.junit.Assert.fail("a stopped worker does not return a result")
        } catch (_: kotlinx.coroutines.CancellationException) {
        }
        assertEquals("the copy is still there for the next run", 1, inboxFolders().size)

        documents.failure = null
        assertTrue(worker(listOf(copy), iteration = 1).doWork() is ListenableWorker.Result.Success)
        assertEquals(listOf("x.pdf" to "%PDF kept"), documents.uploaded)
        assertTrue("it ended, so the copy is gone now", inboxFolders().isEmpty())
    }

    @Test
    fun something_nobody_expected_ends_the_batch_with_a_message_and_the_copy_is_deleted() = runBlocking {
        InboxFiles.rootIn(context.cacheDir).deleteRecursively()
        documents.failure = IllegalStateException("a bug")

        val result = worker(listOf(inboxCopy("x.pdf", "%PDF")), iteration = 1).doWork()

        assertTrue(result is ListenableWorker.Result.Failure)
        assertEquals(UPLOAD_STOPPED_MESSAGE, UploadWork.outcome((result as ListenableWorker.Result.Failure).outputData)?.error?.message)
        assertTrue(inboxFolders().isEmpty())
    }

    @Test
    fun a_copy_is_kept_between_attempts_because_the_next_one_needs_it() = runBlocking {
        InboxFiles.rootIn(context.cacheDir).deleteRecursively()
        documents.failure = ApiException(ErrorEnvelope("NETWORK", ApiException.NETWORK_MESSAGE), ApiException.Kind.NETWORK)
        val copy = inboxCopy("x.pdf", "%PDF")

        assertTrue(worker(listOf(copy), iteration = 1, attempt = 0).doWork() is ListenableWorker.Result.Retry)
        assertEquals("kept for the retry", 1, inboxFolders().size)

        documents.failure = null
        assertTrue(worker(listOf(copy), iteration = 1, attempt = 1).doWork() is ListenableWorker.Result.Success)
        assertTrue(inboxFolders().isEmpty())
    }

    @Test
    fun a_file_the_person_picked_is_never_deleted() = runBlocking {
        val picked = pdf("picked.pdf", "%PDF mine")
        worker(listOf(picked), iteration = 0).doWork()
        assertTrue("it is the person's file, not a copy", File(Uri.parse(picked).path!!).exists())
    }

    @Test
    fun a_refused_file_fails_the_batch_with_the_servers_reason() = runBlocking {
        documents.failure = ApiException(ErrorEnvelope("VALIDATION_ERROR", "The file is not a PDF.", requestId = "req-1"), ApiException.Kind.HTTP, 422)
        val result = worker(listOf(pdf("x.pdf", "nope")), iteration = 1).doWork()

        assertTrue(result is ListenableWorker.Result.Failure)
        val outcome = UploadWork.outcome((result as ListenableWorker.Result.Failure).outputData)
        assertEquals("The file is not a PDF.", outcome?.error?.message)
        assertEquals("req-1", outcome?.error?.requestId)
        assertTrue(bundles.runs.isEmpty())
    }

    @Test
    fun a_connection_that_fails_is_tried_again_until_the_attempts_are_used_up() = runBlocking {
        documents.failure = ApiException(ErrorEnvelope("NETWORK", ApiException.NETWORK_MESSAGE), ApiException.Kind.NETWORK)
        val uris = listOf(pdf("x.pdf", "%PDF"))

        assertTrue(worker(uris, iteration = 1, attempt = 0).doWork() is ListenableWorker.Result.Retry)
        assertTrue(worker(uris, iteration = 1, attempt = 1).doWork() is ListenableWorker.Result.Retry)
        val last = worker(uris, iteration = 1, attempt = UploadWorker.MAX_ATTEMPTS - 1).doWork()
        assertTrue(last is ListenableWorker.Result.Failure)
        assertEquals(ApiException.NETWORK_MESSAGE, UploadWork.outcome((last as ListenableWorker.Result.Failure).outputData)?.error?.message)
    }

    @Test
    fun a_file_that_is_gone_ends_the_batch_without_a_retry_and_nothing_reaches_the_server() = runBlocking {
        // the real repository, so the failure to read goes through the same mapping as in the app
        val server = MockWebServer().apply { start() }
        try {
            val config = ApiConfig(server.url("/api/v1/").toString())
            val realDocuments = NetworkDocumentRepository(Backend(config, OkHttpClient()))
            val gone = Uri.fromFile(File(context.cacheDir, "vanished.pdf")).toString()
            val result = TestListenableWorkerBuilder<UploadWorker>(context)
                .setInputData(UploadWork.input("bnd-1", listOf(gone), 1))
                .setWorkerFactory(object : WorkerFactory() {
                    override fun createWorker(appContext: Context, workerClassName: String, workerParameters: WorkerParameters): ListenableWorker =
                        UploadWorker(appContext, workerParameters, UploadBatchRunner(realDocuments, bundles), BatchFiles.forContext(appContext))
                })
                .build()
                .doWork()

            assertTrue(result is ListenableWorker.Result.Failure)
            val outcome = UploadWork.outcome((result as ListenableWorker.Result.Failure).outputData)
            assertEquals("Could not read vanished.pdf. The file may have been moved or deleted.", outcome?.error?.message)
            assertNull(outcome?.runId)
            assertEquals(0, server.requestCount)
        } finally {
            server.close()
        }
    }

    // ---- fakes

    private class RecordingDocuments : DocumentRepository {
        val uploaded = mutableListOf<Pair<String, String>>()
        val declaredSizes = mutableListOf<Long?>()
        var failure: Throwable? = null

        override suspend fun upload(bundleId: String, file: UploadFile, declaredType: String?): DocumentRecord {
            failure?.let { throw it }
            declaredSizes += file.size
            val text = file.open().bufferedReader().readText()
            uploaded += file.name to text
            return DocumentRecord("doc-${uploaded.size}", bundleId, file.name, "UNKNOWN", "gs://x", "sha", text.length.toLong(), "2026-01-01T00:00:00Z")
        }

        override suspend fun deleteDocument(bundleId: String, documentId: String): DocumentDeleted = throw UnsupportedOperationException()
        override suspend fun sampleMtc(): UploadFile = throw UnsupportedOperationException()
        override suspend fun transformMetadata(bundleId: String, documentId: String): TransformMetadataResponse? = null
    }

    private class RecordingBundles : BundleRepository {
        var iteration = 0
        val runs = mutableListOf<String>()

        override suspend fun create(reference: String?, destination: Destination): Bundle = throw UnsupportedOperationException()
        override suspend fun createDemo(case: DemoCase): Bundle = throw UnsupportedOperationException()
        override suspend fun bundle(id: String): Bundle = Bundle(id, null, "SG", "PENDING", iteration, emptyList(), "2026-01-01T00:00:00Z")
        override suspend fun latestAssessment(id: String): AssessmentIteration? = null
        override suspend fun iterations(id: String): List<AssessmentIteration> = emptyList()
        override suspend fun analyze(id: String): RunResponse = run("analyze", id)
        override suspend fun reassess(id: String): RunResponse = run("reassess", id)
        override suspend fun recompute(id: String): RunResponse = run("recompute", id)
        override fun events(id: String): Flow<StreamEvent> = emptyFlow()

        private fun run(kind: String, id: String): RunResponse {
            runs += kind
            return RunResponse("run-9", id, RunState.RUNNING)
        }
    }
}
