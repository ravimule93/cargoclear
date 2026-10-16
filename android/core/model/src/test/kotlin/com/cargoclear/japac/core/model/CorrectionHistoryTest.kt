package com.cargoclear.japac.core.model

import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The correction history the backend sends (recorded from the Case D journey) and the rules the card, the evidence rows and the editor apply to it. */
class CorrectionHistoryTest {
    private fun extractions(name: String): List<ExtractedDoc> = Fixtures.strict.decodeFromString(Fixtures.text(name))

    private fun certificateId(docs: List<ExtractedDoc>): String =
        docs.single { it["doc_type"]?.jsonPrimitive?.content == "MILL_TEST_CERTIFICATE" }["document_id"]!!.jsonPrimitive.content

    private val crCell = "test_results[20]"

    // ---- what the backend sent

    @Test
    fun `the recorded answers decode strictly`() {
        val created = Fixtures.decode<CorrectionRecord>("correction_created.json")
        assertEquals(CorrectionKind.CORRECTION, created.kind)
        assertEquals(crCell, created.path)
        assertEquals("0.28", created.value)
        assertEquals("0.35", created.originalValue)
        assertEquals("%", created.unit)
        assertEquals("the certificate prints 0.28", created.reason)

        assertEquals(CorrectionKind.CONFIRMATION, Fixtures.decode<CorrectionRecord>("correction_confirmed.json").kind)
        val reverted = Fixtures.decode<CorrectionRecord>("correction_reverted.json")
        assertEquals(CorrectionKind.REVERT, reverted.kind)
        assertEquals(created.correctionId, reverted.reverts)

        val none = Fixtures.decode<CorrectionsResponse>("case_d_corrections_none.json")
        assertEquals(0, none.pending)
        assertTrue(none.effective.isEmpty())
        assertEquals(2, Fixtures.decode<CorrectionsResponse>("case_d_corrections_pending.json").pending)
        assertEquals(0, Fixtures.decode<CorrectionsResponse>("case_d_corrections_applied.json").pending)
    }

    @Test
    fun `an undone correction leaves the overlay but stays in the history`() {
        val undone = Fixtures.decode<CorrectionsResponse>("case_d_corrections_undone.json")
        assertEquals(listOf(CorrectionKind.CORRECTION, CorrectionKind.CONFIRMATION, CorrectionKind.REVERT), undone.corrections.map { it.kind })
        assertEquals(listOf(CorrectionKind.CONFIRMATION), undone.effective.map { it.kind })
        assertTrue("the undo is a change the latest assessment does not include", undone.pending > 0)
    }

    @Test
    fun `the extraction shows the model's reading, and after a recompute the correction with what it replaced`() {
        val before = extractions("case_d_extractions.json")
        val cert = certificateId(before)
        val read = checkNotNull(readCell(before, cert, crCell))
        assertEquals("0.35", read.value)
        assertEquals("%", read.unit)
        assertFalse(read.corrected)

        val after = checkNotNull(readCell(extractions("case_d_extractions_recomputed.json"), cert, crCell))
        assertEquals("0.28", after.value)
        assertTrue(after.corrected)
        assertEquals("0.35", after.originalValue)
        assertEquals("%", after.originalUnit)
    }

    // ---- the card

    @Test
    fun `a correction is pending until an assessment that used it exists`() {
        val pending = Fixtures.decode<CorrectionsResponse>("case_d_corrections_pending.json")
        val first = Fixtures.decode<AssessmentIteration>("case_d_assessment_contradiction.json")
        assertTrue(pending.effective.all { correctionStatus(it, first) == CorrectionStatus.PendingRecompute })

        val second = Fixtures.decode<AssessmentIteration>("case_d_assessment_recomputed.json")
        assertTrue(pending.effective.all { correctionStatus(it, second) == CorrectionStatus.InAssessment })
    }

    @Test
    fun `a correction the assessment could not place is shown as not used, with its note`() {
        val entry = Fixtures.decode<CorrectionRecord>("correction_created.json")
        val skipped = AppliedCorrection(
            correctionId = entry.correctionId, seq = entry.seq, documentId = entry.documentId, path = entry.path, createdAt = entry.createdAt,
            status = AppliedCorrectionStatus.SKIPPED, note = "the row is not in the extraction any more",
        )
        val assessment = AssessmentIteration(iteration = 2, bundleId = "b", status = "SPECIALIST_REVIEW_REQUIRED", corrections = listOf(skipped))
        assertEquals(CorrectionStatus.NotUsed("the row is not in the extraction any more"), correctionStatus(entry, assessment))
    }

    @Test
    fun `values are printed with their unit unless they already end with it`() {
        assertEquals("(not stated)", shownValue(null, "KGS"))
        assertEquals("(not stated)", shownValue("", null))
        assertEquals("25400 KGS", shownValue("25400", "KGS"))
        assertEquals("25400 kgs", shownValue("25400 kgs", "KGS"))
        assertEquals("0.28", shownValue("0.28", null))
        assertEquals("0.28 %", shownValue("0.28", "%"))
    }

    // ---- the evidence row

    private fun applied(id: String, status: AppliedCorrectionStatus = AppliedCorrectionStatus.APPLIED) = AppliedCorrection(
        correctionId = id, seq = 1, documentId = "doc-1", path = crCell, createdAt = "t", status = status, originalValue = "0.35",
    )

    private fun record(id: String) = Fixtures.decode<CorrectionRecord>("correction_created.json").copy(correctionId = id, documentId = "doc-1")

    @Test
    fun `an evidence row says whether its value was corrected, is waiting for a recompute, or had a correction undone`() {
        fun response(vararg ids: String) = CorrectionsResponse(effective = ids.map(::record), pending = 0)

        assertNull(evidenceCorrection("doc-1", crCell, response(), emptyList()))
        assertNull("another document", evidenceCorrection("doc-2", crCell, response("cor-9"), listOf(applied("cor-9"))))
        assertNull("another address", evidenceCorrection("doc-1", "consignee", response("cor-9"), listOf(applied("cor-9"))))

        assertTrue(evidenceCorrection("doc-1", crCell, response("cor-9"), listOf(applied("cor-9"))) is EvidenceCorrection.Used)
        assertTrue("in force, but the assessment on screen used an older one", evidenceCorrection("doc-1", crCell, response("cor-12"), listOf(applied("cor-9"))) is EvidenceCorrection.Pending)
        assertTrue("in force, not yet in any assessment", evidenceCorrection("doc-1", crCell, response("cor-12"), emptyList()) is EvidenceCorrection.Pending)
        assertTrue("used, then undone", evidenceCorrection("doc-1", crCell, response(), listOf(applied("cor-9"))) is EvidenceCorrection.Undone)
        assertNull("a correction the assessment skipped never counted", evidenceCorrection("doc-1", crCell, response(), listOf(applied("cor-9", AppliedCorrectionStatus.SKIPPED))))
        assertNull(evidenceCorrection("doc-1", crCell, null, emptyList()))
    }

    @Test
    fun `an evidence row can be edited only when it names exactly one value in a known document`() {
        fun ev(doc: String? = "d", field: String?, line: Int? = null, row: Int? = null) = EvidenceRef(doc = doc, field = field, lineItem = line, row = row)
        assertEquals("consignee", editablePath(ev(field = "consignee")))
        assertEquals("line_items[1].hs_code_declared", editablePath(ev(field = "hs_code_declared", line = 1)))
        assertEquals(crCell, editablePath(ev(field = "test_results", row = 20)))
        assertNull("no document", editablePath(ev(doc = null, field = "consignee")))
        assertNull("a derived figure", editablePath(ev(field = "net_plus_tare")))
        assertNull("a row list without the row", editablePath(ev(field = "test_results")))
    }

    // ---- the editor

    private fun cell(value: String?, unit: String? = null) = CellValue(value, unit, corrected = false, originalValue = null, originalUnit = null)

    @Test
    fun `saving the value as it is records a confirmation, anything else a correction`() {
        val current = cell("0.35", "%")
        val draft = CorrectionDraft("doc-1", crCell).loaded(current)
        assertEquals("0.35", draft.value)
        assertEquals("%", draft.unit)
        assertTrue(draft.unchanged(current))
        assertFalse(draft.valueChanged("0.28").unchanged(current))
        assertFalse("a different unit is a change too", draft.unitChanged("PCT").unchanged(current))
        assertTrue("whitespace around the same value is not a change", draft.valueChanged(" 0.35 ").unchanged(current))
        assertFalse("clearing is always a change", draft.clearChanged(true).unchanged(current))
    }

    @Test
    fun `a field without a unit ignores the unit box when judging a change`() {
        val current = cell("MUMBAI INFRA PIPING PVT LTD")
        val draft = CorrectionDraft("doc-1", "consignee").loaded(current)
        assertFalse(draft.showUnit)
        assertTrue(draft.unitChanged("KGS").unchanged(current))
    }

    @Test
    fun `typing wins over a value that arrives later`() {
        val untouched = CorrectionDraft("doc-1", crCell)
        assertEquals("0.35", untouched.loaded(cell("0.35", "%")).value)
        val typed = untouched.valueChanged("0.28")
        assertEquals("0.28", typed.loaded(cell("0.35", "%")).value)
        assertEquals("the unit box is protected as well", "", typed.loaded(cell("0.35", "%")).unit)
    }

    @Test
    fun `saving needs the extracted value and something to say`() {
        val current = cell("0.35", "%")
        val draft = CorrectionDraft("doc-1", crCell).loaded(current)
        assertTrue(draft.canSave(current))
        assertFalse("the extraction has not arrived", draft.canSave(null))
        assertFalse("an empty value", draft.valueChanged("  ").canSave(current))
        assertTrue("but 'not stated' needs no value", draft.valueChanged("").clearChanged(true).canSave(current))
        assertFalse("while it is being saved", draft.saving().canSave(current))
    }

    @Test
    fun `the request carries the value, the unit only where it belongs, and a trimmed reason`() {
        val certificate = CorrectionDraft("doc-1", crCell).valueChanged("0.28").unitChanged(" % ").reasonChanged("  prints 0.28 ")
        assertEquals(CorrectionRequest("doc-1", crCell, value = "0.28", unit = "%", clear = false, reason = "prints 0.28"), certificate.request())

        val header = CorrectionDraft("doc-1", "consignee").valueChanged("ACME").unitChanged("KGS")
        assertNull("a consignee has no unit", header.request().unit)
        assertNull("an empty reason is none", header.request().reason)

        val cleared = CorrectionDraft("doc-1", "incoterm").valueChanged("FOB").unitChanged("x").clearChanged(true).request()
        assertTrue(cleared.clear)
        assertNull(cleared.value)
        assertNull(cleared.unit)

        assertNull("unit left empty", CorrectionDraft("doc-1", "total_gross_weight_kg").valueChanged("25400").request().unit)
    }

    @Test
    fun `rows can be corrected but never cleared`() {
        assertFalse(CorrectionDraft("doc-1", crCell).clearable)
        assertFalse(CorrectionDraft("doc-1", "heat_numbers[0]").clearable)
        assertTrue(CorrectionDraft("doc-1", "consignee").clearable)
        assertTrue(CorrectionDraft("doc-1", "line_items[0].description").clearable)
    }

    @Test
    fun `the fields stop at the backend's limits`() {
        val draft = CorrectionDraft("doc-1", crCell)
        assertEquals(500, draft.valueChanged("x".repeat(600)).value.length)
        assertEquals(24, draft.unitChanged("u".repeat(40)).unit.length)
        assertEquals(500, draft.reasonChanged("r".repeat(600)).reason.length)
    }

    @Test
    fun `a failed save keeps what was typed and shows the server's words, a new try clears them`() {
        val failed = CorrectionDraft("doc-1", crCell).valueChanged("1,2.3").saving().failed("'1,2.3' is not a number.")
        assertEquals("1,2.3", failed.value)
        assertFalse(failed.busy)
        assertEquals("'1,2.3' is not a number.", failed.error)
        assertNull(failed.saving().error)
    }

    // ---- the wire

    /** The app's own Json: nulls and defaults are left out, which the backend's model accepts (its defaults are the same). */
    private val wire = Json { explicitNulls = false }

    @Test
    fun `the request goes out under the backend's field names`() {
        val body = wire.parseToJsonElement(wire.encodeToString(CorrectionRequest("doc-1", crCell, value = "0.28", unit = "%", reason = "r"))).jsonObject
        assertEquals(setOf("document_id", "path", "value", "unit", "reason"), body.keys)
        assertEquals("doc-1", body.getValue("document_id").jsonPrimitive.content)

        val cleared = wire.parseToJsonElement(wire.encodeToString(CorrectionRequest("doc-1", "incoterm", clear = true))).jsonObject
        assertEquals(setOf("document_id", "path", "clear"), cleared.keys)
        assertEquals(JsonPrimitive(true), cleared.getValue("clear"))
    }

    @Test
    fun `the recorded Case D assessments carry the corrections they used`() {
        val second = Fixtures.decode<AssessmentIteration>("case_d_assessment_recomputed.json")
        assertEquals("recompute", second.runMode)
        assertEquals(Status.SPECIALIST_REVIEW_REQUIRED, second.statusKind)
        assertEquals(2, second.corrections.size)
        assertTrue(second.corrections.all { it.status == AppliedCorrectionStatus.APPLIED })
        assertNotNull(second.corrections.firstOrNull { it.path == crCell && it.originalValue == "0.35" && it.value == "0.28" })
    }

    // ---- surviving the system ending the process

    @Test
    fun `an open editor comes back as it was typed`() {
        val draft = CorrectionDraft("doc-1", crCell).loaded(cell("0.35", "%")).valueChanged("0.28").reasonChanged("prints 0.28")
        val back = checkNotNull(correctionEditorFromSavedState(CorrectionEditor("cert.pdf", draft).toSavedState()))
        assertEquals("cert.pdf", back.documentName)
        assertEquals("doc-1", back.draft.documentId)
        assertEquals(crCell, back.draft.path)
        assertEquals("0.28", back.draft.value)
        assertEquals("%", back.draft.unit)
        assertEquals("prints 0.28", back.draft.reason)
        assertTrue("typing still wins over a value that arrives later", back.draft.touched)
    }

    @Test
    fun `a save in flight or a failure is not remembered`() {
        val failed = CorrectionDraft("doc-1", "consignee").valueChanged("ACME").saving().failed("boom")
        val back = checkNotNull(correctionEditorFromSavedState(CorrectionEditor("a.pdf", failed).toSavedState()))
        assertFalse(back.draft.busy)
        assertNull(back.draft.error)
        assertEquals("ACME", back.draft.value)
    }

    @Test
    fun `the not-stated choice is remembered`() {
        val back = checkNotNull(correctionEditorFromSavedState(CorrectionEditor("a.pdf", CorrectionDraft("d", "incoterm").clearChanged(true)).toSavedState()))
        assertTrue(back.draft.clear)
    }

    @Test
    fun `nothing, or text that is not an editor, means no editor`() {
        assertNull(correctionEditorFromSavedState(null))
        assertNull(correctionEditorFromSavedState(""))
        assertNull(correctionEditorFromSavedState("not json"))
        assertNull(correctionEditorFromSavedState("""{"documentName":"x"}"""))
    }
}
