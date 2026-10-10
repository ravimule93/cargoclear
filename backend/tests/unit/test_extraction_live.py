"""The live Gemini extraction path: async call, labelled pages, sanitised parsing, retry policy, concurrency,
guards and stats. Every test uses a fake client (tests/unit/extraction_fakes.py): no network, no credentials.
"""

from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai import types

from app.agents import extraction
from app.agents.extraction import SYSTEM_INSTRUCTION, run_extraction_agent
from app.core.config import Settings, settings
from app.domain.schemas import ExtractedDocument
from app.gateway.errors import ExtractionError
from app.repo import firestore
from tests.unit.extraction_fakes import (
    HANG,
    FakeGenai,
    always,
    ctx_for,
    doc_of,
    good_doc,
    payload_of,
    response,
    script,
    texts_of,
)

INSTRUCTION = "Extract all trade data into the requested JSON schema."


def _sanitise_extraction(raw: dict[str, Any], page_count: int | None):
    return extraction._sanitise_extraction(raw, page_count)


@pytest.fixture(autouse=True)
def delays(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Backoff never really sleeps; the delays it asked for are recorded here."""
    recorded: list[float] = []

    async def record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(extraction, "_sleep", record, raising=False)
    return recorded


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch):
    def _install(fake: FakeGenai) -> FakeGenai:
        monkeypatch.setattr(settings, "app_mode", "live")
        monkeypatch.setattr(extraction, "_get_genai_client", lambda: fake)
        return fake

    return _install


def configure(monkeypatch: pytest.MonkeyPatch, **values: Any) -> None:
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


def api_error(code: int, message: str = "details") -> genai_errors.APIError:
    return genai_errors.APIError(code, {"error": {"code": code, "message": message, "status": "SOME_STATUS"}})


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

SETTING_DEFAULTS = {
    "GEMINI_TIMEOUT_SECONDS": ("gemini_timeout_seconds", 120, "7.5", 7.5),
    "GEMINI_MAX_ATTEMPTS": ("gemini_max_attempts", 3, "5", 5),
    "GEMINI_MAX_CONCURRENCY": ("gemini_max_concurrency", 3, "2", 2),
    "GEMINI_MAX_OUTPUT_TOKENS": ("gemini_max_output_tokens", 16384, "8192", 8192),
    "GEMINI_THINKING_BUDGET": ("gemini_thinking_budget", 0, "-1", -1),
    "GEMINI_MAX_REQUEST_MB": ("gemini_max_request_mb", 18, "10", 10),
    "GEMINI_MAX_PAGES": ("gemini_max_pages", 30, "12", 12),
}


@pytest.mark.parametrize(("env", "spec"), list(SETTING_DEFAULTS.items()))
def test_settings_have_the_documented_defaults_and_read_their_environment_variable(monkeypatch, env, spec) -> None:
    attribute, default, raw, parsed = spec
    for name in SETTING_DEFAULTS:
        monkeypatch.delenv(name, raising=False)

    assert getattr(Settings(_env_file=None), attribute) == default

    monkeypatch.setenv(env, raw)
    assert getattr(Settings(_env_file=None), attribute) == parsed


def test_env_example_lists_every_new_setting_with_its_default() -> None:
    from pathlib import Path

    lines = (Path(__file__).resolve().parents[2] / ".env.example").read_text().splitlines()
    assigned = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in lines if "=" in line and not line.startswith("#")}
    for env, (_attribute, default, _raw, _parsed) in SETTING_DEFAULTS.items():
        assert assigned.get(env) == str(default), env


# ---------------------------------------------------------------------------
# C2: the call is async, awaited with a timeout, with the documented config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_event_loop_keeps_running_during_a_slow_call(install) -> None:
    install(FakeGenai(always(response(good_doc())), delay=0.3))
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        await run_extraction_agent(ctx_for("doc-1"))
    finally:
        task.cancel()

    assert ticks > 3, f"the event loop ticked {ticks} times during a 0.3 s Gemini call"


@pytest.mark.asyncio
async def test_a_success_returns_the_document_under_the_real_document_id(install) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))

    result = await run_extraction_agent(ctx_for("doc-1"))

    [doc] = result["extracted"]
    assert doc.document_id == "doc-1"  # not what the model wrote
    assert doc.doc_type == "COMMERCIAL_INVOICE"
    assert result["extraction_source"] == "live"
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_the_request_carries_the_documented_config(install, monkeypatch) -> None:
    configure(monkeypatch, gemini_max_output_tokens=4096, gemini_thinking_budget=0)
    fake = install(FakeGenai(always(response(good_doc()))))

    await run_extraction_agent(ctx_for("doc-1"))

    call = fake.calls[0]
    config = call["config"]
    assert call["model"] == settings.gemini_live_model
    assert config.response_mime_type == "application/json"
    assert config.response_schema is ExtractedDocument
    assert config.system_instruction == SYSTEM_INSTRUCTION
    assert config.temperature == 0.0
    assert config.max_output_tokens == 4096
    assert config.thinking_config.thinking_budget == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("budget", "expected"), [(0, 0), (1024, 1024), (-1, None), (-5, None)])
async def test_the_thinking_config_is_sent_only_for_a_non_negative_budget(install, monkeypatch, budget, expected) -> None:
    configure(monkeypatch, gemini_thinking_budget=budget)
    fake = install(FakeGenai(always(response(good_doc()))))

    await run_extraction_agent(ctx_for("doc-1"))

    config = fake.calls[0]["config"]
    if expected is None:
        assert config.thinking_config is None
    else:
        assert config.thinking_config.thinking_budget == expected


@pytest.mark.asyncio
async def test_a_call_that_never_returns_times_out_is_cancelled_and_retried(install, monkeypatch) -> None:
    configure(monkeypatch, gemini_timeout_seconds=0.05)
    fake = install(FakeGenai(script(HANG, response(good_doc()))))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(result["extracted"]) == 1
    assert len(fake.calls) == 2
    assert fake.cancelled == 1  # wait_for cancelled the hung request


@pytest.mark.asyncio
async def test_every_attempt_timing_out_fails_with_the_attempt_count_and_the_error_class(install, monkeypatch) -> None:
    configure(monkeypatch, gemini_timeout_seconds=0.05, gemini_max_attempts=2)
    fake = install(FakeGenai(always(HANG)))

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 2
    assert "doc-1" in raised.value.message and "2 attempts" in raised.value.message
    assert "TimeoutError" in raised.value.message
    assert raised.value.detail["attempts"] == 2


def test_the_client_seam_is_still_there() -> None:
    assert callable(extraction._get_genai_client)


# ---------------------------------------------------------------------------
# C3: page labels and the prompt
# ---------------------------------------------------------------------------


def _kinds(call: dict[str, Any]) -> list[tuple[str, str]]:
    kinds = []
    for part in call["contents"]:
        if part.text:
            kinds.append(("text", part.text))
        else:
            kinds.append(("file", part.inline_data.mime_type))
    return kinds


@pytest.mark.asyncio
async def test_every_page_image_is_preceded_by_a_page_n_of_m_label(install) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))

    await run_extraction_agent(ctx_for("doc-1", pages=3))

    assert _kinds(fake.calls[0]) == [
        ("text", "Page 1 of 3."), ("file", "image/png"),
        ("text", "Page 2 of 3."), ("file", "image/png"),
        ("text", "Page 3 of 3."), ("file", "image/png"),
        ("text", INSTRUCTION),
    ]


@pytest.mark.asyncio
async def test_a_single_page_image_is_still_labelled(install) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))

    await run_extraction_agent(ctx_for("doc-1", pages=1))

    assert _kinds(fake.calls[0])[0] == ("text", "Page 1 of 1.")


@pytest.mark.asyncio
async def test_a_raw_pdf_passthrough_gets_no_label(install) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))

    await run_extraction_agent(ctx_for("doc-1", mime="application/pdf"))

    assert _kinds(fake.calls[0]) == [("file", "application/pdf"), ("text", INSTRUCTION)]


@pytest.mark.asyncio
async def test_labels_are_per_document(install) -> None:
    fake = install(FakeGenai(always(response(good_doc()))))

    await run_extraction_agent(ctx_for("doc-a", "doc-b", pages=2))

    for call in fake.calls:
        assert [t for t in texts_of(call) if t.startswith("Page")] == ["Page 1 of 2.", "Page 2 of 2."]


@pytest.mark.asyncio
async def test_a_page_beyond_the_labelled_count_loses_its_box_but_not_the_document(install) -> None:
    doc = good_doc()
    doc["consignee"]["bbox"]["page"] = 4
    fake = install(FakeGenai(always(response(doc))))

    result = await run_extraction_agent(ctx_for("doc-1", pages=3))

    assert len(fake.calls) == 1
    assert result["extracted"][0].consignee.bbox is None
    assert result["extracted"][0].consignee.value == "SINGAPORE PRECISION PIPING PTE LTD"
    assert "page 4" in result["extraction_warnings"][0]["reason"]


@pytest.mark.asyncio
async def test_with_a_passthrough_the_page_count_is_unknown_so_a_high_page_is_kept(install) -> None:
    doc = good_doc()
    doc["consignee"]["bbox"]["page"] = 7
    install(FakeGenai(always(response(doc))))

    result = await run_extraction_agent(ctx_for("doc-1", mime="application/pdf"))

    assert result["extracted"][0].consignee.bbox.page == 7
    assert result["extraction_warnings"] == []


# ---------------------------------------------------------------------------
# C4: parse and sanitise
# ---------------------------------------------------------------------------

GOOD_BOX = {"page": 1, "ymin": 10, "xmin": 10, "ymax": 20, "xmax": 20}


def raw_doc(**fields: Any) -> dict[str, Any]:
    return {"document_id": "x", "doc_type": "PACKING_LIST", "doc_type_confidence": 0.9, **fields}


def ref(value: Any = "ACME", confidence: Any = 0.9, bbox: Any = "default", **extra: Any) -> dict[str, Any]:
    return {"value": value, "confidence": confidence, "bbox": dict(GOOD_BOX) if bbox == "default" else bbox, **extra}


@pytest.mark.parametrize(
    ("bbox", "reason"),
    [
        ({**GOOD_BOX, "ymax": 1001}, "outside 0-1000"),
        ({**GOOD_BOX, "xmin": -1}, "outside 0-1000"),
        ({**GOOD_BOX, "ymin": 50, "ymax": 40}, "ymax <= ymin"),
        ({**GOOD_BOX, "ymin": 20, "ymax": 20}, "ymax <= ymin"),
        ({**GOOD_BOX, "xmin": 30, "xmax": 20}, "xmax <= xmin"),
        ({**GOOD_BOX, "xmin": 20, "xmax": 20}, "xmax <= xmin"),
        ({**GOOD_BOX, "page": 0}, "page"),
        ({**GOOD_BOX, "page": -2}, "page"),
        ({**GOOD_BOX, "page": 4}, "page 4"),
        ({**GOOD_BOX, "page": 1.5}, "page"),
        ({**GOOD_BOX, "page": "1"}, "page"),
        ({**GOOD_BOX, "page": True}, "page"),
        ({**GOOD_BOX, "ymin": "abc"}, "non-numeric"),
        ({**GOOD_BOX, "xmax": None}, "non-numeric"),
        ({**GOOD_BOX, "ymax": True}, "non-numeric"),
        ({**GOOD_BOX, "ymin": float("nan")}, "non-numeric"),
        ({k: v for k, v in GOOD_BOX.items() if k != "xmax"}, "non-numeric"),
        ([10, 10, 20, 20], "not an object"),
        ("10,10,20,20", "not an object"),
        (7, "not an object"),
    ],
)
def test_each_invalid_bbox_is_dropped_with_a_reason(bbox: Any, reason: str) -> None:
    clean, warnings = _sanitise_extraction(raw_doc(consignee=ref(bbox=bbox)), 3)

    assert clean["consignee"]["bbox"] is None
    assert clean["consignee"]["value"] == "ACME"
    [warning] = warnings
    assert warning["path"] == "consignee.bbox"
    assert reason in warning["reason"]


def test_a_box_exactly_on_the_limits_is_kept() -> None:
    edge = {"page": 3, "ymin": 0, "xmin": 0, "ymax": 1000, "xmax": 1000}
    clean, warnings = _sanitise_extraction(raw_doc(consignee=ref(bbox=edge)), 3)
    assert clean["consignee"]["bbox"] == edge
    assert warnings == []


def test_a_null_or_absent_bbox_is_not_a_problem() -> None:
    clean, warnings = _sanitise_extraction(raw_doc(consignee=ref(bbox=None), consignor={"value": "X", "confidence": 0.9}), 3)
    assert clean["consignee"]["bbox"] is None
    assert warnings == []


def test_page_count_none_skips_only_the_upper_page_test() -> None:
    far = {**GOOD_BOX, "page": 99}
    assert _sanitise_extraction(raw_doc(consignee=ref(bbox=far)), None)[0]["consignee"]["bbox"] == far
    assert _sanitise_extraction(raw_doc(consignee=ref(bbox={**GOOD_BOX, "page": 0})), None)[0]["consignee"]["bbox"] is None


@pytest.mark.parametrize(
    ("given", "clamped"),
    [(1.4, 1.0), (-0.2, 0.0), (0.5, 0.5), (0, 0.0), (1, 1.0), ("high", 0.0), (None, 0.0), (True, 0.0),
     (float("nan"), 0.0), (float("inf"), 1.0), ([0.9], 0.0)],
)
def test_confidence_is_clamped_to_0_1_and_a_non_number_becomes_0(given: Any, clamped: float) -> None:
    clean, warnings = _sanitise_extraction(raw_doc(consignee=ref(confidence=given)), 3)

    assert clean["consignee"]["confidence"] == clamped
    assert clean["consignee"]["value"] == "ACME"
    assert bool(warnings) == (given != clamped or isinstance(given, bool))  # only a real change is reported


def test_one_bad_box_among_many_good_fields_costs_only_that_box() -> None:
    raw = raw_doc(
        document_number=ref("PL-1"),
        consignee=ref("ACME", bbox={**GOOD_BOX, "ymax": 5000}),
        consignor=ref("SELLER"),
        total_net_weight_kg=ref("14,000.0", unit="KGS"),
        line_items=[{"description": ref("pipes"), "hs_code_declared": ref("73041900", bbox={**GOOD_BOX, "page": 0})}],
    )

    clean, warnings = _sanitise_extraction(raw, 2)

    assert [w["path"] for w in warnings] == ["consignee.bbox", "line_items[0].hs_code_declared.bbox"]
    assert clean["consignee"]["bbox"] is None and clean["line_items"][0]["hs_code_declared"]["bbox"] is None
    assert clean["document_number"]["bbox"] == GOOD_BOX
    assert clean["line_items"][0]["description"]["bbox"] == GOOD_BOX


def test_the_sanitiser_never_alters_a_value_a_unit_or_the_doc_type() -> None:
    raw = raw_doc(
        doc_type="MILL_TEST_CERTIFICATE",
        consignee=ref("  ACME  PTE. LTD.  ", 3.0, bbox=[1, 2, 3, 4]),
        total_net_weight_kg=ref("14,280.50", 7, bbox={"page": 0}, unit="kgs "),
        tare_weight_kg=ref(280, -1, unit=None),
        hs_code_header=ref(73041900.0, "n/a", bbox=None),
        line_items=[{"quantity": ref("120 LENGTHS", 1.2), "hs_code_declared": ref("7304.19.00", bbox={**GOOD_BOX, "page": 9})}],
    )
    before = copy.deepcopy(raw)

    clean, _ = _sanitise_extraction(raw, 2)

    assert raw == before, "the input must not be mutated"
    assert clean["doc_type"] == "MILL_TEST_CERTIFICATE"
    assert clean["consignee"]["value"] == "  ACME  PTE. LTD.  "
    assert clean["total_net_weight_kg"]["value"] == "14,280.50" and clean["total_net_weight_kg"]["unit"] == "kgs "
    assert clean["tare_weight_kg"]["value"] == 280 and clean["tare_weight_kg"]["unit"] is None
    assert clean["hs_code_header"]["value"] == 73041900.0
    assert clean["line_items"][0]["quantity"]["value"] == "120 LENGTHS"
    assert clean["line_items"][0]["hs_code_declared"]["value"] == "7304.19.00"


def test_only_a_dict_with_both_value_and_confidence_is_a_field_reference() -> None:
    raw = raw_doc(note={"value": 5, "bbox": {"page": 0}}, other={"confidence": 7, "bbox": [1]})

    clean, warnings = _sanitise_extraction(raw, 1)

    assert clean["note"] == {"value": 5, "bbox": {"page": 0}}
    assert clean["other"] == {"confidence": 7, "bbox": [1]}
    assert warnings == []


def test_the_document_level_doc_type_confidence_is_clamped_too() -> None:
    clean, warnings = _sanitise_extraction(raw_doc(note={"value": 5, "bbox": {"page": 0}}, doc_type_confidence=3), 1)

    assert clean["doc_type_confidence"] == 1.0
    assert clean["note"] == {"value": 5, "bbox": {"page": 0}}  # still not a field reference
    assert [w["path"] for w in warnings] == ["doc_type_confidence"]


# ---- through the agent -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_bad_bbox_does_not_cost_the_whole_document(install) -> None:
    doc = good_doc()
    doc["consignee"]["bbox"]["ymax"] = 5000
    doc["line_items"][0]["description"]["bbox"]["page"] = 0
    fake = install(FakeGenai(always(response(doc))))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 1, "the document is accepted on the first attempt"
    [extracted] = result["extracted"]
    assert extracted.consignee.bbox is None
    assert extracted.line_items[0].description.bbox is None
    assert extracted.document_number.bbox is not None
    # every value is exactly what the model returned
    assert extracted.consignee.value == "SINGAPORE PRECISION PIPING PTE LTD"
    assert extracted.total_net_weight_kg.value == "14,000.0" and extracted.total_net_weight_kg.unit == "KGS"
    assert extracted.line_items[0].hs_code_declared.value == "73041900"
    warnings = result["extraction_warnings"]
    assert [(w["document_id"], w["path"]) for w in warnings] == [
        ("doc-1", "consignee.bbox"), ("doc-1", "line_items[0].description.bbox"),
    ]
    assert all(w["reason"] for w in warnings)


@pytest.mark.asyncio
@pytest.mark.parametrize("wrap", ["```json\n{}\n```", "```\n{}\n```", "  ```JSON\n{}\n```  \n", "\n\n{}\n"])
async def test_fenced_json_is_accepted(install, wrap) -> None:
    fake = install(FakeGenai(always(response(wrap.replace("{}", json.dumps(good_doc()))))))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 1
    assert result["extracted"][0].doc_type == "COMMERCIAL_INVOICE"


@pytest.mark.asyncio
async def test_text_is_read_not_parsed(install) -> None:
    """`.parsed` is ignored: the answer is judged from `.text`, even when the SDK's own parse is None."""
    answer = response(good_doc())
    answer.parsed = None
    install(FakeGenai(always(answer)))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(result["extracted"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("garbage", ["this is not json", "{\"doc_type\": ", "[1, 2, 3]", "\"just a string\"", "null", "```json\n```"])
async def test_text_that_is_not_a_json_object_is_a_failed_attempt(install, garbage) -> None:
    fake = install(FakeGenai(script(response(garbage), response(good_doc()))))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 2
    assert len(result["extracted"]) == 1


@pytest.mark.asyncio
async def test_a_schema_violation_is_a_failed_attempt_and_the_retry_names_the_fields_not_the_values(install) -> None:
    bad = good_doc() | {"doc_type": "SECRET-VALUE-XYZ"}
    fake = install(FakeGenai(script(response(bad), response(good_doc()))))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 2 and len(result["extracted"]) == 1
    first, second = texts_of(fake.calls[0]), texts_of(fake.calls[1])
    assert not [t for t in first if t.startswith("Your previous answer")]
    [hint] = [t for t in second if t.startswith("Your previous answer was rejected")]
    assert hint.startswith("Your previous answer was rejected (fields: doc_type")
    assert hint.endswith("Return valid JSON that matches the schema.")
    assert "SECRET-VALUE-XYZ" not in hint


@pytest.mark.asyncio
async def test_invalid_json_then_valid_takes_two_calls_and_the_second_carries_the_hint(install) -> None:
    fake = install(FakeGenai(script(response("not json at all"), response(good_doc()))))

    await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 2
    assert [t for t in texts_of(fake.calls[1]) if t.startswith("Your previous answer was rejected")]
    assert texts_of(fake.calls[1])[-1].startswith("Your previous answer was rejected")  # appended after the instruction


@pytest.mark.asyncio
async def test_only_the_latest_hint_is_carried_not_a_growing_pile(install) -> None:
    fake = install(FakeGenai(script(response("garbage"), response(good_doc() | {"doc_type": "NOPE"}), response(good_doc()))))

    await run_extraction_agent(ctx_for("doc-1"))

    third = [t for t in texts_of(fake.calls[2]) if t.startswith("Your previous answer")]
    assert len(third) == 1 and "doc_type" in third[0]


@pytest.mark.asyncio
async def test_a_hint_never_repeats_a_value_the_model_returned(install) -> None:
    bad = good_doc()
    bad["consignee"]["value"] = {"surprise": "TOP-SECRET-CONTENT"}  # a dict where a scalar belongs
    fake = install(FakeGenai(script(response(bad), response(good_doc()))))

    await run_extraction_agent(ctx_for("doc-1"))

    assert "TOP-SECRET-CONTENT" not in " ".join(texts_of(fake.calls[1]))


# ---------------------------------------------------------------------------
# C5: retry policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [response(None), response(""), response("   \n"), response(None, finish=None),
                                   SimpleNamespace(text=None, parsed=None, candidates=None, usage_metadata=None)])
async def test_an_empty_response_on_every_attempt_raises_instead_of_dropping_the_document(install, empty) -> None:
    fake = install(FakeGenai(always(empty)))

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 3
    assert "doc-1" in raised.value.message and "3 attempts" in raised.value.message
    assert "empty response" in raised.value.message
    assert raised.value.detail["document_id"] == "doc-1" and raised.value.detail["attempts"] == 3


@pytest.mark.asyncio
async def test_an_empty_answer_followed_by_a_good_one_succeeds(install) -> None:
    fake = install(FakeGenai(script(response(None), response(good_doc()))))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 2 and len(result["extracted"]) == 1
    assert [t for t in texts_of(fake.calls[1]) if "it was empty" in t]


@pytest.mark.asyncio
async def test_an_unparseable_answer_on_the_last_attempt_raises(install) -> None:
    fake = install(FakeGenai(always(response("{not json"))))

    with pytest.raises(ExtractionError, match="not valid JSON"):
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_a_schema_invalid_answer_on_every_attempt_raises_naming_the_fields(install) -> None:
    fake = install(FakeGenai(always(response(good_doc() | {"doc_type": "SECRET-VALUE-XYZ"}))))

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 3
    assert "doc_type" in raised.value.message
    assert "SECRET-VALUE-XYZ" not in raised.value.message


@pytest.mark.asyncio
async def test_429_429_ok_makes_three_calls_with_two_backed_off_delays(install, delays) -> None:
    fake = install(FakeGenai(script(api_error(429), api_error(429), response(good_doc()))))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 3 and len(result["extracted"]) == 1
    assert len(delays) == 2
    assert 0.5 <= delays[0] < 1.5       # min(8, 2**0) * [0.5, 1.5)
    assert 1.0 <= delays[1] < 3.0       # min(8, 2**1) * [0.5, 1.5)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
async def test_each_transient_status_is_retried(install, delays, code) -> None:
    fake = install(FakeGenai(script(api_error(code), response(good_doc()))))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 2 and len(result["extracted"]) == 1
    assert len(delays) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transient",
    [TimeoutError("slow"), asyncio.TimeoutError(), ConnectionError("reset"), ConnectionResetError("reset"),
     httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("bad")],
)
async def test_timeouts_and_transport_errors_are_retried(install, delays, transient) -> None:
    fake = install(FakeGenai(script(transient, response(good_doc()))))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 2 and len(result["extracted"]) == 1
    assert len(delays) == 1


@pytest.mark.asyncio
async def test_the_backoff_is_capped_at_eight_seconds_times_the_jitter(install, monkeypatch, delays) -> None:
    configure(monkeypatch, gemini_max_attempts=6)
    install(FakeGenai(always(api_error(503))))

    with pytest.raises(ExtractionError):
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(delays) == 5  # no sleep after the last attempt
    for attempt, delay in enumerate(delays, start=1):
        base = min(8, 2 ** (attempt - 1))
        assert 0.5 * base <= delay < 1.5 * base, (attempt, delay)
    assert delays[4] >= 4.0  # attempt 5 uses the cap (8), not 16


@pytest.mark.asyncio
async def test_exhausted_transient_errors_report_the_status_and_attempts_but_not_the_server_text(install) -> None:
    fake = install(FakeGenai(always(api_error(503, message="TOP-SECRET-CONTENT"))))

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 3
    error = raised.value
    assert "doc-1" in error.message and "3 attempts" in error.message and "503" in error.message
    assert "APIError" in error.message
    assert "TOP-SECRET-CONTENT" not in error.message
    assert error.detail == {"document_id": "doc-1", "attempts": 3, "status_code": 503}


HINTS = {
    404: "model or location not available to this project: check GEMINI_LIVE_MODEL / GEMINI_LIVE_LOCATION",
    401: "check the credentials and that the principal has roles/aiplatform.user",
    403: "check the credentials and that the principal has roles/aiplatform.user",
    400: "request rejected: schema or payload",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [404, 403, 401, 400])
async def test_a_client_error_that_can_never_succeed_fails_at_once_with_a_hint(install, delays, code) -> None:
    fake = install(FakeGenai(always(api_error(code))))

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 1 and delays == []
    assert raised.value.detail == {"document_id": "doc-1", "attempts": 1, "status_code": code, "hint": HINTS[code]}
    assert HINTS[code] in raised.value.message
    assert f"{code}" in raised.value.message and "1 attempt" in raised.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [409, 422, 501, 505])
async def test_other_status_codes_fail_at_once_without_a_hint(install, code) -> None:
    fake = install(FakeGenai(always(api_error(code))))

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 1
    assert raised.value.detail == {"document_id": "doc-1", "attempts": 1, "status_code": code}


@pytest.mark.asyncio
@pytest.mark.parametrize("unexpected", [ValueError("bug"), TypeError("bug"), KeyError("k"), RuntimeError("boom")])
async def test_an_exception_that_is_not_known_to_be_transient_is_not_retried(install, unexpected) -> None:
    fake = install(FakeGenai(always(unexpected)))

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 1
    assert type(unexpected).__name__ in raised.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["MAX_TOKENS", types.FinishReason.MAX_TOKENS])
async def test_max_tokens_fails_at_once_because_temperature_zero_would_truncate_again(install, delays, finish) -> None:
    truncated = response('{"doc_type": "COMMERCIAL_INV', finish=finish)
    fake = install(FakeGenai(always(truncated)))

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 1 and delays == []
    assert "MAX_TOKENS" in raised.value.message
    assert "GEMINI_MAX_OUTPUT_TOKENS" in raised.value.detail["hint"]


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", types.FinishReason.SAFETY])
async def test_a_blocked_answer_fails_at_once(install, delays, finish) -> None:
    fake = install(FakeGenai(always(response(None, finish=finish))))

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 1 and delays == []
    assert str(getattr(finish, "name", finish)) in raised.value.message


@pytest.mark.asyncio
async def test_a_blocked_prompt_fails_at_once(install) -> None:
    blocked = response(None, finish=None, block="SAFETY")
    fake = install(FakeGenai(always(blocked)))

    with pytest.raises(ExtractionError, match="SAFETY"):
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("attempts", [1, 2, 5])
async def test_the_attempt_limit_is_a_setting(install, monkeypatch, delays, attempts) -> None:
    configure(monkeypatch, gemini_max_attempts=attempts)
    fake = install(FakeGenai(always(api_error(503))))

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == attempts
    assert raised.value.detail["attempts"] == attempts
    assert len(delays) == attempts - 1


@pytest.mark.asyncio
async def test_cancellation_is_never_swallowed_or_retried(install) -> None:
    fake = install(FakeGenai(always(HANG)))
    task = asyncio.create_task(run_extraction_agent(ctx_for("doc-1")))
    await asyncio.sleep(0.05)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(fake.calls) == 1 and fake.cancelled == 1


def test_the_sleep_seam_defaults_to_asyncio_sleep() -> None:
    import importlib

    assert importlib.reload(extraction)._sleep is asyncio.sleep


# ---------------------------------------------------------------------------
# C6: concurrency
# ---------------------------------------------------------------------------

TYPES = {"doc-1": "COMMERCIAL_INVOICE", "doc-2": "PACKING_LIST", "doc-3": "BILL_OF_LADING", "doc-4": "MILL_TEST_CERTIFICATE",
         "doc-5": "CERTIFICATE_OF_ORIGIN", "doc-6": "PHYTOSANITARY"}


def by_document(_n: int, kwargs: dict[str, Any]) -> Any:
    return response(good_doc(doc_type=TYPES[doc_of(kwargs)]))


@pytest.mark.asyncio
async def test_documents_come_back_in_input_order_even_when_the_first_is_the_slowest(install) -> None:
    latency = {"doc-1": 0.15, "doc-2": 0.01, "doc-3": 0.05}
    install(FakeGenai(by_document, delay=lambda kw: latency[doc_of(kw)]))

    result = await run_extraction_agent(ctx_for("doc-1", "doc-2", "doc-3"))

    assert [d.document_id for d in result["extracted"]] == ["doc-1", "doc-2", "doc-3"]
    assert [d.doc_type for d in result["extracted"]] == ["COMMERCIAL_INVOICE", "PACKING_LIST", "BILL_OF_LADING"]


@pytest.mark.asyncio
async def test_order_follows_the_bundle_documents_not_the_page_order(install) -> None:
    install(FakeGenai(by_document))
    ctx = ctx_for("doc-1", "doc-2", "doc-3")
    ctx["processed_pages"].reverse()  # pages arrive grouped 3, 2, 1

    result = await run_extraction_agent(ctx)

    assert [d.document_id for d in result["extracted"]] == ["doc-1", "doc-2", "doc-3"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("limit", "documents", "expected"), [(3, 6, 3), (2, 5, 2), (1, 3, 1), (4, 2, 2)])
async def test_at_most_the_configured_number_of_calls_are_in_flight(install, monkeypatch, limit, documents, expected) -> None:
    configure(monkeypatch, gemini_max_concurrency=limit)
    fake = install(FakeGenai(by_document, delay=0.03))

    result = await run_extraction_agent(ctx_for(*[f"doc-{i}" for i in range(1, documents + 1)]))

    assert fake.max_in_flight == expected
    assert len(result["extracted"]) == documents


@pytest.mark.asyncio
async def test_a_failing_document_cancels_the_others_and_raises_the_extraction_error_itself(install) -> None:
    def outcome(_n: int, kwargs: dict[str, Any]) -> Any:
        return api_error(404) if doc_of(kwargs) == "doc-2" else HANG

    # doc-2 fails after 50 ms, while doc-1 and doc-3 are in flight (and would otherwise hang for an hour)
    fake = install(FakeGenai(outcome, delay=lambda kw: 0.05 if doc_of(kw) == "doc-2" else 0.0))
    before = asyncio.all_tasks()

    started = asyncio.get_running_loop().time()
    with pytest.raises(ExtractionError) as raised:  # not an ExceptionGroup
        await run_extraction_agent(ctx_for("doc-1", "doc-2", "doc-3"))

    assert asyncio.get_running_loop().time() - started < 1.0, "siblings must be cancelled, not waited for"
    assert raised.value.detail["document_id"] == "doc-2"
    assert fake.cancelled == 2  # doc-1 and doc-3 were in flight and got cancelled
    assert fake.in_flight == 0
    assert asyncio.all_tasks() == before, "no task may be left running"


@pytest.mark.asyncio
async def test_a_queued_document_never_starts_once_a_sibling_has_failed(install, monkeypatch) -> None:
    configure(monkeypatch, gemini_max_concurrency=1)
    fake = install(FakeGenai(lambda _n, kw: api_error(404) if doc_of(kw) == "doc-1" else response(good_doc())))

    with pytest.raises(ExtractionError):
        await run_extraction_agent(ctx_for("doc-1", "doc-2", "doc-3"))

    assert [doc_of(call) for call in fake.calls] == ["doc-1"]


@pytest.mark.asyncio
async def test_the_failure_reported_is_the_first_in_document_order(install) -> None:
    install(FakeGenai(lambda _n, kw: api_error(403 if doc_of(kw) == "doc-1" else 404)))

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx_for("doc-1", "doc-2", "doc-3"))

    assert raised.value.detail["document_id"] == "doc-1"
    assert raised.value.detail["status_code"] == 403


@pytest.mark.asyncio
async def test_cancelling_the_run_cancels_every_document_call(install) -> None:
    fake = install(FakeGenai(always(HANG)))
    before = asyncio.all_tasks()
    task = asyncio.create_task(run_extraction_agent(ctx_for("doc-1", "doc-2", "doc-3")))
    await asyncio.sleep(0.05)
    assert fake.in_flight == 3

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake.cancelled == 3 and fake.in_flight == 0
    assert asyncio.all_tasks() - before == set()


@pytest.mark.asyncio
async def test_document_types_are_recorded_after_all_documents_succeed_in_order(install, monkeypatch) -> None:
    recorded: list[tuple[str, str, str]] = []

    async def update(bundle_id: str, document_id: str, doc_type: str) -> None:
        recorded.append((bundle_id, document_id, doc_type))

    monkeypatch.setattr(firestore, "update_document_doc_type", update)
    latency = {"doc-1": 0.1, "doc-2": 0.0}
    install(FakeGenai(by_document, delay=lambda kw: latency[doc_of(kw)]))

    await run_extraction_agent(ctx_for("doc-1", "doc-2", bundle_id="bnd-1"))

    assert recorded == [("bnd-1", "doc-1", "COMMERCIAL_INVOICE"), ("bnd-1", "doc-2", "PACKING_LIST")]


@pytest.mark.asyncio
async def test_a_failed_run_records_no_document_types(install, monkeypatch) -> None:
    recorded: list[str] = []

    async def update(_bundle_id: str, document_id: str, _doc_type: str) -> None:
        recorded.append(document_id)

    monkeypatch.setattr(firestore, "update_document_doc_type", update)
    install(FakeGenai(lambda _n, kw: api_error(404) if doc_of(kw) == "doc-2" else response(good_doc())))

    with pytest.raises(ExtractionError):
        await run_extraction_agent(ctx_for("doc-1", "doc-2", bundle_id="bnd-1"))

    assert recorded == []


# ---------------------------------------------------------------------------
# C7: guards before any call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_document_over_the_page_limit_is_refused_before_any_call(install, monkeypatch) -> None:
    configure(monkeypatch, gemini_max_pages=3)
    fake = install(FakeGenai(by_document))
    ctx = ctx_for("doc-1")  # fine
    big = ctx_for("doc-2", pages=4)
    ctx["documents"] += big["documents"]
    ctx["processed_pages"] += big["processed_pages"]

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx)

    assert fake.calls == [], "no Gemini request may be made, not even for the document that was fine"
    assert raised.value.message == "document doc-2 has 4 pages; the limit is 3"
    assert raised.value.detail["document_id"] == "doc-2"


@pytest.mark.asyncio
async def test_a_document_exactly_at_the_page_limit_is_accepted(install, monkeypatch) -> None:
    configure(monkeypatch, gemini_max_pages=3)
    fake = install(FakeGenai(by_document))

    await run_extraction_agent(ctx_for("doc-1", pages=3))

    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_a_request_over_the_size_limit_is_refused_before_any_call(install, monkeypatch) -> None:
    configure(monkeypatch, gemini_max_request_mb=1)
    fake = install(FakeGenai(by_document))
    ctx = ctx_for("doc-1")
    ctx["processed_pages"][0]["payload"] = b"x" * (2 * 1024 * 1024)

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx)

    assert fake.calls == []
    assert "doc-1" in raised.value.message and "MB" in raised.value.message and "the limit is 1 MB" in raised.value.message
    assert raised.value.detail["document_id"] == "doc-1"


@pytest.mark.asyncio
async def test_the_size_limit_counts_the_base64_encoded_request(install, monkeypatch) -> None:
    """The SDK sends bytes as base64 (4 bytes per 3), so 786432 raw bytes are exactly 1 MiB on the wire."""
    configure(monkeypatch, gemini_max_request_mb=1)
    fake = install(FakeGenai(always(response(good_doc()))))

    exactly = ctx_for("doc-1")
    exactly["processed_pages"][0]["payload"] = b"x" * 786_432
    await run_extraction_agent(exactly)
    assert len(fake.calls) == 1

    over = ctx_for("doc-2")
    over["processed_pages"][0]["payload"] = b"x" * 786_433
    with pytest.raises(ExtractionError):
        await run_extraction_agent(over)
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_the_size_limit_is_per_request_not_per_bundle(install, monkeypatch) -> None:
    configure(monkeypatch, gemini_max_request_mb=1)
    fake = install(FakeGenai(always(response(good_doc()))))
    ctx = ctx_for("doc-1", "doc-2", "doc-3")
    for page in ctx["processed_pages"]:
        page["payload"] = b"x" * 600_000  # 800 KB on the wire each: fine one at a time, 2.4 MB together

    await run_extraction_agent(ctx)

    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_the_size_of_all_pages_of_one_document_adds_up(install, monkeypatch) -> None:
    configure(monkeypatch, gemini_max_request_mb=1)
    fake = install(FakeGenai(by_document))
    ctx = ctx_for("doc-1", pages=3)
    for page in ctx["processed_pages"]:
        page["payload"] = b"x" * 400_000  # 533 KB each, 1.6 MB together

    with pytest.raises(ExtractionError, match="doc-1"):
        await run_extraction_agent(ctx)

    assert fake.calls == []


# ---------------------------------------------------------------------------
# C8: stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_describe_each_document_in_document_order(install) -> None:
    latency = {"doc-1": 0.05, "doc-2": 0.0}
    doc = good_doc()
    doc["consignee"]["bbox"]["ymax"] = 9999
    install(FakeGenai(script(api_error(503), response(doc), response(good_doc())), delay=lambda kw: latency[doc_of(kw)]))

    result = await run_extraction_agent(ctx_for("doc-1", "doc-2"))

    stats = result["extraction_stats"]
    assert [s["document_id"] for s in stats] == ["doc-1", "doc-2"]
    assert set(stats[0]) == {"document_id", "attempts", "latency_ms", "prompt_tokens", "output_tokens", "warnings"}
    assert {s["attempts"] for s in stats} == {1, 2}
    for s in stats:
        assert s["latency_ms"] >= 0
        assert s["prompt_tokens"] == 1200 and s["output_tokens"] == 340
    assert sum(s["warnings"] for s in stats) == 1 == len(result["extraction_warnings"])


@pytest.mark.asyncio
async def test_missing_usage_metadata_gives_none_tokens(install) -> None:
    install(FakeGenai(always(response(good_doc(), usage=False))))

    [stat] = (await run_extraction_agent(ctx_for("doc-1")))["extraction_stats"]

    assert stat["prompt_tokens"] is None and stat["output_tokens"] is None
    assert stat["warnings"] == 0 and stat["attempts"] == 1


@pytest.mark.asyncio
async def test_a_fake_without_the_usage_attribute_at_all_is_tolerated(install) -> None:
    bare = response(good_doc())
    del bare.usage_metadata
    del bare.candidates
    install(FakeGenai(always(bare)))

    [stat] = (await run_extraction_agent(ctx_for("doc-1")))["extraction_stats"]

    assert stat["prompt_tokens"] is None and stat["output_tokens"] is None


@pytest.mark.asyncio
async def test_one_structured_log_line_per_document(install) -> None:
    from structlog.testing import capture_logs

    install(FakeGenai(by_document))

    with capture_logs() as logs:
        await run_extraction_agent(ctx_for("doc-1", "doc-2"))

    lines = [entry for entry in logs if entry["event"] == "gemini_extraction_document"]
    assert sorted(entry["document_id"] for entry in lines) == ["doc-1", "doc-2"]
    assert {"attempts", "latency_ms", "prompt_tokens", "output_tokens", "warnings", "doc_type"} <= set(lines[0])


@pytest.mark.asyncio
async def test_the_fixture_path_reports_empty_stats_and_warnings() -> None:
    result = await run_extraction_agent({"bundle_id": "", "documents": [{"document_id": "d", "filename": "packing_list.pdf"}]})

    assert result["extraction_source"] == "fixture"
    assert result["extraction_stats"] == [] and result["extraction_warnings"] == []


# ---------------------------------------------------------------------------
# the request is what the tests believe it is (guard against a fake that proves nothing)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_document_is_sent_in_its_own_request(install) -> None:
    fake = install(FakeGenai(by_document))

    await run_extraction_agent(ctx_for("doc-1", "doc-2"))

    assert sorted(payload_of(c) for c in fake.calls) == ["doc-1-p1", "doc-2-p1"]


# ---------------------------------------------------------------------------
# the client factory and a response whose .text raises
# ---------------------------------------------------------------------------


def test_the_client_is_built_for_vertex_in_the_configured_project_and_location_and_cached(monkeypatch) -> None:
    import google.genai as genai_module

    built: list[dict[str, Any]] = []
    monkeypatch.setattr(genai_module, "Client", lambda **kw: built.append(kw) or SimpleNamespace(kind="client"))
    monkeypatch.setattr(extraction, "use_live_gcp", lambda: True)

    first = extraction._get_genai_client()
    second = extraction._get_genai_client()

    assert built == [{"vertexai": True, "project": settings.project_id, "location": settings.gemini_live_location}]
    assert first is second


def test_a_client_that_cannot_be_built_is_an_upstream_error_in_live_mode_and_a_fallback_in_demo(monkeypatch) -> None:
    import google.genai as genai_module

    from app.gateway.errors import UpstreamError

    def boom(**_kw):
        raise RuntimeError("bad credentials file")

    monkeypatch.setattr(genai_module, "Client", boom)
    monkeypatch.setattr(extraction, "use_live_gcp", lambda: True)

    assert extraction._get_genai_client() is None  # demo mode: fixtures remain available

    monkeypatch.setattr(settings, "app_mode", "live")
    with pytest.raises(UpstreamError, match="Gemini client init failed in live mode"):
        extraction._get_genai_client()


@pytest.mark.asyncio
async def test_a_response_whose_text_property_raises_counts_as_empty(install) -> None:
    class Exploding:
        candidates = None
        usage_metadata = None
        prompt_feedback = None

        @property
        def text(self) -> str:
            raise ValueError("no text part")

    fake = install(FakeGenai(always(Exploding())))

    with pytest.raises(ExtractionError, match="empty response"):
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 3


# ---------------------------------------------------------------------------
# A1: every listed document must have pages (live mode)
# ---------------------------------------------------------------------------


def with_unpaged(ctx: dict[str, Any], *doc_ids: str) -> dict[str, Any]:
    ctx["documents"] += [{"document_id": d, "filename": f"{d}.pdf"} for d in doc_ids]
    return ctx


@pytest.mark.asyncio
async def test_a_listed_document_without_pages_raises_before_any_request_in_live_mode(install) -> None:
    fake = install(FakeGenai(by_document))

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(with_unpaged(ctx_for("doc-1"), "doc-2", "doc-3"))

    assert fake.calls == [], "no Gemini request may be made for the document that does have pages"
    assert raised.value.detail == {"document_ids": ["doc-2", "doc-3"]}
    assert "doc-2" in raised.value.message and "doc-3" in raised.value.message
    assert "doc-1" not in raised.value.message


@pytest.mark.asyncio
async def test_a_single_unpaged_document_is_named_in_the_message(install) -> None:
    install(FakeGenai(by_document))

    with pytest.raises(ExtractionError, match="no processed pages for document.*doc-2"):
        await run_extraction_agent(with_unpaged(ctx_for("doc-1"), "doc-2"))


@pytest.mark.asyncio
async def test_listed_documents_that_all_have_pages_are_extracted_as_before(install) -> None:
    fake = install(FakeGenai(by_document))

    result = await run_extraction_agent(ctx_for("doc-1", "doc-2"))

    assert [d.document_id for d in result["extracted"]] == ["doc-1", "doc-2"] and len(fake.calls) == 2


@pytest.mark.asyncio
async def test_pages_of_a_document_that_is_not_listed_do_not_trip_the_check(install) -> None:
    fake = install(FakeGenai(by_document))
    ctx = ctx_for("doc-1", "doc-2")
    ctx["documents"] = ctx["documents"][:1]  # doc-2 has pages but is not in the bundle's list

    result = await run_extraction_agent(ctx)

    assert [d.document_id for d in result["extracted"]] == ["doc-1", "doc-2"] and len(fake.calls) == 2


@pytest.mark.asyncio
async def test_a_listed_entry_without_a_document_id_is_ignored(install) -> None:
    fake = install(FakeGenai(by_document))
    ctx = ctx_for("doc-1")
    ctx["documents"] += [{"filename": "mystery.pdf"}, {"document_id": None}, {"document_id": ""}]

    result = await run_extraction_agent(ctx)

    assert len(result["extracted"]) == 1 and len(fake.calls) == 1


@pytest.mark.asyncio
async def test_demo_mode_is_unchanged_for_a_listed_document_without_pages(install, monkeypatch) -> None:
    fake = install(FakeGenai(by_document))
    monkeypatch.setattr(settings, "app_mode", "demo")

    result = await run_extraction_agent(with_unpaged(ctx_for("doc-1"), "doc-2"))

    assert [d.document_id for d in result["extracted"]] == ["doc-1"] and len(fake.calls) == 1


@pytest.mark.asyncio
async def test_the_check_runs_before_the_page_and_size_guards(install, monkeypatch) -> None:
    monkeypatch.setattr(settings, "gemini_max_pages", 1)
    install(FakeGenai(by_document))

    with pytest.raises(ExtractionError, match="no processed pages"):
        await run_extraction_agent(with_unpaged(ctx_for("doc-1", pages=3), "doc-2"))


# ---------------------------------------------------------------------------
# A2: doc_type_confidence is clamped like any other confidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_doc_type_confidence_of_1_2_is_accepted_with_a_warning_instead_of_burning_the_attempts(install) -> None:
    doc = good_doc()
    doc["doc_type_confidence"] = 1.2
    fake = install(FakeGenai(always(response(doc))))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 1, "one attempt: the answer is usable"
    assert result["extracted"][0].doc_type_confidence == 1.0
    assert result["extracted"][0].doc_type == "COMMERCIAL_INVOICE"  # never touched
    assert [(w["document_id"], w["path"]) for w in result["extraction_warnings"]] == [("doc-1", "doc_type_confidence")]
    assert "1.2" in result["extraction_warnings"][0]["reason"] and "1" in result["extraction_warnings"][0]["reason"]
    assert result["extraction_stats"][0]["warnings"] == 1


@pytest.mark.parametrize(
    ("given", "clamped"),
    [(1.4, 1.0), (-0.3, 0.0), (0.9, 0.9), (0, 0.0), (1, 1.0), ("high", 0.0), (None, 0.0), (True, 0.0),
     (float("nan"), 0.0), (float("inf"), 1.0), ([0.9], 0.0)],
)
def test_doc_type_confidence_is_clamped_to_0_1_and_a_non_number_becomes_0(given: Any, clamped: float) -> None:
    clean, warnings = _sanitise_extraction(raw_doc(doc_type_confidence=given), 3)

    assert clean["doc_type_confidence"] == clamped
    assert bool(warnings) == (given != clamped or isinstance(given, bool))
    assert all(w["path"] == "doc_type_confidence" for w in warnings)


def test_doc_type_itself_is_never_touched() -> None:
    clean, _ = _sanitise_extraction(raw_doc(doc_type="NOT-A-REAL-TYPE", doc_type_confidence=9), 1)
    assert clean["doc_type"] == "NOT-A-REAL-TYPE"  # left for the schema to reject


def test_a_missing_doc_type_confidence_is_left_for_the_schema() -> None:
    raw = {"document_id": "x", "doc_type": "PACKING_LIST"}
    clean, warnings = _sanitise_extraction(raw, 1)
    assert "doc_type_confidence" not in clean and warnings == []


@pytest.mark.asyncio
async def test_a_missing_doc_type_confidence_still_fails_validation_and_is_retried(install) -> None:
    doc = good_doc()
    del doc["doc_type_confidence"]
    fake = install(FakeGenai(script(response(doc), response(good_doc()))))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(fake.calls) == 2 and len(result["extracted"]) == 1
    assert "doc_type_confidence" in " ".join(texts_of(fake.calls[1]))
