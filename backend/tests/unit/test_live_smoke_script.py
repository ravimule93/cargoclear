"""scripts/live_smoke_extraction.py, tested with a fake Gemini client: no network, no credentials.

The real run is done by a person (see Handoff.md). Here the script's own logic is verified: what it compares,
what gates the exit code, what it refuses to do, and that --dry-run touches neither the network nor the credentials.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents import extraction
from app.core import mode
from app.core.config import settings
from app.domain.schemas import BBox, FieldRef, QuantityRef
from tests.helpers import CASE_C_DIR, REPO_ROOT, load_script
from tests.unit.extraction_fakes import FakeGenai, response

script = load_script("live_smoke_extraction.py")
CASE_C = CASE_C_DIR
PDFS = {path.read_bytes(): path.name for path in sorted(CASE_C.glob("*.pdf"))}


def fixture_json(filename: str) -> dict[str, Any]:
    """What a flawless extraction of this PDF returns: exactly the values and boxes the PDF was drawn from."""
    return extraction._generate_fixture_for_file("model-id", filename).model_dump(mode="json")


def answer_by_pdf(tweak=None):
    """Outcome function: the fixture answer for whichever PDF the request carries, optionally edited."""
    def outcome(_n: int, kwargs: dict[str, Any]):
        inline = next(p.inline_data for p in kwargs["contents"] if getattr(p, "inline_data", None) is not None)
        filename = PDFS[bytes(inline.data)]
        doc = fixture_json(filename)
        if tweak is not None:
            tweak(filename, doc)
        return response(doc)

    return outcome


@pytest.fixture(autouse=True)
def passthrough_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever the machine has installed, pages are the raw PDF (no poppler needed, nothing rendered)."""
    import pdf2image
    from pdf2image.exceptions import PDFInfoNotInstalledError

    def no_poppler(*_a, **_kw):
        raise PDFInfoNotInstalledError("poppler is not available")

    monkeypatch.setattr(pdf2image, "convert_from_bytes", no_poppler)
    monkeypatch.setattr(pdf2image, "convert_from_path", no_poppler)  # the pages of a plan are rendered from a file on disk


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """APP_MODE=live with a credentials PATH that points at an empty file; the script must never read it."""
    key = tmp_path / "not-a-real-key.json"
    key.write_text("")
    monkeypatch.setattr(settings, "app_mode", "live")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(key))
    return key


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch):
    def _install(outcome) -> FakeGenai:
        fake = FakeGenai(outcome)
        monkeypatch.setattr(extraction, "_get_genai_client", lambda: fake)
        return fake

    return _install


async def smoke(tmp_path: Path, *argv: str):
    args = script.parse_args(["--out", str(tmp_path / "out"), *argv])
    return await script.run_smoke(args)


def rows(report: dict[str, Any], filename: str, run: int = 0) -> dict[str, dict[str, Any]]:
    entry = next(d for d in report["documents"] if d["file"] == filename)
    return {r["name"]: r for r in entry["runs"][run]["check"]["rows"]}


# ---------------------------------------------------------------------------
# a flawless extraction passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_flawless_extraction_of_all_four_pdfs_passes(live, install, tmp_path, capsys) -> None:
    fake = install(answer_by_pdf())

    report, code = await smoke(tmp_path)

    assert code == 0 and report["passed"] is True and report["failures"] == []
    assert len(fake.calls) == 4
    assert sorted(d["file"] for d in report["documents"]) == sorted(PDFS.values())
    for entry in report["documents"]:
        [run] = entry["runs"]
        assert run["check"]["failed"] == []
        assert run["check"]["iou_mean"] == 1.0  # the boxes are exactly the ones the PDF was drawn from
        assert run["check"]["bbox"]["bbox_pct"] == 100.0
        assert run["check"]["doc_type_confidence"] > 0.9
        assert run["warnings"] == []
        assert {"attempts", "latency_ms", "prompt_tokens", "output_tokens"} <= set(run["stats"])
    out = capsys.readouterr().out
    assert "synthetic Case C documents only: do not run it on real customer documents" in out
    assert "RESULT: PASS" in out
    assert "line_items[0].hs_code_declared" in out and "total_net_weight_kg" in out


@pytest.mark.asyncio
async def test_the_report_is_written_and_contains_no_document_bytes(live, install, tmp_path) -> None:
    install(answer_by_pdf())

    report, _ = await smoke(tmp_path)

    [written] = (tmp_path / "out").glob("report-*.json")
    text = written.read_text()
    assert json.loads(text)["passed"] is True
    assert "%PDF" not in text and "payload" not in text and "_pages" not in text
    assert set(json.loads(text)["environment"]) >= {"project", "location", "model", "sdk_version", "credential_source", "pages"}
    assert json.loads(text)["environment"]["pages"] == "passthrough"


@pytest.mark.asyncio
async def test_the_environment_block_names_the_credential_source_but_never_its_content(live, install, tmp_path, capsys) -> None:
    install(answer_by_pdf())

    await smoke(tmp_path, "--docs", str(CASE_C / "packing_list.pdf"))

    out = capsys.readouterr().out
    assert "GOOGLE_APPLICATION_CREDENTIALS env var" in out
    assert str(live) not in out and "not-a-real-key" not in out
    assert settings.gemini_live_model in out and settings.gemini_live_location in out and settings.project_id in out
    assert "RAW PDF PASSTHROUGH" in out and "bbox.page is unreliable" in out and "brew install poppler" in out


# ---------------------------------------------------------------------------
# what gates the exit code
# ---------------------------------------------------------------------------


def hs_of_invoice(code: str):
    def tweak(filename: str, doc: dict[str, Any]) -> None:
        if filename == "commercial_invoice.pdf":
            doc["line_items"][0]["hs_code_declared"]["value"] = code

    return tweak


@pytest.mark.asyncio
async def test_a_wrong_hs_code_fails(live, install, tmp_path, capsys) -> None:
    install(answer_by_pdf(hs_of_invoice("73041100")))

    report, code = await smoke(tmp_path)

    assert code == 1 and report["passed"] is False
    assert rows(report, "commercial_invoice.pdf")["line_items[0].hs_code_declared"]["status"] == "MISMATCH"
    assert "commercial_invoice.pdf: line_items[0].hs_code_declared" in report["failures"]
    assert "RESULT: FAIL" in capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize("printed", ["7304.19.00", "7304 19 00", "7304190000", 73041900])
async def test_hs_codes_compare_as_digits_so_formatting_does_not_matter(live, install, tmp_path, printed) -> None:
    install(answer_by_pdf(hs_of_invoice(printed)))

    _, code = await smoke(tmp_path)

    assert code == 0


@pytest.mark.asyncio
async def test_a_six_digit_hs_code_is_not_enough(live, install, tmp_path) -> None:
    install(answer_by_pdf(hs_of_invoice("730419")))

    report, code = await smoke(tmp_path)

    assert code == 1
    assert rows(report, "commercial_invoice.pdf")["line_items[0].hs_code_declared"]["status"] == "MISMATCH"


def doc_type_of_bol(wrong: str):
    def tweak(filename: str, doc: dict[str, Any]) -> None:
        if filename == "bill_of_lading.pdf":
            doc["doc_type"] = wrong

    return tweak


@pytest.mark.asyncio
async def test_a_wrong_doc_type_fails(live, install, tmp_path) -> None:
    install(answer_by_pdf(doc_type_of_bol("PACKING_LIST")))

    report, code = await smoke(tmp_path)

    assert code == 1
    row = rows(report, "bill_of_lading.pdf")["doc_type"]
    assert (row["expected"], row["extracted"], row["status"]) == ("BILL_OF_LADING", "PACKING_LIST", "MISMATCH")


def net_weight_of_packing_list(value: Any, unit: Any):
    def tweak(filename: str, doc: dict[str, Any]) -> None:
        if filename == "packing_list.pdf":
            doc["total_net_weight_kg"]["value"] = value
            doc["total_net_weight_kg"]["unit"] = unit

    return tweak


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "unit", "passes"),
    [
        ("14000.0", "KGS", True),
        ("14,000.0", "KGS", True),
        ("14.0", "MT", True),             # tonnes are converted
        ("30865.0", "LBS", True),         # 14000.1 kg
        ("14069.0", "KGS", True),         # +69 kg  = +0.493 %, inside the 70 kg tolerance
        ("13931.0", "KGS", True),         # -69 kg  = -0.493 %
        ("14071.0", "KGS", False),        # +71 kg  = +0.507 %
        ("13929.0", "KGS", False),        # -71 kg  = -0.507 %
        ("14.0", "KGS", False),           # the unit matters
        ("fourteen thousand", "KGS", False),
    ],
)
async def test_weights_are_compared_in_kg_within_half_a_percent(live, install, tmp_path, value, unit, passes) -> None:
    install(answer_by_pdf(net_weight_of_packing_list(value, unit)))

    report, code = await smoke(tmp_path)

    row = rows(report, "packing_list.pdf")["total_net_weight_kg"]
    assert (row["status"] == "OK") is passes, row
    assert (code == 0) is passes


@pytest.mark.asyncio
async def test_a_weight_without_a_unit_is_read_as_kg_and_says_so(live, install, tmp_path) -> None:
    install(answer_by_pdf(net_weight_of_packing_list("14000.0", None)))

    report, code = await smoke(tmp_path)

    row = rows(report, "packing_list.pdf")["total_net_weight_kg"]
    assert code == 0 and row["status"] == "OK"
    assert "assumed kg" in row["note"]


@pytest.mark.asyncio
async def test_a_missing_gating_field_fails_as_missing(live, install, tmp_path) -> None:
    def tweak(filename: str, doc: dict[str, Any]) -> None:
        if filename == "mtc_pipe_test_cert.pdf":
            doc["hs_code_header"] = {"value": None, "confidence": 0.0, "bbox": None}

    install(answer_by_pdf(tweak))

    report, code = await smoke(tmp_path)

    assert code == 1
    assert rows(report, "mtc_pipe_test_cert.pdf")["hs_code_header"]["status"] == "MISSING"


@pytest.mark.asyncio
async def test_entity_and_document_number_mismatches_are_reported_but_do_not_gate(live, install, tmp_path, capsys) -> None:
    def tweak(filename: str, doc: dict[str, Any]) -> None:
        doc["consignee"]["value"] = "SOMEONE ELSE LTD"
        doc["document_number"]["value"] = "XX-0"

    install(answer_by_pdf(tweak))

    report, code = await smoke(tmp_path)

    assert code == 0
    row = rows(report, "commercial_invoice.pdf")
    assert row["consignee"]["status"] == "MISMATCH" and row["document_number"]["status"] == "MISMATCH"
    assert row["consignee"]["gating"] is False
    assert "(not gating)" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_consignee_punctuation_and_case_do_not_matter(live, install, tmp_path) -> None:
    def tweak(filename: str, doc: dict[str, Any]) -> None:
        doc["consignee"]["value"] = doc["consignee"]["value"].title().replace(" Pte Ltd", " Pte. Ltd.")

    install(answer_by_pdf(tweak))

    report, _ = await smoke(tmp_path)

    assert rows(report, "commercial_invoice.pdf")["consignee"]["status"] == "OK"


@pytest.mark.asyncio
async def test_bad_boxes_and_low_confidence_are_reported_but_never_gate(live, install, tmp_path) -> None:
    def tweak(filename: str, doc: dict[str, Any]) -> None:
        doc["doc_type_confidence"] = 0.4
        for name in ("consignee", "consignor", "document_number", "total_net_weight_kg"):
            ref = doc.get(name)
            if ref:
                ref["confidence"] = 0.31
                if ref["bbox"]:  # x and y swapped: the classic convention mistake
                    box = ref["bbox"]
                    box["ymin"], box["xmin"], box["ymax"], box["xmax"] = box["xmin"], box["ymin"], box["xmax"], box["ymax"]

    install(answer_by_pdf(tweak))

    report, code = await smoke(tmp_path)

    assert code == 0, "box quality and confidence must not gate"
    check = report["documents"][0]["runs"][0]["check"]
    assert check["iou_mean"] is not None and check["iou_mean"] < 1.0
    assert check["lowest_expected_confidence"] == 0.31


@pytest.mark.asyncio
async def test_boxes_dropped_by_the_sanitiser_are_listed_per_document(live, install, tmp_path, capsys) -> None:
    def tweak(filename: str, doc: dict[str, Any]) -> None:
        if filename == "packing_list.pdf":
            doc["consignee"]["bbox"]["ymax"] = 9999

    install(answer_by_pdf(tweak))

    report, code = await smoke(tmp_path)

    run = next(d for d in report["documents"] if d["file"] == "packing_list.pdf")["runs"][0]
    assert code == 0
    assert [w["path"] for w in run["warnings"]] == ["consignee.bbox"]
    assert rows(report, "packing_list.pdf")["consignee"]["iou"] is None
    assert "consignee.bbox: bounding box dropped" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_a_failed_extraction_is_reported_not_raised(live, install, tmp_path, capsys) -> None:
    from google.genai import errors

    def outcome(n: int, kwargs: dict[str, Any]):
        return errors.APIError(404, {"error": {"code": 404, "message": "x", "status": "NOT_FOUND"}})

    install(outcome)

    report, code = await smoke(tmp_path)

    assert code == 1
    assert all("error" in d["runs"][0] for d in report["documents"])
    assert any("extraction failed" in f for f in report["failures"])
    out = capsys.readouterr().out
    assert "EXTRACTION FAILED" in out and "GEMINI_LIVE_MODEL" in out  # the hint reaches the operator


@pytest.mark.asyncio
async def test_a_file_outside_case_c_is_extracted_but_cannot_pass_or_fail(live, install, tmp_path, capsys) -> None:
    stray = tmp_path / "some_other_invoice.pdf"
    stray.write_bytes((CASE_C / "commercial_invoice.pdf").read_bytes())
    install(answer_by_pdf())

    report, code = await smoke(tmp_path, "--docs", str(stray))

    assert code == 1  # nothing could be verified
    assert report["documents"][0]["has_expectations"] is False
    assert any("no document had expectations" in f for f in report["failures"])
    assert "no expectations for this file" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_unchecked_files_do_not_hide_the_checked_ones(live, install, tmp_path) -> None:
    stray = tmp_path / "some_other_invoice.pdf"
    stray.write_bytes((CASE_C / "commercial_invoice.pdf").read_bytes())
    install(answer_by_pdf())

    report, code = await smoke(tmp_path, "--docs", str(stray), str(CASE_C / "packing_list.pdf"))

    assert code == 0 and report["failures"] == []


# ---------------------------------------------------------------------------
# --runs: agreement across runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_identical_runs_agree_completely(live, install, tmp_path, capsys) -> None:
    fake = install(answer_by_pdf())

    report, code = await smoke(tmp_path, "--runs", "3", "--docs", str(CASE_C / "packing_list.pdf"))

    assert code == 0 and len(fake.calls) == 3
    [entry] = report["documents"]
    assert len(entry["runs"]) == 3
    assert entry["agreement"]["pct"] == 100.0 and entry["agreement"]["disagreeing"] == {}
    assert "agreement across 3 runs for packing_list.pdf" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_runs_that_disagree_on_a_field_are_reported(live, install, tmp_path) -> None:
    def outcome(n: int, kwargs: dict[str, Any]):
        doc = fixture_json("packing_list.pdf")
        doc["consignee"]["value"] = "ACME ONE" if n % 2 else "ACME TWO"
        return response(doc)

    install(outcome)

    report, code = await smoke(tmp_path, "--runs", "4", "--docs", str(CASE_C / "packing_list.pdf"))

    agreement = report["documents"][0]["agreement"]
    assert code == 0  # an entity mismatch does not gate
    assert set(agreement["disagreeing"]) == {"consignee"}
    assert agreement["disagreeing"]["consignee"] == ["ACME ONE", "ACME TWO"]
    assert agreement["identical_every_run"] == agreement["fields"] - 1


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def test_it_refuses_to_run_outside_live_mode(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(settings, "app_mode", "demo")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "k.json"))

    assert script.main(["--out", str(tmp_path)]) == 2

    captured = capsys.readouterr()
    assert "APP_MODE" in captured.err and "live" in captured.err
    assert captured.out == ""
    assert not list(tmp_path.glob("report-*"))


def test_it_refuses_in_live_mode_without_credentials(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(settings, "app_mode", "live")

    assert script.main(["--out", str(tmp_path)]) == 2

    err = capsys.readouterr().err
    assert mode.NO_CREDENTIALS_MESSAGE in err
    assert "gcloud auth application-default login" in err


def test_the_refusal_names_a_key_file_path_that_does_not_exist(monkeypatch, tmp_path, capsys) -> None:
    missing = tmp_path / "gone" / "key.json"
    monkeypatch.setattr(settings, "app_mode", "live")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(missing))

    assert script.refusal_reason() == mode.no_credentials_message()
    assert script.main(["--out", str(tmp_path)]) == 2

    err = capsys.readouterr().err
    assert mode.NO_CREDENTIALS_MESSAGE in err
    assert f"GOOGLE_APPLICATION_CREDENTIALS points to '{missing}', which does not exist." in err


def test_a_dry_run_also_refuses_outside_live_mode(monkeypatch, capsys) -> None:
    monkeypatch.setattr(settings, "app_mode", "demo")
    assert script.main(["--dry-run"]) == 2


def test_help_needs_neither_live_mode_nor_credentials(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        script.main(["--help"])

    assert raised.value.code == 0
    out = " ".join(capsys.readouterr().out.split())  # argparse wraps long lines
    for option in ("--docs", "--runs", "--overlay", "--dry-run", "--out", "synthetic Case C documents only"):
        assert option in out


@pytest.mark.parametrize("bad", [["--runs", "0"], ["--docs", "/no/such/file.pdf"]])
def test_bad_arguments_are_rejected(bad) -> None:
    with pytest.raises(SystemExit) as raised:
        script.parse_args(bad)
    assert raised.value.code == 2


# ---------------------------------------------------------------------------
# --dry-run: the exact request, zero network, credentials untouched
# ---------------------------------------------------------------------------


def test_a_dry_run_prints_the_exact_request_and_touches_neither_network_nor_credentials(
    live, monkeypatch, tmp_path, capsys
) -> None:
    os.chmod(live, 0)  # reading this file would raise PermissionError
    orig_connect = socket.socket.connect

    def guarded_connect(self, *a, **k):
        addr = a[0] if a else k.get("address")
        if isinstance(addr, tuple) and addr[0] in ("127.0.0.1", "localhost", "::1"):
            return orig_connect(self, *a, **k)
        raise AssertionError("network call attempted")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    def forbidden_client():
        raise AssertionError("the real client (which reads credentials) must not be created in a dry run")

    monkeypatch.setattr(extraction, "_get_genai_client", forbidden_client)

    try:
        code = script.main(["--dry-run", "--out", str(tmp_path)])
    finally:
        os.chmod(live, 0o600)

    assert code == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "No network call is made and no credential is read" in out
    assert settings.gemini_live_model in out and settings.gemini_live_location in out and settings.project_id in out
    assert "thinking_budget=0" in out and "max_output_tokens=16384" in out and "response_mime_type=application/json" in out
    for name in PDFS.values():
        assert name in out
    assert out.count("response schema:") == 4 and "request=" in out and "parts=2" in out
    assert "raw PDF passthrough" in out
    assert not list(tmp_path.glob("report-*")), "a dry run writes no report"


def test_a_dry_run_shows_page_labels_when_pages_are_images(live, monkeypatch, tmp_path, capsys) -> None:
    import pdf2image
    from PIL import Image

    from app.services import preprocess

    monkeypatch.setattr(pdf2image, "convert_from_bytes", lambda *_a, **_k: [Image.new("RGB", (40, 60), "white")] * 2)
    monkeypatch.setattr(preprocess, "_plan_pages", lambda _raw: None)  # the renderer is faked: no real file to plan pages for

    assert script.main(["--dry-run", "--docs", str(CASE_C / "packing_list.pdf"), "--out", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "labels=['Page 1 of 2.', 'Page 2 of 2.']" in out and "parts=5" in out and "(png)" in out


def test_a_dry_run_says_when_a_document_would_be_refused(live, monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(settings, "gemini_max_request_mb", 0.0001)

    assert script.main(["--dry-run", "--docs", str(CASE_C / "packing_list.pdf"), "--out", str(tmp_path)]) == 0

    assert "WOULD BE REFUSED before any call" in capsys.readouterr().out


def test_a_dry_run_notes_when_the_thinking_field_is_not_sent(live, monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(settings, "gemini_thinking_budget", -1)

    assert script.main(["--dry-run", "--docs", str(CASE_C / "packing_list.pdf"), "--out", str(tmp_path)]) == 0

    assert "(field not sent)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# --overlay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overlays_are_saved_per_page_when_pages_are_images(live, install, monkeypatch, tmp_path, capsys) -> None:
    import pdf2image
    from PIL import Image
    from app.services import upload_checks

    monkeypatch.setattr(pdf2image, "convert_from_path", lambda *_a, **_k: [Image.new("RGB", (300, 400), "white")])  # a plan's pages come from a file
    monkeypatch.setattr(pdf2image, "convert_from_bytes", lambda *_a, **_k: [Image.new("RGB", (300, 400), "white")])
    monkeypatch.setattr(upload_checks, "read_pdf_facts", lambda *_a, **_k: SimpleNamespace(pages=1, page_sizes=[(1, 300.0, 400.0)], has_js=False))
    order = iter(sorted(PDFS.values()))

    def shifted(_n: int, _kw: dict[str, Any]):
        """Boxes 20 units lower than the printed ones, so the red (extracted) box does not hide the green (expected) one."""
        doc = fixture_json(next(order))
        for ref in [v for v in doc.values() if isinstance(v, dict) and v.get("bbox")]:
            ref["bbox"]["ymin"] += 20
            ref["bbox"]["ymax"] += 20
        return response(doc)

    install(shifted)

    report, code = await smoke(tmp_path, "--overlay")

    overlays = tmp_path / "out" / "overlays"
    assert code == 0
    assert sorted(p.name for p in overlays.iterdir()) == sorted(f"{Path(n).stem}.page1.png" for n in PDFS.values())
    image = Image.open(overlays / "packing_list.page1.png")
    assert image.size == (300, 400)
    colours = {colour for _count, colour in image.convert("RGB").getcolors(maxcolors=100_000)}
    assert (220, 0, 0) in colours and (0, 160, 0) in colours  # both the extracted and the expected boxes are drawn
    assert report["environment"]["pages"] == "png"
    assert "overlay:" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_overlay_is_skipped_with_advice_for_a_raw_pdf(live, install, tmp_path, capsys) -> None:
    install(answer_by_pdf())

    _, code = await smoke(tmp_path, "--overlay", "--docs", str(CASE_C / "packing_list.pdf"))

    assert code == 0
    assert not (tmp_path / "out" / "overlays").exists()
    assert "overlay skipped" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# the pure helpers
# ---------------------------------------------------------------------------


def box(page=1, ymin=100, xmin=100, ymax=200, xmax=200) -> BBox:
    return BBox(page=page, ymin=ymin, xmin=xmin, ymax=ymax, xmax=xmax)


def test_iou() -> None:
    assert script.iou(box(), box()) == 1.0
    assert script.iou(box(), box(ymin=300, ymax=400)) == 0.0
    assert script.iou(box(), box(page=2)) == 0.0
    assert script.iou(box(), box(xmin=150, xmax=250)) == pytest.approx(1 / 3)
    assert script.iou(box(ymin=0, xmin=0, ymax=1000, xmax=1000), box()) == pytest.approx(0.01)


def test_bbox_stats_flags_a_zero_to_one_scale() -> None:
    from app.domain.schemas import ExtractedDocument

    def doc(**boxes) -> ExtractedDocument:
        return ExtractedDocument(document_id="d", doc_type="PACKING_LIST", doc_type_confidence=0.9,
                                 consignee=FieldRef(value="A", confidence=0.9, **boxes),
                                 consignor=FieldRef(value="B", confidence=0.9))

    unit_scale = doc(bbox=BBox(page=1, ymin=0.1, xmin=0.1, ymax=0.2, xmax=0.2))
    stats = script.bbox_stats(unit_scale)
    assert stats["scale_suspect"] is True and stats["with_bbox"] == 1 and stats["populated_fields"] == 2
    assert stats["bbox_pct"] == 50.0

    assert script.bbox_stats(doc(bbox=box()))["scale_suspect"] is False
    assert script.bbox_stats(doc())["with_bbox"] == 0


def test_expectations_come_from_the_fixture_and_nothing_is_duplicated_in_the_script() -> None:
    expected = extraction._generate_fixture_for_file("x", "mtc_pipe_test_cert.pdf")

    names = [e.name for e in script.build_expectations(expected)]

    assert names[0] == "doc_type"
    assert {"hs_code_header", "line_items[0].hs_code_declared", "line_items[0].net_weight_kg", "consignee"} <= set(names)
    source = (REPO_ROOT / "scripts" / "live_smoke_extraction.py").read_text()
    for literal in ("73041900", "14280", "14000", "SINGAPORE PRECISION", "BHARAT SEAMLESS", "INV-2024"):
        assert literal not in source, f"{literal!r} is duplicated in the script; read it from the fixture instead"


def test_locate_walks_headers_and_line_items() -> None:
    doc = extraction._generate_fixture_for_file("x", "commercial_invoice.pdf")
    assert script.locate(doc, ("line_items", 0, "hs_code_declared")).value == "73041900"
    assert script.locate(doc, ("line_items", 5, "hs_code_declared")) is None
    assert script.locate(doc, ("tare_weight_kg",)) is None
    assert script.locate(doc, ("doc_type",)) == "COMMERCIAL_INVOICE"


def test_weight_kg_reads_units_the_way_the_engine_does() -> None:
    assert script.weight_kg(QuantityRef(value="14,280.50", unit="KGS", confidence=1.0)) == (14280.5, "")
    assert script.weight_kg(QuantityRef(value="14.28", unit="MT", confidence=1.0))[0] == pytest.approx(14280.0)
    assert script.weight_kg(FieldRef(value="14280 KGS", confidence=1.0))[0] == 14280.0  # unit printed in the value
    kg, note = script.weight_kg(FieldRef(value="14280", confidence=1.0))
    assert kg == 14280.0 and "assumed kg" in note
    assert script.weight_kg(FieldRef(value="lots", confidence=1.0))[0] is None
    assert script.weight_kg(QuantityRef(value="5", unit="parsecs", confidence=1.0))[0] is None


def test_the_documented_weight_tolerance() -> None:
    assert script.WEIGHT_TOLERANCE == 0.005


# ---------------------------------------------------------------------------
# Phase 1: the certificate's table (heats, chemistry, strengths) and the terms of sale gate the exit code
# ---------------------------------------------------------------------------


def mtc_expectations():
    expected = extraction._generate_fixture_for_file("model-id", "mtc_pipe_test_cert.pdf")
    return expected, script.build_expectations(expected)


def check_mtc(mutate):
    expected, expectations = mtc_expectations()
    actual = expected.model_copy(deep=True)
    mutate(actual)
    return script.check_document(expectations, actual)


def test_the_certificate_table_becomes_expectations_keyed_by_heat_and_parameter() -> None:
    expected, expectations = mtc_expectations()
    by_name = {e.name: e for e in expectations}

    assert by_name["specification"].gating and by_name["heat_numbers[0]"].kind == "heat"
    assert len([e for e in expectations if e.kind == "lab"]) == len(expected.test_results) == 30
    assert "test_results[H-24-0882.Cr]" in by_name and by_name["test_results[H-24-0882.Cr]"].gating


def test_a_flawless_reading_of_the_certificate_passes_every_gate() -> None:
    report = check_mtc(lambda doc: None)

    assert report["failed"] == [] and all(r["status"] == "OK" for r in report["rows"])


def test_a_wrong_chemistry_value_fails_that_cell_and_names_it() -> None:
    def misread(doc):
        row = next(r for r in doc.test_results if r.heat_number == "H-24-0882" and r.parameter == "Cr")
        row.value = "0.35"                      # the page says 0.09

    report = check_mtc(misread)

    assert report["failed"] == ["test_results[H-24-0882.Cr]"]
    failing = next(r for r in report["rows"] if r["status"] != "OK")
    assert failing["expected"] == "0.09 %" and failing["note"] == "read 0.35 %"


def test_the_table_may_come_back_in_another_order() -> None:
    report = check_mtc(lambda doc: doc.test_results.reverse())

    assert report["failed"] == []


def test_a_heading_spelt_out_or_a_number_in_another_unit_is_the_same_value() -> None:
    def respell(doc):
        for row in doc.test_results:
            if row.parameter == "Mn":
                row.parameter = "Manganese"
            if row.parameter == "YS" and row.heat_number == "H-24-0881":
                row.value, row.unit = "44.96", "ksi"        # 310 MPa

    assert check_mtc(respell)["failed"] == []


def test_a_missing_row_a_missing_heat_and_a_misread_standard_each_fail() -> None:
    def damage(doc):
        doc.test_results = [r for r in doc.test_results if not (r.heat_number == "H-24-0881" and r.parameter == "S")]
        doc.heat_numbers = doc.heat_numbers[:1]
        doc.specification.value = "API 5L PSL1 GR.B"

    failed = check_mtc(damage)["failed"]

    assert set(failed) == {"test_results[H-24-0881.S]", "heat_numbers[1]", "specification"}


def test_an_upper_bound_is_not_the_same_as_an_exact_value() -> None:
    def bound(doc):
        next(r for r in doc.test_results if r.heat_number == "H-24-0881" and r.parameter == "P").value = "<0.015"

    assert check_mtc(bound)["failed"] == ["test_results[H-24-0881.P]"]


def test_the_origin_is_compared_by_country_not_by_spelling() -> None:
    expected = extraction._generate_fixture_for_file("model-id", "commercial_invoice.pdf")
    expectations = script.build_expectations(expected)
    actual = expected.model_copy(deep=True)
    actual.country_of_origin.value = "REPUBLIC OF INDIA"
    assert script.check_document(expectations, actual)["failed"] == []

    actual.country_of_origin.value = "CHINA"
    assert script.check_document(expectations, actual)["failed"] == ["country_of_origin"]


def test_boxes_of_table_cells_count_in_the_box_statistics() -> None:
    expected = extraction._generate_fixture_for_file("model-id", "mtc_pipe_test_cert.pdf")

    stats = script.bbox_stats(expected)

    assert stats["with_bbox"] >= 30 and stats["bbox_pct"] == 100.0 and not stats["scale_suspect"]
