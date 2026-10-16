package com.cargoclear.japac.ui.viewer

import android.graphics.Bitmap
import com.cargoclear.japac.core.model.NormRect

/** Reading the ink of a rendered page, for tests: where the big solid block is, and how much of a box is printed on. */
object Ink {
    class Blob(val rect: NormRect, val area: Int)

    private const val DARK = 128

    private fun luma(pixel: Int): Int = ((pixel shr 16 and 0xFF) * 299 + (pixel shr 8 and 0xFF) * 587 + (pixel and 0xFF) * 114) / 1000

    /** The largest connected block of dark pixels, as a 0-1000 box (the marker of the alignment pages is a solid block; text is small beside it). */
    fun largestBlob(bitmap: Bitmap, maxWidth: Int = 600): Blob {
        val step = maxOf(1, bitmap.width / maxWidth)
        val w = bitmap.width / step
        val h = bitmap.height / step
        val pixels = IntArray(bitmap.width * bitmap.height).also { bitmap.getPixels(it, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height) }
        val dark = BooleanArray(w * h) { i -> luma(pixels[(i / w * step) * bitmap.width + (i % w * step)]) < DARK }
        val seen = BooleanArray(w * h)
        var best: Blob? = null
        val stack = IntArray(w * h)
        for (start in dark.indices) {
            if (!dark[start] || seen[start]) continue
            var sp = 0
            stack[sp++] = start
            seen[start] = true
            var area = 0
            var x0 = w; var y0 = h; var x1 = -1; var y1 = -1
            while (sp > 0) {
                val i = stack[--sp]
                val x = i % w
                val y = i / w
                area++
                if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y
                for ((nx, ny) in arrayOf(x - 1 to y, x + 1 to y, x to y - 1, x to y + 1)) {
                    if (nx !in 0 until w || ny !in 0 until h) continue
                    val n = ny * w + nx
                    if (dark[n] && !seen[n]) { seen[n] = true; stack[sp++] = n }
                }
            }
            if (best == null || area > best.area) {
                best = Blob(NormRect(x0.toDouble() / w * 1000, y0.toDouble() / h * 1000, (x1 + 1).toDouble() / w * 1000, (y1 + 1).toDouble() / h * 1000), area)
            }
        }
        return checkNotNull(best) { "no ink on the page" }
    }

    /** The share of the pixels inside [rect] (0-1000 coordinates) that are dark. */
    fun inkFraction(bitmap: Bitmap, rect: NormRect): Double {
        val x0 = (rect.xmin / 1000 * bitmap.width).toInt().coerceIn(0, bitmap.width - 1)
        val x1 = (rect.xmax / 1000 * bitmap.width).toInt().coerceIn(x0 + 1, bitmap.width)
        val y0 = (rect.ymin / 1000 * bitmap.height).toInt().coerceIn(0, bitmap.height - 1)
        val y1 = (rect.ymax / 1000 * bitmap.height).toInt().coerceIn(y0 + 1, bitmap.height)
        var dark = 0
        var total = 0
        val row = IntArray(x1 - x0)
        for (y in y0 until y1) {
            bitmap.getPixels(row, 0, row.size, x0, y, row.size, 1)
            for (p in row) { if (luma(p) < DARK) dark++; total++ }
        }
        return if (total == 0) 0.0 else dark.toDouble() / total
    }

    fun iou(a: NormRect, b: NormRect): Double {
        val ix = maxOf(0.0, minOf(a.xmax, b.xmax) - maxOf(a.xmin, b.xmin))
        val iy = maxOf(0.0, minOf(a.ymax, b.ymax) - maxOf(a.ymin, b.ymin))
        val inter = ix * iy
        val union = a.area + b.area - inter
        return if (union == 0.0) 0.0 else inter / union
    }
}
