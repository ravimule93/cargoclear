"""Safety contract for the operator-only bundle cleanup utility."""

from __future__ import annotations

from tests.helpers import load_script


cleanup = load_script("clean_bundles.py")


def test_cleanup_enumerates_all_bundle_owned_subcollections(monkeypatch) -> None:
    paths: list[str] = []

    def empty_listing(_token: str, path: str, **_kwargs):
        paths.append(path)
        return {}

    monkeypatch.setattr(cleanup, "firestore_request", empty_listing)
    cleanup.delete_bundle_subcollections("token", "bnd-12345678")
    assert paths == [
        "bundles/bnd-12345678/documents?pageSize=300",
        "bundles/bnd-12345678/runs?pageSize=300",
        "bundles/bnd-12345678/iterations?pageSize=300",
        "bundles/bnd-12345678/extractions?pageSize=300",
        "bundles/bnd-12345678/audit?pageSize=300",
        "bundles/bnd-12345678/control?pageSize=300",
    ]


def test_cleanup_refuses_malformed_bundle_ids() -> None:
    assert cleanup.BUNDLE_ID_RE.fullmatch("bnd-abc12345")
    assert not cleanup.BUNDLE_ID_RE.fullmatch("bnd-../../etc")


def test_storage_cleanup_uses_argument_list_not_a_shell(monkeypatch) -> None:
    calls = []

    def record(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(cleanup.subprocess, "run", record)
    cleanup.delete_gcs_files("bnd-12345678")
    assert calls == [
        ((["gsutil", "-m", "rm", "-r", f"gs://{cleanup.RAW_BUCKET}/bundles/bnd-12345678"],),
         {"capture_output": True, "text": True, "check": True})
    ]
