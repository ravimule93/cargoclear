package com.cargoclear.japac.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BundleIdsTest {
    @Test
    fun `ids are shaped as the backend accepts them`() {
        assertTrue(isValidBundleId("bnd-e39886342936"))
        assertTrue(isValidBundleId("A"))
        assertTrue(isValidBundleId("a".repeat(64)))
        assertFalse(isValidBundleId("a".repeat(65)))
        assertFalse(isValidBundleId(""))
        assertFalse(isValidBundleId("-starts-with-dash"))
        assertFalse(isValidBundleId("has space"))
        assertFalse(isValidBundleId("../etc"))
        assertFalse(isValidBundleId("a/b"))
    }

    @Test
    fun `an id or a pasted workbench link yields the id`() {
        assertEquals("bnd-1", extractBundleId("bnd-1"))
        assertEquals("bnd-1", extractBundleId("  bnd-1\n"))
        assertEquals("bnd-1", extractBundleId("https://ui.example/workbench/bnd-1"))
        assertEquals("bnd-1", extractBundleId("https://ui.example/workbench/bnd-1/"))
        assertEquals("bnd-1", extractBundleId("http://localhost:3000/workbench/bnd-1?x=1#top"))
    }

    @Test
    fun `anything else is not an id and never reaches a URL`() {
        assertNull(extractBundleId(""))
        assertNull(extractBundleId("   "))
        assertNull(extractBundleId("https://ui.example/"))
        assertNull(extractBundleId("https://ui.example/workbench/"))
        assertNull(extractBundleId("https://ui.example/workbench/../secret"))
        assertNull(extractBundleId("hello world"))
        assertNull(extractBundleId("bnd-1/../../x"))
    }
}
