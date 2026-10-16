"""Input-gating audit, offline half: what the product does with the fixtures in tests/fixtures/gating, with NO Gemini call and no
credentials (docs/input-gating-audit.md). The live half, which measures tokens, is tests/gating/run_live_gating.py.

Each test states what the claim "irrelevant or hostile PDF content is rejected or stripped before it reaches an expensive Gemini
call" requires. A test the product passes is an ordinary test. A test it fails is ``xfail(strict=True)`` with the finding in its
reason: the suite stays green, and the day someone fixes the finding the test starts passing, strict mode turns that into a failure,
and the marker has to come off. Nothing in the product is changed by this file. Fix items 1-3 of the audit (the upload checks, the
page-size budget, no raw-PDF fallback) have been applied: their tests are ordinary tests now, and so are those of every later item
(10 and 11 included): no xfail is left, which is not the same as every risk being closed (section 8 of the audit lists what is not).

Gemini is replaced by a counting fake that answers every request with the same valid answer, so the tests can ask "was it called,
how many times, with how many pages", which is exactly what cost depends on.

    cd backend && .venv/bin/python -m pytest tests/gating -o addopts="" -q
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import structlog

from app.core.config import settings
from app.services import relevance
from tests.gating import harness
from tests.gating.harness import fixture
from tests.helpers import REPO_ROOT, api_client, wait_for_run

BACKEND = REPO_ROOT / "backend"

# ---------------------------------------------------------------------------
# a counting stand-in for Vertex AI
# ---------------------------------------------------------------------------


def _answer(doc_type: str = "UNKNOWN", extra: dict[str, Any] | None = None) -> str:
    return json.dumps({"doc_type": doc_type, "doc_type_confidence": 0.9, "fields": [], "heat_numbers": [], "line_cells": [],
                       "test_results": [], **(extra or {})})


class FakeVertex:
    """``client.aio.models.generate_content`` that records each request and answers one scripted document type. The relevance
    gate's request (a 24-token cap) is told apart and answered with ``gate`` (a kind, or an exception to raise)."""

    def __init__(self, doc_type: str = "UNKNOWN", extra: dict[str, Any] | None = None, gate: str | Exception = "COMMERCIAL_INVOICE") -> None:
        self.doc_type, self.extra, self.gate = doc_type, extra, gate
        self.finish = "STOP"  # "MAX_TOKENS": the extraction answer is cut off at the output cap
        self.requests: list[dict[str, Any]] = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    @property
    def gate_requests(self) -> list[dict[str, Any]]:
        return [r for r in self.requests if r["gate"]]

    @property
    def extraction_requests(self) -> list[dict[str, Any]]:
        """What the expensive call received: every request that is not the gate's."""
        return [r for r in self.requests if not r["gate"]]

    async def _generate(self, *, model: str, contents: Any, config: Any) -> Any:
        gate = isinstance(getattr(config, "response_schema", None), dict)  # the gate's schema is a plain dict; extraction's is a model
        self.requests.append({"model": model, "shape": harness.request_shape(contents), "config": config, "gate": gate, "contents": contents})
        if gate and isinstance(self.gate, Exception):
            raise self.gate
        return SimpleNamespace(
            text=json.dumps({"kind": self.gate}) if gate else (_answer(self.doc_type, self.extra) if self.finish == "STOP" else '{"doc_type": "COMM'),
            candidates=[SimpleNamespace(finish_reason="STOP" if gate else self.finish)], prompt_feedback=None,
            usage_metadata=SimpleNamespace(prompt_token_count=1000, candidates_token_count=50, thoughts_token_count=0, total_token_count=1050,
                                           prompt_tokens_details=None),
        )


@pytest.fixture
def vertex(monkeypatch) -> FakeVertex:
    fake = FakeVertex()
    harness.install_meter(fake, monkeypatch)  # the same meter the live run uses, in front of the fake
    return fake


def pages_sent(fake: FakeVertex) -> int:
    return sum(r["shape"]["image_parts"] + r["shape"]["pdf_parts"] for r in fake.extraction_requests)


async def _upload_one(name: str, data: bytes | None = None, *, upload_as: str = "commercial_invoice.pdf") -> harness.Upload:
    async with api_client() as client:
        created = await client.post("/api/v1/bundles", json={"reference": "GATING", "destination_country": "SG"})
        return await harness.upload(client, created.json()["id"], upload_as, data if data is not None else fixture(name))


async def _analyse(files: list[tuple[str, bytes]], *, mode: str = "analyze") -> harness.BundleRun:
    async with api_client() as client:
        return await harness.run_bundle(client, files, timeout=60.0, mode=mode)


# ---------------------------------------------------------------------------
# C1  file validation before any model call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "status", "fragment"),
    [
        ("f07a_zip_renamed.pdf", 422, "not a PDF"),
        ("f07b_exe_renamed.pdf", 422, "not a PDF"),
        ("f08a_user_password.pdf", 422, "Password-protected"),
        ("f03_300_pages.pdf", 422, "The document has 300 pages; the limit is 100."),
    ],
)
async def test_c1_c2_the_upload_route_refuses_these_before_anything_is_stored(name: str, status: int, fragment: str) -> None:
    result = await _upload_one(name)
    assert result.status == status and fragment in (result.message or "")


async def test_c1_an_empty_file_is_refused() -> None:
    assert (await _upload_one("-", b"")).status == 422


async def test_c2_the_caps_are_settings_with_documented_defaults() -> None:
    env_example = (BACKEND / ".env.example").read_text(encoding="utf-8")
    assert (settings.max_upload_mb, settings.gemini_max_pages, settings.gemini_max_request_mb) == (50, 30, 18)
    for name in ("MAX_UPLOAD_MB", "GEMINI_MAX_PAGES", "GEMINI_MAX_REQUEST_MB"):
        assert f"{name}=" in env_example


async def test_c2_an_upload_over_the_size_cap_is_a_413(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_mb", 0.01)
    result = await _upload_one("-", b"%PDF-1.4\n" + b"0" * 40_000)
    assert result.status == 413


async def test_c1_a_file_that_only_starts_like_a_pdf_is_refused() -> None:
    result = await _upload_one("f07c_pdf_header_then_zip.pdf")
    assert result.status == 422 and result.message == "The file could not be read as a PDF."


async def test_c1_a_truncated_pdf_is_refused() -> None:
    data = fixture("f01_clean/commercial_invoice.pdf")
    assert (await _upload_one("-", data[: len(data) // 2])).status == 422


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("f09_javascript_and_attachment.pdf", "The PDF contains scripts, which are not accepted."),
        ("f09b_javascript_only.pdf", "The PDF contains scripts, which are not accepted."),
        ("f09c_attachment_only.pdf", "The PDF contains attached or embedded files, which are not accepted."),
    ],
)
async def test_c1_a_pdf_with_a_script_or_an_attachment_is_refused(name: str, message: str) -> None:
    result = await _upload_one(name)
    assert result.status == 422 and result.message == message


async def test_c1_a_pdf_with_only_an_owner_password_is_accepted() -> None:
    assert (await _upload_one("f08b_owner_password_only.pdf")).status == 201


@pytest.mark.parametrize("name", ["f10a_huge_page_100mpx.pdf", "f10b_huge_page_278mpx.pdf", "f10c_huge_page_1600mpx.pdf"])
async def test_c2_a_page_the_size_of_a_billboard_is_refused_before_it_is_rendered(name: str) -> None:
    result = await _upload_one(name)
    assert result.status == 422 and "megapixels" in (result.message or "")


async def test_c2_a_stored_document_with_a_page_that_is_too_large_is_refused_again_before_the_render(vertex: FakeVertex, monkeypatch) -> None:
    """The second line: a document that got past the upload (stored before the check existed, or registered by another route) is
    stopped by preprocessing, before poppler renders it and before any request is made."""
    from app.api.v1 import documents

    monkeypatch.setattr(documents, "check_pdf", lambda *_a, **_kw: None)  # as if it had been stored before the upload check existed
    run = await _analyse([("commercial_invoice.pdf", fixture("f10b_huge_page_278mpx.pdf"))])
    assert run.uploads[0].status == 201 and run.run["state"] == "ERROR" and vertex.extraction_requests == []


# ---------------------------------------------------------------------------
# C3 / C4 / C5  does irrelevant content reach the model?
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["f02a_resume_as_invoice.pdf", "f02b_bank_statement_as_invoice.pdf"])
async def test_c3_a_resume_or_a_bank_statement_never_reaches_the_extraction_call(vertex: FakeVertex, name: str) -> None:
    """Rejected at the upload by the vision gate (the text layer names no document): one small request, no extraction, nothing stored."""
    vertex.gate = "OTHER"
    result = await _upload_one(name)
    assert result.status == 422 and result.message == relevance.REJECTION_MESSAGE
    assert len(vertex.gate_requests) == 1 and vertex.extraction_requests == []
    config = vertex.gate_requests[0]["config"]
    assert config.max_output_tokens == 24 and config.thinking_config.thinking_budget == 0


@pytest.mark.parametrize("name", ["f17a_resume_white_title.pdf", "f17b_resume_one_point_title.pdf"])
async def test_c3_a_title_only_the_text_layer_can_see_does_not_buy_a_free_pass(vertex: FakeVertex, name: str) -> None:
    """The text layer is the uploader's: a resume with COMMERCIAL INVOICE in white (or one point) text is asked about like any file whose
    page does not say what it is, and refused when the model says OTHER (review finding, section 20 of the audit)."""
    vertex.gate = "OTHER"
    result = await _upload_one(name)
    assert result.status == 422 and result.message == relevance.REJECTION_MESSAGE
    assert len(vertex.gate_requests) == 1 and vertex.extraction_requests == []


@pytest.mark.parametrize("name", ["f01_clean/commercial_invoice.pdf", "f01_clean/bill_of_lading.pdf", "f01_clean/packing_list.pdf",
                                  "f01_clean/mtc_pipe_test_cert.pdf", "f12_non_english_invoice.pdf", "f05_visible_injection.pdf",
                                  "f04b_invoice_plus_15_pages_terms.pdf", "f13_bol_in_invoice_slot.pdf"])
async def test_c3_a_document_whose_text_names_it_costs_the_gate_nothing(vertex: FakeVertex, name: str) -> None:
    vertex.gate = "OTHER"  # would refuse, if it were asked
    assert (await _upload_one(name)).status == 201
    assert vertex.extraction_requests == []


async def test_c3_a_scan_has_no_text_so_the_vision_gate_decides_and_a_scan_of_an_invoice_is_kept(vertex: FakeVertex) -> None:
    assert (await _upload_one("f11_scanned_invoice.pdf")).status == 201
    assert len(vertex.gate_requests) == 1 and vertex.extraction_requests == []


async def test_c3_the_gate_sends_one_image_and_one_fixed_sentence_and_never_the_text_layer(vertex: FakeVertex) -> None:
    vertex.gate = "OTHER"
    await _upload_one("f02a_resume_as_invoice.pdf")
    [request] = vertex.gate_requests
    parts = request["contents"]
    assert len(parts) == 2 and parts[0].inline_data.mime_type == "image/png" and parts[1].text == relevance.GATE_INSTRUCTION
    assert "JANE EXAMPLE" not in repr(parts[1])


async def test_c3_a_gate_that_cannot_answer_does_not_turn_the_upload_away(vertex: FakeVertex) -> None:
    vertex.gate = RuntimeError("Gemini is down")
    assert (await _upload_one("f02a_resume_as_invoice.pdf")).status == 201  # fails open: the extraction call types it UNKNOWN


async def test_c3_without_a_model_a_file_the_text_cannot_place_is_accepted() -> None:
    assert (await _upload_one("f02a_resume_as_invoice.pdf")).status == 201  # demo mode: no client, nothing can be asked


async def test_c3_the_gate_can_be_switched_off(vertex: FakeVertex, monkeypatch) -> None:
    monkeypatch.setattr(settings, "relevance_gate", False)
    vertex.gate = "OTHER"
    assert (await _upload_one("f02a_resume_as_invoice.pdf")).status == 201
    assert vertex.extraction_requests == []


async def test_c3_the_same_bytes_are_not_asked_about_twice_in_a_bundle(vertex: FakeVertex) -> None:
    async with api_client() as client:
        created = await client.post("/api/v1/bundles", json={"reference": "GATING", "destination_country": "SG"})
        bundle_id = created.json()["id"]
        for _ in range(3):
            assert (await harness.upload(client, bundle_id, "scan.pdf", fixture("f11_scanned_invoice.pdf"))).status == 201
    assert len(vertex.gate_requests) == 1


async def test_c4_only_the_invoice_page_of_an_invoice_with_terms_is_sent(vertex: FakeVertex) -> None:
    run = await _analyse([("commercial_invoice.pdf", fixture("f04b_invoice_plus_15_pages_terms.pdf"))])
    assert pages_sent(vertex) == 1
    skipped = [c for c in run.assessment["checks"] if c["check_id"].startswith("P-002-")]
    assert len(skipped) == 1 and skipped[0]["severity"] == "PASS" and "pages 2-16" in skipped[0]["message"]


async def test_c4_a_41_page_invoice_with_terms_is_accepted_and_reads_one_page(vertex: FakeVertex) -> None:
    run = await _analyse([("commercial_invoice.pdf", fixture("f04a_invoice_plus_40_pages_terms.pdf"))])
    assert run.uploads[0].status == 201 and pages_sent(vertex) == 1


async def test_c4_the_cap_bounds_what_a_30_page_table_costs_and_the_assessment_says_what_was_not_read(vertex: FakeVertex) -> None:
    run = await _analyse([("commercial_invoice.pdf", fixture("f16_worst_case_30_dense_pages.pdf"))])
    assert pages_sent(vertex) == settings.max_pages_sent == 10
    [missed] = [c for c in run.assessment["checks"] if c["check_id"].startswith("P-001-")]
    assert missed["severity"] == "WARN" and "20 of 30 pages were not read: pages 11-30" in missed["message"]
    assert run.assessment["status"] != "COMPLIANT_FOR_SUBMISSION"


async def test_c4_a_recompute_still_says_which_pages_were_not_read(vertex: FakeVertex) -> None:
    async with api_client() as client:
        first = await harness.run_bundle(client, [("commercial_invoice.pdf", fixture("f16_worst_case_30_dense_pages.pdf"))], timeout=60.0)
        again = await harness.run_bundle(client, [], bundle_id=first.bundle_id, mode="recompute", timeout=60.0)
    assert [c["check_id"] for c in again.assessment["checks"] if c["check_id"].startswith("P-001-")] == \
        [c["check_id"] for c in first.assessment["checks"] if c["check_id"].startswith("P-001-")] != []


async def test_c5_a_bill_of_lading_uploaded_as_an_invoice_is_flagged() -> None:
    """Fix item 11. The upload declares the type (``declared_type``); the model reads the file as what it is; the assessment says so."""
    fake = FakeVertex(doc_type="BILL_OF_LADING")
    with pytest.MonkeyPatch.context() as patch:
        harness.install_meter(fake, patch)
        async with api_client() as client:
            run = await harness.run_bundle(
                client, [("commercial_invoice.pdf", fixture("f13_bol_in_invoice_slot.pdf"))], timeout=60.0,
                declared_types={"commercial_invoice.pdf": "COMMERCIAL_INVOICE"},
            )
    [flag] = [c for c in run.assessment["checks"] if c["check_id"].startswith("T-001-")]
    assert flag["severity"] == "WARN" and flag["focus_document"] == run.uploads[0].document_id
    assert "uploaded as a Commercial Invoice" in flag["message"] and "read it as a Bill of Lading" in flag["message"]
    assert "No other file was read as a Commercial Invoice" in flag["message"]
    assert run.assessment["status"] != "COMPLIANT_FOR_SUBMISSION"


async def test_c5_nothing_is_flagged_when_no_type_was_declared_and_the_file_name_is_never_used_to_guess_one() -> None:
    """The same file in the same slot, with no declared type: no finding. A name such as ``commercial_invoice.pdf`` is not a claim."""
    fake = FakeVertex(doc_type="BILL_OF_LADING")
    with pytest.MonkeyPatch.context() as patch:
        harness.install_meter(fake, patch)
        run = await _analyse([("commercial_invoice.pdf", fixture("f13_bol_in_invoice_slot.pdf"))])
    assert [c for c in run.assessment["checks"] if c["check_id"].startswith(("T-001-", "L-001-"))] == []


async def test_c5_nothing_is_flagged_when_the_declared_type_is_what_the_model_read() -> None:
    fake = FakeVertex(doc_type="BILL_OF_LADING")
    with pytest.MonkeyPatch.context() as patch:
        harness.install_meter(fake, patch)
        async with api_client() as client:
            run = await harness.run_bundle(
                client, [("bol.pdf", fixture("f13_bol_in_invoice_slot.pdf"))], timeout=60.0, declared_types={"bol.pdf": "bill of lading"},
            )
    assert [c for c in run.assessment["checks"] if c["check_id"].startswith("T-001-")] == []


async def test_f12_an_invoice_whose_values_are_not_in_latin_script_is_flagged_and_says_why_other_findings_may_be_wrong() -> None:
    """F12 (a Chinese invoice): the values come back as printed. The assessment now says most of them are not Latin script."""
    chinese = {"fields": [
        {"name": "consignee", "value": "新加坡精密管道有限公司", "unit": None, "confidence": 0.95, "page": None, "box": None},
        {"name": "consignor", "value": "印度无缝钢管有限公司", "unit": None, "confidence": 0.95, "page": None, "box": None},
        {"name": "document_number", "value": "INV-2024-001", "unit": None, "confidence": 0.95, "page": None, "box": None},
    ]}
    fake = FakeVertex(doc_type="COMMERCIAL_INVOICE", extra=chinese)
    with pytest.MonkeyPatch.context() as patch:
        harness.install_meter(fake, patch)
        run = await _analyse([("commercial_invoice.pdf", fixture("f12_non_english_invoice.pdf"))])
    [flag] = [c for c in run.assessment["checks"] if c["check_id"].startswith("L-001-")]
    assert flag["severity"] == "WARN" and "not Latin script" in flag["message"] and "Chinese" in flag["message"]
    assert "may be a difference of language" in flag["message"]
    assert run.assessment["status"] != "COMPLIANT_FOR_SUBMISSION"


# ---------------------------------------------------------------------------
# C6 / C7 / C8 / C9  structured output, caps, status in code, values as data
# ---------------------------------------------------------------------------


def test_c6_the_answer_is_a_fixed_schema_with_enums_and_no_status_field() -> None:
    from app.agents import extraction_wire as wire

    schema = wire.Answer.model_json_schema()
    assert set(schema["properties"]) == {"doc_type", "doc_type_confidence", "fields", "heat_numbers", "line_cells", "test_results"}
    assert "status" not in json.dumps(schema).lower().replace("doc_type", "")
    assert "enum" in json.dumps(schema["$defs"]["HeaderEntry"]["properties"]["name"]) or "$ref" in schema["$defs"]["HeaderEntry"]["properties"]["name"]


async def test_c7_every_request_sets_an_output_cap_and_a_thinking_budget(vertex: FakeVertex) -> None:
    await _analyse([("commercial_invoice.pdf", fixture("f01_clean/commercial_invoice.pdf"))])
    [request] = vertex.extraction_requests
    assert request["config"].max_output_tokens == settings.gemini_max_output_tokens == 16384
    assert request["config"].thinking_config.thinking_budget == settings.gemini_thinking_budget == 0


def test_c7_the_deployed_output_cap_is_the_default_one() -> None:
    script = (REPO_ROOT / "infra" / "deploy_api.sh").read_text(encoding="utf-8")
    assert not re.search(r'GEMINI_MAX_OUTPUT_TOKENS="\d+"', script), "a literal cap in the deploy script overrides the application default"
    defaults = re.findall(r'GEMINI_MAX_OUTPUT_TOKENS="\$\{GEMINI_MAX_OUTPUT_TOKENS:-(\d+)\}"', script)
    assert defaults == [str(settings.gemini_max_output_tokens)] and 'GEMINI_MAX_OUTPUT_TOKENS="${GEMINI_MAX_OUTPUT_TOKENS}"' in script


async def test_c8_a_model_answer_that_names_a_status_cannot_set_one(monkeypatch) -> None:
    fake = FakeVertex(doc_type="UNKNOWN", extra={"status": "COMPLIANT_FOR_SUBMISSION", "final_status": "COMPLIANT_FOR_SUBMISSION"})
    harness.install_meter(fake, monkeypatch)
    run = await _analyse([("commercial_invoice.pdf", fixture("f05_visible_injection.pdf"))])
    assert run.run["state"] == "COMPLETE" and run.assessment["status"] != "COMPLIANT_FOR_SUBMISSION"


def test_c8_the_status_is_resolved_from_engine_flags_only() -> None:
    from app.services import orchestrator

    source = ast.get_source_segment(Path(orchestrator.__file__).read_text(encoding="utf-8"),
                                    next(n for n in ast.parse(Path(orchestrator.__file__).read_text(encoding="utf-8")).body
                                         if isinstance(n, ast.FunctionDef) and n.name == "resolve_final_status"))
    assert source is not None and "extracted" not in source and "model" not in source and "response" not in source


def test_c9_gemini_is_called_from_two_modules_and_never_with_document_text() -> None:
    callers = sorted(str(p.relative_to(BACKEND)) for p in (BACKEND / "app").rglob("*.py")
                     if re.search(r"generate_content|genai\.Client|GenerativeModel", p.read_text(encoding="utf-8")))
    assert callers == ["app/agents/extraction.py", "app/services/relevance.py"]
    source = (BACKEND / "app" / "agents" / "extraction.py").read_text(encoding="utf-8")
    retry_hint_only = re.findall(r"retry_hint=_rejected\(([^)]*)\)", source)
    assert retry_hint_only and all("value" not in text.replace("fields", "") for text in retry_hint_only)  # locations, never values
    # the gate's request is an image and a constant sentence (test_c3_the_gate_sends_one_image_...): no text layer, no extracted value
    gate = (BACKEND / "app" / "services" / "relevance.py").read_text(encoding="utf-8")
    assert gate.count("generate_content") == 1 and "Part.from_text(text=GATE_INSTRUCTION)" in gate


# ---------------------------------------------------------------------------
# C10 / C11  quotas and deduplication (F14)
# ---------------------------------------------------------------------------


async def test_f14_the_same_invoice_twenty_times_is_one_document(vertex: FakeVertex) -> None:
    data = fixture("f01_clean/commercial_invoice.pdf")
    async with api_client() as client:
        created = await client.post("/api/v1/bundles", json={"reference": "GATING", "destination_country": "SG"})
        bundle_id = created.json()["id"]
        results = await asyncio.gather(*[harness.upload(client, bundle_id, "commercial_invoice.pdf", data) for _ in range(20)])
        bundle = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()
        audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
    assert [r.status for r in results] == [201] * 20  # the write limit is 60 a minute
    assert len(bundle["documents"]) == 1
    assert [e["event_type"] for e in audit["events"]].count("DOCUMENT_UPLOADED") == 20  # each repeat still appends to the audit chain


async def test_f14_the_run_limit_stops_the_eleventh_analysis_in_a_minute(vertex: FakeVertex) -> None:
    async with api_client() as client:
        first = await harness.run_bundle(client, [("commercial_invoice.pdf", fixture("f01_clean/commercial_invoice.pdf"))], timeout=60.0)
        statuses = [first.run["http_status"]]
        for _ in range(11):
            started = await client.post(f"/api/v1/bundles/{first.bundle_id}/reassess")
            statuses.append(started.status_code)
            if started.status_code == 202:
                await wait_for_run(first.bundle_id, started.json()["run_id"], timeout=60.0)
    assert statuses.count(202) == settings.rate_limit_runs_per_minute == 10 and statuses.count(429) == 2


async def test_c11_an_unchanged_file_is_not_extracted_twice(vertex: FakeVertex) -> None:
    async with api_client() as client:
        first = await harness.run_bundle(client, [("commercial_invoice.pdf", fixture("f01_clean/commercial_invoice.pdf"))], timeout=60.0)
        again = await harness.run_bundle(client, [], bundle_id=first.bundle_id, mode="reassess", timeout=60.0)
    assert len(vertex.extraction_requests) == 1
    assert again.run["state"] == "COMPLETE" and again.assessment["status"] == first.assessment["status"]


async def test_c11_a_reassess_after_a_new_upload_reads_only_the_new_file(vertex: FakeVertex) -> None:
    async with api_client() as client:
        first = await harness.run_bundle(client, [("commercial_invoice.pdf", fixture("f01_clean/commercial_invoice.pdf")),
                                                  ("packing_list.pdf", fixture("f01_clean/packing_list.pdf"))], timeout=60.0)
        assert len(vertex.extraction_requests) == 2
        await harness.run_bundle(client, [("bill_of_lading.pdf", fixture("f01_clean/bill_of_lading.pdf"))], bundle_id=first.bundle_id,
                                 mode="reassess", timeout=60.0)
    assert len(vertex.extraction_requests) == 3


async def test_c11_the_cache_is_not_part_of_a_recompute(vertex: FakeVertex, monkeypatch) -> None:
    """A recompute reads no document: it reuses the extraction stored with the last assessment and never consults the cache."""
    from app.repo import firestore

    async with api_client() as client:
        first = await harness.run_bundle(client, [("commercial_invoice.pdf", fixture("f01_clean/commercial_invoice.pdf"))], timeout=60.0)
        asked: list[tuple] = []
        real = firestore.get_cached_answer

        async def spy(*args):
            asked.append(args)
            return await real(*args)

        monkeypatch.setattr(firestore, "get_cached_answer", spy)
        again = await harness.run_bundle(client, [], bundle_id=first.bundle_id, mode="recompute", timeout=60.0)
    assert again.run["state"] == "COMPLETE" and asked == [] and len(vertex.extraction_requests) == 1


async def test_c11_a_changed_setting_asks_the_model_again(vertex: FakeVertex, monkeypatch) -> None:
    async with api_client() as client:
        first = await harness.run_bundle(client, [("commercial_invoice.pdf", fixture("f01_clean/commercial_invoice.pdf"))], timeout=60.0)
        monkeypatch.setattr(settings, "page_image_mode", "gray")  # a different picture of the same page
        await harness.run_bundle(client, [], bundle_id=first.bundle_id, mode="reassess", timeout=60.0)
    assert len(vertex.extraction_requests) == 2


async def test_c10_the_daily_token_budget_stops_new_analyses_and_not_a_recompute(vertex: FakeVertex, monkeypatch) -> None:
    """The audit's loop of uploads and reassessments: it is bounded by a daily number of tokens, not only by requests per minute."""
    monkeypatch.setattr(settings, "daily_token_budget", 1000)  # one document costs 1,050 in this fake
    async with api_client() as client:
        first = await harness.run_bundle(client, [("commercial_invoice.pdf", fixture("f01_clean/commercial_invoice.pdf"))], timeout=60.0)
        refused = await client.post(f"/api/v1/bundles/{first.bundle_id}/reassess")
        recompute = await client.post(f"/api/v1/bundles/{first.bundle_id}/recompute")
    assert first.run["state"] == "COMPLETE"
    assert refused.status_code == 429 and refused.json()["code"] == "TOKEN_BUDGET_EXCEEDED" and "Retry-After" in refused.headers
    assert recompute.status_code == 202


def test_c10_the_infra_scripts_carry_a_budget_alert_and_explicit_memory_and_cpu() -> None:
    import subprocess

    infra = REPO_ROOT / "infra"
    alert = (infra / "budget" / "setup_budget_alert.sh").read_text(encoding="utf-8")
    assert "billing budgets create" in alert and "--filter-projects" in alert and "--threshold-rule percent=0.9" in alert
    deploy = (infra / "deploy_api.sh").read_text(encoding="utf-8")
    assert '--memory "${MEMORY}"' in deploy and '--cpu "${CPU}"' in deploy
    assert 'MEMORY="${MEMORY:-4Gi}"' in deploy and 'CPU="${CPU:-2}"' in deploy
    for script in ("budget/setup_budget_alert.sh", "deploy_api.sh", "firestore/setup_ttl.sh"):
        assert subprocess.run(["bash", "-n", str(infra / script)], capture_output=True, text=True).returncode == 0


# ---------------------------------------------------------------------------
# C12 / C13  what a rejected file leaves behind, and whether cost is visible
# ---------------------------------------------------------------------------


async def test_c12_a_file_refused_at_upload_is_not_stored_audited_or_logged(tmp_path) -> None:
    hostile = b"MZ" + b"SECRET-MARKER-" * 50
    with structlog.testing.capture_logs() as logs:
        async with api_client() as client:
            created = await client.post("/api/v1/bundles", json={"reference": "GATING", "destination_country": "SG"})
            bundle_id = created.json()["id"]
            result = await harness.upload(client, bundle_id, "confidential-name.pdf", hostile)
            bundle = (await client.get(f"/api/v1/bundles/{bundle_id}")).json()
            audit = (await client.get(f"/api/v1/bundles/{bundle_id}/audit")).json()
    assert result.status == 422 and bundle["documents"] == []
    assert "DOCUMENT_UPLOADED" not in [e["event_type"] for e in audit["events"]]
    assert not [p for p in Path(settings.local_storage_path).rglob("*") if p.is_file()]
    logged = json.dumps(logs, default=str)
    assert "SECRET-MARKER" not in logged and "confidential-name" not in logged


async def test_c12_a_file_that_cannot_be_rendered_is_not_forwarded_to_gemini_raw(vertex: FakeVertex, monkeypatch) -> None:
    """A polyglot that got past the upload (stored before the check existed) fails its run at the render; the raw PDF is not sent."""
    from app.api.v1 import documents

    monkeypatch.setattr(documents, "check_pdf", lambda *_a, **_kw: None)
    run = await _analyse([("commercial_invoice.pdf", fixture("f07c_pdf_header_then_zip.pdf"))])
    assert run.uploads[0].status == 201 and run.run["state"] == "ERROR"
    assert vertex.extraction_requests == []


async def test_c13_tokens_are_logged_per_document(vertex: FakeVertex) -> None:
    with structlog.testing.capture_logs() as logs:
        await _analyse([("commercial_invoice.pdf", fixture("f01_clean/commercial_invoice.pdf"))])
    [event] = [e for e in logs if e.get("event") == "gemini_extraction_document"]
    assert event["prompt_tokens"] == 1000 and event["output_tokens"] == 50 and event["document_id"]


async def test_c13_token_usage_reaches_the_assessment_the_audit_trail_and_the_usage_route(vertex: FakeVertex) -> None:
    run = await _analyse([("commercial_invoice.pdf", fixture("f01_clean/commercial_invoice.pdf"))])
    async with api_client() as client:
        audit = (await client.get(f"/api/v1/bundles/{run.bundle_id}/audit")).json()
        usage = (await client.get(f"/api/v1/bundles/{run.bundle_id}/usage")).json()
        listed = (await client.get(f"/api/v1/bundles/{run.bundle_id}/iterations")).json()

    stored = run.assessment["token_usage"]
    assert (stored["requests"], stored["prompt_tokens"], stored["output_tokens"], stored["thinking_tokens"], stored["total_tokens"]) == (1, 1000, 50, 0, 1050)
    [row] = stored["documents"]
    assert row["filename"] == "commercial_invoice.pdf" and row["cached"] is False and row["attempts"][0]["outcome"] == "ok"
    completed = next(e for e in audit["events"] if e["event_type"] == "ASSESSMENT_COMPLETED")
    assert completed["payload"]["token_usage"]["total_tokens"] == 1050 and "documents" not in completed["payload"]["token_usage"]
    assert listed[0]["token_usage"] == stored
    [record] = usage["runs"]
    assert record["state"] == "COMPLETE" and record["iteration"] == 1 and record["token_usage"] == stored
    assert usage["totals"]["total_tokens"] == 1050 and usage["totals"]["runs"] == 1 and usage["totals"]["failed_runs"] == 0


async def test_c13_a_run_that_fails_still_shows_what_it_spent(vertex: FakeVertex) -> None:
    """The audit's F16: a run that hit the output cap spent its tokens and left no trace. Now the failed run has a usage record."""
    vertex.finish = "MAX_TOKENS"
    run = await _analyse([("commercial_invoice.pdf", fixture("f16_worst_case_30_dense_pages.pdf"))])
    async with api_client() as client:
        audit = (await client.get(f"/api/v1/bundles/{run.bundle_id}/audit")).json()
        usage = (await client.get(f"/api/v1/bundles/{run.bundle_id}/usage")).json()

    assert run.run["state"] == "ERROR" and run.assessment is None
    [record] = usage["runs"]
    assert record["state"] == "ERROR" and record["iteration"] is None
    [row] = record["token_usage"]["documents"]
    assert row["failed_requests"] == 1 and row["total_tokens"] == 1050
    assert row["attempts"][0]["outcome"].startswith("refused: finish_reason MAX_TOKENS") and row["attempts"][0]["finish_reason"] == "MAX_TOKENS"
    assert usage["totals"]["failed_runs"] == 1 and usage["totals"]["failed_requests"] == 1 and usage["totals"]["total_tokens"] == 1050
    failed = next(e for e in audit["events"] if e["event_type"] == "ANALYSIS_FAILED")
    assert failed["payload"]["token_usage"]["total_tokens"] == 1050


async def test_c13_a_reassess_says_what_the_cache_saved_and_a_recompute_makes_no_record(vertex: FakeVertex) -> None:
    async with api_client() as client:
        first = await harness.run_bundle(client, [("commercial_invoice.pdf", fixture("f01_clean/commercial_invoice.pdf"))], timeout=60.0)
        again = await harness.run_bundle(client, [], bundle_id=first.bundle_id, mode="reassess", timeout=60.0)
        await harness.run_bundle(client, [], bundle_id=first.bundle_id, mode="recompute", timeout=60.0)
        usage = (await client.get(f"/api/v1/bundles/{first.bundle_id}/usage")).json()

    assert again.assessment["token_usage"]["requests"] == 0 and again.assessment["token_usage"]["cached_documents"] == 1
    assert again.assessment["token_usage"]["saved_tokens"] == 1050 and again.assessment["token_usage"]["documents"][0]["cached"] is True
    assert [r["mode"] for r in usage["runs"]] == ["full", "reassess"]  # the recompute asked and served nothing: no record
    assert usage["totals"]["total_tokens"] == 1050 and usage["totals"]["saved_tokens"] == 1050


async def test_c13_the_relevance_check_at_upload_is_counted_per_document(vertex: FakeVertex) -> None:
    run = await _analyse([("commercial_invoice.pdf", fixture("f11_scanned_invoice.pdf"))])  # a scan: the vision gate decides
    async with api_client() as client:
        usage = (await client.get(f"/api/v1/bundles/{run.bundle_id}/usage")).json()

    assert usage["totals"]["upload_gate_tokens"] == 1050
    assert run.assessment["token_usage"]["documents"][0]["gate_tokens"] == 1050
    assert run.assessment["token_usage"]["total_tokens"] == 1050  # the gate is not part of the run's totals


async def test_c13_a_file_the_text_names_makes_no_gate_request_and_shows_none(vertex: FakeVertex) -> None:
    run = await _analyse([("commercial_invoice.pdf", fixture("f01_clean/commercial_invoice.pdf"))])

    assert run.assessment["token_usage"]["documents"][0]["gate_tokens"] is None


async def test_c13_the_same_scan_uploaded_again_keeps_its_gate_cost_on_the_record(vertex: FakeVertex) -> None:
    async with api_client() as client:
        created = await client.post("/api/v1/bundles", json={"reference": "GATING", "destination_country": "SG"})
        bundle_id = created.json()["id"]
        for _ in range(2):
            await harness.upload(client, bundle_id, "scan.pdf", fixture("f11_scanned_invoice.pdf"))
        usage = (await client.get(f"/api/v1/bundles/{bundle_id}/usage")).json()

    assert usage["totals"]["upload_gate_tokens"] == 1050 and len(vertex.gate_requests) == 1


async def test_c13_a_file_the_gate_refuses_is_stored_nowhere_so_the_log_carries_its_cost(vertex: FakeVertex) -> None:
    vertex.gate = "OTHER"
    with structlog.testing.capture_logs() as logs:
        result = await _upload_one("f02a_resume_as_invoice.pdf")

    [event] = [e for e in logs if e.get("event") == "relevance_gate_asked_the_model"]
    assert result.status == 422 and event["gate_total_tokens"] == 1050 and event["gate_requests"] == 1 and event["kind"] == "OTHER"


async def test_c13_failing_to_write_the_usage_record_never_fails_the_run(vertex: FakeVertex, monkeypatch) -> None:
    from app.repo import firestore

    async def broken(*_a, **_kw):
        raise ConnectionError("firestore is down")

    monkeypatch.setattr(firestore, "save_usage", broken)

    run = await _analyse([("commercial_invoice.pdf", fixture("f01_clean/commercial_invoice.pdf"))])

    assert run.run["state"] == "COMPLETE" and run.assessment["token_usage"]["total_tokens"] == 1050


async def test_c13_the_usage_route_for_an_unknown_bundle_is_a_404_and_an_empty_bundle_has_no_runs() -> None:
    async with api_client() as client:
        missing = await client.get("/api/v1/bundles/bnd-nope/usage")
        created = await client.post("/api/v1/bundles", json={"reference": "GATING", "destination_country": "SG"})
        empty = (await client.get(f"/api/v1/bundles/{created.json()['id']}/usage")).json()

    assert missing.status_code == 404
    assert empty["runs"] == [] and empty["totals"]["total_tokens"] == 0 and empty["totals"]["runs"] == 0
