package com.cargoclear.japac

import android.content.Context
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File

/** The test assets (the recorded payloads and the sample and alignment PDFs) as files, because PdfRenderer needs a seekable file. */
object Assets {
    private val context: Context get() = InstrumentationRegistry.getInstrumentation().context

    fun file(name: String): File {
        val target = File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir, "assets-under-test/$name")
        if (!target.exists()) {
            target.parentFile?.mkdirs()
            context.assets.open(name).use { input -> target.outputStream().use { input.copyTo(it) } }
        }
        return target
    }

    fun text(name: String): String = context.assets.open(name).bufferedReader().use { it.readText() }
}
