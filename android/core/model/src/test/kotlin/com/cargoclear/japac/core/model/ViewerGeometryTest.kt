package com.cargoclear.japac.core.model

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private val CASES = listOf("clean", "skew5", "skew-8", "sideways90-skew4", "sideways270-skew4", "sideways180", "pdf-rotate90")

private fun rect(o: JsonObject) = NormRect(
    o.getValue("xmin").jsonPrimitive.content.toDouble(), o.getValue("ymin").jsonPrimitive.content.toDouble(),
    o.getValue("xmax").jsonPrimitive.content.toDouble(), o.getValue("ymax").jsonPrimitive.content.toDouble(),
)

private fun iou(a: NormRect, b: NormRect): Double {
    val ix = maxOf(0.0, minOf(a.xmax, b.xmax) - maxOf(a.xmin, b.xmin))
    val iy = maxOf(0.0, minOf(a.ymax, b.ymax) - maxOf(a.ymin, b.ymin))
    val inter = ix * iy
    val union = a.area + b.area - inter
    return if (union == 0.0) 0.0 else inter / union
}

/** The geometry the viewer must get right, against what the backend's real preprocessing recorded (android/tools/make_alignment_fixtures.py). */
class AlignmentFixtureTest {
    private fun load(case: String) = Json.parseToJsonElement(Fixtures.text("viewer/$case.json")).jsonObject

    @Test
    fun `the fixtures decode as the transform metadata the API sends`() {
        for (case in CASES) {
            val response = Fixtures.parse<TransformMetadataResponse>(load(case).getValue("transform_metadata").toString())
            assertEquals(1, response.transformMeta.size)
            assertEquals(1, response.transformMeta.single().page)
        }
    }

    @Test
    fun `a box the model cited on the processed page lands on the marker of the original page, for every kind of scan`() {
        for (case in CASES) {
            val record = load(case)
            val meta = Fixtures.parse<TransformMetadataResponse>(record.getValue("transform_metadata").toString()).transformMeta.single()
            val cited = rect(record.getValue("processed_marker").jsonObject)
            val actual = rect(record.getValue("original_marker").jsonObject)

            val mapped = mapProcessedBBoxToOriginal(BBox(1, cited.ymin, cited.xmin, cited.ymax, cited.xmax), meta)
            val agreement = iou(NormRect(mapped.xmin, mapped.ymin, mapped.xmax, mapped.ymax), actual)
            assertTrue("$case: IoU $agreement between the mapped box and the marker as the page shows it", agreement >= 0.85)
        }
    }

    @Test
    fun `the cases cover rotation, tilt and both together`() {
        val metas = CASES.associateWith { Fixtures.parse<TransformMetadataResponse>(load(it).getValue("transform_metadata").toString()).transformMeta.single() }
        assertTrue(metas.getValue("skew5").deskewApplied == true && metas.getValue("skew5").rotation == 0)
        assertTrue(metas.getValue("sideways90-skew4").deskewApplied == true && metas.getValue("sideways90-skew4").rotation != 0)
        assertTrue(metas.getValue("pdf-rotate90").rotation != 0)
        assertNotNull(metas.getValue("clean").processedToSourceAffine)
    }
}

class ViewerGeometryTest {
    private fun hl(id: String, doc: String = "d1", page: Int = 1, severity: Severity = Severity.MATERIAL, bbox: BBox = BBox(page, 100.0, 200.0, 160.0, 400.0)) =
        Highlight(id, doc, page, bbox, severity, "label $id")

    private fun meta(page: Int = 1, source: Int? = null, rotation: Int = 0, processedUri: String? = null, deskew: Boolean? = null, deg: Double = 0.0) =
        TransformMetadata(page = page, sourcePage = source, rotation = rotation, processedUri = processedUri, deskewApplied = deskew, deskewDeg = deg)

    // ---- boxes on a page

    @Test
    fun `only the boxes of this document and this page are drawn`() {
        val boxes = boxesOnOriginalPage(listOf(hl("a"), hl("b", doc = "d2"), hl("c", page = 2)), "d1", 1, emptyList())
        assertEquals(listOf("a"), boxes.map { it.id })
    }

    @Test
    fun `without metadata a box is where the model put it`() {
        val box = boxesOnOriginalPage(listOf(hl("a")), "d1", 1, emptyList()).single()
        assertEquals(NormRect(200.0, 100.0, 400.0, 160.0), box.rect)
        assertEquals(Severity.MATERIAL, box.severity)
        assertEquals("label a", box.label)
    }

    @Test
    fun `a box on a rotated page is carried back through the page's transform`() {
        val box = boxesOnOriginalPage(listOf(hl("a")), "d1", 1, listOf(meta(rotation = 90))).single()
        assertEquals(NormRect(100.0, 600.0, 160.0, 800.0), box.rect)
    }

    @Test
    fun `the transform of a page is found by its source page, falling back to the page number`() {
        val split = listOf(meta(page = 1, source = 3, rotation = 180), meta(page = 2, source = null, rotation = 90))
        assertEquals(180, transformFor(3, split)?.rotation)
        assertEquals(90, transformFor(2, split)?.rotation)
        assertNull(transformFor(1, split))
    }

    @Test
    fun `the processed page shows the boxes exactly as the model cited them`() {
        val box = boxesOnProcessedPage(listOf(hl("a"), hl("b", doc = "d2")), "d1", 1).single()
        assertEquals(NormRect(200.0, 100.0, 400.0, 160.0), box.rect)
    }

    @Test
    fun `boxes are drawn only when how the page was transformed is known`() {
        assertTrue(GeometryState.Known(emptyList()).allowsBoxes())
        assertTrue(GeometryState.Known(listOf(meta())).allowsBoxes())
        assertFalse(GeometryState.Loading.allowsBoxes())
        assertFalse("a failed fetch must not fall back to boxes that may be on the wrong side of a turned page", GeometryState.Unavailable.allowsBoxes())
    }

    @Test
    fun `the straightened note appears only when a deskew was applied, with one decimal`() {
        assertEquals("straightened 5.0°", deskewNote(meta(deskew = true, deg = 5.0)))
        assertEquals("straightened -3.2°", deskewNote(meta(deskew = true, deg = -3.24)))
        assertNull(deskewNote(meta(deskew = false, deg = 0.0)))
        assertNull(deskewNote(meta(deskew = null)))
        assertNull(deskewNote(null))
    }

    @Test
    fun `what the model saw is offered only when its page image was kept`() {
        assertTrue(hasModelView(meta(processedUri = "gs://b/page-001.png")))
        assertFalse(hasModelView(meta(processedUri = null)))
        assertFalse(hasModelView(meta(processedUri = "")))
        assertFalse(hasModelView(null))
    }

    // ---- taps

    @Test
    fun `a tap picks the smallest box under the finger`() {
        val big = PageBox("big", Severity.WARN, "", NormRect(100.0, 100.0, 900.0, 900.0))
        val small = PageBox("small", Severity.MATERIAL, "", NormRect(400.0, 400.0, 500.0, 450.0))
        assertEquals("small", boxAt(listOf(big, small), 450.0, 420.0)?.id)
        assertEquals("big", boxAt(listOf(big, small), 200.0, 200.0)?.id)
        assertNull(boxAt(listOf(big, small), 50.0, 50.0))
    }

    @Test
    fun `a thin box can be hit with some slop`() {
        val thin = PageBox("t", Severity.WARN, "", NormRect(100.0, 500.0, 900.0, 504.0))
        assertNull(boxAt(listOf(thin), 500.0, 510.0))
        assertEquals("t", boxAt(listOf(thin), 500.0, 510.0, slopNorm = 12.0)?.id)
    }

    // ---- evidence targets and ids

    private fun evidence(doc: String? = "d1", field: String? = "f", page: Int? = 1, bbox: BBox? = BBox(1, 1.0, 2.0, 3.0, 4.0)) =
        EvidenceRef(doc = doc, field = field, page = page, bbox = bbox)

    @Test
    fun `the id an evidence row carries is the id of the box the viewer draws`() {
        val check = CheckResult("M-001", Severity.MATERIAL, "contradiction", evidence = listOf(evidence(field = "a"), evidence(field = "b")))
        val assessment = AssessmentIteration(iteration = 1, bundleId = "b", status = "MATERIAL_CONTRADICTION", checks = listOf(check, check.copy(checkId = "W-001")))
        val drawn = buildHighlights(assessment).map { it.id }.toSet()
        for ((checkIndex, c) in assessment.checks.withIndex()) {
            for ((i, ev) in c.evidence.orEmpty().withIndex()) {
                assertTrue(evidenceTarget(c, checkIndex, ev, i)!!.highlightId in drawn)
            }
        }
    }

    @Test
    fun `a highlight remembers the value its box outlines, which tells apart the boxes of one finding`() {
        val check = CheckResult("M-001", Severity.MATERIAL, "contradiction", evidence = listOf(
            EvidenceRef(doc = "d1", field = "a", page = 1, bbox = BBox(1, 1.0, 2.0, 3.0, 4.0), rawValue = kotlinx.serialization.json.JsonPrimitive("TH-77121: Cr 0.35%")),
            EvidenceRef(doc = "d1", field = "b", page = 1, bbox = BBox(1, 5.0, 6.0, 7.0, 8.0)),
        ))
        val highlights = buildHighlights(AssessmentIteration(iteration = 1, bundleId = "b", status = "MATERIAL_CONTRADICTION", checks = listOf(check)))
        assertEquals(listOf("TH-77121: Cr 0.35%", null), highlights.map { it.value })
        val boxes = boxesOnOriginalPage(highlights, "d1", 1, emptyList())
        assertEquals(listOf("TH-77121: Cr 0.35%", null), boxes.map { it.value })
        assertEquals("TH-77121: Cr 0.35%", boxesOnProcessedPage(highlights, "d1", 1).first().value)
    }

    @Test
    fun `evidence with no box opens its page without a box to emphasise`() {
        val check = CheckResult("M-001", Severity.MATERIAL, "m")
        assertEquals(EvidenceTarget("d1", 2, null), evidenceTarget(check, 0, evidence(page = 2, bbox = null), 0))
        assertEquals(EvidenceTarget("d1", null, null), evidenceTarget(check, 0, evidence(page = null, bbox = null), 0))
        assertNull("no document, nowhere to go", evidenceTarget(check, 0, evidence(doc = null), 0))
    }

    // ---- zoom and pan

    private val layout = PageLayout(viewWidth = 1000f, viewHeight = 1400f, pageAspect = 1.414f) // an A4 page on a phone

    @Test
    fun `at first the page fits the viewport's width and sits at the top`() {
        val t = initialTransform(layout)
        assertEquals(ViewTransform(1f, 0f, 0f), t)
    }

    @Test
    fun `a page shorter than the viewport is centred, a longer one is not`() {
        val short = PageLayout(1000f, 1400f, 0.7f) // landscape page
        assertEquals(1400f / 2 - 350f, initialTransform(short).offsetY, 0.01f)
        assertEquals(0f, initialTransform(layout).offsetY, 0.01f)
    }

    @Test
    fun `zoom stays between fit and the limit`() {
        val out = initialTransform(layout).zoomedBy(layout, 0.1f, 500f, 700f)
        assertEquals(ViewTransform.MIN_ZOOM, out.zoom, 0f)
        val far = initialTransform(layout).zoomedBy(layout, 100f, 500f, 700f)
        assertEquals(ViewTransform.MAX_ZOOM, far.zoom, 0f)
    }

    @Test
    fun `a pinch keeps the page point under the fingers where it was`() {
        val start = initialTransform(layout)
        val (px, py) = start.viewToPage(layout, 300f, 500f)
        val zoomed = start.zoomedBy(layout, 2.5f, 300f, 500f)
        val (qx, qy) = zoomed.viewToPage(layout, 300f, 500f)
        assertEquals(px, qx, 0.01)
        assertEquals(py, qy, 0.01)
        assertEquals(2.5f, zoomed.zoom, 0f)
    }

    @Test
    fun `the page cannot be dragged away from the viewport`() {
        val z = initialTransform(layout).zoomedBy(layout, 3f, 500f, 700f)
        val farRight = z.panBy(layout, 99999f, 99999f)
        assertEquals(0f, farRight.offsetX, 0f)
        assertEquals(0f, farRight.offsetY, 0f)
        val farLeft = z.panBy(layout, -99999f, -99999f)
        assertEquals(1000f - 3000f, farLeft.offsetX, 0.01f)
        assertEquals(1400f - 1.414f * 1000f * 3f, farLeft.offsetY, 0.5f)
        // at fit zoom the width is filled, so it cannot be moved sideways at all
        assertEquals(0f, initialTransform(layout).panBy(layout, 300f, 0f).offsetX, 0f)
    }

    @Test
    fun `the buttons zoom about the centre and the result stays in range`() {
        var t = initialTransform(layout)
        repeat(12) { t = t.zoomedAboutCentre(layout, ViewTransform.STEP) }
        assertEquals(ViewTransform.MAX_ZOOM, t.zoom, 0f)
        repeat(12) { t = t.zoomedAboutCentre(layout, 1f / ViewTransform.STEP) }
        assertEquals(initialTransform(layout), t)
    }

    @Test
    fun `zooming to a box centres it and gives it room, up to a sensible zoom`() {
        val box = NormRect(600.0, 500.0, 800.0, 530.0)
        val t = zoomToRect(layout, box)
        val (x0, y0, x1, y1) = t.pageToView(layout, box).toList()
        assertTrue("the whole box is in view", x0 >= 0f && x1 <= layout.viewWidth && y0 >= 0f && y1 <= layout.viewHeight)
        assertEquals("centred", layout.viewWidth / 2f, (x0 + x1) / 2f, 1f)
        assertTrue(t.zoom > 1f && t.zoom <= 4f)
    }

    @Test
    fun `a box too close to the edge cannot be centred but is still fully in view`() {
        val box = NormRect(920.0, 20.0, 990.0, 50.0)
        val t = zoomToRect(layout, box)
        val (x0, y0, x1, y1) = t.pageToView(layout, box).toList()
        assertTrue(x0 >= 0f && x1 <= layout.viewWidth && y0 >= 0f && y1 <= layout.viewHeight)
    }

    @Test
    fun `a page box maps to viewport pixels and back`() {
        val t = ViewTransform(2f, -300f, -100f)
        val box = NormRect(500.0, 250.0, 600.0, 300.0)
        val (l, top, r, b) = t.pageToView(layout, box).toList()
        val (px, py) = t.viewToPage(layout, l, top)
        assertEquals(500.0, px, 0.01)
        assertEquals(250.0, py, 0.01)
        assertTrue(r > l && b > top)
    }

    @Test
    fun `the visible part is the whole page at fit and a window when zoomed`() {
        val whole = initialTransform(layout).visiblePart(layout)
        assertEquals(0.0, whole.xmin, 0.01)
        assertEquals(1000.0, whole.xmax, 0.01)
        val z = initialTransform(layout).zoomedBy(layout, 4f, 500f, 700f)
        val part = z.visiblePart(layout)
        assertEquals(250.0, part.width, 1.0)
        assertTrue(part.xmin >= 0.0 && part.xmax <= 1000.0 && part.ymin >= 0.0 && part.ymax <= 1000.0)
    }

    @Test
    fun `an unusable layout is recognised`() {
        assertFalse(PageLayout(0f, 100f, 1.4f).isUsable)
        assertFalse(PageLayout(100f, 100f, 0f).isUsable)
        assertFalse(PageLayout(100f, 100f, Float.NaN).isUsable)
        assertTrue(layout.isUsable)
    }
}

class TransformMetadataFixtureTest {
    @Test
    fun `the recorded demo metadata decodes strictly, and its page has a kept image`() {
        val response = Fixtures.decode<TransformMetadataResponse>("transform_metadata_demo.json")
        val page = response.transformMeta.single()
        assertTrue(hasModelView(page))
        assertEquals(0, page.rotation)
        assertNull(deskewNote(page))
        assertEquals(page, transformFor(1, response.transformMeta))
    }

    @Test
    fun `the 404 a document gets before it was analysed is the usual envelope`() {
        val envelope = Json { ignoreUnknownKeys = true }.decodeFromString<ErrorEnvelope>(Fixtures.text("error_transform_metadata_not_found.json"))
        assertEquals("NOT_FOUND", envelope.code)
    }
}
