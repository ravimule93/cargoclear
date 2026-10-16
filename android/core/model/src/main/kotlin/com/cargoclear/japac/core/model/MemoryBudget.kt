package com.cargoclear.japac.core.model

/*
 * How big a bitmap the document viewer may ask for. A phone's heap limit (what `ActivityManager.memoryClass` reports) ranges from 64 MB to
 * over 500 MB, and the viewer holds the whole page, a sharp window onto the part in view, and the page image the model saw, at the same
 * time: a number that suits a flagship runs a small phone out of memory.
 */

private const val BYTES_PER_PIXEL = 4L // ARGB_8888
private const val MEGABYTE = 1024L * 1024L

/** The most pixels one bitmap may have on any phone: twelve megapixels, 48 MB as ARGB_8888 (a phone-sized window at any zoom, never a whole page at 8x). */
const val MAX_BITMAP_PIXELS: Long = 12_000_000L

/** Below this a page is too coarse to read, so the budget never goes lower; a phone that cannot afford it fails with a message instead. */
const val MIN_BITMAP_PIXELS: Long = 2_000_000L

/** One bitmap may take a fifth of the heap: several are alive together. */
private const val HEAP_SHARE = 5L

/** The pixel budget of one bitmap on a phone whose app heap limit is [memoryClassMb] megabytes. */
fun pixelBudget(memoryClassMb: Int): Long =
    (memoryClassMb.coerceAtLeast(0).toLong() * MEGABYTE / BYTES_PER_PIXEL / HEAP_SHARE).coerceIn(MIN_BITMAP_PIXELS, MAX_BITMAP_PIXELS)

/**
 * Runs [attempt] with [pixels] and, when the phone runs out of memory doing it, again with half as many, until it works or the size would
 * fall under [MIN_BITMAP_PIXELS] (then the last failure is thrown). A render that is a little soft is better than a viewer that crashed.
 */
fun <T> shrinkingOnOutOfMemory(pixels: Long, attempt: (Long) -> T): T {
    var size = pixels
    while (true) {
        try {
            return attempt(size)
        } catch (e: OutOfMemoryError) {
            val next = size / 2
            if (next < MIN_BITMAP_PIXELS) throw e
            size = next
        }
    }
}

/** The sub-sampling factor (a power of two) that brings a [width] by [height] image within [maxPixels]. */
fun sampleSizeFor(width: Int, height: Int, maxPixels: Long): Int {
    var sample = 1
    while ((width.toLong() / sample) * (height.toLong() / sample) > maxPixels) sample *= 2
    return sample
}
