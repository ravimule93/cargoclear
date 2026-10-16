package com.cargoclear.japac.core.data

import java.io.File
import java.io.IOException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class InboxFilesTest {
    @get:Rule
    val temp = TemporaryFolder()

    private var clock = 1_000_000L
    private val root get() = temp.root.resolve("inbox")
    private fun inbox() = InboxFiles(root) { clock }

    @Test
    fun `a shared file is copied under the name it arrived with`() = runTest {
        val result = inbox().import(listOf(UploadFile.of("mtc_pipe_test_cert.pdf", "%PDF-1.4 certificate".toByteArray())))

        val copy = result.imported.single()
        assertEquals("mtc_pipe_test_cert.pdf", copy.name)
        assertEquals(20L, copy.bytes)
        assertTrue(copy.uri.startsWith("file:"))
        val file = File(java.net.URI(copy.uri))
        assertEquals("%PDF-1.4 certificate", file.readText())
        assertTrue(file.canonicalPath.startsWith(root.canonicalPath))
        assertTrue(result.unreadable.isEmpty())
    }

    @Test
    fun `several files with the same name do not overwrite each other`() = runTest {
        val result = inbox().import(listOf(UploadFile.of("scan.pdf", "one".toByteArray()), UploadFile.of("scan.pdf", "two".toByteArray())))
        assertEquals(listOf("one", "two"), result.imported.map { File(java.net.URI(it.uri)).readText() })
        assertEquals(2, result.imported.map { it.uri }.toSet().size)
    }

    @Test
    fun `a file that cannot be read is skipped and named, the others still come`() = runTest {
        val gone = UploadFile("gone.pdf", null) { throw IOException("moved") }
        val result = inbox().import(listOf(gone, UploadFile.of("ok.pdf", "ok".toByteArray())))
        assertEquals(listOf("ok.pdf"), result.imported.map { it.name })
        assertEquals(listOf("gone.pdf"), result.unreadable)
        assertEquals("no half-written folder is left for the failure", 1, root.listFiles()?.size)
    }

    @Test
    fun `an empty file is no document`() = runTest {
        val result = inbox().import(listOf(UploadFile.of("empty.pdf", ByteArray(0))))
        assertTrue(result.imported.isEmpty())
        assertEquals(listOf("empty.pdf"), result.unreadable)
    }

    @Test
    fun `a name that tries to leave the folder stays inside it`() = runTest {
        val result = inbox().import(listOf(UploadFile.of("../../etc/passwd.pdf", "x".toByteArray())))
        val file = File(java.net.URI(result.imported.single().uri))
        assertEquals("passwd.pdf", file.name)
        assertTrue(file.canonicalPath.startsWith(root.canonicalPath + File.separator))
    }

    @Test
    fun `names keep their letters of any script and lose what a file name cannot hold`() {
        assertEquals("請求書 2026.pdf", InboxFiles.safeName("請求書 2026.pdf"))
        assertEquals("a_b_c.pdf", InboxFiles.safeName("a:b*c.pdf"))
        assertEquals("hidden.pdf", InboxFiles.safeName(".hidden.pdf"))
        assertEquals("document.pdf", InboxFiles.safeName(""))
        assertEquals("document.pdf", InboxFiles.safeName("   "))
        assertEquals(100, InboxFiles.safeName("x".repeat(300)).length)
        assertEquals("invoice.pdf", InboxFiles.safeName("C:\\Users\\me\\invoice.pdf"))
    }

    @Test
    fun `a copy is deleted with its folder when its upload is over`() = runTest {
        val cache = inbox()
        val copy = cache.import(listOf(UploadFile.of("a.pdf", "a".toByteArray()))).imported.single()
        cache.discard(copy.uri)
        assertFalse(File(java.net.URI(copy.uri)).exists())
        assertTrue("and the folder", root.listFiles().isNullOrEmpty())
    }

    @Test
    fun `discarding something that is not in the inbox deletes nothing`() = runTest {
        val outside = temp.newFile("keep.pdf")
        val cache = inbox()
        cache.discard(outside.toURI().toString())
        cache.discard("content://com.example/doc/1")
        cache.discard("not a uri at all")
        cache.discard(root.resolve("../keep.pdf").toURI().toString())
        assertTrue(outside.exists())
    }

    @Test
    fun `copies nobody used for a day are removed at the next import`() = runTest {
        val cache = inbox()
        val old = cache.import(listOf(UploadFile.of("old.pdf", "old".toByteArray()))).imported.single()
        File(java.net.URI(old.uri)).parentFile!!.setLastModified(clock)
        clock += InboxFiles.MAX_AGE_MILLIS + 1
        val fresh = cache.import(listOf(UploadFile.of("new.pdf", "new".toByteArray()))).imported.single()
        assertFalse(File(java.net.URI(old.uri)).exists())
        assertTrue(File(java.net.URI(fresh.uri)).exists())
    }

    @Test
    fun `clearing removes everything`() = runTest {
        val cache = inbox()
        cache.import(listOf(UploadFile.of("a.pdf", "a".toByteArray())))
        cache.clear()
        assertFalse(root.exists())
    }
}
