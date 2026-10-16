"""Shared helpers for the input-gating audit: the fixtures, a bundle driven through the real HTTP routes and the real pipeline, and a
metered Gemini client that records what every request cost.

The pipeline is the product's own: the FastAPI app in process (upload route, middleware, orchestrator, preprocessing, extraction,
engines). Storage, Firestore and the tariff lookup are the demo-mode local stand-ins (so nothing is written to a Google Cloud
project); the Gemini endpoint is the real Vertex AI one, reached through ``MeteredClient``, which forwards every call unchanged and
records ``usage_metadata`` (prompt, candidates, thoughts, total tokens, per modality) for each request, including the ones the
product's retry loop makes and the ones whose answer it then refuses.
"""

from __future__ import annotations

import contextvars
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from httpx import AsyncClient

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures" / "gating"
REPO_ROOT = HERE.parents[2]

CASE_C = REPO_ROOT / "fixtures" / "case_c"
CASE_D = REPO_ROOT / "fixtures" / "case_d"
CASE_C_FILES = ("commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf", "mtc_pipe_test_cert.pdf")
CASE_D_FILES = ("case_d_commercial_invoice.pdf", "case_d_bill_of_lading.pdf", "case_d_packing_list.pdf", "case_d_mtc_test_cert.pdf")


def manifest() -> dict[str, dict[str, Any]]:
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# metering
# ---------------------------------------------------------------------------

CURRENT_DOCUMENT: contextvars.ContextVar[str | None] = contextvars.ContextVar("gating_current_document", default=None)


def _modalities(details: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in details or []:
        modality = getattr(getattr(item, "modality", None), "name", None) or str(getattr(item, "modality", "?"))
        out[modality] = out.get(modality, 0) + int(getattr(item, "token_count", 0) or 0)
    return out


def usage_of(response: Any) -> dict[str, Any]:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return {}
    return {
        "prompt_token_count": getattr(meta, "prompt_token_count", None),
        "candidates_token_count": getattr(meta, "candidates_token_count", None),
        "thoughts_token_count": getattr(meta, "thoughts_token_count", None),
        "total_token_count": getattr(meta, "total_token_count", None),
        "prompt_tokens_by_modality": _modalities(getattr(meta, "prompt_tokens_details", None)),
    }


def request_shape(contents: Any) -> dict[str, Any]:
    """What was sent, without the bytes: how many image / pdf / text parts, the bytes of the media."""
    shape = {"image_parts": 0, "pdf_parts": 0, "text_parts": 0, "media_bytes": 0}
    for part in contents or []:
        data = getattr(part, "inline_data", None)
        if data is not None:
            mime = getattr(data, "mime_type", "") or ""
            shape["pdf_parts" if mime == "application/pdf" else "image_parts"] += 1
            shape["media_bytes"] += len(getattr(data, "data", b"") or b"")
        elif getattr(part, "text", None) is not None:
            shape["text_parts"] += 1
    return shape


class _Models:
    def __init__(self, real: Any, calls: list[dict[str, Any]]) -> None:
        self._real = real
        self._calls = calls

    async def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        started = time.perf_counter()
        entry: dict[str, Any] = {
            "document_id": CURRENT_DOCUMENT.get(),
            "model": model,
            "max_output_tokens": getattr(config, "max_output_tokens", None),
            "thinking_budget": getattr(getattr(config, "thinking_config", None), "thinking_budget", "not sent"),
            "request": request_shape(contents),
        }
        try:
            response = await self._real.aio.models.generate_content(model=model, contents=contents, config=config)
        except Exception as exc:  # noqa: BLE001 - recorded, then raised unchanged for the product's own retry policy
            entry.update(error=type(exc).__name__, code=getattr(exc, "code", None), seconds=round(time.perf_counter() - started, 2))
            self._calls.append(entry)
            raise
        candidates = getattr(response, "candidates", None) or []
        finish = getattr(candidates[0], "finish_reason", None) if candidates else None
        entry.update(
            usage=usage_of(response), finish_reason=getattr(finish, "name", None) or (str(finish) if finish else None),
            seconds=round(time.perf_counter() - started, 2),
        )
        self._calls.append(entry)
        return response


class MeteredClient:
    """Stands in for ``extraction._get_genai_client()``: ``client.aio.models.generate_content`` is all the product uses."""

    def __init__(self, real: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self.aio = SimpleNamespace(models=_Models(real, self.calls))


def install_meter(real_client: Any, monkeypatch: Any | None = None) -> MeteredClient:
    """Route the product's Gemini calls through a ``MeteredClient``. With a pytest ``monkeypatch`` the change is undone at teardown."""
    from app.agents import extraction

    meter = MeteredClient(real_client)
    original = extraction._extract_document

    async def tracked(client: Any, doc_id: str, pages: list[dict[str, Any]]) -> Any:
        token = CURRENT_DOCUMENT.set(doc_id)
        try:
            return await original(client, doc_id, pages)
        finally:
            CURRENT_DOCUMENT.reset(token)

    if monkeypatch is not None:
        monkeypatch.setattr(extraction, "_get_genai_client", lambda: meter)
        monkeypatch.setattr(extraction, "_extract_document", tracked)
    else:
        extraction._get_genai_client = lambda: meter  # type: ignore[assignment]
        extraction._extract_document = tracked  # type: ignore[assignment]
    return meter


def real_vertex_client() -> Any:
    from google import genai

    from app.core.config import settings

    return genai.Client(vertexai=True, project=settings.project_id, location=settings.gemini_live_location)


# ---------------------------------------------------------------------------
# a bundle through the real routes
# ---------------------------------------------------------------------------


@dataclass
class Upload:
    filename: str
    status: int
    code: str | None = None
    message: str | None = None
    document_id: str | None = None


@dataclass
class BundleRun:
    bundle_id: str = ""
    uploads: list[Upload] = field(default_factory=list)
    run: dict[str, Any] = field(default_factory=dict)
    assessment: dict[str, Any] | None = None
    extractions: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0


async def upload(
    client: AsyncClient, bundle_id: str, filename: str, data: bytes, content_type: str = "application/pdf", declared_type: str | None = None
) -> Upload:
    form = {"declared_type": declared_type} if declared_type else None
    response = await client.post(f"/api/v1/bundles/{bundle_id}/documents", files={"file": (filename, data, content_type)}, data=form)
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    error = body.get("error") if isinstance(body.get("error"), dict) else body
    return Upload(
        filename=filename, status=response.status_code, code=(error or {}).get("code"), message=(error or {}).get("message"),
        document_id=body.get("document_id") if response.status_code == 201 else None,
    )


async def run_bundle(
    client: AsyncClient, files: list[tuple[str, bytes]], *, destination: str = "SG", mode: str = "analyze", timeout: float = 900.0,
    bundle_id: str | None = None, declared_types: dict[str, str] | None = None,
) -> BundleRun:
    """Create a bundle (or reuse ``bundle_id``), upload ``files`` through the upload route, and, if anything was accepted, run
    ``/analyze`` (or ``/reassess``) and wait for the run to end."""
    from tests.helpers import wait_for_run

    result = BundleRun()
    started = time.perf_counter()
    if bundle_id is None:
        created = await client.post("/api/v1/bundles", json={"reference": "GATING-AUDIT", "destination_country": destination})
        assert created.status_code == 201, created.text
        bundle_id = created.json()["id"]
    result.bundle_id = bundle_id
    for filename, data in files:
        result.uploads.append(await upload(client, bundle_id, filename, data, declared_type=(declared_types or {}).get(filename)))
    if mode != "none" and (files == [] or any(u.status == 201 for u in result.uploads)):
        started_run = await client.post(f"/api/v1/bundles/{bundle_id}/{mode}")
        result.run = {"http_status": started_run.status_code}
        if started_run.status_code == 202:
            run_id = started_run.json()["run_id"]
            state = await wait_for_run(bundle_id, run_id, timeout=timeout, interval=0.25)
            result.run.update(run_id=run_id, state=state.get("state"), error=state.get("error"), stage=state.get("stage"))
            if state.get("state") == "COMPLETE":
                assessment = await client.get(f"/api/v1/bundles/{bundle_id}/assessment")
                result.assessment = assessment.json() if assessment.status_code == 200 else None
                extractions = await client.get(f"/api/v1/bundles/{bundle_id}/extractions")
                result.extractions = extractions.json() if extractions.status_code == 200 else []
        else:
            result.run["error"] = started_run.text[:300]
    result.seconds = round(time.perf_counter() - started, 2)
    return result


def swap_bundle(bundle: str, replacement_name: str, replacement: bytes, replaces: str | None) -> list[tuple[str, bytes]]:
    """The four documents of ``bundle`` ('case_c' or 'case_d') with ``replaces`` swapped for ``replacement`` (uploaded under that
    file name). A document with the same bytes as the replacement is dropped, as the upload route would merge the two."""
    base = {"case_c": (CASE_C, CASE_C_FILES), "case_d": (CASE_D, CASE_D_FILES)}[bundle.removesuffix("_swap")]
    out: list[tuple[str, bytes]] = []
    for name in base[1]:
        data = (base[0] / name).read_bytes()
        if name == replaces:
            out.append((replaces, replacement))
        elif data != replacement:
            out.append((name, data))
    return out


# ---------------------------------------------------------------------------
# reading a result
# ---------------------------------------------------------------------------


def flatten(document: dict[str, Any]) -> dict[str, Any]:
    """An extracted document as {path: value} for every populated value (boxes and confidences left out), to compare two readings."""
    flat: dict[str, Any] = {"doc_type": document.get("doc_type")}

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "value" in node and "confidence" in node:
                unit = node.get("unit")
                flat[path] = f"{node['value']} {unit}".strip() if unit else node["value"]
                return
            for key, child in node.items():
                if key in ("document_id", "doc_type_confidence", "bbox"):
                    continue
                walk(child, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]")

    for key, value in document.items():
        if key not in ("document_id", "doc_type", "doc_type_confidence"):
            walk(value, key)
    return flat


def diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    return {k: (a.get(k), b.get(k)) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


def calls_by_document(calls: list[dict[str, Any]]) -> dict[str | None, dict[str, Any]]:
    """Token totals per document id over every request made for it (retries included)."""
    out: dict[str | None, dict[str, Any]] = {}
    for call in calls:
        usage = call.get("usage") or {}
        row = out.setdefault(call.get("document_id"), {"requests": 0, "errors": 0, "prompt": 0, "candidates": 0, "thoughts": 0, "total": 0,
                                                       "image_parts": 0, "pdf_parts": 0, "finish_reasons": []})
        row["requests"] += 1
        row["errors"] += 1 if call.get("error") else 0
        row["prompt"] += usage.get("prompt_token_count") or 0
        row["candidates"] += usage.get("candidates_token_count") or 0
        row["thoughts"] += usage.get("thoughts_token_count") or 0
        row["total"] += usage.get("total_token_count") or 0
        row["image_parts"] = max(row["image_parts"], call["request"]["image_parts"])
        row["pdf_parts"] = max(row["pdf_parts"], call["request"]["pdf_parts"])
        if call.get("finish_reason"):
            row["finish_reasons"].append(call["finish_reason"])
    return out
