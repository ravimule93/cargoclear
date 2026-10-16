package com.cargoclear.japac.core.data.work

import java.io.FileNotFoundException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/** A file on the phone's own storage (the copies of shared and scanned PDFs) is uploaded with its real name and length. */
class UploadFileOfTest {
    @get:Rule
    val temp = TemporaryFolder()

    @Test
    fun `the name and the length are the file's, and the bytes are read when asked`() {
        val file = temp.newFile("invoice (2).pdf").apply { writeText("%PDF-1.4 abc") }

        val upload = uploadFileOf(file)

        assertEquals("invoice (2).pdf", upload.name)
        assertEquals("a declared length lets the request carry a Content-Length", 12L, upload.size)
        assertEquals("%PDF-1.4 abc", upload.open().bufferedReader().readText())
        assertEquals("it can be read again from the start", "%PDF-1.4 abc", upload.open().bufferedReader().readText())
    }

    @Test
    fun `an empty file declares no length`() {
        assertNull(uploadFileOf(temp.newFile("empty.pdf")).size)
    }

    @Test
    fun `a file that is gone fails when it is opened, as a file that cannot be read`() {
        val file = temp.newFile("gone.pdf")
        val upload = uploadFileOf(file)
        file.delete()
        assertThrows(FileNotFoundException::class.java) { upload.open() }
    }
}
