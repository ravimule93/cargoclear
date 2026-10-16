package com.cargoclear.japac.ui.viewer

import android.content.ComponentCallbacks2
import android.content.res.Configuration
import android.graphics.Bitmap
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.cargoclear.japac.core.model.NormRect
import com.cargoclear.japac.core.model.PageBox
import com.cargoclear.japac.core.model.PageLayout
import com.cargoclear.japac.core.model.Severity
import com.cargoclear.japac.core.model.ViewMode
import com.cargoclear.japac.core.model.ViewTransform
import com.cargoclear.japac.core.model.ViewerState
import com.cargoclear.japac.core.model.boxAt
import com.cargoclear.japac.core.model.clamped
import com.cargoclear.japac.core.model.initialTransform
import com.cargoclear.japac.core.model.pageToView
import com.cargoclear.japac.core.model.panBy
import com.cargoclear.japac.core.model.runCatchingCancellable
import com.cargoclear.japac.core.model.viewToPage
import com.cargoclear.japac.core.model.visiblePart
import com.cargoclear.japac.core.model.zoomToRect
import com.cargoclear.japac.core.model.zoomedAboutCentre
import com.cargoclear.japac.core.model.zoomedBy
import com.cargoclear.japac.ui.theme.CargoClearColors
import com.cargoclear.japac.ui.theme.cargo
import androidx.compose.material3.MaterialTheme
import kotlin.math.max
import kotlin.math.min
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.collectLatest

/** Where a page sits in the viewport, shared between the surface that draws it and the buttons that move it. A new one per page, so each page opens fitted. */
@Stable
class ViewportState {
    var layout by mutableStateOf<PageLayout?>(null)
        private set
    var transform by mutableStateOf(ViewTransform(1f, 0f, 0f))
        private set

    fun onLayout(next: PageLayout) {
        val previous = layout
        layout = next
        transform = if (previous == null || previous.pageAspect != next.pageAspect) initialTransform(next) else transform.clamped(next)
    }

    fun gesture(centroid: Offset, pan: Offset, zoom: Float) {
        val l = layout ?: return
        transform = transform.zoomedBy(l, zoom, centroid.x, centroid.y).panBy(l, pan.x, pan.y)
    }

    fun zoomIn() {
        val l = layout ?: return
        transform = transform.zoomedAboutCentre(l, ViewTransform.STEP)
    }

    fun zoomOut() {
        val l = layout ?: return
        transform = transform.zoomedAboutCentre(l, 1f / ViewTransform.STEP)
    }

    fun fit() {
        val l = layout ?: return
        transform = initialTransform(l)
    }

    /** A double tap: back to fit when zoomed in, else in on the spot that was tapped. */
    fun doubleTap(at: Offset) {
        val l = layout ?: return
        transform = if (transform.zoom > 1.2f) initialTransform(l) else transform.zoomedBy(l, DOUBLE_TAP_ZOOM, at.x, at.y)
    }

    fun focusOn(rect: NormRect) {
        val l = layout ?: return
        transform = zoomToRect(l, rect)
    }

    private companion object {
        const val DOUBLE_TAP_ZOOM = 2.5f
    }
}

/** Whether the screen is showing (started, not stopped): false while the app is in the background or another screen covers it. */
@Composable
private fun rememberVisibility(): Boolean {
    val owner = LocalLifecycleOwner.current
    var visible by remember(owner) { mutableStateOf(owner.lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) }
    DisposableEffect(owner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> visible = true
                Lifecycle.Event.ON_STOP -> visible = false
                else -> Unit
            }
        }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer) }
    }
    return visible
}

/** A sharper rendering of the part of the page in view, laid over the whole-page one while zoomed in. */
private class Detail(val bitmap: Bitmap, val region: NormRect)

/**
 * One page drawn on a canvas: the page as bitmaps (the whole page for panning, a sharp window onto the part in view when zoomed), the
 * evidence boxes over it, and pinch, drag, double tap and tap-a-box on top. Boxes are drawn here, not rendered into the bitmap, so their
 * lines stay crisp and the same width at every zoom.
 */
@OptIn(FlowPreview::class)
@Composable
fun PageSurface(
    pages: PdfPages?,
    modelImage: Bitmap?,
    state: ViewerState,
    viewport: ViewportState,
    description: String,
    onTapBox: (String?) -> Unit,
    modifier: Modifier = Modifier,
) {
    val tokens = MaterialTheme.cargo
    val density = LocalDensity.current
    val mode = state.mode
    val page = state.page
    var viewSize by remember { mutableStateOf(IntSize.Zero) }

    // Memory: the page bitmaps are let go while the screen is not showing (the first thing a system short of memory wants back), and drawn again
    // when it returns; a trim signal while the screen is up drops the sharp window, which is the biggest of them and is drawn again on the next move.
    val visible = rememberVisibility()
    var trimmed by remember { mutableStateOf(0) }
    val context = LocalContext.current
    DisposableEffect(context) {
        val callbacks = object : ComponentCallbacks2 {
            override fun onTrimMemory(level: Int) {
                if (level >= ComponentCallbacks2.TRIM_MEMORY_RUNNING_LOW) trimmed++
            }

            override fun onConfigurationChanged(newConfig: Configuration) = Unit

            @Deprecated("replaced by onTrimMemory")
            override fun onLowMemory() {
                trimmed++
            }
        }
        context.registerComponentCallbacks(callbacks)
        onDispose { context.unregisterComponentCallbacks(callbacks) }
    }

    val aspect by produceState<Float?>(null, pages, page, mode, modelImage) {
        value = when (mode) {
            ViewMode.MODEL_VIEW -> modelImage?.let { it.height.toFloat() / it.width }
            ViewMode.ORIGINAL -> pages?.let { runCatchingCancellable { it.aspect(page) }.getOrNull() }
        }
    }
    val whole by produceState<Bitmap?>(null, pages, page, mode, modelImage, viewSize.width, visible) {
        value = when {
            !visible -> null
            mode == ViewMode.MODEL_VIEW -> modelImage
            pages == null || viewSize.width <= 0 -> null
            else -> runCatchingCancellable { pages.renderPage(page, viewSize.width) }.getOrNull()
        }
    }
    LaunchedEffect(viewSize, aspect) {
        val a = aspect
        if (a != null && viewSize.width > 0 && viewSize.height > 0) viewport.onLayout(PageLayout(viewSize.width.toFloat(), viewSize.height.toFloat(), a))
    }

    // Zoomed in, the whole-page bitmap is soft: once the gesture settles, render just the window in view (with a margin so a small pan stays sharp).
    var detail by remember(pages, page, mode) { mutableStateOf<Detail?>(null) }
    LaunchedEffect(trimmed) { if (trimmed > 0) detail = null }
    LaunchedEffect(pages, page, mode, visible) {
        if (!visible) {
            detail = null
            return@LaunchedEffect
        }
        if (mode != ViewMode.ORIGINAL || pages == null) return@LaunchedEffect
        snapshotFlow { viewport.transform to viewport.layout }.debounce(DETAIL_SETTLE_MILLIS).collectLatest { (t, layout) ->
            if (layout == null || t.zoom < DETAIL_MIN_ZOOM) {
                detail = null
                return@collectLatest
            }
            val visible = t.visiblePart(layout)
            val mx = visible.width * DETAIL_MARGIN
            val my = visible.height * DETAIL_MARGIN
            val region = NormRect(max(0.0, visible.xmin - mx), max(0.0, visible.ymin - my), min(1000.0, visible.xmax + mx), min(1000.0, visible.ymax + my))
            val bitmap = runCatchingCancellable { pages.renderRegion(page, (layout.fitWidth * t.zoom).toInt(), region) }.getOrNull()
            if (bitmap != null) detail = Detail(bitmap, region)
        }
    }

    val boxes = rememberUpdatedState(state.boxes)
    val onTap = rememberUpdatedState(onTapBox)
    val selected = state.selectedBoxId
    val shownDetail = detail

    Canvas(
        modifier
            .fillMaxSize()
            .clipToBounds() // the page is drawn larger than the viewport when zoomed in; it must not paint over the controls around it
            .onSizeChanged { viewSize = it }
            .semantics {
                contentDescription = description
                customActions = listOf(
                    CustomAccessibilityAction("Zoom in") { viewport.zoomIn(); true },
                    CustomAccessibilityAction("Zoom out") { viewport.zoomOut(); true },
                    CustomAccessibilityAction("Fit page to screen") { viewport.fit(); true },
                )
            }
            .pointerInput(viewport) {
                detectTransformGestures { centroid, pan, zoom, _ -> viewport.gesture(centroid, pan, zoom) }
            }
            .pointerInput(viewport) {
                detectTapGestures(
                    onDoubleTap = { viewport.doubleTap(it) },
                    onTap = { at ->
                        val layout = viewport.layout ?: return@detectTapGestures
                        val t = viewport.transform
                        val (px, py) = t.viewToPage(layout, at.x, at.y)
                        val slop = TAP_SLOP_DP * density.density / (layout.fitWidth * t.zoom) * 1000.0
                        onTap.value(boxAt(boxes.value, px, py, slop)?.id)
                    },
                )
            },
    ) {
        val layout = viewport.layout ?: return@Canvas
        val t = viewport.transform
        val pageRect = t.pageToView(layout, NormRect(0.0, 0.0, 1000.0, 1000.0))
        val pageTopLeft = Offset(pageRect[0], pageRect[1])
        val pageSize = Size(pageRect[2] - pageRect[0], pageRect[3] - pageRect[1])

        drawRect(tokens.surface2)
        drawRect(Color.White, pageTopLeft, pageSize)
        clipRect {
            whole?.let { drawBitmap(it, pageTopLeft, pageSize, FilterQuality.Medium) }
            shownDetail?.let {
                val r = t.pageToView(layout, it.region)
                drawBitmap(it.bitmap, Offset(r[0], r[1]), Size(r[2] - r[0], r[3] - r[1]), FilterQuality.Medium)
            }
            val strokePx = BOX_STROKE_DP * density.density
            for (box in state.boxes) {
                val r = t.pageToView(layout, box.rect)
                drawBox(box, r, selected = box.id == selected, tokens = tokens, strokePx = strokePx)
            }
        }
    }
}

private fun DrawScope.drawBitmap(bitmap: Bitmap, topLeft: Offset, size: Size, quality: FilterQuality) {
    drawImage(
        image = bitmap.asImageBitmap(),
        dstOffset = IntOffset(topLeft.x.toInt(), topLeft.y.toInt()),
        dstSize = IntSize(max(1, size.width.toInt()), max(1, size.height.toInt())),
        filterQuality = quality,
    )
}

private fun DrawScope.drawBox(box: PageBox, r: FloatArray, selected: Boolean, tokens: CargoClearColors, strokePx: Float) {
    val colors = when (box.severity) {
        Severity.PASS -> tokens.ok
        Severity.WARN -> tokens.warn
        Severity.MATERIAL -> tokens.err
    }
    // colour is never the only cue: a material finding is a solid line, a warning dashed, a passed check dotted
    val pattern = when (box.severity) {
        Severity.MATERIAL -> null
        Severity.WARN -> PathEffect.dashPathEffect(floatArrayOf(strokePx * 4, strokePx * 2.5f))
        Severity.PASS -> PathEffect.dashPathEffect(floatArrayOf(strokePx * 0.5f, strokePx * 2.5f))
    }
    val topLeft = Offset(r[0], r[1])
    val size = Size(max(r[2] - r[0], strokePx * 3), max(r[3] - r[1], strokePx * 3))
    if (selected) drawRect(colors.bd.copy(alpha = 0.18f), topLeft, size)
    drawRect(
        color = colors.bd,
        topLeft = topLeft,
        size = size,
        style = Stroke(width = if (selected) strokePx * 2 else strokePx, cap = if (box.severity == Severity.PASS) StrokeCap.Round else StrokeCap.Butt, pathEffect = pattern),
    )
}

private const val DETAIL_SETTLE_MILLIS = 180L
private const val DETAIL_MIN_ZOOM = 1.05f
private const val DETAIL_MARGIN = 0.12
private const val BOX_STROKE_DP = 2f
private const val TAP_SLOP_DP = 20f
