#!/usr/bin/env python3
"""Record the backend's real JSON for the Android tests, from a LOCAL DEMO backend (APP_MODE=demo, synthetic data only).

    cd backend && APP_MODE=demo .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
    python3 android/tools/record_fixtures.py [--base http://127.0.0.1:8080/api/v1]

    python3 android/tools/record_fixtures.py --only run-errors     # just the error answers of the run and upload endpoints
    python3 android/tools/record_fixtures.py --only viewer         # just the page geometry, the model's page image and their 404
    python3 android/tools/record_fixtures.py --only corrections    # just the Case D correction journey (corrections, audit, recompute, pre-fill)
    python3 android/tools/record_fixtures.py --only documents      # just removing a document and uploading with a declared type

Writes android/fixtures/*.json (and *.sse for raw event-stream transcripts). The Android unit tests decode these files, so the DTOs are
checked against what the backend really sends rather than against what someone remembers it sends. Re-run it when the API changes; the
diff of the fixtures is the diff of the contract. Standard library only. It refuses to run against a backend that is not in demo mode.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_MTC_FILENAME = "mtc_pipe_test_cert.pdf"  # the pipeline's demo fixtures are keyed on this exact name


def call(base: str, method: str, path: str, body: bytes | None = None, headers: dict | None = None, raw: bool = False):
    request = urllib.request.Request(f"{base}{path}", data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
            return response.status, (data if raw else json.loads(data or b"null"))
    except urllib.error.HTTPError as err:
        data = err.read()
        return err.code, (data if raw else json.loads(data or b"null"))


def post_json(base: str, path: str, payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    return call(base, "POST", path, body, {"Content-Type": "application/json"} if body else {})


def post_json_patiently(base: str, path: str, payload: dict | None = None):
    """Like post_json, but waits out the backend's per-client run limit (RATE_LIMIT_RUNS_PER_MINUTE, 10 by default).
    The first rate-limited answer seen is kept as a fixture of its own."""
    for _ in range(4):
        status, body = post_json(base, path, payload)
        if status != 429:
            return status, body
        if not (OUT / "error_rate_limited.json").exists():
            save("error_rate_limited.json", {"status": status, **body})
        wait = int((body.get("detail") or {}).get("retry_after_seconds", 10)) + 1
        print(f"  rate limited, waiting {wait}s")
        time.sleep(wait)
    raise SystemExit(f"still rate limited: {path}")


def upload(base: str, bundle_id: str, filename: str, pdf: bytes, declared_type: str | None = None):
    boundary = uuid.uuid4().hex
    declared = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="declared_type"\r\n\r\n{declared_type}\r\n'.encode() if declared_type else b""
    )
    body = (
        declared
        + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
        + pdf
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return call(base, "POST", f"/bundles/{bundle_id}/documents", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})


def save(name: str, payload) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"  wrote {name}")


def wait_for_iteration(base: str, bundle_id: str, number: int, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body = call(base, "GET", f"/bundles/{bundle_id}/assessment")
        if status == 200 and body["iteration"] >= number:
            return body
        time.sleep(0.5)
    raise SystemExit(f"timed out waiting for iteration {number} of {bundle_id}")


def start_stream_recorder(base: str, bundle_id: str, until_iteration: int, seconds: float = 60.0):
    """Start reading the SSE stream in the background; returns (thread, done-event, lines) so the transcript covers a whole run."""
    lines: list[str] = []
    done = threading.Event()

    def reader() -> None:
        request = urllib.request.Request(f"{base}/bundles/{bundle_id}/stream", headers={"Accept": "text/event-stream"})
        try:
            with urllib.request.urlopen(request, timeout=seconds) as response:
                for raw in response:
                    line = raw.decode("utf-8")
                    lines.append(line)
                    if line.startswith("data:") and f'"iteration": {until_iteration}' in line and '"bundle_id"' in line and '"checks"' in line:
                        done.set()
                        return
        except Exception:  # noqa: BLE001 - the transcript is what it is
            done.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    time.sleep(1.0)  # let it connect before the run starts, so the transcript shows the whole run
    return thread, done, lines


def record_run_errors(base: str) -> None:
    """The answers the run and upload endpoints give when they refuse: the app words them (runErrorMessage, uploadErrorMessage) from these codes."""
    print("run and upload errors")
    _, empty = post_json(base, "/bundles", {"reference": "ANDROID-ERRORS", "destination_country": "SG"})
    status, body = post_json_patiently(base, f"/bundles/{empty['id']}/analyze")
    save("error_analyze_empty_bundle.json", {"status": status, **body})

    boundary = uuid.uuid4().hex
    text = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="notes.txt"\r\nContent-Type: text/plain\r\n\r\nhello\r\n--{boundary}--\r\n'.encode()
    )
    status, body = call(base, "POST", f"/bundles/{empty['id']}/documents", text, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    save("error_upload_not_pdf.json", {"status": status, **body})
    status, body = upload(base, empty["id"], "empty.pdf", b"")
    save("error_upload_empty.json", {"status": status, **body})

    _, case_d = post_json(base, "/demo/case-d")
    did = case_d["id"]
    status, body = post_json_patiently(base, f"/bundles/{did}/recompute")
    save("error_recompute_nothing_to_reuse.json", {"status": status, **body})
    status, body = post_json_patiently(base, f"/bundles/{did}/analyze")
    assert status == 202, (status, body)
    status, body = post_json_patiently(base, f"/bundles/{did}/analyze")  # a second request while the first run is going
    assert status == 409, (status, body)
    save("error_run_already_in_progress.json", {"status": status, **body})
    wait_for_iteration(base, did, 1)  # leave the demo backend idle


def record_viewer(base: str) -> None:
    """What the document viewer reads: the transform metadata of an analysed document, the page image the model was shown, and the 404 a document gets before it has been analysed."""
    print("viewer")
    _, bundle = post_json(base, "/demo/case-c")
    cid = bundle["id"]
    first = bundle["documents"][0]["document_id"]
    status, body = call(base, "GET", f"/bundles/{cid}/documents/{first}/transform-metadata")
    save("error_transform_metadata_not_found.json", {"status": status, **body})  # nothing has been preprocessed yet

    status, run = post_json_patiently(base, f"/bundles/{cid}/analyze")
    assert status == 202, (status, run)
    wait_for_iteration(base, cid, 1)
    status, meta = call(base, "GET", f"/bundles/{cid}/documents/{first}/transform-metadata")
    assert status == 200, (status, meta)
    save("transform_metadata_demo.json", meta)
    status, png = call(base, "GET", f"/bundles/{cid}/documents/{first}/pages/1", raw=True)
    assert status == 200 and png[:4] == b"\x89PNG", status
    (OUT / "page_processed_demo.png").write_bytes(png)
    print("  wrote page_processed_demo.png")
    _, pdf = call(base, "GET", f"/bundles/{cid}/documents/{first}/file", raw=True)
    print(f"  (the document file is {len(pdf)} bytes, a %PDF: {pdf[:4] == b'%PDF'})")


def record_corrections(base: str) -> None:
    """The whole Case D correction journey: correct the Cr cell of the certificate, confirm a value, sign, recompute, undo; what each step answers.

    The answers are what the corrections card, the correction editor, the Reasoning Delta and the audit chain read. Case D is the demo's
    contradiction: certificate cell test_results[20] says Cr 0.35 %, which makes the declared non-alloy HS code wrong; 0.28 does not."""
    print("corrections")
    _, bundle = post_json(base, "/demo/case-d")
    did = bundle["id"]
    cert = next(d["document_id"] for d in bundle["documents"] if "mtc" in d["filename"])
    invoice = next(d["document_id"] for d in bundle["documents"] if "invoice" in d["filename"])

    status, body = post_json(base, f"/bundles/{did}/corrections", {"document_id": cert, "path": "test_results[20]", "value": "0.28", "unit": "%"})
    save("error_correction_before_analysis.json", {"status": status, **body})  # nothing to correct before the first analysis

    status, run = post_json_patiently(base, f"/bundles/{did}/analyze")
    assert status == 202, (status, run)
    first = wait_for_iteration(base, did, 1)
    save("case_d_extractions.json", call(base, "GET", f"/bundles/{did}/extractions?iteration=1")[1])
    save("case_d_corrections_none.json", call(base, "GET", f"/bundles/{did}/corrections")[1])
    save("case_d_audit_signed.json", call(base, "GET", f"/bundles/{did}/audit")[1])

    status, body = post_json(base, f"/bundles/{did}/corrections", {"document_id": "doc-does-not-exist", "path": "consignee", "value": "X"})
    save("error_correction_unknown_document.json", {"status": status, **body})
    status, body = post_json(base, f"/bundles/{did}/corrections", {"document_id": invoice, "path": "total_gross_weight_kg", "value": "1,234.5.6", "unit": "KGS"})
    save("error_correction_unreadable_value.json", {"status": status, **body})

    status, corrected = post_json(base, f"/bundles/{did}/corrections", {"document_id": cert, "path": "test_results[20]", "value": "0.28", "unit": "%", "reason": "the certificate prints 0.28"})
    assert status == 201, (status, corrected)
    save("correction_created.json", corrected)
    status, confirmed = post_json(base, f"/bundles/{did}/corrections", {"document_id": invoice, "path": "consignee", "value": "MUMBAI INFRA PIPING PVT LTD"})
    assert status == 201 and confirmed["kind"] == "confirmation", (status, confirmed)
    save("correction_confirmed.json", confirmed)
    save("case_d_corrections_pending.json", call(base, "GET", f"/bundles/{did}/corrections")[1])
    save("case_d_audit_partial.json", call(base, "GET", f"/bundles/{did}/audit")[1])  # events after the signed head

    status, signed = post_json(base, f"/bundles/{did}/audit/sign")
    assert status == 200, (status, signed)
    save("audit_sign_response.json", signed)

    status, run = post_json_patiently(base, f"/bundles/{did}/recompute")
    assert status == 202, (status, run)
    second = wait_for_iteration(base, did, 2)
    save("case_d_assessment_recomputed.json", second)
    save("case_d_extractions_recomputed.json", call(base, "GET", f"/bundles/{did}/extractions?iteration=2")[1])
    save("case_d_corrections_applied.json", call(base, "GET", f"/bundles/{did}/corrections")[1])

    status, reverted = post_json(base, f"/bundles/{did}/corrections/{corrected['correction_id']}/revert", {"reason": None})
    assert status == 201 and reverted["kind"] == "revert", (status, reverted)
    save("correction_reverted.json", reverted)
    save("case_d_corrections_undone.json", call(base, "GET", f"/bundles/{did}/corrections")[1])
    status, body = post_json(base, f"/bundles/{did}/corrections/cor-999/revert", {"reason": None})
    save("error_revert_not_in_force.json", {"status": status, **body})
    save("case_d_audit_after_undo.json", call(base, "GET", f"/bundles/{did}/audit")[1])

    # the pre-fill pack, as the app downloads it (a file it hands on without reading)
    status, pack = call(base, "GET", f"/bundles/{did}/prefill?iteration=2&download=true")
    assert status == 200, status
    save("case_d_prefill.json", pack)
    status, pdf = call(base, "GET", f"/bundles/{did}/prefill.pdf?iteration=2", raw=True)
    assert status == 200 and pdf[:4] == b"%PDF", status
    (OUT / "case_d_prefill.pdf").write_bytes(pdf)
    print(f"  wrote case_d_prefill.pdf ({len(pdf)} bytes)")
    print(f"  (assessment 1 {first['status']}, assessment 2 {second['status']}, delta: {second['reasoning_delta']['narrative'][:90]})")


def record_documents(base: str) -> None:
    """Taking a document out of a bundle, and uploading a file with a declared type: what the app's delete and upload calls read back.

    Case D is analysed once; its packing list is removed (the newest assessment used it, so the answer says so), a removal while a run is going is
    refused (409), an unknown document is a 404, and a declared type the server does not know is a 422. The sample certificate goes up with a declared type."""
    print("documents")
    _, bundle = post_json(base, "/demo/case-d")
    did = bundle["id"]
    packing = next(d["document_id"] for d in bundle["documents"] if "packing" in d["filename"])

    status, run = post_json_patiently(base, f"/bundles/{did}/analyze")
    assert status == 202, (status, run)
    status, body = call(base, "DELETE", f"/bundles/{did}/documents/{packing}")  # the run has just started: refused
    assert status == 409, (status, body)
    save("error_document_delete_run_in_progress.json", {"status": status, **body})
    wait_for_iteration(base, did, 1)

    status, body = call(base, "DELETE", f"/bundles/{did}/documents/doc-0000000000000000")
    assert status == 404, (status, body)
    save("error_document_delete_not_found.json", {"status": status, **body})

    status, removed = call(base, "DELETE", f"/bundles/{did}/documents/{packing}")
    assert status == 200 and removed["in_latest_assessment"] is True, (status, removed)
    save("document_deleted.json", removed)
    _, after = call(base, "GET", f"/bundles/{did}")
    print(f"  (the bundle now holds {len(after['documents'])} documents)")

    _, empty = post_json(base, "/bundles", {"reference": "ANDROID-DECLARED", "destination_country": "SG"})
    _, mtc = call(base, "GET", "/demo/case-c/mtc", raw=True)
    status, body = upload(base, empty["id"], SAMPLE_MTC_FILENAME, mtc, declared_type="NOT A TYPE")
    assert status == 422, (status, body)
    save("error_declared_type_unknown.json", {"status": status, **body})
    status, doc = upload(base, empty["id"], SAMPLE_MTC_FILENAME, mtc, declared_type="mill test certificate")
    assert status == 201 and doc["declared_type"] == "MILL_TEST_CERTIFICATE", (status, doc)
    save("document_uploaded_declared.json", doc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8080/api/v1")
    parser.add_argument("--only", choices=["run-errors", "viewer", "corrections", "documents"], help="record only this group of fixtures")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    status, meta = call(base, "GET", "/meta")
    if status != 200 or meta.get("app_mode") != "demo":
        sys.exit(f"refusing to record: {base} is not a demo backend ({status} {meta})")
    print("recording from", base)
    if args.only == "run-errors":
        record_run_errors(base)
        print("done")
        return
    if args.only == "viewer":
        record_viewer(base)
        print("done")
        return
    if args.only == "corrections":
        record_corrections(base)
        print("done")
        return
    if args.only == "documents":
        record_documents(base)
        print("done")
        return
    save("meta_demo.json", meta)

    status, unknown = call(base, "GET", "/bundles/bnd-does-not-exist")
    save("error_bundle_not_found.json", {"status": status, **unknown})

    # ---- Case C: three documents -> MISSING_EVIDENCE -> add the sample certificate -> COMPLIANT_FOR_SUBMISSION
    print("case C")
    _, bundle = post_json(base, "/demo/case-c")
    cid = bundle["id"]
    save("case_c_bundle_new.json", bundle)

    _thread, done, lines = start_stream_recorder(base, cid, until_iteration=1)
    _, run = post_json(base, f"/bundles/{cid}/analyze", {"mode": "full"})
    save("run_response_analyze.json", run)
    first = wait_for_iteration(base, cid, 1)
    save("case_c_assessment_missing_evidence.json", first)
    done.wait(10)
    transcript = "".join(lines)
    if not transcript.endswith("\r\n\r\n"):  # the reader stops at the iteration's data line, before the blank line that ends the event
        transcript = transcript.rstrip("\r\n") + "\r\n\r\n"
    (OUT / "stream_case_c_first_run.sse").write_bytes(transcript.encode("utf-8"))
    print("  wrote stream_case_c_first_run.sse")

    _, bundle = call(base, "GET", f"/bundles/{cid}")
    save("case_c_bundle_analyzed.json", bundle)

    _, mtc = call(base, "GET", "/demo/case-c/mtc", raw=True)
    status, doc = upload(base, cid, SAMPLE_MTC_FILENAME, mtc)
    assert status == 201, (status, doc)
    save("document_uploaded.json", doc)
    post_json(base, f"/bundles/{cid}/reassess", {"mode": "full"})
    second = wait_for_iteration(base, cid, 2)
    save("case_c_assessment_compliant.json", second)
    _, iterations = call(base, "GET", f"/bundles/{cid}/iterations")
    save("case_c_iterations.json", iterations)
    _, bundle = call(base, "GET", f"/bundles/{cid}")
    save("case_c_bundle_final.json", bundle)

    # ---- Case D: an import into India; the certificate contradicts the declared HS code
    print("case D")
    _, bundle = post_json(base, "/demo/case-d")
    did = bundle["id"]
    save("case_d_bundle_new.json", bundle)
    post_json(base, f"/bundles/{did}/analyze", {"mode": "full"})
    contradiction = wait_for_iteration(base, did, 1)
    save("case_d_assessment_contradiction.json", contradiction)
    _, bundle = call(base, "GET", f"/bundles/{did}")
    save("case_d_bundle_analyzed.json", bundle)

    # ---- an empty bundle and the "not analysed yet" answers
    print("empty bundle")
    _, empty = post_json(base, "/bundles", {"reference": "ANDROID-FIXTURE", "destination_country": "IN"})
    save("bundle_empty_created.json", empty)
    status, none_yet = call(base, "GET", f"/bundles/{empty['id']}/assessment")
    save("error_assessment_not_found.json", {"status": status, **none_yet})
    record_run_errors(base)
    record_viewer(base)
    record_corrections(base)
    print("done")


if __name__ == "__main__":
    main()
