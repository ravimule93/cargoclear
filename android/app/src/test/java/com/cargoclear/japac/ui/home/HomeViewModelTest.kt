package com.cargoclear.japac.ui.home

import app.cash.turbine.test
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.DemoCase
import com.cargoclear.japac.core.model.Destination
import com.cargoclear.japac.ui.FakeBundleRepository
import com.cargoclear.japac.ui.FakeRecents
import com.cargoclear.japac.ui.apiFailure
import com.cargoclear.japac.ui.bundle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class HomeViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val repo = FakeBundleRepository()
    private val recents = FakeRecents()

    @Before
    fun setUp() = Dispatchers.setMain(dispatcher)

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun `an id or a pasted workbench link opens that bundle`() = runTest(dispatcher) {
        val vm = HomeViewModel(repo, recents)
        vm.opens.test {
            vm.open("  bnd-123  ")
            vm.open("https://ui.example/workbench/bnd-456/")
            assertEquals("bnd-123", awaitItem())
            assertEquals("bnd-456", awaitItem())
        }
        assertEquals("opening makes no request: the bundle screen does the loading", 0, repo.bundleCalls)
    }

    @Test
    fun `text that is no id is refused, and the refusal goes away when the text changes`() = runTest(dispatcher) {
        val vm = HomeViewModel(repo, recents)
        keepActive(vm)
        vm.open("hello world")
        runCurrent()
        assertTrue(vm.state.value.openInvalid)
        vm.open("../etc/passwd")
        runCurrent()
        assertTrue(vm.state.value.openInvalid)

        vm.openTextChanged()
        runCurrent()
        assertFalse(vm.state.value.openInvalid)
    }

    @Test
    fun `a new empty bundle uses the chosen destination, is remembered and opened`() = runTest(dispatcher) {
        repo.created = bundle(0, "PENDING").copy(id = "bnd-new", destinationCountry = "IN")
        val vm = HomeViewModel(repo, recents)
        keepActive(vm)
        vm.selectDestination(Destination.INDIA)
        vm.opens.test {
            vm.createEmpty()
            runCurrent()
            assertEquals("bnd-new", awaitItem())
        }
        assertEquals(listOf(null to Destination.INDIA), repo.creates)
        assertEquals("bnd-new", recents.remembered.single().first.id)
        assertNull(recents.remembered.single().second)
        assertNull(vm.state.value.pending)
    }

    @Test
    fun `a demo journey asks the backend for that case`() = runTest(dispatcher) {
        repo.created = bundle(0, "PENDING", "d1").copy(id = "bnd-demo")
        val vm = HomeViewModel(repo, recents)
        keepActive(vm)
        vm.opens.test {
            vm.createDemo(DemoCase.CASE_D)
            runCurrent()
            assertEquals("bnd-demo", awaitItem())
        }
        assertEquals(listOf(DemoCase.CASE_D), repo.demos)
    }

    @Test
    fun `a failure is shown, nothing is remembered and the buttons come back`() = runTest(dispatcher) {
        repo.createError = apiFailure(ApiException.Kind.NETWORK, "Can't reach the server.")
        val vm = HomeViewModel(repo, recents)
        keepActive(vm)
        vm.createEmpty()
        runCurrent()

        assertEquals("Can't reach the server.", vm.state.value.error)
        assertNull(vm.state.value.pending)
        assertTrue(recents.remembered.isEmpty())
    }

    @Test
    fun `a second tap while a bundle is being created is ignored`() = runTest(dispatcher) {
        val vm = HomeViewModel(repo, recents)
        keepActive(vm)
        vm.createEmpty()
        vm.createEmpty()
        runCurrent()
        assertEquals(1, repo.creates.size)
    }

    @Test
    fun `the list shows what this phone has seen and forgetting removes only the local row`() = runTest(dispatcher) {
        recents.remember(bundle(1, "MISSING_EVIDENCE", "d1"), null)
        val vm = HomeViewModel(repo, recents)
        keepActive(vm)
        runCurrent()
        assertEquals(listOf("bnd-1"), vm.state.value.recents.map { it.bundleId })

        vm.forget("bnd-1")
        runCurrent()
        assertTrue(vm.state.value.recents.isEmpty())
        assertEquals("the server is never asked to delete anything", 0, repo.bundleCalls)
    }

    /** `state` is only active while somebody collects it (WhileSubscribed), as it is on screen. */
    private fun TestScope.keepActive(vm: HomeViewModel) {
        backgroundScope.launch { vm.state.collect { } }
    }
}
