"""The REAL google-genai SDK builds the generate_content request that extraction sends: offline, no network.

The SDK is given an ``httpx.MockTransport`` and fake (already valid) credentials, so nothing is refreshed and
nothing leaves the process. ``run_extraction_agent`` runs unchanged on top of it, which proves three things the
fake-client tests cannot:

  1. what is actually serialised on the wire (parts, labels, config, the response schema);
  2. that extraction reads the SDK's REAL response objects (``.text``, enum ``finish_reason``, ``usage_metadata``);
  3. that the retry policy classifies the SDK's REAL error classes (HTTP 503 / 404 / ...) correctly.

The response schema is pinned in ``gemini_request_schema_snapshot.json`` (a golden file): any change to
``agents/extraction_wire.py`` (or to a reference field of ``ExtractedDocument``, whose names it derives) that changes what Gemini is
asked for fails here and must be a deliberate edit. To accept
a change: ``UPDATE_GEMINI_SCHEMA_SNAPSHOT=1 .venv/bin/python -m pytest tests/unit/test_gemini_request_schema.py``
and review the diff of the JSON file.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
from google import genai
from google.auth.credentials import Credentials
from google.genai import types

from app.agents import extraction
from app.agents.extraction import SYSTEM_INSTRUCTION, run_extraction_agent
from app.core.config import settings
from app.gateway.errors import ExtractionError
from tests.unit.extraction_fakes import ctx_for, good_doc

SNAPSHOT = Path(__file__).with_name("gemini_request_schema_snapshot.json")
ALLOWED_KEYWORDS = {
    "description", "enum", "items", "maximum", "minimum", "nullable", "properties", "property_ordering", "required", "title", "type",
}


def pick(mapping: dict[str, Any], snake: str) -> Any:
    """Nested keys are snake_case in the installed SDK's JSON (protobuf-JSON accepts both); tolerate either."""
    camel = "".join(word if i == 0 else word.capitalize() for i, word in enumerate(snake.split("_")))
    return mapping[snake] if snake in mapping else mapping[camel]


class FakeCredentials(Credentials):
    """Looks valid (a token, no expiry), so the SDK never calls refresh() and never contacts a token endpoint."""

    def __init__(self) -> None:
        super().__init__()
        self.token = "fake-token-never-sent-anywhere"

    def refresh(self, request: Any) -> None:  # pragma: no cover - would mean the SDK tried to reach out
        raise AssertionError("the SDK tried to refresh credentials")


def ok(text: str | None = None, **extra: Any) -> Callable[[], httpx.Response]:
    answer = text if text is not None else json.dumps(good_doc())
    body = {
        "candidates": [{"content": {"role": "model", "parts": [{"text": answer}]}, "finishReason": extra.pop("finish", "STOP")}],
        "usageMetadata": {"promptTokenCount": 1234, "candidatesTokenCount": 567},
        **extra,
    }
    return lambda: httpx.Response(200, json=body)


def failure(code: int) -> Callable[[], httpx.Response]:
    body = {"error": {"code": code, "message": "TOP-SECRET-CONTENT", "status": "SOME_STATUS"}}
    return lambda: httpx.Response(code, json=body)


def transport_error(exc: Exception) -> Callable[[], httpx.Response]:
    def raise_it() -> httpx.Response:
        raise exc

    return raise_it


class Wire:
    """Plays the Vertex endpoint: answers the n-th request with the n-th scripted answer (the last repeats)."""

    def __init__(self, *answers: Callable[[], httpx.Response]) -> None:
        self.answers = answers or (ok(),)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.answers[min(len(self.requests), len(self.answers)) - 1]()

    def body(self, index: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[index].read())


@pytest.fixture
def delays(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []

    async def record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(extraction, "_sleep", record)
    return recorded


@pytest.fixture
async def offline(monkeypatch: pytest.MonkeyPatch):
    """Factory: ``offline(wire)`` installs a real genai client wired to the mock endpoint as the extraction client."""
    opened: list[httpx.AsyncClient] = []

    def install(wire: Wire) -> genai.Client:
        async_http = httpx.AsyncClient(transport=httpx.MockTransport(wire))
        opened.append(async_http)
        client = genai.Client(
            vertexai=True,
            project="offline-project",
            location="asia-south1",
            credentials=FakeCredentials(),
            http_options=types.HttpOptions(
                httpx_client=httpx.Client(transport=httpx.MockTransport(wire)), httpx_async_client=async_http
            ),
        )
        monkeypatch.setattr(settings, "app_mode", "live")
        monkeypatch.setattr(extraction, "_get_genai_client", lambda: client)
        return client

    yield install
    for http in opened:
        await http.aclose()


# ---------------------------------------------------------------------------
# what goes on the wire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_request_the_sdk_sends_for_a_page_image_bundle(offline, monkeypatch) -> None:
    monkeypatch.setattr(settings, "gemini_max_output_tokens", 4096)
    monkeypatch.setattr(settings, "gemini_thinking_budget", 0)
    wire = Wire()
    offline(wire)

    result = await run_extraction_agent(ctx_for("doc-1", pages=2))

    assert len(wire.requests) == 1
    request = wire.requests[0]
    assert request.method == "POST"
    assert request.url.host == "asia-south1-aiplatform.googleapis.com"
    assert request.url.path.endswith(
        "/projects/offline-project/locations/asia-south1/publishers/google/models/gemini-2.5-flash:generateContent"
    )
    body = wire.body()
    assert set(body) == {"contents", "generationConfig", "systemInstruction"}

    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert "responseSchema" in config
    assert config["temperature"] == 0.0
    assert config["maxOutputTokens"] == 4096
    assert pick(config["thinkingConfig"], "thinking_budget") == 0
    assert body["systemInstruction"]["parts"][0]["text"] == SYSTEM_INSTRUCTION

    [content] = body["contents"]
    assert content["role"] == "user"
    parts = content["parts"]
    assert [p.get("text") for p in parts] == [
        "Page 1 of 2.", None, "Page 2 of 2.", None, extraction.EXTRACT_INSTRUCTION,
    ]
    assert pick(parts[1]["inlineData"], "mime_type") == "image/png"
    assert parts[1]["inlineData"]["data"] == base64.b64encode(b"doc-1-p1").decode()
    assert parts[3]["inlineData"]["data"] == base64.b64encode(b"doc-1-p2").decode()
    assert result["extracted"][0].doc_type == "COMMERCIAL_INVOICE"


@pytest.mark.asyncio
async def test_a_raw_pdf_passthrough_is_one_unlabelled_application_pdf_part(offline) -> None:
    wire = Wire()
    offline(wire)

    await run_extraction_agent(ctx_for("doc-1", mime="application/pdf"))

    parts = wire.body()["contents"][0]["parts"]
    assert [pick(p["inlineData"], "mime_type") if "inlineData" in p else p["text"] for p in parts] == [
        "application/pdf", extraction.EXTRACT_INSTRUCTION,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(("budget", "present"), [(0, True), (2048, True), (-1, False)])
async def test_the_thinking_config_reaches_the_wire_only_when_configured(offline, monkeypatch, budget, present) -> None:
    monkeypatch.setattr(settings, "gemini_thinking_budget", budget)
    wire = Wire()
    offline(wire)

    await run_extraction_agent(ctx_for("doc-1"))

    config = wire.body()["generationConfig"]
    assert ("thinkingConfig" in config) is present
    if present:
        assert pick(config["thinkingConfig"], "thinking_budget") == budget


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("level", "sent"), [("MINIMAL", "MINIMAL"), ("LOW", "LOW"), ("HIGH", "HIGH"), ("DEFAULT", None)]
)
async def test_gemini_3_gets_a_thinking_level_and_never_a_budget(offline, monkeypatch, level, sent) -> None:
    """gemini-3.x refuses thinking_budget (any value) on a request with an image: it is never on the wire for that family."""
    monkeypatch.setattr(settings, "gemini_live_model", "gemini-3.5-flash")
    monkeypatch.setattr(settings, "gemini_thinking_level", level)
    monkeypatch.setattr(settings, "gemini_thinking_budget", 1024)
    wire = Wire()
    offline(wire)

    await run_extraction_agent(ctx_for("doc-1"))

    assert wire.requests[0].url.path.endswith("/models/gemini-3.5-flash:generateContent")
    config = wire.body()["generationConfig"]
    if sent is None:
        assert "thinkingConfig" not in config
    else:
        assert pick(config["thinkingConfig"], "thinking_level") == sent and "thinkingBudget" not in config["thinkingConfig"]
        assert "thinking_budget" not in config["thinkingConfig"]


# ---------------------------------------------------------------------------
# the response schema (golden file)
# ---------------------------------------------------------------------------


def _keywords(schema: Any) -> set[str]:
    """Every JSON-schema keyword used (property NAMES under ``properties`` are not keywords)."""
    found: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties":
                found.add("properties")
                for property_schema in value.values():
                    found |= _keywords(property_schema)
            else:
                found.add(key)
                found |= _keywords(value)
    elif isinstance(schema, list):
        for item in schema:
            found |= _keywords(item)
    return found


async def _request_schema(offline) -> dict[str, Any]:
    wire = Wire()
    offline(wire)
    await run_extraction_agent(ctx_for("doc-1"))
    return wire.body()["generationConfig"]["responseSchema"]


@pytest.mark.asyncio
async def test_the_response_schema_matches_the_golden_snapshot(offline) -> None:
    schema = await _request_schema(offline)

    if os.environ.get("UPDATE_GEMINI_SCHEMA_SNAPSHOT") == "1":
        SNAPSHOT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    expected = json.loads(SNAPSHOT.read_text())

    assert schema == expected, (
        "The response schema sent to Gemini changed. If that is intended, regenerate the golden file with "
        "UPDATE_GEMINI_SCHEMA_SNAPSHOT=1 and review the diff of tests/unit/gemini_request_schema_snapshot.json."
    )


@pytest.mark.asyncio
async def test_the_schema_uses_only_the_keywords_vertex_accepts(offline) -> None:
    keywords = _keywords(await _request_schema(offline))

    assert keywords == ALLOWED_KEYWORDS, (
        f"new: {sorted(keywords - ALLOWED_KEYWORDS)}, gone: {sorted(ALLOWED_KEYWORDS - keywords)}"
    )
    # no unresolved references reach the model
    assert not {"$ref", "$defs", "definitions", "anyOf", "default", "additionalProperties"} & keywords


@pytest.mark.asyncio
async def test_the_schema_is_four_lists_of_entries_with_the_field_name_as_an_enum(offline) -> None:
    """The shape that fits Gemini's limit on constraint states (agents/extraction_wire.py): one object shape per list, every
    property required, the field names an enum derived from the document model."""
    from app.agents import extraction_wire

    schema = await _request_schema(offline)

    assert schema["type"] == "OBJECT"
    assert schema["required"] == ["doc_type", "doc_type_confidence", "fields", "heat_numbers", "line_cells", "test_results"]
    assert schema["properties"]["doc_type"]["enum"][0] == "COMMERCIAL_INVOICE"
    assert "document_id" not in schema["properties"]  # the id is the system's, never the model's

    header = schema["properties"]["fields"]["items"]
    assert header["required"] == ["name", "value", "unit", "confidence", "page", "box"]
    assert header["properties"]["name"]["enum"] == list(extraction_wire.HEADER_FIELDS)
    assert header["properties"]["value"]["type"] == "STRING" and header["properties"]["value"]["nullable"] is True
    assert header["properties"]["box"]["type"] == "ARRAY" and header["properties"]["box"]["items"] == {"type": "NUMBER"}

    line = schema["properties"]["line_cells"]["items"]
    assert line["properties"]["name"]["enum"] == list(extraction_wire.LINE_FIELDS)
    assert line["properties"]["row"]["type"] == "INTEGER"

    lab = schema["properties"]["test_results"]["items"]
    assert {"heat_number", "parameter", "value", "unit"} <= set(lab["required"])


@pytest.mark.asyncio
async def test_the_schema_stays_far_below_the_size_and_shape_gemini_refused(offline) -> None:
    """Gemini refuses a response schema whose constrained-decoding grammar has too many states ("too many states for serving").
    Measured against gemini-2.5-flash and gemini-3.5-flash in asia-south1 on 2026-10-14: this shape (about 6 KB on the wire) is
    accepted with room to spare (40 more field names, or four more lists, were still accepted); the nested ExtractedDocument (about
    47 KB) was refused, and so was every nested variant above about 14 KB, those below it fitting with no room for one more field.
    Size is only a tripwire. What the grammar pays for is the number of distinct nested objects, so this also caps those. Passing is
    not proof of acceptance (that is scripts/preflight_gcp.py against the real endpoint); failing means the shape is drifting back."""
    schema = await _request_schema(offline)

    def object_shapes(node: Any) -> int:
        if isinstance(node, dict):
            return (node.get("type") == "OBJECT") + sum(object_shapes(child) for child in node.values())
        if isinstance(node, list):
            return sum(object_shapes(child) for child in node)
        return 0

    assert len(json.dumps(schema, separators=(",", ":"))) <= 12_000
    assert object_shapes(schema) - 1 <= 6, "the root is not counted: four entry shapes today, two more lists of room"


def test_the_snapshot_file_is_a_deliberate_artifact() -> None:
    schema = json.loads(SNAPSHOT.read_text())
    assert SNAPSHOT.read_text().endswith("\n")
    assert _keywords(schema) == ALLOWED_KEYWORDS


# ---------------------------------------------------------------------------
# extraction against the SDK's REAL response and error objects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_reads_the_real_response_object(offline) -> None:
    offline(Wire(ok()))

    result = await run_extraction_agent(ctx_for("doc-1"))

    [stat] = result["extraction_stats"]
    assert (stat["attempts"], stat["prompt_tokens"], stat["output_tokens"]) == (1, 1234, 567)
    assert result["extracted"][0].line_items[0].hs_code_declared.value == "73041900"


@pytest.mark.asyncio
async def test_a_real_max_tokens_finish_reason_fails_at_once(offline) -> None:
    wire = Wire(ok('{"doc_type": "COMMERCIAL_INV', finish="MAX_TOKENS"))
    offline(wire)

    with pytest.raises(ExtractionError, match="MAX_TOKENS"):
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(wire.requests) == 1


@pytest.mark.asyncio
async def test_a_real_503_is_retried_then_succeeds(offline, delays) -> None:
    wire = Wire(failure(503), failure(429), ok())
    offline(wire)

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(wire.requests) == 3 and len(delays) == 2
    assert result["extraction_stats"][0]["attempts"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "hint"), [
    (404, "check GEMINI_LIVE_MODEL / GEMINI_LIVE_LOCATION"),
    (403, "roles/aiplatform.user"),
    (400, "schema or payload"),
])
async def test_a_real_client_error_fails_at_once_with_its_hint(offline, delays, code, hint) -> None:
    wire = Wire(failure(code), ok())
    offline(wire)

    with pytest.raises(ExtractionError) as raised:
        await run_extraction_agent(ctx_for("doc-1"))

    assert len(wire.requests) == 1 and delays == []
    assert hint in raised.value.detail["hint"]
    assert raised.value.detail["status_code"] == code
    assert "TOP-SECRET-CONTENT" not in raised.value.message  # the server's text is never echoed


@pytest.mark.asyncio
async def test_a_real_transport_error_is_retried(offline, delays) -> None:
    wire = Wire(transport_error(httpx.ConnectError("connection refused")), ok())
    offline(wire)

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert len(wire.requests) == 2 and len(delays) == 1
    assert len(result["extracted"]) == 1


@pytest.mark.asyncio
async def test_a_fenced_answer_and_a_bad_box_survive_the_real_sdk_path(offline) -> None:
    doc = good_doc()
    doc["consignee"]["bbox"]["ymax"] = 4000
    offline(Wire(ok("```json\n" + json.dumps(doc) + "\n```")))

    result = await run_extraction_agent(ctx_for("doc-1"))

    assert result["extracted"][0].consignee.bbox is None
    assert [w["path"] for w in result["extraction_warnings"]] == ["consignee.bbox"]
