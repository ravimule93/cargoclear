package com.cargoclear.japac.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class MemoryBudgetTest {
    @Test
    fun `a roomy phone gets the full budget and no phone gets more`() {
        assertEquals(MAX_BITMAP_PIXELS, pixelBudget(512))
        assertEquals(MAX_BITMAP_PIXELS, pixelBudget(256))
        assertEquals(MAX_BITMAP_PIXELS, pixelBudget(10_000))
    }

    @Test
    fun `a smaller heap gets a proportionally smaller bitmap`() {
        assertEquals(10_066_329L, pixelBudget(192)) // 192 MB / 4 bytes / 5
        assertEquals(6_710_886L, pixelBudget(128))
        assertEquals(3_355_443L, pixelBudget(64))
    }

    @Test
    fun `the budget never goes under what a page needs to be readable`() {
        assertEquals(MIN_BITMAP_PIXELS, pixelBudget(16))
        assertEquals(MIN_BITMAP_PIXELS, pixelBudget(0))
        assertEquals(MIN_BITMAP_PIXELS, pixelBudget(-5))
    }

    @Test
    fun `the budget grows with the heap and one bitmap is never more than a fifth of it`() {
        var last = 0L
        for (mb in 16..600 step 8) {
            val budget = pixelBudget(mb)
            assertTrue(budget >= last)
            last = budget
            if (budget > MIN_BITMAP_PIXELS) assertTrue(budget * 4 * 5 <= mb.toLong() * 1024 * 1024)
        }
    }

    @Test
    fun `an allocation that works is not shrunk`() {
        val asked = mutableListOf<Long>()
        val result = shrinkingOnOutOfMemory(12_000_000L) { asked += it; "bitmap of $it" }
        assertEquals("bitmap of 12000000", result)
        assertEquals(listOf(12_000_000L), asked)
    }

    @Test
    fun `an allocation that runs out of memory is retried at half the size until it fits`() {
        val asked = mutableListOf<Long>()
        val result = shrinkingOnOutOfMemory(12_000_000L) {
            asked += it
            if (it > 4_000_000L) throw OutOfMemoryError("no room for $it")
            it
        }
        assertEquals(3_000_000L, result)
        assertEquals(listOf(12_000_000L, 6_000_000L, 3_000_000L), asked)
    }

    @Test
    fun `when even the smallest size does not fit the failure is thrown`() {
        val asked = mutableListOf<Long>()
        val failure = assertThrows(OutOfMemoryError::class.java) {
            shrinkingOnOutOfMemory(8_000_000L) { asked += it; throw OutOfMemoryError("never") }
        }
        assertEquals("never", failure.message)
        assertEquals("it stops before going under the readable minimum", listOf(8_000_000L, 4_000_000L, 2_000_000L), asked)
    }

    @Test
    fun `other failures are not mistaken for running out of memory`() {
        var tries = 0
        assertThrows(IllegalStateException::class.java) { shrinkingOnOutOfMemory(12_000_000L) { tries++; error("closed") } }
        assertEquals(1, tries)
    }

    @Test
    fun `an image is sub-sampled by powers of two until it fits`() {
        assertEquals(1, sampleSizeFor(1240, 1754, 12_000_000L))
        assertEquals(2, sampleSizeFor(4000, 6000, 12_000_000L)) // 24 MP: half each side is 6 MP
        assertEquals(4, sampleSizeFor(8000, 8000, 12_000_000L)) // 64 MP: a quarter each side is 4 MP
        assertEquals(1, sampleSizeFor(3464, 3464, 12_000_000L)) // 11.99 MP: just fits
    }
}
