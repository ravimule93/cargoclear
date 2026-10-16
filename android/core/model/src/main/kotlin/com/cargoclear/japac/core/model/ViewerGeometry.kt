package com.cargoclear.japac.core.model

import kotlin.math.max
import kotlin.math.min

/** A box on a page in the 0-1000 coordinates every box of the API uses: (0, 0) is the top left corner, (1000, 1000) the bottom right. */
data class NormRect(val xmin: Double, val ymin: Double, val xmax: Double, val ymax: Double) {
    val width: Double get() = xmax - xmin
    val height: Double get() = ymax - ymin
    val centerX: Double get() = (xmin + xmax) / 2
    val centerY: Double get() = (ymin + ymax) / 2

    fun contains(x: Double, y: Double): Boolean = x in xmin..xmax && y in ymin..ymax

    val area: Double get() = max(0.0, width) * max(0.0, height)
}

/** A highlight laid out on the page being viewed. */
data class PageBox(val id: String, val severity: Severity, val label: String, val rect: NormRect, val value: String? = null)

private fun BBox.rect() = NormRect(xmin, ymin, xmax, ymax)

/** The metadata of the page: new records name the original page as `sourcePage`, older ones use `page`. */
fun transformFor(page: Int, transforms: List<TransformMetadata>): TransformMetadata? =
    transforms.firstOrNull { (it.sourcePage ?: it.page) == page }

/**
 * The boxes to draw on page [page] of document [documentId] of the ORIGINAL file (the `boxes` memo of DocumentViewer.tsx): the model cited
 * them on the processed page it was shown, so each is carried back through the page's transform. Without metadata (the page was not
 * transformed) a box is where the model put it.
 */
fun boxesOnOriginalPage(highlights: List<Highlight>, documentId: String, page: Int, transforms: List<TransformMetadata>): List<PageBox> =
    highlights
        .filter { it.documentId == documentId && it.page == page }
        .map { h -> PageBox(h.id, h.severity, h.label, mapProcessedBBoxToOriginal(h.bbox, transformFor(h.page, transforms)).rect(), h.value) }

/** The same highlights exactly as cited, for drawing on "What the model saw", the processed page they were cited on. */
fun boxesOnProcessedPage(highlights: List<Highlight>, documentId: String, page: Int): List<PageBox> =
    highlights.filter { it.documentId == documentId && it.page == page }.map { PageBox(it.id, it.severity, it.label, it.bbox.rect(), it.value) }

/** What the viewer knows of the page geometry of a document: not asked yet, being asked, known (maybe to be none), or could not be learnt. */
sealed interface GeometryState {
    data object Loading : GeometryState

    /** Known: the pages' transforms. An empty list is a document that was not transformed (or has no metadata: the API answers 404), so boxes are exact. */
    data class Known(val transforms: List<TransformMetadata>) : GeometryState

    /** The metadata could not be fetched. A box cannot be placed with certainty (the page may have been turned), so none is drawn. */
    data object Unavailable : GeometryState
}

/** Whether boxes may be drawn on the original page: only when how the page was transformed is known. A wrong box is worse than none. */
fun GeometryState.allowsBoxes(): Boolean = this is GeometryState.Known

/** The note the viewer shows for a page that was straightened before the model read it. */
fun deskewNote(transform: TransformMetadata?): String? =
    if (transform?.deskewApplied == true) "straightened ${"%.1f".format(java.util.Locale.ROOT, transform.deskewDeg)}°" else null

/** Whether the page image the model was shown was kept (and can be fetched). */
fun hasModelView(transform: TransformMetadata?): Boolean = !transform?.processedUri.isNullOrEmpty()

// ---------------------------------------------------------------------------------------------------------------------------------
// zoom and pan
// ---------------------------------------------------------------------------------------------------------------------------------

/**
 * How a page sits in the viewer. Zoom 1 fits the page's width to the viewport; the page is never zoomed out below that, and never
 * panned so far that the viewport shows empty space on an axis the page fills. ([offsetX], [offsetY]) is where the page's top left corner
 * is in viewport pixels. Pure arithmetic so it is tested on the JVM; the gestures that feed it are in the UI.
 */
data class ViewTransform(val zoom: Float, val offsetX: Float, val offsetY: Float) {
    companion object {
        const val MIN_ZOOM = 1f
        const val MAX_ZOOM = 8f
        /** One step of the zoom buttons. */
        const val STEP = 1.5f
    }
}

/** A page of height/width ratio [pageAspect] in a viewport of [viewWidth] x [viewHeight] pixels. */
data class PageLayout(val viewWidth: Float, val viewHeight: Float, val pageAspect: Float) {
    /** The page's size at zoom 1: as wide as the viewport. */
    val fitWidth: Float get() = viewWidth
    val fitHeight: Float get() = viewWidth * pageAspect

    val isUsable: Boolean get() = viewWidth > 0f && viewHeight > 0f && pageAspect > 0f && pageAspect.isFinite()
}

private fun axisOffset(offset: Float, content: Float, view: Float): Float =
    if (content <= view) (view - content) / 2f else offset.coerceIn(view - content, 0f)

/** Keeps the page where it belongs: centred on an axis it does not fill, covering the viewport on one it does. */
fun ViewTransform.clamped(layout: PageLayout): ViewTransform {
    val z = zoom.coerceIn(ViewTransform.MIN_ZOOM, ViewTransform.MAX_ZOOM)
    return ViewTransform(
        zoom = z,
        offsetX = axisOffset(offsetX, layout.fitWidth * z, layout.viewWidth),
        offsetY = axisOffset(offsetY, layout.fitHeight * z, layout.viewHeight),
    )
}

/** The page fitted to the viewport's width, its top at the top of the viewport when it is taller than the viewport. */
fun initialTransform(layout: PageLayout): ViewTransform = ViewTransform(1f, 0f, 0f).clamped(layout)

fun ViewTransform.panBy(layout: PageLayout, dx: Float, dy: Float): ViewTransform =
    ViewTransform(zoom, offsetX + dx, offsetY + dy).clamped(layout)

/** Zooms by [factor] keeping the page point under ([focusX], [focusY]) where it is, as a pinch does. */
fun ViewTransform.zoomedBy(layout: PageLayout, factor: Float, focusX: Float, focusY: Float): ViewTransform {
    val target = (zoom * factor).coerceIn(ViewTransform.MIN_ZOOM, ViewTransform.MAX_ZOOM)
    val ratio = target / zoom
    return ViewTransform(target, focusX - (focusX - offsetX) * ratio, focusY - (focusY - offsetY) * ratio).clamped(layout)
}

/** Zooms the way the buttons and a double tap do: about the centre of the viewport. */
fun ViewTransform.zoomedAboutCentre(layout: PageLayout, factor: Float): ViewTransform =
    zoomedBy(layout, factor, layout.viewWidth / 2f, layout.viewHeight / 2f)

/** Shows [rect] (a page box) as large as fits with [margin] of the viewport around it, centred; the zoom never exceeds [maxZoom]. */
fun zoomToRect(layout: PageLayout, rect: NormRect, margin: Float = 0.15f, maxZoom: Float = 4f): ViewTransform {
    val boxW = (rect.width / 1000.0).toFloat() * layout.fitWidth
    val boxH = (rect.height / 1000.0).toFloat() * layout.fitHeight
    val usableW = layout.viewWidth * (1f - 2 * margin)
    val usableH = layout.viewHeight * (1f - 2 * margin)
    val wanted = if (boxW <= 0f || boxH <= 0f) 1f else min(usableW / boxW, usableH / boxH)
    val zoom = wanted.coerceIn(ViewTransform.MIN_ZOOM, min(maxZoom, ViewTransform.MAX_ZOOM))
    val centreX = (rect.centerX / 1000.0).toFloat() * layout.fitWidth * zoom
    val centreY = (rect.centerY / 1000.0).toFloat() * layout.fitHeight * zoom
    return ViewTransform(zoom, layout.viewWidth / 2f - centreX, layout.viewHeight / 2f - centreY).clamped(layout)
}

/** The page point (0-1000 coordinates) under a viewport pixel. */
fun ViewTransform.viewToPage(layout: PageLayout, x: Float, y: Float): Pair<Double, Double> =
    Pair(((x - offsetX) / (layout.fitWidth * zoom) * 1000.0), ((y - offsetY) / (layout.fitHeight * zoom) * 1000.0))

/** A page box as a rectangle of viewport pixels: (left, top, right, bottom). */
fun ViewTransform.pageToView(layout: PageLayout, rect: NormRect): FloatArray {
    val w = layout.fitWidth * zoom
    val h = layout.fitHeight * zoom
    return floatArrayOf(
        offsetX + (rect.xmin / 1000.0).toFloat() * w,
        offsetY + (rect.ymin / 1000.0).toFloat() * h,
        offsetX + (rect.xmax / 1000.0).toFloat() * w,
        offsetY + (rect.ymax / 1000.0).toFloat() * h,
    )
}

/** The part of the page in view, as a 0-1000 rectangle (used to render only what can be seen at a high zoom). */
fun ViewTransform.visiblePart(layout: PageLayout): NormRect {
    val (x0, y0) = viewToPage(layout, 0f, 0f)
    val (x1, y1) = viewToPage(layout, layout.viewWidth, layout.viewHeight)
    return NormRect(max(0.0, x0), max(0.0, y0), min(1000.0, x1), min(1000.0, y1))
}

/**
 * The box a tap lands on: of the boxes that contain the point, the smallest (the more specific evidence), else none. [slopNorm] widens each
 * box a little so a thin box can be hit with a finger.
 */
fun boxAt(boxes: List<PageBox>, pageX: Double, pageY: Double, slopNorm: Double = 0.0): PageBox? =
    boxes.filter {
        NormRect(it.rect.xmin - slopNorm, it.rect.ymin - slopNorm, it.rect.xmax + slopNorm, it.rect.ymax + slopNorm).contains(pageX, pageY)
    }.minByOrNull { it.rect.area }
