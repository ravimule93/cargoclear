package com.cargoclear.japac.ui.viewer

import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.pdf.PdfRenderer
import android.os.ParcelFileDescriptor
import com.cargoclear.japac.core.model.MAX_BITMAP_PIXELS
import com.cargoclear.japac.core.model.NormRect
import com.cargoclear.japac.core.model.shrinkingOnOutOfMemory
import java.io.File
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock
import kotlin.math.ceil
import kotlin.math.sqrt
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.withContext

/** Why a PDF could not be opened, in words for the person (the file itself is the server's, so there is nothing for them to fix here). */
class PdfUnreadableException(message: String, cause: Throwable? = null) : IOException(message, cause)

/**
 * The pages of one PDF as bitmaps. Pages are shown the way a viewer shows them: a page's own /Rotate is applied, and the boxes of the API
 * are laid over exactly that orientation (the alignment tests render real scans with PdfRenderer to check it).
 */
interface PdfPages : AutoCloseable {
    val pageCount: Int

    /** Height divided by width of the page as displayed (1-based page number). */
    suspend fun aspect(page: Int): Float

    /** The whole page, [widthPx] wide. */
    suspend fun renderPage(page: Int, widthPx: Int): Bitmap

    /** The part [region] (0-1000 page coordinates) of the page, as it looks when the whole page is [pageWidthPx] wide: a sharp window onto a zoomed page. */
    suspend fun renderRegion(page: Int, pageWidthPx: Int, region: NormRect): Bitmap
}

fun interface PdfOpener {
    /** Opens [file]; throws [PdfUnreadableException] when it is not a PDF this phone can read. */
    suspend fun open(file: File): PdfPages
}

/**
 * [PdfRenderer] allows one open page at a time and is not thread-safe, so every call takes one lock. Rendering happens off the main
 * thread, one render at a time on a thread of its own: a request that was cancelled while it waited (the person pinched on) is dropped
 * before it renders, and the waiting does not hold up the shared worker threads. A bitmap is never larger than [MAX_PIXELS] whatever the
 * zoom, because only the window in view is ever rendered at high zoom.
 */
class PdfRendererPages private constructor(
    private val descriptor: ParcelFileDescriptor,
    private val renderer: PdfRenderer,
    private val maxPixels: Long,
) : PdfPages {
    private val lock = ReentrantLock()
    private var closed = false
    private val sizes = ConcurrentHashMap<Int, Pair<Int, Int>>()

    /** The most pixels a bitmap may have here. Lowered when the phone ran out of memory at a larger size, so the renders after that do not fail first. */
    @Volatile private var cap = maxPixels

    /** How many renders actually ran (tests: a cancelled request must not be one of them). */
    internal val renders = AtomicInteger()

    override val pageCount: Int = renderer.pageCount

    private fun <T> withPage(page: Int, block: (PdfRenderer.Page) -> T): T = lock.withLock {
        check(!closed) { "the document was closed" }
        require(page in 1..pageCount) { "page $page of $pageCount" }
        renderer.openPage(page - 1).use(block)
    }

    private fun sizeOf(page: Int): Pair<Int, Int> = sizes.getOrPut(page) { withPage(page) { it.width to it.height } }

    override suspend fun aspect(page: Int): Float {
        val (w, h) = sizes[page] ?: withContext(renderThread) { lock.withLock { sizeOf(page) } }
        return h.toFloat() / w.toFloat()
    }

    override suspend fun renderPage(page: Int, widthPx: Int): Bitmap =
        renderRegion(page, widthPx, NormRect(0.0, 0.0, 1000.0, 1000.0))

    override suspend fun renderRegion(page: Int, pageWidthPx: Int, region: NormRect): Bitmap = withContext(renderThread) {
        lock.withLock {
            val (widthPt, heightPt) = sizeOf(page)
            // the whole page is pageWidthPx wide; render only [region] of it, into a bitmap exactly that big (shrunk if it would be too large for this phone)
            shrinkingOnOutOfMemory(cap) { limit ->
                var scale = pageWidthPx.toFloat() / widthPt
                var out = Size(ceil(region.width / 1000.0 * widthPt * scale).toInt().coerceAtLeast(1), ceil(region.height / 1000.0 * heightPt * scale).toInt().coerceAtLeast(1))
                if (out.pixels > limit) {
                    val shrink = sqrt(limit.toDouble() / out.pixels).toFloat()
                    scale *= shrink
                    out = Size((out.w * shrink).toInt().coerceAtLeast(1), (out.h * shrink).toInt().coerceAtLeast(1))
                }
                val bitmap = Bitmap.createBitmap(out.w, out.h, Bitmap.Config.ARGB_8888)
                cap = minOf(cap, limit) // this size fitted in memory; a larger one that did not is not asked for again
                bitmap.eraseColor(Color.WHITE) // PdfRenderer draws on what is there; a page has no background of its own
                val matrix = Matrix().apply {
                    postScale(scale, scale)
                    postTranslate(-(region.xmin / 1000.0 * widthPt * scale).toFloat(), -(region.ymin / 1000.0 * heightPt * scale).toFloat())
                }
                withPage(page) { it.render(bitmap, null, matrix, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY) }
                renders.incrementAndGet()
                bitmap
            }
        }
    }

    override fun close() {
        lock.withLock {
            if (closed) return
            closed = true
            runCatching { renderer.close() }
            runCatching { descriptor.close() }
        }
    }

    private data class Size(val w: Int, val h: Int) {
        val pixels: Long get() = w.toLong() * h
    }

    companion object {
        /** The most pixels a bitmap may have on a phone with plenty of memory; a smaller budget is chosen from the heap limit (see `pixelBudget`). */
        const val MAX_PIXELS: Long = MAX_BITMAP_PIXELS

        /** Renders wait here one at a time (see the class comment); a request cancelled while it waits is never started, because the dispatcher checks before it runs one. */
        @OptIn(ExperimentalCoroutinesApi::class)
        private val renderThread = Dispatchers.IO.limitedParallelism(1)

        suspend fun open(file: File, maxPixels: Long = MAX_PIXELS): PdfPages = withContext(Dispatchers.IO) {
            val descriptor = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
            try {
                val renderer = PdfRenderer(descriptor)
                if (renderer.pageCount == 0) {
                    renderer.close()
                    throw PdfUnreadableException("The PDF has no pages.")
                }
                PdfRendererPages(descriptor, renderer, maxPixels)
            } catch (e: SecurityException) {
                descriptor.close()
                throw PdfUnreadableException("The PDF is password protected.", e)
            } catch (e: PdfUnreadableException) {
                descriptor.close()
                throw e
            } catch (e: IOException) {
                descriptor.close()
                throw PdfUnreadableException("The file is not a PDF this phone can read.", e)
            } catch (e: RuntimeException) {
                descriptor.close()
                throw PdfUnreadableException("The file is not a PDF this phone can read.", e)
            }
        }
    }
}
