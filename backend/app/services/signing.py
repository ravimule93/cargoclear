"""Signing the head of the audit chain: tamper-evidence that does not depend on the database.

The audit chain (services/audit.py) is hash-linked, so editing an event breaks every hash after it. But whoever can write the
whole collection can also rewrite the whole chain consistently. A SIGNATURE over the chain head with a key that the database
does not hold closes that gap: a rewritten history cannot carry a valid signature for the head it claims.

What is signed: ``{"purpose": "cargoclear.audit-head/1", "bundle_id", "seq", "hash"}`` (canonical JSON, SHA-256), the sequence
number and hash of the newest event at that moment. The signature goes into the chain itself as an ``AUDIT_HEAD_SIGNED`` event
(payload: ``signed_seq``, ``signed_hash``, ``signature`` (base64 DER), ``key``, ``algorithm``, ``signer``), so it is ordered,
hashed and verified like every other event. After a completed assessment the head is signed; events after the last
signature (a correction, say) are an "unsigned tail" until the next one, and the summary says how long it is.

Who signs: ``SIGNING_KEY_VERSION`` set -> Cloud KMS (an ``EC_SIGN_P256_SHA256`` key version; the private key never leaves KMS).
Unset -> demo mode signs with a throwaway in-process key (``signer: local-demo``; its public key rides in the event, so it
proves only that the chain was not edited since: it says nothing about WHO signed) and live mode does not sign at all
(``NOT_CONFIGURED``). Verifying a KMS signature fetches the key's public half from KMS (cached: a key version is immutable);
the key in an event is NEVER trusted.

What this is NOT: legal non-repudiation. There is no user authentication, so the signer is the operator's service, not a
person. The wording everywhere is "tamper-evident under the operator's key".
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

from app.core.config import settings
from app.services import audit

logger = structlog.get_logger(__name__)

EVENT_SIGNED = "AUDIT_HEAD_SIGNED"
EVENT_SIGNING_FAILED = "AUDIT_SIGNING_FAILED"
PURPOSE = "cargoclear.audit-head/1"
ALGORITHM = "ECDSA_P256_SHA256"
SIGNER_KMS, SIGNER_LOCAL = "kms", "local-demo"

_PREHASHED = ec.ECDSA(Prehashed(hashes.SHA256()))


def statement(bundle_id: str, seq: int, head_hash: str) -> bytes:
    """The exact bytes that are hashed and signed for one chain head."""
    return audit.canonical_json({"purpose": PURPOSE, "bundle_id": bundle_id, "seq": seq, "hash": head_hash}).encode("utf-8")


def digest_of(bundle_id: str, seq: int, head_hash: str) -> bytes:
    return hashlib.sha256(statement(bundle_id, seq, head_hash)).digest()


# ---------------------------------------------------------------------------
# signers
# ---------------------------------------------------------------------------


class Signer(Protocol):
    name: str          # "kms" | "local-demo"
    key_ref: str       # the KMS key version resource name, or "local-demo"

    async def sign(self, digest: bytes) -> bytes: ...

    def embedded_public_key(self) -> str | None: ...


class LocalSigner:
    """A throwaway ECDSA P-256 key held in this process: demo mode only, and never described as anything else."""

    name = SIGNER_LOCAL
    key_ref = "local-demo"

    def __init__(self) -> None:
        self._key = ec.generate_private_key(ec.SECP256R1())

    async def sign(self, digest: bytes) -> bytes:
        return self._key.sign(digest, _PREHASHED)

    def public_key(self) -> ec.EllipticCurvePublicKey:
        return self._key.public_key()

    def embedded_public_key(self) -> str:
        return self.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("ascii")


def _crc32c(data: bytes) -> int:
    import google_crc32c

    return int(google_crc32c.value(data))


class KmsSigner:
    """Signs digests with a Cloud KMS asymmetric key version. The request and the answer are integrity-checked (CRC32C), as
    Google's documentation requires: a corrupted digest or signature in transit must not become a stored signature."""

    name = SIGNER_KMS

    def __init__(self, key_version: str, client: Any = None) -> None:
        self.key_ref = key_version
        self._client = client

    def _kms(self) -> Any:
        if self._client is None:
            from google.cloud import kms_v1

            self._client = kms_v1.KeyManagementServiceAsyncClient()
        return self._client

    async def sign(self, digest: bytes) -> bytes:
        response = await self._kms().asymmetric_sign(
            request={"name": self.key_ref, "digest": {"sha256": digest}, "digest_crc32c": _crc32c(digest)}
        )
        if not response.verified_digest_crc32c:
            raise RuntimeError("KMS did not receive the digest intact")
        if response.name != self.key_ref:
            raise RuntimeError("KMS signed with a different key version than requested")
        if int(response.signature_crc32c) != _crc32c(response.signature):
            raise RuntimeError("the KMS signature was corrupted in transit")
        return bytes(response.signature)

    def embedded_public_key(self) -> str | None:
        return None  # never embedded: verification fetches it from KMS


_local_signer: LocalSigner | None = None


def get_signer() -> Signer | None:
    """The signer for this process, or None when signing is off (live mode without a key)."""
    global _local_signer
    if not settings.audit_signing:
        return None
    if settings.signing_key_version:
        return KmsSigner(settings.signing_key_version)
    if settings.app_mode == "demo":
        if _local_signer is None:
            _local_signer = LocalSigner()
        return _local_signer
    return None


# ---------------------------------------------------------------------------
# public keys (to verify)
# ---------------------------------------------------------------------------

_PUBLIC_KEYS: dict[str, Any] = {}
PublicKeyLoader = Callable[[str], Awaitable[Any]]


async def kms_public_key(key_version: str) -> Any:
    """The public key of a KMS key version (cached: a version never changes). Raises if KMS cannot be reached."""
    cached = _PUBLIC_KEYS.get(key_version)
    if cached is not None:
        return cached
    from google.cloud import kms_v1

    response = await kms_v1.KeyManagementServiceAsyncClient().get_public_key(request={"name": key_version})
    key = serialization.load_pem_public_key(response.pem.encode("ascii"))
    _PUBLIC_KEYS[key_version] = key
    return key


# ---------------------------------------------------------------------------
# signing the head
# ---------------------------------------------------------------------------


async def sign_head(bundle_id: str, *, iteration: int = 0) -> dict[str, Any] | None:
    """Sign the newest event of the bundle's chain and append the AUDIT_HEAD_SIGNED event; returns it.

    Returns None when signing is off or the chain is empty, and the existing event when the head IS a signature already.
    Raises when the signer fails: callers that must not fail (the end of a run) use ``sign_head_quietly``.
    """
    signer = get_signer()
    if signer is None:
        return None
    events = await audit.list_audit_events(bundle_id)
    if not events:
        return None
    head = events[-1]
    if head.get("event_type") == EVENT_SIGNED:
        return head

    signature = await signer.sign(digest_of(bundle_id, int(head["seq"]), str(head["hash"])))
    payload: dict[str, Any] = {
        "signed_seq": int(head["seq"]),
        "signed_hash": str(head["hash"]),
        "signature": base64.b64encode(signature).decode("ascii"),
        "key": signer.key_ref,
        "algorithm": ALGORITHM,
        "signer": signer.name,
        "signed_at": datetime.now(timezone.utc).isoformat(),
    }
    public_key = signer.embedded_public_key()
    if public_key:
        payload["public_key"] = public_key  # demo key only: a KMS key is never taken from the event
    recorded = await audit.record({
        "bundle_id": bundle_id,
        "iteration": iteration,
        "audit_event_type": EVENT_SIGNED,
        "audit_payload": payload,
        "actor": "system",
    })
    event: dict[str, Any] = recorded["audit_event"]
    logger.info("audit_head_signed", bundle_id=bundle_id, signed_seq=payload["signed_seq"], signer=signer.name)
    return event


async def sign_head_quietly(bundle_id: str, *, iteration: int = 0) -> None:
    """``sign_head`` for the end of a run: a signing outage must never fail an assessment. It is recorded instead (a
    ``AUDIT_SIGNING_FAILED`` event with the error TYPE only), so the gap is visible in the trail and the summary."""
    try:
        await sign_head(bundle_id, iteration=iteration)
    except Exception as exc:  # noqa: BLE001
        logger.error("audit_signing_failed", bundle_id=bundle_id, error_type=type(exc).__name__)
        try:
            await audit.record({
                "bundle_id": bundle_id,
                "iteration": iteration,
                "audit_event_type": EVENT_SIGNING_FAILED,
                "audit_payload": {"error_type": type(exc).__name__},
                "actor": "system",
            })
        except Exception:  # noqa: BLE001 - the original failure is already logged; the audit store being down is the same outage
            logger.error("audit_signing_failure_not_recorded", bundle_id=bundle_id)


# ---------------------------------------------------------------------------
# verifying
# ---------------------------------------------------------------------------


@dataclass
class SignatureCheck:
    event_seq: int
    signed_seq: int
    signed_hash: str
    signed_at: str | None
    signer: str
    key: str
    algorithm: str
    valid: bool | None        # None: could not be checked (the public key was unavailable)
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_seq": self.event_seq, "signed_seq": self.signed_seq, "signed_hash": self.signed_hash,
            "signed_at": self.signed_at, "signer": self.signer, "key": self.key, "algorithm": self.algorithm,
            "valid": self.valid, "reason": self.reason,
        }


async def check_signatures(
    events: list[dict[str, Any]], bundle_id: str, *, public_key_loader: PublicKeyLoader = kms_public_key
) -> list[SignatureCheck]:
    """Verify every AUDIT_HEAD_SIGNED event: it must sign a head that really is in the chain, with a signature that verifies
    under the right key. A local-demo signature is checked against the key embedded in its event (and says what that proves)."""
    by_seq = {int(e["seq"]): e for e in events if "seq" in e}
    checks: list[SignatureCheck] = []
    for event in events:
        if event.get("event_type") != EVENT_SIGNED:
            continue
        payload = event.get("payload") or {}
        check = SignatureCheck(
            event_seq=int(event["seq"]),
            signed_seq=int(payload.get("signed_seq", 0) or 0),
            signed_hash=str(payload.get("signed_hash", "")),
            signed_at=payload.get("signed_at"),
            signer=str(payload.get("signer", "")),
            key=str(payload.get("key", "")),
            algorithm=str(payload.get("algorithm", "")),
            valid=False,
        )
        checks.append(check)

        target = by_seq.get(check.signed_seq)
        if target is None or target.get("hash") != check.signed_hash or check.signed_seq >= check.event_seq:
            check.reason = "the signed head is not in the chain"
            continue
        if check.algorithm != ALGORITHM:
            check.reason = f"unsupported algorithm '{check.algorithm}'"
            continue
        try:
            signature = base64.b64decode(str(payload.get("signature", "")), validate=True)
        except ValueError:
            check.reason = "the signature is not readable"
            continue

        try:
            if check.signer == SIGNER_LOCAL:
                # The key in the event is data an attacker can write: it is never what a signature is checked against. A demo
                # signature counts only in demo mode without a KMS key, and only under the throwaway key THIS process holds.
                if settings.app_mode != "demo" or settings.signing_key_version:
                    check.reason = "a demo-key signature is not accepted here: only a Cloud KMS signature counts"
                    continue
                embedded = str(payload.get("public_key", "")).strip()
                if not embedded:
                    check.reason = "no public key in the event"
                    continue
                if _local_signer is None or embedded != _local_signer.embedded_public_key().strip():
                    check.valid, check.reason = None, "signed with the demo key of another process: it cannot be checked now"
                    continue
                key = _local_signer.public_key()
            elif check.signer == SIGNER_KMS and check.key:
                key = await public_key_loader(check.key)
            else:
                check.reason = f"unknown signer '{check.signer}'"
                continue
        except Exception as exc:  # noqa: BLE001 - KMS unreachable, no permission, a malformed key
            logger.warning("audit_public_key_unavailable", bundle_id=bundle_id, error_type=type(exc).__name__)
            check.valid, check.reason = None, "the public key could not be retrieved"
            continue

        if not isinstance(key, ec.EllipticCurvePublicKey):
            check.reason = "the key is not an elliptic-curve key"
            continue
        try:
            key.verify(signature, digest_of(bundle_id, check.signed_seq, check.signed_hash), _PREHASHED)
            check.valid = True
        except InvalidSignature:
            check.reason = "the signature does not match the signed head"
        except Exception:  # noqa: BLE001 - wrong key type and the like
            check.reason = "the signature could not be verified"
    return checks


_NOT_NON_REPUDIATION = "Not legal non-repudiation: there is no user authentication, so the signer is the service, not a person."


def _meaning(signer_name: str | None) -> str:
    """What a signature of this kind proves, in words the UI can show. A demo key proves less than a KMS key, and says so."""
    if signer_name == SIGNER_LOCAL:
        return (
            "Tamper-evident under the operator's key, here a throwaway demo key that only this process holds: it shows the chain was "
            "not edited after it was signed, in this session, and says nothing about who signed it. " + _NOT_NON_REPUDIATION
        )
    return (
        "Tamper-evident under the operator's key: the private key never leaves Cloud KMS, so the chain cannot be rewritten "
        "without the signature failing. " + _NOT_NON_REPUDIATION
    )


async def summarize(
    events: list[dict[str, Any]], bundle_id: str, *, public_key_loader: PublicKeyLoader = kms_public_key
) -> dict[str, Any]:
    """What the UI and the API say about the chain's signatures.

    ``status``: NOT_CONFIGURED (no signer and nothing ever signed), UNSIGNED (nothing signed yet), SIGNED (the newest event
    that is not a signature is covered), PARTIAL (signed earlier; ``unsigned_events`` come after), INVALID (a signature does
    not verify, or its head is not in the chain), UNVERIFIED (signatures exist and none failed, but a public key could not
    be retrieved).
    """
    signer = get_signer()
    checks = await check_signatures(events, bundle_id, public_key_loader=public_key_loader)
    substantive = [e for e in events if e.get("event_type") not in (EVENT_SIGNED, EVENT_SIGNING_FAILED)]
    last_seq = int(substantive[-1]["seq"]) if substantive else 0

    valid = [c for c in checks if c.valid is True]
    signed_through = max((c.signed_seq for c in valid), default=0)
    if any(c.valid is False for c in checks):
        status = "INVALID"
    elif not checks:
        status = "UNSIGNED" if signer is not None else "NOT_CONFIGURED"
    elif not valid:
        status = "UNVERIFIED"
    elif signed_through >= last_seq:
        status = "SIGNED" if all(c.valid is True for c in checks) else "UNVERIFIED"
    else:
        status = "PARTIAL"
    latest = checks[-1] if checks else None
    return {
        "status": status,
        "configured": signer is not None,
        "signer": latest.signer if latest else (signer.name if signer else None),
        "key": latest.key if latest else (signer.key_ref if signer else None),
        "signed_seq": signed_through or None,
        "unsigned_events": max(0, sum(1 for e in substantive if int(e["seq"]) > signed_through)),
        "failures": sum(1 for e in events if e.get("event_type") == EVENT_SIGNING_FAILED),
        "signatures": [c.as_dict() for c in checks],
        "meaning": _meaning(latest.signer if latest else (signer.name if signer else None)),
    }


def reset_for_tests() -> None:
    global _local_signer
    _local_signer = None
    _PUBLIC_KEYS.clear()
