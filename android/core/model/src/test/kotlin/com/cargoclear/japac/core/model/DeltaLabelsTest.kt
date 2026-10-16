package com.cargoclear.japac.core.model

import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class DeltaLabelsTest {
    @Test
    fun `an attribute is named the way a person reads it`() {
        assertEquals("Status", attributeLabel("status"))
        assertEquals("M-001", attributeLabel("M-001"))
        assertEquals("Correction: Certificate cell 21", attributeLabel("correction.doc-f74c9c3e83f32ccc.test_results[20]"))
        assertEquals("Correction: Consignee", attributeLabel("correction.doc-1.consignee"))
        assertEquals("Correction: Line 2 · Hs code declared", attributeLabel("correction.doc-1.line_items[1].hs_code_declared"))
        assertEquals("Required document: Mill Test Certificate", attributeLabel("missing_evidence.ME-MILL_TEST_CERTIFICATE"))
        assertEquals("Required document: Phytosanitary Certificate", attributeLabel("missing_evidence.ME-CORE-PHYTOSANITARY_CERTIFICATE"))
        assertEquals("something_new", attributeLabel("something_new"))
    }

    @Test
    fun `statuses read as words and everything else as it is`() {
        assertEquals("Material Contradiction", plainValue(JsonPrimitive("MATERIAL_CONTRADICTION")))
        assertEquals("a single word is not a status key", "PASS", plainValue(JsonPrimitive("PASS")))
        assertEquals("0.35 %", plainValue(JsonPrimitive("0.35 %")))
        assertEquals("", plainValue(null))
        assertEquals("25400", plainValue(JsonPrimitive(25400.0)))
        assertEquals("MUMBAI INFRA PIPING PVT LTD", plainValue(JsonPrimitive("MUMBAI INFRA PIPING PVT LTD")))
    }

    @Test
    fun `every row of the recorded Reasoning Delta reads cleanly`() {
        val delta = checkNotNull(Fixtures.decode<AssessmentIteration>("case_d_assessment_recomputed.json").reasoningDelta)
        assertEquals(DeltaKind.REASSESSMENT, delta.kind)
        val rows = delta.changes.map { Triple(attributeLabel(it.field.orEmpty()), plainValue(it.from), plainValue(it.to)) }
        assertEquals(Triple("Status", "Material Contradiction", "Specialist Review Required"), rows.first())
        assertTrue(rows.any { it.first == "Correction: Certificate cell 21" && it.second == "0.35 %" && it.third == "0.28 %" })
    }
}
