package com.cargoclear.japac.ui.intake

import app.cash.turbine.test
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.RecentBundle
import com.cargoclear.japac.core.model.Destination
import com.cargoclear.japac.core.model.Status
import com.cargoclear.japac.ui.FakeBundleRepository
import com.cargoclear.japac.ui.FakeFileImporter
import com.cargoclear.japac.ui.FakeRecents
import com.cargoclear.japac.ui.FakeUploadScheduler
import com.cargoclear.japac.ui.apiFailure
import com.cargoclear.japac.ui.bundle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** PDFs another app shared with this one: taken in once, then put in a bundle (or thrown away). */
@OptIn(ExperimentalCoroutinesApi::class)
class IntakeTest {
    private val dispatcher = StandardTestDispatcher()
    private val importer = FakeFileImporter()
    private val pending = PendingIntake(importer)
    private val bundles = FakeBundleRepository()
    private val recents = FakeRecents()
    private val uploads = FakeUploadScheduler()

    @Before
    fun setUp() = Dispatchers.setMain(dispatcher)

    @After
    fun tearDown() = Dispatchers.resetMain()

    private fun viewModel() = IntakeViewModel(pending, bundles, recents, uploads)

    private fun recent(id: String = "bnd-9", iteration: Int = 2) = RecentBundle(id, "REF", "SG", Status.MISSING_EVIDENCE, iteration, 3, 1L)

    // ---- taking the files in

    @Test
    fun `shared files are copied once and wait for a bundle`() = runTest(dispatcher) {
        pending.receive(listOf("content://mail/attachments/invoice.pdf", "content://mail/attachments/packing.pdf"))

        val waiting = checkNotNull(pending.files.value)
        assertEquals(listOf("invoice.pdf", "packing.pdf"), waiting.files.map { it.name })
        assertEquals(0, waiting.unreadable)
        assertEquals(1, importer.imports.size)
    }

    @Test
    fun `a file that cannot be read is counted, the others wait`() = runTest(dispatcher) {
        importer.unreadable += "content://mail/attachments/broken.pdf"
        pending.receive(listOf("content://mail/attachments/broken.pdf", "content://mail/attachments/ok.pdf"))

        val waiting = checkNotNull(pending.files.value)
        assertEquals(listOf("ok.pdf"), waiting.files.map { it.name })
        assertEquals(1, waiting.unreadable)
    }

    @Test
    fun `when none can be read the screen still opens, to say so`() = runTest(dispatcher) {
        importer.unreadable += "content://x/a.pdf"
        pending.receive(listOf("content://x/a.pdf"))
        val waiting = checkNotNull(pending.files.value)
        assertTrue(waiting.files.isEmpty())
        assertEquals(1, waiting.unreadable)
    }

    @Test
    fun `sharing again replaces what was waiting and deletes those copies`() = runTest(dispatcher) {
        pending.receive(listOf("content://x/first.pdf"))
        val first = checkNotNull(pending.files.value).files.single()

        pending.receive(listOf("content://x/second.pdf"))

        assertEquals(listOf("second.pdf"), checkNotNull(pending.files.value).files.map { it.name })
        assertEquals(listOf(first.uri), importer.discarded)
    }

    @Test
    fun `nothing shared means nothing waits`() = runTest(dispatcher) {
        pending.receive(emptyList())
        assertNull(pending.files.value)
        assertTrue(importer.imports.isEmpty())
    }

    // ---- choosing

    @Test
    fun `adding to a recent bundle queues the files for it and opens it`() = runTest(dispatcher) {
        pending.receive(listOf("content://x/a.pdf", "content://x/b.pdf"))
        val vm = viewModel()
        vm.opens.test {
            vm.addTo(recent("bnd-9", iteration = 2))
            runCurrent()

            assertEquals("bnd-9", awaitItem())
        }
        val (bundleId, uris, iteration) = uploads.enqueued.single()
        assertEquals("bnd-9", bundleId)
        assertEquals(2, uris.size)
        assertTrue("the queued files are the copies in the cache", uris.all { it.startsWith("file:") })
        assertEquals(2, iteration)
        assertNull("handed over, so nothing waits", pending.files.value)
        assertTrue("the upload deletes the copies, not the intake", importer.discarded.isEmpty())
    }

    @Test
    fun `backing out while the bundle is being made changes nothing, the files are on their way into it`() = runTest(dispatcher) {
        bundles.created = bundle(0, "PENDING").copy(id = "bnd-new")
        pending.receive(listOf("content://x/a.pdf"))
        val vm = viewModel()

        vm.createAndAdd()
        assertTrue(vm.state.value.busy)
        assertFalse("not let go while busy", vm.cancel())
        vm.addTo(recent("bnd-9")) // nor sent somewhere else at the same time
        assertNotNull(pending.files.value)
        assertTrue(importer.discarded.isEmpty())

        runCurrent()

        assertEquals(listOf("bnd-new"), uploads.enqueued.map { it.first })
        assertTrue("the copies went to the upload, none were thrown away", importer.discarded.isEmpty())
        assertTrue(vm.cancel())
    }

    @Test
    fun `a new bundle is made for the chosen destination, remembered, and given the files`() = runTest(dispatcher) {
        bundles.created = bundle(0, "PENDING").copy(id = "bnd-new", destinationCountry = "IN")
        pending.receive(listOf("content://x/a.pdf"))
        val vm = viewModel()
        vm.selectDestination(Destination.INDIA)
        vm.opens.test {
            vm.createAndAdd()
            assertTrue(vm.state.value.busy)
            runCurrent()

            assertEquals("bnd-new", awaitItem())
        }
        assertEquals(listOf(null to Destination.INDIA), bundles.creates)
        assertEquals("bnd-new", recents.remembered.single().first.id)
        assertEquals("bnd-new", uploads.enqueued.single().first)
        assertEquals("a new bundle has no assessment", 0, uploads.enqueued.single().third)
        assertFalse(vm.state.value.busy)
        assertNull(pending.files.value)
    }

    @Test
    fun `a bundle that cannot be created keeps the files waiting and says why`() = runTest(dispatcher) {
        bundles.createError = apiFailure(ApiException.Kind.NETWORK, message = "Can't reach the server. Check your connection and try again.")
        pending.receive(listOf("content://x/a.pdf"))
        val vm = viewModel()

        vm.createAndAdd()
        runCurrent()

        assertEquals("Can't reach the server. Check your connection and try again.", vm.state.value.error)
        assertFalse(vm.state.value.busy)
        assertNotNull("still waiting: the person can try again", pending.files.value)
        assertTrue(uploads.enqueued.isEmpty())
    }

    @Test
    fun `backing out deletes the copies`() = runTest(dispatcher) {
        pending.receive(listOf("content://x/a.pdf"))
        val copy = checkNotNull(pending.files.value).files.single()
        viewModel().cancel()
        assertNull(pending.files.value)
        assertEquals(listOf(copy.uri), importer.discarded)
    }

    @Test
    fun `with nothing waiting, choosing does nothing`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.addTo(recent())
        vm.createAndAdd()
        runCurrent()
        assertTrue(uploads.enqueued.isEmpty())
        assertTrue(bundles.creates.isEmpty())
    }

    @Test
    fun `a second tap while the bundle is being created does nothing`() = runTest(dispatcher) {
        bundles.created = bundle(0, "PENDING").copy(id = "bnd-new")
        pending.receive(listOf("content://x/a.pdf"))
        val vm = viewModel()
        vm.createAndAdd()
        vm.createAndAdd()
        runCurrent()
        assertEquals(1, bundles.creates.size)
    }
}
