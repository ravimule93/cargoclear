package com.cargoclear.japac.core.model

import kotlin.coroutines.cancellation.CancellationException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class CancellationTest {
    @Test
    fun `a failure is caught like runCatching catches it`() {
        val result = runCatchingCancellable { error("boom") }
        assertTrue(result.isFailure)
        assertEquals("boom", result.exceptionOrNull()?.message)
        assertEquals(7, runCatchingCancellable { 7 }.getOrNull())
    }

    @Test
    fun `a cancellation is not a failure, it goes on`() {
        try {
            runCatchingCancellable { throw CancellationException("stop") }
            fail("the cancellation was swallowed")
        } catch (e: CancellationException) {
            assertEquals("stop", e.message)
        }
    }
}
