package com.cargoclear.japac.ui.history

import androidx.lifecycle.SavedStateHandle
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.model.AuditResponse
import com.cargoclear.japac.core.model.AuditSignature
import com.cargoclear.japac.ui.FakeAudit
import com.cargoclear.japac.ui.apiFailure
import kotlinx.coroutines.CompletableDeferred
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

@OptIn(ExperimentalCoroutinesApi::class)
class AuditViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val audit = FakeAudit()

    @Before
    fun setUp() = Dispatchers.setMain(dispatcher)

    @After
    fun tearDown() = Dispatchers.resetMain()

    private fun viewModel() = AuditViewModel(SavedStateHandle(mapOf("bundleId" to "bnd-1")), audit)

    private fun signature(status: String) = AuditSignature(status = status, configured = true, signer = "local-demo", signedSeq = 7, meaning = "m")

    @Test
    fun `the first load is a blank state until the chain arrives`() = runTest(dispatcher) {
        val vm = viewModel()
        assertTrue(vm.state.value.loading)
        assertNull(vm.state.value.audit)

        vm.load()
        runCurrent()

        assertFalse(vm.state.value.loading)
        assertEquals(audit.chain, vm.state.value.audit)
        assertNull(vm.state.value.error)
    }

    @Test
    fun `the chain stays on screen while a newer one is fetched`() = runTest(dispatcher) {
        val vm = viewModel()
        vm.load()
        runCurrent()
        val first = vm.state.value.audit

        val gate = CompletableDeferred<Unit>()
        audit.gate = gate
        vm.load()
        runCurrent()

        assertTrue(vm.state.value.loading)
        assertEquals("not blanked", first, vm.state.value.audit)
        gate.complete(Unit)
        runCurrent()
        assertFalse(vm.state.value.loading)
    }

    @Test
    fun `a failed load shows the failure, and Retry loads again`() = runTest(dispatcher) {
        audit.auditError = apiFailure(ApiException.Kind.NETWORK, message = "Can't reach the server.")
        val vm = viewModel()
        vm.load()
        runCurrent()
        assertEquals("Can't reach the server.", vm.state.value.error)
        assertFalse(vm.state.value.loading)

        audit.auditError = null
        vm.load()
        runCurrent()
        assertNull(vm.state.value.error)
        assertNotNull(vm.state.value.audit)
    }

    @Test
    fun `an older answer cannot overwrite a newer request`() = runTest(dispatcher) {
        val vm = viewModel()
        val gate = CompletableDeferred<Unit>()
        audit.chain = AuditResponse(verified = false, error = "old")
        audit.gate = gate
        vm.load() // reads "old", held at the gate
        runCurrent()
        audit.gate = null
        audit.chain = AuditResponse(verified = true)
        vm.load() // replaces it
        runCurrent()
        gate.complete(Unit)
        runCurrent()

        assertTrue(vm.state.value.audit?.verified == true)
    }

    @Test
    fun `Sign now signs the head and reads the chain again`() = runTest(dispatcher) {
        audit.chain = AuditResponse(verified = true, signature = signature("PARTIAL"))
        val vm = viewModel()
        vm.load()
        runCurrent()

        audit.chain = AuditResponse(verified = true, signature = signature("SIGNED"))
        vm.signNow()
        assertTrue(vm.state.value.signing)
        runCurrent()

        assertEquals(1, audit.signCalls)
        assertEquals(2, audit.auditCalls)
        assertFalse(vm.state.value.signing)
        assertEquals("SIGNED", vm.state.value.audit?.signature?.status)
    }

    @Test
    fun `a refused signing is reported and the chain is left as it was`() = runTest(dispatcher) {
        audit.chain = AuditResponse(verified = true, signature = signature("PARTIAL"))
        audit.signError = apiFailure(ApiException.Kind.HTTP, message = "Audit signing is not configured for this service.", code = "CONFLICT", status = 409)
        val vm = viewModel()
        vm.load()
        runCurrent()

        vm.signNow()
        runCurrent()

        assertEquals("Audit signing is not configured for this service.", vm.state.value.signError)
        assertFalse(vm.state.value.signing)
        assertEquals("PARTIAL", vm.state.value.audit?.signature?.status)
        assertEquals("the chain was not fetched again", 1, audit.auditCalls)
    }

    @Test
    fun `a second tap while signing does nothing`() = runTest(dispatcher) {
        audit.chain = AuditResponse(verified = true, signature = signature("PARTIAL"))
        val vm = viewModel()
        vm.load()
        runCurrent()

        vm.signNow()
        vm.signNow()
        runCurrent()

        assertEquals(1, audit.signCalls)
    }
}
