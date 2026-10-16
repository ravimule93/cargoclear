package com.cargoclear.japac.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PrefillTest {
    private fun assessment(status: String) = AssessmentIteration(iteration = 2, bundleId = "b", status = status)

    @Test
    fun `an assessment that is not cleared says the pack leads with what blocks it`() {
        for (status in listOf("MATERIAL_CONTRADICTION", "MISSING_EVIDENCE", "SPECIALIST_REVIEW_REQUIRED", "SOMETHING_NEW")) {
            assertEquals(PrefillCaveat.NotCleared, prefillCaveat(assessment(status), pendingCorrections = 0))
            assertEquals("pending corrections change nothing about a pack that is not cleared", PrefillCaveat.NotCleared, prefillCaveat(assessment(status), 3))
        }
    }

    @Test
    fun `a cleared assessment is reassuring only when no correction is missing from it`() {
        val cleared = assessment("COMPLIANT_FOR_SUBMISSION")
        assertEquals(PrefillCaveat.ClearedWithAllCorrections, prefillCaveat(cleared, 0))
        assertTrue(prefillCaveat(cleared, 0).reassuring)
        assertEquals(PrefillCaveat.Pending(2), prefillCaveat(cleared, 2))
        assertFalse(prefillCaveat(cleared, 2).reassuring)
        assertFalse(PrefillCaveat.NotCleared.reassuring)
    }

    @Test
    fun `the file is named as the backend names its download`() {
        assertEquals("cargoclear-prefill-bnd-ed45cfcc6224-assessment2.json", prefillFileName("bnd-ed45cfcc6224", 2, PrefillFormat.JSON))
        assertEquals("cargoclear-prefill-bnd-ed45cfcc6224-assessment2.pdf", prefillFileName("bnd-ed45cfcc6224", 2, PrefillFormat.PDF))
        assertEquals("application/pdf", PrefillFormat.PDF.mimeType)
    }
}
