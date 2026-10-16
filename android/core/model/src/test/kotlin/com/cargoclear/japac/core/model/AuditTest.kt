package com.cargoclear.japac.core.model

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The audit chain as the backend sent it (Case D, recorded) and the words the screen puts on it. */
class AuditTest {
    private fun signature(status: String, signedSeq: Int? = 7, unsigned: Int = 0, signer: String? = "local-demo", configured: Boolean = true) =
        AuditSignature(status = status, configured = configured, signer = signer, signedSeq = signedSeq, unsignedEvents = unsigned, meaning = "m")

    @Test
    fun `the recorded chains decode and say whether they hold`() {
        val signed = Fixtures.decode<AuditResponse>("case_d_audit_signed.json")
        assertTrue(signed.verified)
        assertNull(signed.error)
        assertEquals(SignatureStatus.SIGNED, signed.signature?.statusKind)
        assertEquals("local-demo", signed.signature?.signer)
        assertTrue(signed.signature!!.signatures.single().valid == true)
        assertEquals(1, signed.events.first().seq)
        assertEquals("GENESIS", signed.events.first().prevHash)
        assertEquals(signed.events.map { it.seq }, signed.events.indices.map { it + 1 })

        val partial = Fixtures.decode<AuditResponse>("case_d_audit_partial.json")
        assertEquals(SignatureStatus.PARTIAL, partial.signature?.statusKind)
        assertEquals(2, partial.signature?.unsignedEvents)
        assertEquals(SignatureStatus.SIGNED, Fixtures.decode<AuditSignature>("audit_sign_response.json").statusKind)
    }

    @Test
    fun `every status has its words, with a tone that is never the only signal`() {
        assertEquals(SignatureSummary("Head signed through #7 (demo key, not KMS)", Tone.OK), describeSignature(signature("SIGNED")))
        assertEquals(
            SignatureSummary("Signed through #7 (Cloud KMS key); 3 later events not signed yet", Tone.WARN),
            describeSignature(signature("PARTIAL", unsigned = 3, signer = "kms")),
        )
        assertEquals("Signed through #7 (Cloud KMS key); 1 later event not signed yet", describeSignature(signature("PARTIAL", unsigned = 1, signer = "kms")).text)
        assertEquals(SignatureSummary("Head not signed yet", Tone.WARN), describeSignature(signature("UNSIGNED", signedSeq = null)))
        assertEquals(Tone.ERR, describeSignature(signature("INVALID")).tone)
        assertTrue(describeSignature(signature("INVALID")).text.contains("does NOT verify"))
        assertEquals("Signed, but the public key could not be retrieved to verify it", describeSignature(signature("UNVERIFIED")).text)
        assertEquals("Signing is not configured for this service", describeSignature(signature("NOT_CONFIGURED", configured = false)).text)
    }

    @Test
    fun `a status this app does not know is not passed off as one it does`() {
        val summary = describeSignature(signature("REVOKED"))
        assertEquals(Tone.WARN, summary.tone)
        assertTrue(summary.text.contains("REVOKED"))
        assertNull(signature("REVOKED").statusKind)
        assertFalse("and no signing is offered on a status that cannot be read", canSignNow(signature("REVOKED")))
    }

    @Test
    fun `an unknown signer is named as it is`() {
        assertEquals("Head signed through #7 (hsm-9)", describeSignature(signature("SIGNED", signer = "hsm-9")).text)
        assertEquals("Head signed through #7 (unknown key)", describeSignature(signature("SIGNED", signer = null)).text)
    }

    @Test
    fun `Sign now is offered only when signing is set up and events are not covered`() {
        assertTrue(canSignNow(signature("UNSIGNED")))
        assertTrue(canSignNow(signature("PARTIAL", unsigned = 2)))
        assertFalse(canSignNow(signature("SIGNED")))
        assertFalse("a chain that does not verify cannot be signed", canSignNow(signature("INVALID")))
        assertFalse(canSignNow(signature("UNSIGNED", configured = false)))
        assertFalse(canSignNow(signature("NOT_CONFIGURED", configured = false)))
    }

    @Test
    fun `the badge says the chain holds, or why it does not`() {
        assertEquals(SignatureSummary("Chain verified", Tone.OK), chainBadge(AuditResponse(verified = true)))
        assertEquals("Chain BROKEN: hash mismatch at #4", chainBadge(AuditResponse(verified = false, error = "hash mismatch at #4")).text)
        assertEquals("Chain BROKEN: unknown reason", chainBadge(AuditResponse(verified = false)).text)
        assertEquals(Tone.ERR, chainBadge(AuditResponse(verified = false)).tone)
    }

    @Test
    fun `hashes are cut after twelve characters but short markers stay whole`() {
        assertEquals("GENESIS", shortHash("GENESIS"))
        assertEquals("e5dad072d767…", shortHash("e5dad072d767ad55448993bce22764499dfbe4711e3310e8c5373ce2b5ea772d"))
        assertEquals("123456789012", shortHash("123456789012"))
    }

    private fun event(type: String, payload: kotlinx.serialization.json.JsonObject) =
        AuditEvent("b:1:9", "b", 1, 9, "2026-10-14T18:00:00+00:00", "user", type, payload, "p", "h")

    @Test
    fun `the events a person causes are described in a line`() {
        val events = Fixtures.decode<AuditResponse>("case_d_audit_after_undo.json").events
        fun line(type: String) = events.first { it.eventType == type }.let(::describeEvent)

        assertEquals("test_results[20] in doc-f74c9c3e83f32ccc: 0.35 → 0.28 — the certificate prints 0.28", line("FIELD_CORRECTED").let { it?.replace(Regex("doc-[0-9a-f]+"), "doc-f74c9c3e83f32ccc") })
        assertTrue(line("FIELD_CONFIRMED")!!.endsWith("confirmed as MUMBAI INFRA PIPING PVT LTD"))
        assertTrue(line("CORRECTION_REVERTED")!!.startsWith("undid cor-"))
        assertEquals("signed the chain head at #7 (demo key, not KMS)", line("AUDIT_HEAD_SIGNED"))
        assertNull("machine events need no detail", line("BUNDLE_CREATED"))
        assertNull(line("ASSESSMENT_COMPLETED"))
    }

    @Test
    fun `missing parts of a payload fall back to the web's placeholders`() {
        assertEquals("? in ?: (not stated) → (cleared)", describeEvent(event("FIELD_CORRECTED", buildJsonObject { })))
        assertEquals("? in ?: confirmed as (not stated)", describeEvent(event("FIELD_CONFIRMED", buildJsonObject { })))
        assertEquals("signing the chain head failed (error); the chain itself is unaffected", describeEvent(event("AUDIT_SIGNING_FAILED", buildJsonObject { })))
        assertEquals("signing the chain head failed (HttpError); the chain itself is unaffected", describeEvent(event("AUDIT_SIGNING_FAILED", buildJsonObject { put("error_type", "HttpError") })))
        assertEquals("signed the chain head at #3 (Cloud KMS)", describeEvent(event("AUDIT_HEAD_SIGNED", buildJsonObject { put("signed_seq", 3); put("signer", "kms") })))
    }

    @Test
    fun `numbers in a payload read like JavaScript prints them`() {
        val text = describeEvent(event("FIELD_CORRECTED", buildJsonObject { put("path", "total_net_weight_kg"); put("document_id", "d"); put("original_value", 25400.0); put("value", 0) }))
        assertEquals("total_net_weight_kg in d: 25400 → 0", text)
        val withReason = describeEvent(event("FIELD_CORRECTED", buildJsonObject { put("path", "p"); put("document_id", "d"); put("value", "v"); put("reason", "0") }))
        assertTrue("a reason of '0' is text, and text counts", withReason!!.endsWith(" — 0"))
        assertNotNull(withReason)
    }
}
