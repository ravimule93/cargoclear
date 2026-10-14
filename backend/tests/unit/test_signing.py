"""Signing the head of the audit chain: what is signed, what verifies, and every way a rewritten history gets caught."""

from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

from app.core.config import settings
from app.gateway.errors import ConflictError
from app.services import audit, orchestrator, signing
from tests.helpers import api_client, create_bundle_with_documents, wait_for_run
from tests.unit.test_run_lifecycle import FILES, events_of

KMS_KEY = "projects/p/locations/asia-south1/keyRings/cargoclear/cryptoKeys/audit-head/cryptoKeyVersions/1"


@pytest.fixture
def signing_on(monkeypatch):
    monkeypatch.setattr(settings, "audit_signing", True)
    monkeypatch.setattr(settings, "signing_key_version", None)


async def append(bundle_id: str, event_type: str = "SYSTEM_EVENT", **payload: Any) -> dict[str, Any]:
    recorded = await audit.record({"bundle_id": bundle_id, "iteration": 1, "audit_event_type": event_type, "audit_payload": payload, "actor": "system"})
    return recorded["audit_event"]


async def chain(bundle_id: str) -> list[dict[str, Any]]:
    return await audit.list_audit_events(bundle_id)


# ---------------------------------------------------------------------------
# what is signed
# ---------------------------------------------------------------------------


def test_the_signed_statement_names_its_purpose_the_bundle_the_position_and_the_hash() -> None:
    assert signing.statement("bnd-1", 7, "abc") == b'{"bundle_id":"bnd-1","hash":"abc","purpose":"cargoclear.audit-head/1","seq":7}'
    assert signing.digest_of("bnd-1", 7, "abc") == hashlib.sha256(signing.statement("bnd-1", 7, "abc")).digest()
    assert signing.digest_of("bnd-2", 7, "abc") != signing.digest_of("bnd-1", 7, "abc"), "a signature of one bundle is not valid for another"


# ---------------------------------------------------------------------------
# signing and verifying (the local demo signer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_head_is_signed_into_the_chain_and_verifies(signing_on) -> None:
    for n in range(3):
        await append("bnd-1", n=n)
    event = await signing.sign_head("bnd-1", iteration=2)

    events = await chain("bnd-1")
    assert [e["event_type"] for e in events] == ["SYSTEM_EVENT"] * 3 + ["AUDIT_HEAD_SIGNED"] and events[-1] == event
    payload = event["payload"]
    assert (payload["signed_seq"], payload["signed_hash"]) == (3, events[2]["hash"]) and payload["algorithm"] == "ECDSA_P256_SHA256"
    assert payload["signer"] == "local-demo" and payload["key"] == "local-demo" and "BEGIN PUBLIC KEY" in payload["public_key"]
    assert audit.verify_audit_chain(events) == (True, None), "the signature event is an ordinary, hashed event of the chain"

    summary = await signing.summarize(events, "bnd-1")
    assert (summary["status"], summary["signed_seq"], summary["unsigned_events"], summary["signer"]) == ("SIGNED", 3, 0, "local-demo")
    assert [s["valid"] for s in summary["signatures"]] == [True]
    assert "operator's key" in summary["meaning"] and "Not legal non-repudiation" in summary["meaning"]


@pytest.mark.asyncio
async def test_signing_a_head_that_is_already_signed_changes_nothing(signing_on) -> None:
    await append("bnd-1")
    first = await signing.sign_head("bnd-1")
    again = await signing.sign_head("bnd-1")
    assert again == first and len(await chain("bnd-1")) == 2


@pytest.mark.asyncio
async def test_events_after_the_signature_are_an_unsigned_tail_until_the_next_signature(signing_on) -> None:
    await append("bnd-1")
    await signing.sign_head("bnd-1")
    await append("bnd-1", "FIELD_CORRECTED", path="consignee")
    await append("bnd-1", "FIELD_CORRECTED", path="incoterm")

    partial = await signing.summarize(await chain("bnd-1"), "bnd-1")
    assert (partial["status"], partial["signed_seq"], partial["unsigned_events"]) == ("PARTIAL", 1, 2)

    await signing.sign_head("bnd-1")
    signed = await signing.summarize(await chain("bnd-1"), "bnd-1")
    assert (signed["status"], signed["signed_seq"], signed["unsigned_events"]) == ("SIGNED", 4, 0)
    assert len(signed["signatures"]) == 2 and all(s["valid"] for s in signed["signatures"])


@pytest.mark.asyncio
async def test_a_chain_with_no_signature_is_unsigned_or_not_configured(signing_on, monkeypatch) -> None:
    await append("bnd-1")
    assert (await signing.summarize(await chain("bnd-1"), "bnd-1"))["status"] == "UNSIGNED"
    monkeypatch.setattr(settings, "audit_signing", False)
    off = await signing.summarize(await chain("bnd-1"), "bnd-1")
    assert (off["status"], off["configured"], off["signer"]) == ("NOT_CONFIGURED", False, None)
    assert await signing.sign_head("bnd-1") is None and len(await chain("bnd-1")) == 1


# ---------------------------------------------------------------------------
# every way of rewriting history is caught
# ---------------------------------------------------------------------------


def rebuild(events: list[dict[str, Any]], mutate) -> list[dict[str, Any]]:
    """What an attacker with write access to the whole collection does: edit an event, then recompute every hash after it so
    the hash chain is consistent again. (The signature, which they cannot recompute, is carried over unchanged.)"""
    rebuilt: list[dict[str, Any]] = []
    prev = "GENESIS"
    for event in events:
        copy = {**event, "payload": dict(event["payload"])}
        mutate(copy)
        copy["prev_hash"] = prev
        copy["hash"] = audit.compute_hash(prev, copy["seq"], copy["ts"], copy["bundle_id"], copy["iteration"], copy["event_type"], copy["actor"], copy["payload"])
        prev = copy["hash"]
        rebuilt.append(copy)
    return rebuilt


@pytest.mark.asyncio
async def test_a_history_rewritten_consistently_is_caught_by_the_signature(signing_on) -> None:
    for n in range(4):
        await append("bnd-1", n=n)
    await signing.sign_head("bnd-1")
    original = await chain("bnd-1")

    def edit(event: dict[str, Any]) -> None:
        if event["seq"] == 2:
            event["payload"]["n"] = "tampered"

    rewritten = rebuild(original, edit)
    assert audit.verify_audit_chain(rewritten) == (True, None), "the hash chain alone is fooled: every link was recomputed"
    summary = await signing.summarize(rewritten, "bnd-1")
    assert summary["status"] == "INVALID"
    assert [(s["valid"], s["reason"]) for s in summary["signatures"]] == [(False, "the signed head is not in the chain")]


@pytest.mark.asyncio
async def test_a_signature_cannot_be_moved_to_another_head_or_bundle(signing_on) -> None:
    await append("bnd-1")
    await append("bnd-1")
    event = await signing.sign_head("bnd-1")
    events = await chain("bnd-1")

    elsewhere = await signing.check_signatures(events, "bnd-OTHER")  # the same events presented as another bundle's
    assert [c.valid for c in elsewhere] == [False] and elsewhere[0].reason == "the signature does not match the signed head"

    moved = rebuild(events, lambda e: e["payload"].update(signed_seq=1, signed_hash=events[0]["hash"]) if e["event_type"] == "AUDIT_HEAD_SIGNED" else None)
    assert [c.valid for c in await signing.check_signatures(moved, "bnd-1")] == [False], "the signature was made for seq 2, not seq 1"
    assert event["payload"]["signed_seq"] == 2


@pytest.mark.asyncio
async def test_corrupt_or_forged_signatures_do_not_verify(signing_on) -> None:
    await append("bnd-1")
    await signing.sign_head("bnd-1")
    events = await chain("bnd-1")

    forged = ec.generate_private_key(ec.SECP256R1()).sign(signing.digest_of("bnd-1", 1, events[0]["hash"]), ec.ECDSA(Prehashed(hashes.SHA256())))
    cases = {
        "another key's signature": lambda p: p.update(signature=base64.b64encode(forged).decode()),
        "garbage": lambda p: p.update(signature=base64.b64encode(b"not a signature").decode()),
        "not base64": lambda p: p.update(signature="%%%"),
        "unsupported algorithm": lambda p: p.update(algorithm="RSA_SIGN_PKCS1_2048_SHA256"),
        "no public key": lambda p: p.pop("public_key"),
        "unknown signer": lambda p: p.update(signer="mystery"),
        "head not before the signature": lambda p: p.update(signed_seq=2),
    }
    for name, mutate in cases.items():
        broken = rebuild(events, lambda e, m=mutate: m(e["payload"]) if e["event_type"] == "AUDIT_HEAD_SIGNED" else None)
        assert [c.valid for c in await signing.check_signatures(broken, "bnd-1")] == [False], name
    assert (await signing.summarize(rebuild(events, lambda e: e["payload"].update(signature="%%%") if e["event_type"] == "AUDIT_HEAD_SIGNED" else None), "bnd-1"))["status"] == "INVALID"


def _forge_demo_signature(events: list[dict[str, Any]], bundle_id: str) -> list[dict[str, Any]]:
    """The attack on a signature whose public key rides in its own event: rewrite the history, drop the real signatures, sign the
    new head with a key of the attacker's own, and embed that key."""
    attacker = ec.generate_private_key(ec.SECP256R1())
    pem = attacker.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    history = [e for e in rebuild(events, lambda e: e["payload"].update(n="tampered") if e["seq"] == 1 else None) if e["event_type"] != "AUDIT_HEAD_SIGNED"]
    head = history[-1]
    seq = int(head["seq"]) + 1
    payload = {
        "signed_seq": head["seq"], "signed_hash": head["hash"], "algorithm": "ECDSA_P256_SHA256", "signer": "local-demo", "key": "local-demo",
        "public_key": pem, "signed_at": "2026-10-14T00:00:00+00:00",
        "signature": base64.b64encode(attacker.sign(signing.digest_of(bundle_id, head["seq"], head["hash"]), ec.ECDSA(Prehashed(hashes.SHA256())))).decode(),
    }
    forged = {"seq": seq, "ts": head["ts"], "bundle_id": bundle_id, "iteration": head["iteration"], "event_type": "AUDIT_HEAD_SIGNED", "actor": "system", "payload": payload}
    forged["prev_hash"] = head["hash"]
    forged["hash"] = audit.compute_hash(head["hash"], seq, forged["ts"], bundle_id, forged["iteration"], "AUDIT_HEAD_SIGNED", "system", payload)
    return [*history, forged]


@pytest.mark.asyncio
async def test_a_demo_signature_with_the_attackers_own_key_is_not_a_valid_signature(signing_on) -> None:
    for n in range(3):
        await append("bnd-1", n=n)
    await signing.sign_head("bnd-1")
    forged = _forge_demo_signature(await chain("bnd-1"), "bnd-1")
    assert audit.verify_audit_chain(forged) == (True, None), "the hash chain is consistent: only the signature can tell"

    summary = await signing.summarize(forged, "bnd-1")

    assert summary["status"] != "SIGNED", "a key the attacker wrote into the event must not make the chain look signed"
    assert [c["valid"] for c in summary["signatures"]] == [None]
    assert "another process" in summary["signatures"][0]["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("deployment", ["live mode", "a KMS key is configured"])
async def test_a_demo_signature_is_refused_where_only_kms_signatures_count(signing_on, monkeypatch, deployment) -> None:
    await append("bnd-1")
    await signing.sign_head("bnd-1")
    events = await chain("bnd-1")
    if deployment == "live mode":
        monkeypatch.setattr(settings, "app_mode", "live")
    else:
        monkeypatch.setattr(settings, "signing_key_version", "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")

    summary = await signing.summarize(events, "bnd-1", public_key_loader=lambda key: (_ for _ in ()).throw(AssertionError("KMS is not asked")))

    assert summary["status"] == "INVALID"
    assert summary["signatures"][0]["valid"] is False and "only a Cloud KMS signature counts" in summary["signatures"][0]["reason"]


@pytest.mark.asyncio
async def test_the_meaning_says_what_the_kind_of_signature_proves(signing_on) -> None:
    await append("bnd-1")
    await signing.sign_head("bnd-1")
    demo = (await signing.summarize(await chain("bnd-1"), "bnd-1"))["meaning"]
    assert "throwaway demo key" in demo and "says nothing about who signed" in demo and "Not legal non-repudiation" in demo
    assert "cannot be rewritten" not in demo, "a demo key does not promise that"
    assert "cannot be rewritten" in signing._meaning("kms") and "operator's key" in signing._meaning("kms")


# ---------------------------------------------------------------------------
# Cloud KMS
# ---------------------------------------------------------------------------


class FakeKms:
    """A stand-in for KeyManagementServiceAsyncClient backed by a real EC key, so signatures are real."""

    def __init__(self, *, verified: bool = True, name: str | None = None, corrupt: bool = False) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.requests: list[dict[str, Any]] = []
        self.verified, self.name, self.corrupt = verified, name, corrupt
        self.public_key_calls = 0

    async def asymmetric_sign(self, request: dict[str, Any]) -> Any:
        self.requests.append(request)
        signature = self.key.sign(request["digest"]["sha256"], ec.ECDSA(Prehashed(hashes.SHA256())))
        crc = signing._crc32c(signature) + (1 if self.corrupt else 0)
        return SimpleNamespace(signature=signature, name=self.name or request["name"], verified_digest_crc32c=self.verified, signature_crc32c=crc)

    async def get_public_key(self, request: dict[str, Any]) -> Any:
        self.public_key_calls += 1
        pem = self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        return SimpleNamespace(pem=pem)

    def loader(self):
        async def load(key_version: str) -> Any:
            return self.key.public_key()

        return load


@pytest.mark.asyncio
async def test_a_kms_signature_is_requested_with_integrity_checks_and_verifies_under_the_kms_public_key(monkeypatch) -> None:
    kms = FakeKms()
    monkeypatch.setattr(settings, "audit_signing", True)
    monkeypatch.setattr(settings, "signing_key_version", KMS_KEY)
    monkeypatch.setattr(signing, "get_signer", lambda: signing.KmsSigner(KMS_KEY, kms))  # the real signer, a fake KMS client
    await append("bnd-1")
    event = await signing.sign_head("bnd-1")

    [request] = kms.requests
    head = (await chain("bnd-1"))[0]
    assert request["name"] == KMS_KEY and request["digest"] == {"sha256": signing.digest_of("bnd-1", 1, head["hash"])}
    assert request["digest_crc32c"] == signing._crc32c(request["digest"]["sha256"])
    assert event["payload"]["signer"] == "kms" and event["payload"]["key"] == KMS_KEY and "public_key" not in event["payload"], "a KMS key is never taken from the event"

    events = await chain("bnd-1")
    assert [c.valid for c in await signing.check_signatures(events, "bnd-1", public_key_loader=kms.loader())] == [True]
    other = FakeKms()  # an attacker's key standing in for KMS
    assert [c.valid for c in await signing.check_signatures(events, "bnd-1", public_key_loader=other.loader())] == [False]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kms", "message"),
    [
        (FakeKms(verified=False), "did not receive the digest intact"),
        (FakeKms(name="projects/p/other/version/9"), "different key version"),
        (FakeKms(corrupt=True), "corrupted in transit"),
    ],
)
async def test_a_kms_answer_that_fails_its_integrity_checks_is_never_stored(kms, message) -> None:
    signer = signing.KmsSigner(KMS_KEY, kms)
    with pytest.raises(RuntimeError, match=message):
        await signer.sign(b"\x00" * 32)


@pytest.mark.asyncio
async def test_a_key_that_is_not_an_elliptic_curve_key_never_verifies(signing_on) -> None:
    from cryptography.hazmat.primitives.asymmetric import rsa

    kms = FakeKms()
    await append("bnd-1")
    signer = signing.KmsSigner(KMS_KEY, kms)
    import app.services.signing as module

    original = module.get_signer
    module.get_signer = lambda: signer
    try:
        await signing.sign_head("bnd-1")
    finally:
        module.get_signer = original
    events = await chain("bnd-1")

    async def rsa_key(key_version: str) -> Any:
        return rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()

    [check] = await signing.check_signatures(events, "bnd-1", public_key_loader=rsa_key)
    assert (check.valid, check.reason) == (False, "the key is not an elliptic-curve key")


@pytest.mark.asyncio
async def test_a_public_key_is_fetched_from_kms_once_and_an_outage_is_unverified_not_invalid(signing_on, monkeypatch) -> None:
    kms = FakeKms()
    signer = signing.KmsSigner(KMS_KEY, kms)
    monkeypatch.setattr(settings, "signing_key_version", KMS_KEY)
    monkeypatch.setattr(signing, "get_signer", lambda: signer)
    await append("bnd-1")
    await signing.sign_head("bnd-1")
    events = await chain("bnd-1")

    from google.cloud import kms_v1

    monkeypatch.setattr(kms_v1, "KeyManagementServiceAsyncClient", lambda: kms)
    assert (await signing.summarize(events, "bnd-1"))["status"] == "SIGNED"
    assert (await signing.summarize(events, "bnd-1"))["status"] == "SIGNED"
    assert kms.public_key_calls == 1, "a key version is immutable: fetched once"

    signing._PUBLIC_KEYS.clear()

    async def unreachable(key_version: str) -> Any:
        raise ConnectionError("KMS is unreachable")

    summary = await signing.summarize(events, "bnd-1", public_key_loader=unreachable)
    assert summary["status"] == "UNVERIFIED" and summary["signatures"][0]["valid"] is None
    assert summary["signatures"][0]["reason"] == "the public key could not be retrieved"


# ---------------------------------------------------------------------------
# who signs, and what a failure does
# ---------------------------------------------------------------------------


def test_the_signer_follows_the_configuration(monkeypatch) -> None:
    monkeypatch.setattr(settings, "audit_signing", False)
    assert signing.get_signer() is None, "switched off"

    monkeypatch.setattr(settings, "audit_signing", True)
    monkeypatch.setattr(settings, "app_mode", "demo")
    monkeypatch.setattr(settings, "signing_key_version", None)
    local = signing.get_signer()
    assert isinstance(local, signing.LocalSigner) and signing.get_signer() is local, "one throwaway key per process"

    monkeypatch.setattr(settings, "app_mode", "live")
    assert signing.get_signer() is None, "live mode without a key does not sign, and the summary says NOT_CONFIGURED"

    monkeypatch.setattr(settings, "signing_key_version", KMS_KEY)
    kms = signing.get_signer()
    assert isinstance(kms, signing.KmsSigner) and kms.key_ref == KMS_KEY
    monkeypatch.setattr(settings, "app_mode", "demo")
    assert isinstance(signing.get_signer(), signing.KmsSigner), "a configured KMS key wins in any mode"


@pytest.mark.asyncio
async def test_a_signing_failure_is_recorded_without_its_text_and_never_raised(signing_on, monkeypatch) -> None:
    class Broken:
        name, key_ref = "kms", KMS_KEY

        async def sign(self, digest: bytes) -> bytes:
            raise PermissionError("secret: the caller lacks cloudkms.cryptoKeyVersions.useToSign on projects/p")

        def embedded_public_key(self) -> None:
            return None

    monkeypatch.setattr(signing, "get_signer", lambda: Broken())
    await append("bnd-1")
    await signing.sign_head_quietly("bnd-1", iteration=3)

    events = await chain("bnd-1")
    assert [e["event_type"] for e in events] == ["SYSTEM_EVENT", "AUDIT_SIGNING_FAILED"]
    assert events[-1]["payload"] == {"error_type": "PermissionError"} and events[-1]["iteration"] == 3
    summary = await signing.summarize(events, "bnd-1")
    assert (summary["status"], summary["failures"], summary["unsigned_events"]) == ("UNSIGNED", 1, 1), "the gap is visible"
    with pytest.raises(PermissionError):
        await signing.sign_head("bnd-1")


# ---------------------------------------------------------------------------
# in the product: a completed assessment signs the head; the API reports and signs on demand
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_completed_assessment_signs_the_head_and_a_failing_signer_cannot_fail_it(signing_on, monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"
        audit_log = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
        types = [e["event_type"] for e in audit_log["events"]]
        assert types[-3:] == ["ANALYSIS_STARTED", "ASSESSMENT_COMPLETED", "AUDIT_HEAD_SIGNED"]
        assert audit_log["verified"] is True and audit_log["signature"]["status"] == "SIGNED"
        assert audit_log["signature"]["signer"] == "local-demo" and "operator's key" in audit_log["signature"]["meaning"]

        async def broken(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("kms down")

        monkeypatch.setattr(signing, "sign_head", broken)
        second = await orchestrator.start_run(bundle_id, mode="reassess")
        assert (await wait_for_run(bundle_id, second))["state"] == "COMPLETE", "the assessment is not hostage to the signer"
        failed = await events_of(client, bundle_id, "AUDIT_SIGNING_FAILED")
        assert [e["payload"] for e in failed] == [{"error_type": "RuntimeError"}]


@pytest.mark.asyncio
async def test_the_sign_endpoint_signs_the_current_head_on_demand(signing_on) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        before = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()["signature"]
        assert before["status"] == "UNSIGNED"

        signed = await client.post(f"/api/v1/bundles/{bundle_id}/audit/sign")
        assert signed.status_code == 200 and signed.json()["status"] == "SIGNED" and signed.json()["unsigned_events"] == 0
        again = await client.post(f"/api/v1/bundles/{bundle_id}/audit/sign")
        assert again.status_code == 200 and len(again.json()["signatures"]) == 1, "an already signed head is not signed twice"

        assert (await client.post("/api/v1/bundles/bnd-000000000000/audit/sign")).status_code == 404


@pytest.mark.asyncio
async def test_the_sign_endpoint_refuses_without_a_signer_and_on_a_broken_chain(monkeypatch) -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        off = await client.post(f"/api/v1/bundles/{bundle_id}/audit/sign")
        assert off.status_code == 409 and "not configured" in off.json()["message"]

        monkeypatch.setattr(settings, "audit_signing", True)
        audit._IN_MEMORY_AUDIT[bundle_id][0]["payload"] = {"tampered": True}
        broken = await client.post(f"/api/v1/bundles/{bundle_id}/audit/sign")
        assert broken.status_code == 409 and "does not verify" in broken.json()["message"]
