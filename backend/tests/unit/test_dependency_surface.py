"""Offline API-surface checks for third-party SDKs (no GCP credentials, no network).

These pin the *shape* of the SDK calls the app makes, so a dependency upgrade that renames or removes
something fails here instead of in production. They deliberately mirror the call sites in
  app/agents/extraction.py   (google-genai)
  app/services/storage.py    (google-cloud-storage)
  app/repo/firestore.py, app/services/audit.py   (google-cloud-firestore, async)
  app/agents/tools/bq_tariff.py   (google-cloud-bigquery)
  app/services/preprocess.py (opencv, numpy, Pillow, pdf2image)
  app/api/v1/stream.py       (sse-starlette)
"""

from __future__ import annotations

import inspect
import io
import json
import shutil
import warnings
from typing import Any

import pytest
from google.auth.credentials import AnonymousCredentials
from httpx import ASGITransport, AsyncClient

from app.domain.schemas import ExtractedDocument
from tests.helpers import CASE_C_DIR

# ---------------------------------------------------------------------------
# E1  google-genai
# ---------------------------------------------------------------------------


def test_genai_config_and_part_build_offline() -> None:
    from google.genai import types

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ExtractedDocument,
        system_instruction="x",
        temperature=0.0,
    )
    assert config.response_mime_type == "application/json"
    assert config.temperature == 0.0
    assert config.response_schema is ExtractedDocument

    part = types.Part.from_bytes(data=b"%PDF", mime_type="application/pdf")
    assert part.inline_data is not None
    assert part.inline_data.data == b"%PDF"
    assert part.inline_data.mime_type == "application/pdf"


def test_genai_client_constructs_without_network_and_exposes_the_async_surface() -> None:
    from google import genai

    client = genai.Client(api_key="offline")
    assert inspect.iscoroutinefunction(client.aio.models.generate_content)  # the async call extraction.py awaits


def test_genai_client_accepts_the_vertex_constructor_shape_used_by_the_app() -> None:
    from google import genai

    # extraction._get_genai_client builds genai.Client(vertexai=True, project=..., location=...);
    # anonymous credentials stand in for ADC so nothing is looked up or sent.
    client = genai.Client(
        vertexai=True,
        project="offline-project",
        location="asia-south1",
        credentials=AnonymousCredentials(),
    )
    assert client.vertexai is True


def test_genai_response_exposes_what_extraction_reads() -> None:
    """extraction.py reads response.text (not .parsed), the first candidate's finish_reason, the prompt-feedback
    block reason and the usage counts."""
    from google.genai import errors, types

    assert isinstance(getattr(types.GenerateContentResponse, "text", None), property)
    assert {"candidates", "usage_metadata", "prompt_feedback"} <= set(types.GenerateContentResponse.model_fields)
    assert "finish_reason" in types.Candidate.model_fields
    assert {"prompt_token_count", "candidates_token_count"} <= set(types.GenerateContentResponseUsageMetadata.model_fields)
    assert "block_reason" in types.GenerateContentResponsePromptFeedback.model_fields
    assert {"MAX_TOKENS", "SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"} <= {r.name for r in types.FinishReason}
    assert "thinking_budget" in types.ThinkingConfig.model_fields
    assert "max_output_tokens" in types.GenerateContentConfig.model_fields
    assert "thinking_config" in types.GenerateContentConfig.model_fields
    assert issubclass(errors.APIError, Exception) and errors.APIError(503, {"error": {"code": 503}}).code == 503


def _find_value_schemas(node: Any, found: list[dict[str, Any]]) -> None:
    """Collect every FieldRef-like schema: an object whose properties include `value` and `confidence`."""
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict) and "value" in props and "confidence" in props:
            found.append(props["value"])
        for child in node.values():
            _find_value_schemas(child, found)
    elif isinstance(node, list):
        for child in node:
            _find_value_schemas(child, found)


def test_extracted_document_converts_to_a_gemini_response_schema_offline() -> None:
    """The union `FieldRef.value: str | float | int | None` must survive conversion for Gemini.

    Uses a private helper (google.genai._transformers.t_schema); if the SDK renames it this test
    skips with a reason rather than breaking the suite.
    """
    from google import genai
    from google.genai import _transformers as transformers

    t_schema = getattr(transformers, "t_schema", None)
    if t_schema is None:
        pytest.skip("google.genai._transformers.t_schema no longer exists (private SDK helper was renamed)")

    client = genai.Client(api_key="offline")
    try:
        schema = t_schema(client._api_client, ExtractedDocument)
    except TypeError as exc:  # signature change in a future SDK
        pytest.skip(f"google.genai._transformers.t_schema signature changed: {exc}")

    assert schema is not None
    document = schema.model_dump(mode="json", exclude_none=True)
    json.dumps(document)  # serialises

    values: list[dict[str, Any]] = []
    _find_value_schemas(document, values)
    assert values, "no FieldRef.value schema found in the converted response schema"
    for value in values:
        assert value.get("nullable") is True  # every value may be null (field not printed)

    props = document["properties"]
    line_props = props["line_items"]["items"]["properties"]

    # Text fields (TextRef) convert to a plain nullable STRING: no string/number union. A code such as
    # 73041900 must come back as text, not as a number.
    text_fields = [props[n] for n in (
        "document_number", "consignee", "consignor", "vessel_or_flight", "port_of_loading", "port_of_discharge",
        "shipment_date", "invoice_currency", "hs_code_header")]
    text_fields += [line_props[n] for n in ("description", "quantity", "hs_code_declared", "currency")]
    for field in text_fields:
        value = field["properties"]["value"]
        assert value["type"] == "STRING", value
        assert "any_of" not in value, value
        assert value.get("nullable") is True

    # Numeric fields (plain FieldRef) and weights (QuantityRef) still allow numbers (and text as printed).
    numeric_fields = [props[n] for n in ("invoice_value", "package_count", "total_net_weight_kg",
                                         "total_gross_weight_kg", "tare_weight_kg")]
    numeric_fields += [line_props[n] for n in ("unit_price", "total_value", "net_weight_kg", "gross_weight_kg")]
    for field in numeric_fields:
        value = field["properties"]["value"]
        assert {option["type"] for option in value["any_of"]} == {"STRING", "NUMBER", "INTEGER"}, value

    # Weights carry the printed unit next to the value (QuantityRef): `unit` must reach the model's schema
    # on every weight field, header level and line-item level, and it must be a nullable string.
    for name in ("total_net_weight_kg", "total_gross_weight_kg", "tare_weight_kg"):
        weight = document["properties"][name]
        assert "unit" in weight["properties"], f"{name}: unit missing from the converted schema"
        assert weight["properties"]["unit"]["type"] == "STRING"
        assert weight["properties"]["unit"].get("nullable") is True
        assert "value" in weight["properties"]
    line_item = document["properties"]["line_items"]["items"]["properties"]
    for name in ("net_weight_kg", "gross_weight_kg"):
        assert "unit" in line_item[name]["properties"], f"line_items.{name}: unit missing"
    # non-weight fields stay plain FieldRefs (no unit)
    assert "unit" not in document["properties"]["consignee"]["properties"]


# ---------------------------------------------------------------------------
# E2  google-cloud-storage / firestore / bigquery
# ---------------------------------------------------------------------------


def test_cloud_storage_surface_used_by_services_storage() -> None:
    from google.cloud import storage

    assert callable(storage.Client)
    assert callable(storage.Bucket.blob)
    for method in ("upload_from_string", "exists", "download_as_bytes"):
        assert callable(getattr(storage.Blob, method)), method
    assert isinstance(inspect.getattr_static(storage.Blob, "metadata"), property)  # blob.metadata = {...}

    # Client(project=...) -> bucket() -> blob() -> metadata round-trips, all offline.
    client = storage.Client(project="offline-project", credentials=AnonymousCredentials())
    blob = client.bucket("cargoclear-raw-pdfs").blob("bundles/b/raw/d/original.pdf")
    blob.metadata = {"sha256": "abc", "bundle_id": "b"}
    assert blob.metadata == {"sha256": "abc", "bundle_id": "b"}
    assert "content_type" in inspect.signature(blob.upload_from_string).parameters


def test_firestore_async_surface_used_by_repo_and_audit() -> None:
    from google.cloud.firestore_v1 import async_client
    from google.cloud.firestore_v1.async_collection import AsyncCollectionReference
    from google.cloud.firestore_v1.async_document import AsyncDocumentReference
    from google.cloud.firestore_v1.async_query import AsyncQuery

    assert callable(async_client.AsyncClient)
    for method in ("collection", "collection_group"):
        assert callable(getattr(async_client.AsyncClient, method)), method
    for method in ("document", "order_by", "stream", "where", "limit"):
        assert callable(getattr(AsyncCollectionReference, method)), method
    for method in ("set", "get", "update", "collection"):
        assert callable(getattr(AsyncDocumentReference, method)), method
    for method in ("order_by", "limit", "stream", "where"):
        assert callable(getattr(AsyncQuery, method)), method
    assert "merge" in inspect.signature(AsyncDocumentReference.set).parameters  # set(..., merge=True)

    client = async_client.AsyncClient(
        project="offline-project", database="(default)", credentials=AnonymousCredentials()
    )
    runs = client.collection("bundles").document("bnd-1").collection("runs")
    assert runs.document("run-1").path == "bundles/bnd-1/runs/run-1"
    newest = runs.order_by("updated_at", direction="DESCENDING").limit(1)  # firestore.get_run_state
    assert isinstance(newest, AsyncQuery)
    # firestore.get_evidence_document uses the positional where(); google-cloud-firestore 2.3x still accepts it
    # but warns that `filter=FieldFilter(...)` is preferred. Tolerated here; tracked in Handoff.md.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Detected filter using positional arguments")
        group = client.collection_group("documents").where("document_id", "==", "doc-1").limit(1)
    assert isinstance(group, AsyncQuery)


def test_bigquery_surface_used_by_bq_tariff() -> None:
    from google.cloud import bigquery

    assert callable(bigquery.Client)
    assert callable(bigquery.Client.query)
    assert "job_config" in inspect.signature(bigquery.Client.query).parameters
    assert callable(bigquery.job.QueryJob.result)

    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("q", "STRING", "seamless steel pipes"),
            bigquery.ScalarQueryParameter("dest", "STRING", "SG"),
        ]
    )
    assert [p.name for p in config.query_parameters] == ["q", "dest"]
    assert [p.value for p in config.query_parameters] == ["seamless steel pipes", "SG"]


# ---------------------------------------------------------------------------
# E3  numpy / opencv / Pillow / pdf2image
# ---------------------------------------------------------------------------


def _tilted_lines_png(angle_deg: float) -> bytes:
    """A white page with long dark text-like lines tilted by `angle_deg`, encoded as PNG by Pillow."""
    import math

    from PIL import Image, ImageDraw

    width, height = 900, 500
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    slope = math.tan(math.radians(angle_deg))
    for y0 in (100, 200, 300, 400):
        draw.line([(40, y0), (width - 40, y0 + slope * (width - 80))], fill=0, width=3)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_opencv_decodes_png_with_numpy_2() -> None:
    import cv2
    import numpy as np

    png = _tilted_lines_png(0.0)
    decoded = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert decoded is not None
    assert decoded.shape == (500, 900)
    assert decoded.dtype == np.uint8
    edges = cv2.Canny(decoded, 50, 150, apertureSize=3)
    assert edges.any()
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10)
    assert lines is not None  # the exact calls estimate_skew_angle makes


def test_estimate_skew_angle_really_runs_opencv_not_its_silent_fallback() -> None:
    """estimate_skew_angle swallows every exception and returns 0.0, so a broken opencv/numpy pairing would
    hide behind a zero. A tilted page must therefore come back as a clearly non-zero angle."""
    from app.services.preprocess import estimate_skew_angle

    angle = estimate_skew_angle(_tilted_lines_png(3.0))
    assert angle == pytest.approx(3.0, abs=1.0)


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler (pdftoppm) is not installed")
def test_pdf2image_renders_a_case_c_pdf_when_poppler_is_available() -> None:
    from pdf2image import convert_from_bytes

    pages = convert_from_bytes((CASE_C_DIR / "packing_list.pdf").read_bytes(), dpi=50, fmt="png")
    assert len(pages) == 1
    assert pages[0].width > 100


def test_pdf2image_imports() -> None:
    from pdf2image import convert_from_bytes

    assert callable(convert_from_bytes)


# ---------------------------------------------------------------------------
# E4  sse-starlette
# ---------------------------------------------------------------------------


def test_event_source_response_accepts_generator_and_ping() -> None:
    from sse_starlette.sse import EventSourceResponse

    async def events():
        yield {"event": "status", "data": "{}"}

    response = EventSourceResponse(events(), ping=15)
    assert response.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_event_source_response_emits_named_events_under_starlette() -> None:
    """Named events (`event: status`) must reach the wire exactly as the frontend's addEventListener expects."""
    from fastapi import FastAPI
    from sse_starlette.sse import EventSourceResponse

    app = FastAPI()

    @app.get("/s")
    async def stream():
        async def gen():
            yield {"event": "status", "data": json.dumps({"kind": "status", "state": "RUNNING"})}
            yield {"event": "iteration", "data": json.dumps({"iteration": 1})}

        return EventSourceResponse(gen(), ping=15)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get("/s")

    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: status" in body
    assert 'data: {"kind": "status", "state": "RUNNING"}' in body
    assert "event: iteration" in body
