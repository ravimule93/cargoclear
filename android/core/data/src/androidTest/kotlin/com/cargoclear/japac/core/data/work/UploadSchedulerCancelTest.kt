package com.cargoclear.japac.core.data.work

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.testing.WorkManagerTestInitHelper
import com.cargoclear.japac.core.data.InboxFiles
import com.cargoclear.japac.core.data.UploadFile
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Cancelling the uploads of a bundle on a real WorkManager (its test build, which runs nothing until the constraints are met). */
class UploadSchedulerCancelTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private lateinit var scheduler: WorkManagerUploadScheduler
    private val inbox = InboxFiles(InboxFiles.rootIn(context.cacheDir))

    @Before
    fun setUp() {
        InboxFiles.rootIn(context.cacheDir).deleteRecursively()
        WorkManagerTestInitHelper.initializeTestWorkManager(context)
        scheduler = WorkManagerUploadScheduler(context, BatchFiles.forContext(context))
    }

    private fun copy(name: String): String = runBlocking { inbox.import(listOf(UploadFile.of(name, "%PDF $name".toByteArray()))).imported.single().uri }

    private fun copies() = InboxFiles.rootIn(context.cacheDir).listFiles().orEmpty().flatMap { it.listFiles().orEmpty().toList() }.map { it.name }.sorted()

    @Test
    fun cancelling_gives_back_the_copies_of_a_batch_that_never_started_and_of_the_one_before_it() {
        // nothing runs: the network the batches ask for is "not there" in WorkManager's test build
        scheduler.enqueue("bnd-1", listOf(copy("first.pdf")), currentIteration = 0)
        scheduler.enqueue("bnd-1", listOf(copy("queued-behind.pdf")), currentIteration = 0)
        scheduler.enqueue("bnd-2", listOf(copy("other-bundle.pdf")), currentIteration = 0)
        assertEquals(listOf("first.pdf", "other-bundle.pdf", "queued-behind.pdf"), copies())

        scheduler.cancel("bnd-1")

        assertEquals("only the other bundle's copy is left", listOf("other-bundle.pdf"), copies())
        val states = WorkManager.getInstance(context).getWorkInfosForUniqueWork(UploadWork.uniqueName("bnd-1")).get().map { it.state }
        assertTrue(states.isNotEmpty() && states.all { it == WorkInfo.State.CANCELLED })
    }
}
