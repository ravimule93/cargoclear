package com.cargoclear.japac.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/*
 * The tamper-evident audit chain of a bundle and what its signature says. Port of the types in frontend/lib/types.ts and the wording in
 * components/audit/AuditTimeline.tsx. The backend sends these as plain dicts (GET /bundles/{id}/audit), so there is no Pydantic model to
 * mirror: backend/tests/unit/test_android_contract.py compares the names below with the code that builds the dicts.
 */

/** One entry of the chain: an event with the hash that links it to the one before. */
@Serializable
data class AuditEvent(
    @SerialName("event_id") val eventId: String,
    @SerialName("bundle_id") val bundleId: String,
    val iteration: Int,
    val seq: Int,
    /** ISO-8601 (note: `ts`, not `timestamp`) */
    val ts: String,
    val actor: String,
    @SerialName("event_type") val eventType: String,
    val payload: JsonObject = JsonObject(emptyMap()),
    @SerialName("prev_hash") val prevHash: String,
    val hash: String,
)

/** One AUDIT_HEAD_SIGNED event, checked: [valid] is null when the public key could not be retrieved. */
@Serializable
data class SignatureCheck(
    @SerialName("event_seq") val eventSeq: Int,
    @SerialName("signed_seq") val signedSeq: Int,
    @SerialName("signed_hash") val signedHash: String,
    @SerialName("signed_at") val signedAt: String? = null,
    /** "kms" (Cloud KMS) or "local-demo" (a throwaway key: it shows the chain was not edited, not who signed) */
    val signer: String,
    val key: String,
    val algorithm: String,
    val valid: Boolean? = null,
    val reason: String? = null,
)

/** What the chain's signatures say: tamper-evidence under the operator's key, never legal non-repudiation. */
@Serializable
data class AuditSignature(
    /** Read through [statusKind]: the wire value is a plain string. */
    val status: String,
    val configured: Boolean,
    val signer: String? = null,
    val key: String? = null,
    @SerialName("signed_seq") val signedSeq: Int? = null,
    /** events after the newest signed one */
    @SerialName("unsigned_events") val unsignedEvents: Int = 0,
    /** AUDIT_SIGNING_FAILED events recorded */
    val failures: Int = 0,
    val signatures: List<SignatureCheck> = emptyList(),
    /** What a signature of this kind proves, in the backend's words (it differs for a demo key and a Cloud KMS key). */
    val meaning: String,
) {
    val statusKind: SignatureStatus? get() = SignatureStatus.fromWire(status)
}

@Serializable
data class AuditResponse(
    val events: List<AuditEvent> = emptyList(),
    val verified: Boolean,
    val error: String? = null,
    val signature: AuditSignature? = null,
)

enum class SignatureStatus(val wire: String) {
    NOT_CONFIGURED("NOT_CONFIGURED"),
    UNSIGNED("UNSIGNED"),
    SIGNED("SIGNED"),
    PARTIAL("PARTIAL"),
    INVALID("INVALID"),
    UNVERIFIED("UNVERIFIED");

    companion object {
        /** Null for a status a newer backend adds: shown as "not recognised", never as one of these. */
        fun fromWire(value: String?): SignatureStatus? = entries.firstOrNull { it.wire == value }
    }
}

/** How a line of the history is tinted; always shown with words as well, never colour alone. */
enum class Tone { OK, WARN, ERR }

/** The one-line answer to "is this history signed, and does the signature hold?" */
data class SignatureSummary(val text: String, val tone: Tone)

private val SIGNER_LABEL = mapOf("kms" to "Cloud KMS key", "local-demo" to "demo key, not KMS")

/** The words of [AuditSignature] the web shows under the chain badge (`describeSignature` in AuditTimeline.tsx). */
fun describeSignature(signature: AuditSignature): SignatureSummary {
    val who = SIGNER_LABEL[signature.signer.orEmpty()] ?: signature.signer ?: "unknown key"
    return when (signature.statusKind) {
        SignatureStatus.SIGNED -> SignatureSummary("Head signed through #${signature.signedSeq} ($who)", Tone.OK)
        SignatureStatus.PARTIAL -> SignatureSummary(
            "Signed through #${signature.signedSeq} ($who); ${signature.unsignedEvents} later event${if (signature.unsignedEvents == 1) "" else "s"} not signed yet",
            Tone.WARN,
        )
        SignatureStatus.UNSIGNED -> SignatureSummary("Head not signed yet", Tone.WARN)
        SignatureStatus.INVALID -> SignatureSummary("A signature does NOT verify: the history may have been rewritten", Tone.ERR)
        SignatureStatus.UNVERIFIED -> SignatureSummary("Signed, but the public key could not be retrieved to verify it", Tone.WARN)
        SignatureStatus.NOT_CONFIGURED -> SignatureSummary("Signing is not configured for this service", Tone.WARN)
        // the web calls anything else "not configured"; saying so about a status this app cannot read would be a guess
        null -> SignatureSummary("The signature status (${signature.status}) is not recognised by this version of the app", Tone.WARN)
    }
}

/** "Sign now" is offered when signing is set up and the newest events are not covered yet. */
fun canSignNow(signature: AuditSignature): Boolean =
    signature.configured && signature.statusKind.let { it == SignatureStatus.UNSIGNED || it == SignatureStatus.PARTIAL }

/** The chain badge: either the chain verifies, or the reason it does not. */
fun chainBadge(audit: AuditResponse): SignatureSummary =
    if (audit.verified) SignatureSummary("Chain verified", Tone.OK) else SignatureSummary("Chain BROKEN: ${audit.error ?: "unknown reason"}", Tone.ERR)

private const val SHORT_HASH_LENGTH = 12

/** A hash as shown in a row: "GENESIS" and other short markers whole, a digest cut after twelve characters. */
fun shortHash(hash: String): String = if (hash.length > SHORT_HASH_LENGTH) hash.take(SHORT_HASH_LENGTH) + "…" else hash

private fun JsonElement?.shown(fallback: String): String = when (this) {
    null, JsonNull -> fallback
    is JsonPrimitive -> jsText(this).ifEmpty { fallback }
    else -> toString()
}

private fun JsonElement?.truthy(): Boolean = when (this) {
    null, JsonNull -> false
    // JavaScript truthiness, as the web's `p.reason ? ...`: a non-empty string is true even when it reads "0"
    is JsonPrimitive -> if (isString) content.isNotEmpty() else content != "false" && content.toBigDecimalOrNull()?.signum() != 0
    else -> true
}

/** One line of detail for the events a person causes (corrections) and the signing events; the machine events need none. */
fun describeEvent(event: AuditEvent): String? {
    val p = event.payload
    fun reasonSuffix() = if (p["reason"].truthy()) " — ${p["reason"].shown("")}" else ""
    return when (event.eventType) {
        "FIELD_CORRECTED" ->
            "${p["path"].shown("?")} in ${p["document_id"].shown("?")}: ${p["original_value"].shown("(not stated)")} → ${p["value"].shown("(cleared)")}${reasonSuffix()}"
        "FIELD_CONFIRMED" -> "${p["path"].shown("?")} in ${p["document_id"].shown("?")}: confirmed as ${p["value"].shown("(not stated)")}"
        "CORRECTION_REVERTED" ->
            "undid ${p["reverts"].shown("?")} (${p["path"].shown("?")} in ${p["document_id"].shown("?")})${reasonSuffix()}"
        "AUDIT_HEAD_SIGNED" ->
            "signed the chain head at #${p["signed_seq"].shown("?")} (${if (p["signer"].shown("") == "kms") "Cloud KMS" else "demo key, not KMS"})"
        "AUDIT_SIGNING_FAILED" -> "signing the chain head failed (${p["error_type"].shown("error")}); the chain itself is unaffected"
        else -> null
    }
}
