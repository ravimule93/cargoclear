package com.cargoclear.japac.core.data.work

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class BatchFilesTest {
    @get:Rule
    val temp = TemporaryFolder()

    private val released = mutableListOf<String>()

    private fun files() = BatchFiles(temp.root.resolve("batches")) { released += it }

    @Test
    fun `a batch that ended gives back what it held, and only that`() {
        val files = files()
        files.record("bnd-1", "batch-a", listOf("content://a/1", "file:///inbox/2/x.pdf"))
        files.record("bnd-1", "batch-b", listOf("content://b/1"))

        files.finished("bnd-1", "batch-a", listOf("content://a/1", "file:///inbox/2/x.pdf"))

        assertEquals(listOf("content://a/1", "file:///inbox/2/x.pdf"), released)
    }

    @Test
    fun `the last batch of a bundle to end leaves no folder behind, one that is not the last leaves the others' records`() {
        val files = files()
        files.record("bnd-1", "a", listOf("content://a"))
        files.record("bnd-1", "b", listOf("content://b"))

        files.finished("bnd-1", "a", listOf("content://a"))
        assertEquals(listOf("b"), temp.root.resolve("batches/bnd-1").list()?.toList())

        files.finished("bnd-1", "b", listOf("content://b"))
        assertFalse(temp.root.resolve("batches/bnd-1").exists())
    }

    @Test
    fun `cancelling gives back the files of every batch that has not ended, including one that never started`() {
        val files = files()
        files.record("bnd-1", "running", listOf("content://r/1"))
        files.record("bnd-1", "queued", listOf("content://q/1", "content://q/2"))
        files.record("bnd-1", "done", listOf("content://d/1"))
        files.finished("bnd-1", "done", listOf("content://d/1"))
        released.clear()

        files.cancelled("bnd-1")

        assertEquals(setOf("content://r/1", "content://q/1", "content://q/2"), released.toSet())
        assertEquals(3, released.size)
    }

    @Test
    fun `cancelling twice gives nothing back the second time`() {
        val files = files()
        files.record("bnd-1", "queued", listOf("content://q/1"))
        files.cancelled("bnd-1")
        released.clear()
        files.cancelled("bnd-1")
        assertTrue(released.isEmpty())
    }

    @Test
    fun `a batch of another bundle is not touched`() {
        val files = files()
        files.record("bnd-1", "one", listOf("content://one"))
        files.record("bnd-2", "two", listOf("content://two"))
        files.cancelled("bnd-1")
        assertEquals(listOf("content://one"), released)
        released.clear()
        files.cancelled("bnd-2")
        assertEquals(listOf("content://two"), released)
    }

    @Test
    fun `a batch that is only stopped keeps its record`() {
        val files = files()
        files.record("bnd-1", "stopped", listOf("content://s/1"))
        // the worker was stopped (no connection, time up) and will run again: nothing calls finished, so a later cancel still finds it
        files.cancelled("bnd-1")
        assertEquals(listOf("content://s/1"), released)
    }

    @Test
    fun `an id that is not an id never becomes a path`() {
        val files = files()
        files.record("../escape", "batch", listOf("content://x"))
        files.record("bnd-1", "../escape", listOf("content://y"))
        files.cancelled("../escape")

        assertTrue(released.isEmpty())
        assertFalse(File(temp.root, "escape").exists())
        assertFalse(temp.root.resolve("batches").walkTopDown().any { it.isFile })
    }
}
