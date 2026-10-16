package com.cargoclear.japac.core.model

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private fun check(severity: Severity = Severity.PASS, id: String = "X", focus: String? = null, evidence: List<EvidenceRef>? = null) =
    CheckResult(checkId = id, severity = severity, message = "m", focusDocument = focus, evidence = evidence)

private fun ev(doc: String, field: String = "f", page: Int? = null, bbox: BBox? = null) =
    EvidenceRef(doc = doc, field = field, page = page, bbox = bbox)

private fun doc(id: String) = DocumentRecord(id, "b", "$id.pdf", "INVOICE", "gs://x", "sha", 1000, "2026-01-01T00:00:00Z")

/** Ports of frontend/tests/finding-document.unit.spec.ts. */
class FindingDocumentTest {
    private val docs = listOf("inv-1", "mtc-1", "bl-1")

    @Test
    fun `a finding that names its document is believed, even when the evidence cites another first`() {
        val material = check(Severity.MATERIAL, focus = "mtc-1", evidence = listOf(ev("inv-1"), ev("mtc-1")))
        assertEquals("mtc-1", findingDocumentId(listOf(material), docs))
        assertEquals("mtc-1", findingDocumentId(listOf(material.copy(evidence = material.evidence!!.reversed())), docs))
    }

    @Test
    fun `an older assessment carries no focus so the first document its evidence cites is used`() {
        val material = check(Severity.MATERIAL, evidence = listOf(ev("bl-1"), ev("mtc-1")))
        assertEquals("bl-1", findingDocumentId(listOf(material), docs))
    }

    @Test
    fun `only documents of the bundle on screen count`() {
        val material = check(Severity.MATERIAL, focus = "gone", evidence = listOf(ev("gone-too"), ev("bl-1")))
        assertEquals("bl-1", findingDocumentId(listOf(material), docs))
        assertNull(findingDocumentId(listOf(check(Severity.MATERIAL, focus = "gone")), docs))
    }

    @Test
    fun `no material finding or nothing cited is no opinion`() {
        assertNull(findingDocumentId(listOf(check(Severity.WARN, focus = "mtc-1"), check()), docs))
        assertNull(findingDocumentId(null, docs))
        assertNull(findingDocumentId(listOf(check(Severity.MATERIAL)), docs))
    }

    @Test
    fun `the first material finding wins`() {
        val first = check(Severity.MATERIAL, "A", focus = "mtc-1")
        val second = check(Severity.MATERIAL, "B", focus = "inv-1")
        assertEquals("mtc-1", findingDocumentId(listOf(check(Severity.WARN, focus = "bl-1"), first, second), docs))
    }
}

/** Ports of frontend/tests/corrections.unit.spec.ts, including the cross-language label vectors in docs/schemas/path-labels.json. */
class CorrectionsTest {
    private val extracted: ExtractedDoc = Json.parseToJsonElement(
        """
        {"document_id":"inv-1",
         "consignee":{"value":"ACME PTE LTD","confidence":0.9},
         "total_gross_weight_kg":{"value":"14,280.50","unit":"KGS","confidence":0.9,"corrected":true,"original_value":"14,208.50","original_unit":"KGS"},
         "incoterm":null,
         "line_items":[{"description":{"value":"SEAMLESS PIPE","confidence":0.9},"total_value":{"value":1000,"confidence":0.9}}],
         "test_results":[{"value":"0.35","unit":"%","parameter":"Cr","heat_number":"H2","confidence":0.9}],
         "heat_numbers":[{"value":"H2","confidence":0.9}]}
        """.trimIndent(),
    ).jsonObject

    @Test
    fun `a header field, a line item field and a list row each name exactly one value`() {
        assertEquals("consignee", evidencePath(EvidenceRef(doc = "d", field = "consignee")))
        assertEquals("total_gross_weight_kg", evidencePath(EvidenceRef(doc = "d", field = "total_gross_weight_kg", page = 1)))
        assertEquals("line_items[2].hs_code_declared", evidencePath(EvidenceRef(doc = "d", field = "hs_code_declared", lineItem = 2)))
        assertEquals("test_results[7]", evidencePath(EvidenceRef(doc = "d", field = "test_results", row = 7)))
        assertEquals("heat_numbers[0]", evidencePath(EvidenceRef(doc = "d", field = "heat_numbers", row = 0)))
    }

    @Test
    fun `anything that does not point at one correctable value has no address`() {
        assertNull(evidencePath(EvidenceRef(doc = "d", field = "hs_code_declared"))) // stated on several lines
        assertNull(evidencePath(EvidenceRef(doc = "d", field = "test_results"))) // a row list with no row
        assertNull(evidencePath(EvidenceRef(doc = "d", field = "test_results", row = -1)))
        assertNull(evidencePath(EvidenceRef(doc = "d", field = "bogus")))
        assertNull(evidencePath(EvidenceRef(doc = "d", field = "bogus", lineItem = 0)))
        assertNull(evidencePath(EvidenceRef(doc = "d", field = "document_id")))
        assertNull(evidencePath(EvidenceRef(doc = "d", field = null)))
    }

    @Test
    fun `weights and certificate cells carry a unit and certificate cells and heats cannot be cleared`() {
        assertTrue(hasUnit("total_gross_weight_kg"))
        assertTrue(hasUnit("line_items[0].net_weight_kg"))
        assertTrue(hasUnit("test_results[3]"))
        assertFalse(hasUnit("consignee"))
        assertFalse(hasUnit("heat_numbers[0]"))
        assertTrue(canClear("consignee"))
        assertTrue(canClear("line_items[0].total_value"))
        assertFalse(canClear("test_results[3]"))
        assertFalse(canClear("heat_numbers[0]"))
    }

    @Test
    fun `labels read like words`() {
        assertEquals("Consignee", pathLabel("consignee"))
        assertEquals("Total gross weight", pathLabel("total_gross_weight_kg"))
        assertEquals("Line 2 · Hs code declared", pathLabel("line_items[1].hs_code_declared"))
        assertEquals("Certificate cell 7", pathLabel("test_results[6]"))
        assertEquals("Heat number 1", pathLabel("heat_numbers[0]"))
    }

    @Test
    fun `every label matches the vectors the backend and the web are held to`() {
        val vectors = Json.parseToJsonElement(Fixtures.text("path-labels.json")).jsonObject.getValue("vectors").jsonArray
        assertTrue(vectors.size >= 8)
        for (vector in vectors) {
            val v = vector.jsonObject
            assertEquals(v.getValue("path").jsonPrimitive.content, v.getValue("label").jsonPrimitive.content, pathLabel(v.getValue("path").jsonPrimitive.content))
        }
    }

    @Test
    fun `reads value, unit and the corrected markers`() {
        val docs = listOf(extracted)
        assertEquals(CellValue("ACME PTE LTD", null, false, null, null), readCell(docs, "inv-1", "consignee"))
        assertEquals(CellValue("14,280.50", "KGS", true, "14,208.50", "KGS"), readCell(docs, "inv-1", "total_gross_weight_kg"))
        assertEquals("1000", readCell(docs, "inv-1", "line_items[0].total_value")?.value)
        assertEquals("0.35", readCell(docs, "inv-1", "test_results[0]")?.value)
        assertEquals("%", readCell(docs, "inv-1", "test_results[0]")?.unit)
        assertEquals("H2", readCell(docs, "inv-1", "heat_numbers[0]")?.value)
    }

    @Test
    fun `an empty field is an address with no value and a missing document or row is nothing`() {
        val docs = listOf(extracted)
        assertEquals(CellValue(null, null, false, null, null), readCell(docs, "inv-1", "incoterm"))
        assertNull(readCell(docs, "inv-1", "line_items[0].unit_price")?.value)
        assertNull(readCell(docs, "nope", "consignee"))
        assertNull(readCell(docs, "inv-1", "line_items[4].total_value"))
        assertNull(readCell(docs, "inv-1", "test_results[9]"))
    }

    @Test
    fun `a number reads the way the web shows it, whatever way it was serialised`() {
        val docs = listOf(Json.parseToJsonElement("""{"document_id":"d","invoice_value":{"value":1000.0},"tare_weight_kg":{"value":0.50,"unit":"MT"}}""").jsonObject)
        assertEquals("1000", readCell(docs, "d", "invoice_value")?.value)
        assertEquals("0.5", readCell(docs, "d", "tare_weight_kg")?.value)
    }

    @Test
    fun `the field tables are the ones the backend refuses to go beyond`() {
        // The authority check (against backend/app/domain/corrections.py) is backend/tests/unit/test_android_contract.py; this pins the shape.
        assertEquals(21, HEADER_FIELDS.size)
        assertEquals(9, LINE_FIELDS.size)
        assertEquals(listOf("heat_numbers", "test_results"), ROW_LISTS)
        assertTrue(WEIGHT_FIELDS.all { it in HEADER_FIELDS || it in LINE_FIELDS })
    }
}

/** Ports of frontend/tests/transform-bbox.unit.spec.ts: the same numbers as backend/tests/unit/test_deskew.py (GOLDEN_*). */
class BBoxMappingTest {
    private val goldenDeskew5 = listOf(
        listOf(0.996194698, -0.123283204, 63.544252881),
        listOf(0.061615234, 0.996194698, -28.904966209),
        listOf(0.0, 0.0, 1.0),
    )
    private val goldenRotated270Deskew4 = listOf(
        listOf(-0.049314725, -0.99756405, 1023.439387571),
        listOf(0.99756405, -0.098671657, 50.553803478),
        listOf(0.0, 0.0, 1.0),
    )

    private fun meta(
        rotation: Int = 0,
        deskewApplied: Boolean? = null,
        affine: List<List<Double>>? = null,
        sourcePage: Int? = 1,
        deskewDetected: Double? = null,
    ) = TransformMetadata(
        page = 1, sourcePage = sourcePage, documentId = "d", rotation = rotation, deskewApplied = deskewApplied,
        processedToSourceAffine = affine, deskewDetectedDeg = deskewDetected, splitOffset = 0, width = 1240, height = 1754,
    )

    private fun box(xmin: Double, ymin: Double, xmax: Double, ymax: Double) = BBox(page = 1, ymin = ymin, xmin = xmin, ymax = ymax, xmax = xmax)

    private fun assertBox(expected: BBox, actual: BBox, delta: Double = 1e-9) {
        assertEquals(expected.page, actual.page)
        assertEquals(expected.xmin, actual.xmin, delta)
        assertEquals(expected.ymin, actual.ymin, delta)
        assertEquals(expected.xmax, actual.xmax, delta)
        assertEquals(expected.ymax, actual.ymax, delta)
    }

    @Test
    fun `applyAffine matches the backend's vectors`() {
        val (x, y) = applyAffine(goldenDeskew5, 100.0, 200.0)
        assertEquals(138.507082, x, 1e-4)
        assertEquals(176.495497, y, 1e-4)
        val (rx, ry) = applyAffine(goldenRotated270Deskew4, 900.0, 50.0)
        assertEquals(929.177933, rx, 1e-4)
        assertEquals(943.427866, ry, 1e-4)
        assertEquals(500.0, applyAffine(goldenDeskew5, 500.0, 500.0).first, 1e-4) // the page centre stays put
    }

    @Test
    fun `a page that was only rotated maps by exact corner swaps`() {
        val b = box(100.0, 200.0, 300.0, 260.0)
        assertBox(b, mapProcessedBBoxToOriginal(b, meta(rotation = 0)))
        assertBox(box(200.0, 700.0, 260.0, 900.0), mapProcessedBBoxToOriginal(b, meta(rotation = 90)))
        assertBox(box(700.0, 740.0, 900.0, 800.0), mapProcessedBBoxToOriginal(b, meta(rotation = 180)))
        assertBox(box(740.0, 100.0, 800.0, 300.0), mapProcessedBBoxToOriginal(b, meta(rotation = 270)))
        assertBox(b, mapProcessedBBoxToOriginal(b, null))
    }

    @Test
    fun `the recorded affine of a rotation-only page agrees with the corner swaps`() {
        val rotation270 = listOf(listOf(0.0, -1.0, 1000.0), listOf(1.0, 0.0, 0.0), listOf(0.0, 0.0, 1.0))
        val b = box(100.0, 200.0, 300.0, 260.0)
        assertBox(mapProcessedBBoxToOriginal(b, meta(rotation = 270)), mapProcessedBBoxToOriginal(b, meta(rotation = 270, deskewApplied = true, affine = rotation270)))
    }

    @Test
    fun `a deskewed page maps its box through the recorded affine as the bounding box of the four corners`() {
        val mapped = mapProcessedBBoxToOriginal(box(100.0, 200.0, 300.0, 260.0), meta(deskewApplied = true, affine = goldenDeskew5))
        val corners = listOf(100.0 to 200.0, 300.0 to 200.0, 100.0 to 260.0, 300.0 to 260.0).map { (x, y) -> applyAffine(goldenDeskew5, x, y) }
        assertEquals(corners.minOf { it.first }, mapped.xmin, 1e-6)
        assertEquals(corners.maxOf { it.first }, mapped.xmax, 1e-6)
        assertEquals(corners.minOf { it.second }, mapped.ymin, 1e-6)
        assertEquals(corners.maxOf { it.second }, mapped.ymax, 1e-6)
        assertEquals(1, mapped.page)
    }

    @Test
    fun `a rotated and deskewed page composes both`() {
        val mapped = mapProcessedBBoxToOriginal(box(880.0, 40.0, 920.0, 60.0), meta(rotation = 270, deskewApplied = true, affine = goldenRotated270Deskew4))
        val (cx, cy) = applyAffine(goldenRotated270Deskew4, 900.0, 50.0) // the box centre
        assertEquals(cx, (mapped.xmin + mapped.xmax) / 2, 0.1)
        assertEquals(cy, (mapped.ymin + mapped.ymax) / 2, 0.1)
    }

    @Test
    fun `the result stays on the page`() {
        val mapped = mapProcessedBBoxToOriginal(box(950.0, 950.0, 1000.0, 1000.0), meta(deskewApplied = true, affine = goldenDeskew5))
        for (v in listOf(mapped.xmin, mapped.ymin, mapped.xmax, mapped.ymax)) assertTrue(v in 0.0..1000.0)
    }

    @Test
    fun `a record with no usable affine falls back to the rotation so older metadata keeps working`() {
        val b = box(100.0, 200.0, 300.0, 260.0)
        assertBox(mapProcessedBBoxToOriginal(b, meta(rotation = 90)), mapProcessedBBoxToOriginal(b, meta(rotation = 90, deskewApplied = true, affine = null)))
        assertBox(b, mapProcessedBBoxToOriginal(b, meta(deskewApplied = true, affine = listOf(listOf(1.0, 0.0), listOf(0.0, 1.0)))))
        assertBox(b, mapProcessedBBoxToOriginal(b, meta(deskewApplied = true, affine = listOf(listOf(Double.NaN, 0.0, 0.0), listOf(0.0, 1.0, 0.0), listOf(0.0, 0.0, 1.0)))))
    }

    @Test
    fun `a page whose deskew was not applied ignores the affine`() {
        val b = box(100.0, 200.0, 300.0, 260.0)
        assertBox(b, mapProcessedBBoxToOriginal(b, meta(deskewApplied = false, deskewDetected = 3.0, affine = goldenDeskew5)))
    }

    @Test
    fun `the source page replaces the processed page number`() {
        val b = box(100.0, 200.0, 300.0, 260.0)
        assertEquals(4, mapProcessedBBoxToOriginal(b, meta(sourcePage = 4)).page)
        assertEquals(1, mapProcessedBBoxToOriginal(b, meta(sourcePage = null)).page)
    }

    @Test
    fun `a box maps onto a canvas`() {
        val rect = mapBBoxToCanvas(box(100.0, 200.0, 300.0, 260.0), 800.0, 1000.0)
        assertEquals(CanvasRect(80.0, 200.0, 160.0, 60.0), rect)
        assertEquals(0.0, mapBBoxToCanvas(box(300.0, 200.0, 100.0, 260.0), 800.0, 1000.0).w, 0.0)
    }
}

class HighlightsAndHealthTest {
    private val bbox = BBox(1, 10.0, 10.0, 20.0, 20.0)

    @Test
    fun `only evidence with a document, a page and a box is drawn, and ids are unique per position`() {
        val assessment = assessment(
            check(Severity.MATERIAL, "M-001", evidence = listOf(ev("d1", "a", 1, bbox), ev("d1", "a"), ev("d2", "b", null, bbox), ev("d1", "a", 1, bbox))),
            check(Severity.PASS, "M-001", evidence = listOf(ev("d1", "a", 1, bbox))),
        )
        val highlights = buildHighlights(assessment)
        assertEquals(3, highlights.size)
        assertEquals(highlights.size, highlights.map { it.id }.toSet().size)
        assertEquals(Severity.MATERIAL, highlights.first().severity)
        assertEquals(emptyList<Highlight>(), buildHighlights(null))
    }

    @Test
    fun `a document gets the worst badge of the checks that cite it, and none when nothing cites it`() {
        val documents = listOf(doc("d1"), doc("d2"), doc("d3"), doc("d4"))
        val checks = listOf(
            check(Severity.PASS, evidence = listOf(ev("d1"), ev("d2"), ev("d3"))),
            check(Severity.WARN, evidence = listOf(ev("d2"), ev("d3"))),
            check(Severity.MATERIAL, evidence = listOf(ev("d3"), ev("d3"))),
        )
        val health = documentHealth(documents, checks)
        assertEquals(HealthBadge.CLEAN, health.getValue("d1").badge())
        assertEquals(HealthBadge.GAP, health.getValue("d2").badge())
        assertEquals(HealthBadge.CONFLICT, health.getValue("d3").badge())
        assertEquals(2, health.getValue("d3").material)
        assertNull(health.getValue("d4").badge())
    }

    private fun assessment(vararg checks: CheckResult) = AssessmentIteration(iteration = 1, bundleId = "b", status = "MISSING_EVIDENCE", checks = checks.toList())
}

class SmallHelpersTest {
    @Test
    fun `check titles`() {
        assertEquals("Alloy Status vs Declared HS Code (HS Note 1)", checkTitle("M-001"))
        assertEquals("Certificate HS Verification (MILL TEST CERTIFICATE)", checkTitle("H-003-MILL_TEST_CERTIFICATE"))
        assertEquals("Q-999", checkTitle("Q-999"))
    }

    @Test
    fun `the checks that end in a document id have their own titles, the web app's`() {
        assertEquals("Pages Not Read", checkTitle("P-001-doc-84b80e4e1d7110e3"))
        assertEquals("Pages Skipped (Terms and Conditions)", checkTitle("P-002-doc-84b80e4e1d7110e3"))
        assertEquals("Document Type Differs From the Upload", checkTitle("T-001-doc-84b80e4e1d7110e3"))
        assertEquals("Values Not in Latin Script", checkTitle("L-001-doc-84b80e4e1d7110e3"))
        assertEquals("P-001", checkTitle("P-001")) // without a document id it is not one of these
    }

    @Test
    fun `a status the app does not know is not guessed`() {
        assertEquals(Status.MATERIAL_CONTRADICTION, Status.fromWire("MATERIAL_CONTRADICTION"))
        assertNull(Status.fromWire("PENDING"))
        assertNull(Status.fromWire("SOMETHING_NEW"))
        assertNull(Status.fromWire(null))
    }

    @Test
    fun `the demo banner applies in demo mode and to fixture data`() {
        assertTrue(isDemoData(AppMode.DEMO, null))
        assertTrue(isDemoData(AppMode.LIVE, DataSource.FIXTURE))
        assertFalse(isDemoData(AppMode.LIVE, DataSource.LIVE))
        assertFalse(isDemoData(null, null))
        assertTrue(DEMO_BANNER_TEXT.startsWith("DEMO MODE - extraction uses synthetic fixtures"))
    }

    @Test
    fun `tariff codes are written the way the web writes them`() {
        assertEquals("7304.51", formatHs("730451"))
        assertEquals("7304.31.00", formatHs("73043100"))
        assertEquals("7304.31.00", formatHs("7304.31.00"))
        assertEquals("12345", formatHs("12345"))
        assertEquals("", formatHs(null))
    }

    /** Quotes of what the web's `Intl.NumberFormat` printed for the same inputs (node, 2026-10-14); the separator is a no-break space. */
    @Test
    fun `money reads exactly as it does on the web`() {
        val nbsp = " "
        assertEquals("INR${nbsp}54,43,559.38", formatMoney(5443559.38, "INR"))
        assertEquals("SGD${nbsp}1,234.50", formatMoney(1234.5, "SGD"))
        assertEquals("INR${nbsp}0.00", formatMoney(0.0, "INR"))
        assertEquals("-USD${nbsp}12.35", formatMoney(-12.345, "USD"))
        assertEquals("INR${nbsp}10,00,000.00", formatMoney(999999.999, "INR"))
        assertEquals("USD${nbsp}100.00", formatMoney(100.0, null))
        assertEquals("INR${nbsp}12,34,56,789.10", formatMoney(123456789.1, "INR"))
        assertEquals("EUR${nbsp}1,234,567.89", formatMoney(1234567.891, "EUR"))
        assertEquals("n/a", formatMoney(null, "INR"))
        assertEquals("1.00 US", formatMoney(1.0, "US"))
    }

    @Test
    fun `scalars read the way JavaScript prints them`() {
        assertEquals("1000", jsText(JsonPrimitive(1000.0)))
        assertEquals("1000", jsText(JsonPrimitive(1000)))
        assertEquals("0.35", jsText(JsonPrimitive(0.35)))
        assertEquals("0", jsText(JsonPrimitive(0.0)))
        assertEquals("73043100", jsText(JsonPrimitive("73043100")))
        assertEquals("0.00001", jsText(JsonPrimitive(0.00001)))
        assertNotEquals("1.0E-5", jsText(JsonPrimitive(0.00001)))
    }
}
