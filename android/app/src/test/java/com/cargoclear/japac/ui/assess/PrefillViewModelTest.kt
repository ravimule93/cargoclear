package com.cargoclear.japac.ui.assess

import androidx.lifecycle.SavedStateHandle
import app.cash.turbine.test
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.model.PrefillFormat
import com.cargoclear.japac.ui.FakePrefillFiles
import com.cargoclear.japac.ui.apiFailure
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PrefillViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val files = FakePrefillFiles()

    @Before
    fun setUp() = Dispatchers.setMain(dispatcher)

    @After
    fun tearDown() = Dispatchers.resetMain()

    private fun viewModel() = PrefillViewModel(SavedStateHandle(mapOf("bundleId" to "bnd-1")), files)

    @Test
    fun `a downloaded pack is announced once, for the share sheet`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.shares.test {
            vm.share(2, PrefillFormat.PDF)
            assertEquals(PrefillFormat.PDF, vm.state.value.busy)
            runCurrent()

            val shared = awaitItem()
            assertEquals(PrefillFormat.PDF, shared.format)
            assertEquals("prefill-bnd-1-2.pdf", shared.file.name)
            assertNull(vm.state.value.busy)
            assertEquals(listOf(Triple("bnd-1", 2, PrefillFormat.PDF)), files.downloads)
            expectNoEvents()
        }
    }

    @Test
    fun `a failed download says why and shares nothing`() = runTest(dispatcher) {
        files.error = apiFailure(ApiException.Kind.NETWORK, message = "Can't reach the server.")
        val vm = viewModel()
        vm.shares.test {
            vm.share(1, PrefillFormat.JSON)
            runCurrent()

            assertEquals("Can't reach the server.", vm.state.value.error)
            assertNull(vm.state.value.busy)
            expectNoEvents()
        }
        files.error = null
        vm.share(1, PrefillFormat.JSON)
        assertNull("a new try forgets the old failure", vm.state.value.error)
    }

    @Test
    fun `one download at a time`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.share(1, PrefillFormat.JSON)
        vm.share(1, PrefillFormat.PDF)
        runCurrent()
        assertEquals(1, files.downloads.size)
    }
}
