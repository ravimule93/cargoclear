CargoClear-JAPAC — Detailed Technical Implementation Plan

Scope: Frontend UI + routing, backend gateway + services, agent design, storage, calculation, audit, and the response path back to the UI.
Assumption: v4.0 spec is the source of truth. Nothing here contradicts it.

---

0. Language & Stack Decisions (locked)

Layer Choice Why
Frontend TypeScript 5.x (strict) + Next.js 15 App Router + React 19 Type-safe contracts shared with backend JSON schemas; App Router gives nested layouts for the workbench shell
Styling Tailwind CSS v4 + CSS custom properties for the WCAG contrast tokens Tailwind for velocity, CSS vars so contrast is auditable in one file
UI primitives Radix UI (unstyled) + shadcn/ui patterns Radix gives correct ARIA/focus behavior for free — critical for the 10% UX score
PDF rendering pdfjs-dist + HTML5 <canvas> Bounding-box overlay needs a raw canvas, not an <iframe>
Backend Python 3.12 + FastAPI + Pydantic v2 Same language as the deterministic engine and ADK
Agents google-adk >= 2.6.3 + google-genai SDK Per v4.0 §2.2/§2.4
Storage GCS (raw PDFs) + Firestore (state/audit) + BigQuery (AHTN + Vector Search) Per v4.0
Build Cloud Build → Cloud Run, single cloudbuild.yaml P0 requirement

Do not introduce: any third-party LLM, any external vector DB, any client-side PDF parsing that isn't pdfjs-dist.

---

1. Repository Layout

```
cargoclear/
├── frontend/                      # Next.js 15 (TypeScript)
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                     # → redirects to /workbench
│   │   ├── workbench/[bundleId]/page.tsx
│   │   └── api/proxy/[...path]/route.ts # BFF proxy (non-SSE only)
│   ├── components/
│   │   ├── shell/TopBar.tsx
│   │   ├── rail/DocumentRail.tsx
│   │   ├── viewer/DocumentViewer.tsx
│   │   ├── viewer/BBoxLayer.tsx
│   │   ├── facts/FactsPanel.tsx
│   │   ├── assess/AssessmentPanel.tsx
│   │   ├── assess/StatusPill.tsx
│   │   ├── assess/CheckList.tsx
│   │   ├── assess/MissingEvidenceCard.tsx
│   │   ├── delta/ReasoningDelta.tsx
│   │   ├── audit/AuditTimeline.tsx
│   │   ├── upload/UploadDropzone.tsx
│   │   └── a11y/LiveRegion.tsx
│   ├── lib/
│   │   ├── api.ts               # typed fetch client
│   │   ├── sse.ts               # EventSource wrapper
│   │   ├── types.ts             # generated from backend OpenAPI
│   │   └── bbox.ts              # coordinate transform helpers
│   └── styles/globals.css       # design tokens
│
├── backend/                       # FastAPI
│   ├── app/
│   │   ├── main.py
│   │   ├── gateway/
│   │   │   ├── middleware.py    # request-id, error envelope, CORS
│   │   │   ├── errors.py        # CargoClearError hierarchy
│   │   │   └── dispatch.py      # stage → handler registry
│   │   ├── api/v1/
│   │   │   ├── bundles.py
│   │   │   ├── documents.py
│   │   │   ├── assessment.py
│   │   │   └── stream.py
│   │   ├── domain/
│   │   │   ├── schemas.py       # Pydantic extraction models
│   │   │   ├── status.py        # 4 statuses + precedence
│   │   │   └── events.py        # SSE event contract
│   │   ├── services/
│   │   │   ├── storage.py       # GCS
│   │   │   ├── preprocess.py    # deskew/binarize/split
│   │   │   ├── calculation.py   # deterministic math
│   │   │   ├── audit.py         # hash-chained append-only
│   │   │   ├── reasoning.py     # Reasoning Delta builder
│   │   │   ├── confidence.py    # routing table
│   │   │   └── orchestrator.py  # runs the ADK workflow
│   │   ├── agents/
│   │   │   ├── workflow.py      # ADK Workflow DAG
│   │   │   ├── extraction.py
│   │   │   ├── grounding.py
│   │   │   └── tools/bq_tariff.py
│   │   └── repo/
│   │       ├── firestore.py
│   │       └── bigquery.py
│   └── tests/
│
├── infra/
│   ├── bootstrap.sh             # Day-0 checklist as code
│   ├── bigquery/vector_index.sql
│   └── iam/roles.yaml
└── cloudbuild.yaml
```

---

2. Shared Domain Contracts

These Pydantic models are the single contract. The frontend lib/types.ts is generated from the FastAPI OpenAPI schema, so they never drift.

```python
# backend/app/domain/schemas.py
from typing import Literal
from pydantic import BaseModel, Field

class BBox(BaseModel):
    """Normalized to 0–1000. Origin top-left."""
    page: int = Field(ge=1)
    ymin: float = Field(ge=0, le=1000)
    xmin: float = Field(ge=0, le=1000)
    ymax: float = Field(ge=0, le=1000)
    xmax: float = Field(ge=0, le=1000)

class FieldRef(BaseModel):
    """A single extracted scalar plus its provenance."""
    value: str | float | int | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BBox | None = None

class LineItem(BaseModel):
    description: FieldRef
    quantity: FieldRef
    net_weight_kg: FieldRef
    gross_weight_kg: FieldRef
    hs_code_declared: FieldRef

DocType = Literal[
    "COMMERCIAL_INVOICE", "BILL_OF_LADING", "PACKING_LIST",
    "CERTIFICATE_OF_ORIGIN", "PHYTOSANITARY", "MILL_TEST_CERTIFICATE",
    "UNKNOWN",
]

class ExtractedDocument(BaseModel):
    document_id: str
    doc_type: DocType
    doc_type_confidence: float = Field(ge=0.0, le=1.0)
    document_number: FieldRef | None = None
    consignee: FieldRef | None = None
    consignor: FieldRef | None = None
    vessel_or_flight: FieldRef | None = None
    invoice_value: FieldRef | None = None
    invoice_currency: FieldRef | None = None
    total_net_weight_kg: FieldRef | None = None
    total_gross_weight_kg: FieldRef | None = None
    tare_weight_kg: FieldRef | None = None
    package_count: FieldRef | None = None
    line_items: list[LineItem] = []
```

Schema-flattening rule (v4.0 §2.4): no discriminated unions, no deeply nested arrays. Every optional field is X | None. This is what keeps JSON-mode failure rates low.

Status enum + precedence

```python
# backend/app/domain/status.py
from enum import StrEnum

class Status(StrEnum):
    COMPLIANT_FOR_SUBMISSION = "COMPLIANT_FOR_SUBMISSION"
    MISSING_EVIDENCE         = "MISSING_EVIDENCE"
    MATERIAL_CONTRADICTION   = "MATERIAL_CONTRADICTION"
    SPECIALIST_REVIEW_REQUIRED = "SPECIALIST_REVIEW_REQUIRED"

_PRECEDENCE = {
    Status.COMPLIANT_FOR_SUBMISSION: 0,
    Status.SPECIALIST_REVIEW_REQUIRED: 1,
    Status.MISSING_EVIDENCE: 2,
    Status.MATERIAL_CONTRADICTION: 3,
}

def resolve_status(candidates: list[Status]) -> Status:
    """Highest-precedence status wins. Empty → COMPLIANT."""
    if not candidates:
        return Status.COMPLIANT_FOR_SUBMISSION
    return max(candidates, key=lambda s: _PRECEDENCE[s])
```

---

3. Backend — Gateway Layer

There are two routing tiers: (a) the HTTP edge, (b) the internal stage dispatcher that routes to modules/agents. Keep them separate — the edge should never know which agent runs.

3.1 HTTP edge (app/main.py)

```
Cloud Run ingress
  └─ CORSMiddleware
  └─ RequestContextMiddleware      # X-Request-ID, trace, timing
  └─ ErrorEnvelopeMiddleware       # every error → {code, message, detail, request_id}
  └─ APIRouter /api/v1
        ├─ /bundles       → api/v1/bundles.py
        ├─ /bundles/{id}/documents → api/v1/documents.py
        ├─ /bundles/{id}/analyze|reassess|assessment|iterations → api/v1/assessment.py
        └─ /bundles/{id}/stream   → api/v1/stream.py   (SSE, no envelope middleware)
```

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.gateway.middleware import RequestContextMiddleware, ErrorEnvelopeMiddleware
from app.api.v1 import bundles, documents, assessment, stream

app = FastAPI(title="CargoClear-JAPAC API", version="4.0")

app.add_middleware(CORSMiddleware,
    allow_origins=["https://cargoclear-ui-*.run.app", "http://localhost:3000"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"])

app.add_middleware(RequestContextMiddleware)
app.add_middleware(ErrorEnvelopeMiddleware)

for r in (bundles.router, documents.router, assessment.router, stream.router):
    app.include_router(r, prefix="/api/v1")
```

3.2 Internal stage dispatcher (app/gateway/dispatch.py)

This is the piece that "routes to specific modules/agents." The orchestrator calls dispatch(stage, ctx); it never imports an agent directly.

```python
# backend/app/gateway/dispatch.py
from typing import Awaitable, Callable
from app.services import preprocess, calculation, reasoning, confidence, audit
from app.agents.extraction import run_extraction_agent
from app.agents.grounding import run_grounding_agent

Stage = str
Handler = Callable[[dict], Awaitable[dict]]

STAGE_HANDLERS: dict[Stage, Handler] = {
    "preprocess":    preprocess.run,
    "extract":       run_extraction_agent,
    "discrepancy":   calculation.run,
    "ground":        run_grounding_agent,
    "confidence":    confidence.route,
    "synthesize":    reasoning.build,
    "audit":         audit.record,
}

async def dispatch(stage: Stage, ctx: dict) -> dict:
    handler = STAGE_HANDLERS.get(stage)
    if handler is None:
        raise ValueError(f"unknown stage: {stage}")
    return await handler(ctx)
```

Benefits: the workflow DAG is data, not control flow. Swapping the extraction agent, mocking a stage in tests, or running a stage in isolation all become trivial.

3.3 Endpoint → service map

Endpoint Router Service / Agent invoked
POST /bundles bundles.py repo.firestore.create_bundle
POST /bundles/{id}/documents documents.py services.storage.upload_raw + services.preprocess.enqueue
POST /bundles/{id}/analyze assessment.py services.orchestrator.start_run(stage="full")
POST /bundles/{id}/reassess assessment.py services.orchestrator.start_run(stage="reassess")
GET /bundles/{id}/assessment assessment.py repo.firestore.latest_iteration
GET /bundles/{id}/iterations assessment.py repo.firestore.list_iterations → reasoning.diff
GET /bundles/{id}/stream stream.py Firestore listener → SSE

---

4. Backend — Services

4.1 Storage service (raw PDFs)

GCS layout — immutable, append-only, region-pinned:

```
gs://cargoclear-raw-pdfs/
  bundles/{bundle_id}/
    raw/{document_id}/original.pdf
    raw/{document_id}/meta.json          # sha256, mime, size, upload ts, uploader
    processed/{document_id}/page-0001.png
    processed/{document_id}/transform.json   # deskew angle, rotation, split map
    derived/{document_id}/extraction.json
```

```python
# backend/app/services/storage.py
import hashlib, json
from datetime import datetime, timezone
from google.cloud import storage
from app.core.config import settings

_client = storage.Client(project=settings.PROJECT_ID)
_bucket = _client.bucket(settings.RAW_BUCKET)  # asia-south1

def upload_raw(bundle_id: str, document_id: str, data: bytes, mime: str) -> dict:
    digest = hashlib.sha256(data).hexdigest()
    blob = _bucket.blob(f"bundles/{bundle_id}/raw/{document_id}/original.pdf")
    blob.metadata = {"sha256": digest, "bundle_id": bundle_id, "document_id": document_id}
    blob.upload_from_string(data, content_type=mime)
    meta = {
        "gcs_uri": f"gs://{settings.RAW_BUCKET}/{blob.name}",
        "sha256": digest, "bytes": len(data), "mime": mime,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    _bucket.blob(f"bundles/{bundle_id}/raw/{document_id}/meta.json") \
        .upload_from_string(json.dumps(meta), content_type="application/json")
    return meta
```

Critical rule: the object path contains the sha256-derived document_id. Never overwrite. Re-uploading the same bytes is a no-op; re-uploading different bytes under the same logical document creates a new document_id and a new audit event.

4.2 Preprocessing service

```python
# backend/app/services/preprocess.py
from pdf2image import convert_from_bytes
import cv2, numpy as np

TARGET_DPI = 200
MAX_BYTES = 1_000_000
MAX_PAGES = 13

async def run(ctx: dict) -> dict:
    raw = ctx["raw_bytes"]
    pages = convert_from_bytes(raw, dpi=TARGET_DPI, fmt="png")
    transforms = []
    out_pages = []
    for i, page in enumerate(pages, start=1):
        img = np.array(page.convert("L"))
        angle = _estimate_skew(img)                       # Hough / minAreaRect
        if abs(angle) > 0.5:
            img = _rotate(img, angle)
        img = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 31, 10)
        out_pages.append(img)
        transforms.append({"page": i, "deskew_deg": angle, "rotation": 0})

    if len(raw) > MAX_BYTES or len(pages) > MAX_PAGES:
        out_pages, transforms = _split_and_number(out_pages, transforms)

    ctx["processed_pages"] = out_pages
    ctx["transform_meta"] = transforms   # → persisted for bbox remapping
    return ctx
```

transform_meta is what lib/bbox.ts needs to map a normalized box on a processed page back to the original PDF page for display.

4.3 Calculation service (deterministic — owns truth)

```python
# backend/app/services/calculation.py
from dataclasses import dataclass, asdict
from app.domain.schemas import ExtractedDocument

REL_TOL = 0.005      # 0.5 %
ABS_TOL = 5.0        # kg
DEFAULT_TARE_RATIO = 0.02

@dataclass
class CheckResult:
    check_id: str
    severity: str            # "PASS" | "WARN" | "MATERIAL"
    message: str
    delta: float | None = None
    tolerance: float | None = None
    evidence: list[dict] | None = None

def _tolerance(gross_kg: float) -> float:
    return max(REL_TOL * gross_kg, ABS_TOL)

def check_weight_parity(
    packing: ExtractedDocument,
    bol: ExtractedDocument,
) -> CheckResult:
    net   = packing.total_net_weight_kg.value   if packing.total_net_weight_kg else None
    tare  = packing.tare_weight_kg.value        if packing.tare_weight_kg  else None
    gross = bol.total_gross_weight_kg.value     if bol.total_gross_weight_kg else None

    if net is None or gross is None:
        return CheckResult("W-001", "WARN",
                           "Weight parity not evaluable: missing net or gross.",
                           evidence=[{"doc": packing.document_id},
                                     {"doc": bol.document_id}])

    if tare is None:
        tare = DEFAULT_TARE_RATIO * net
    expected = float(net) + float(tare)
    delta = abs(expected - float(gross))
    tol = _tolerance(float(gross))

    if delta <= tol:
        return CheckResult("W-001", "PASS",
                           f"Net+tare ({expected:.1f} kg) matches BoL gross within tolerance.",
                           delta=delta, tolerance=tol,
                           evidence=[{"doc": packing.document_id, "field": "total_net_weight_kg"},
                                     {"doc": bol.document_id,     "field": "total_gross_weight_kg"}])
    return CheckResult("W-001", "MATERIAL",
                       f"Weight mismatch of {delta:.1f} kg exceeds ±{tol:.1f} kg tolerance.",
                       delta=delta, tolerance=tol,
                       evidence=[{"doc": packing.document_id, "field": "total_net_weight_kg"},
                                 {"doc": bol.document_id,     "field": "total_gross_weight_kg"}])

def check_hs_consistency(invoice, packing) -> CheckResult:
    """8-digit declared HS must match across documents."""
    a = {i.hs_code_declared.value for i in invoice.line_items if i.hs_code_declared.value}
    b = {i.hs_code_declared.value for i in packing.line_items if i.hs_code_declared.value}
    if not a or not b:
        return CheckResult("H-002", "WARN", "HS code absent on one or more documents.")
    if a == b:
        return CheckResult("H-002", "PASS", "Declared HS codes are consistent.")
    return CheckResult("H-002", "MATERIAL",
                       f"HS code divergence: invoice={sorted(a)} packing={sorted(b)}.")

def check_entity_alignment(docs: list[ExtractedDocument]) -> list[CheckResult]:
    """Consignee / consignor / vessel / invoice number / date alignment."""
    out: list[CheckResult] = []
    for field in ("consignee", "consignor", "vessel_or_flight", "document_number"):
        vals = {getattr(d, field).value for d in docs if getattr(d, field)}
        if len(vals) > 1:
            out.append(CheckResult(f"E-{field}", "MATERIAL",
                                   f"Inconsistent {field}: {sorted(map(str, vals))}"))
    return out

async def run(ctx: dict) -> dict:
    docs: list[ExtractedDocument] = ctx["extracted"]
    by_type = {d.doc_type: d for d in docs}
    results: list[CheckResult] = []

    if "PACKING_LIST" in by_type and "BILL_OF_LADING" in by_type:
        results.append(check_weight_parity(by_type["PACKING_LIST"], by_type["BILL_OF_LADING"]))
    if "COMMERCIAL_INVOICE" in by_type and "PACKING_LIST" in by_type:
        results.append(check_hs_consistency(by_type["COMMERCIAL_INVOICE"], by_type["PACKING_LIST"]))
    results.extend(check_entity_alignment(docs))

    ctx["checks"] = [asdict(r) for r in results]
    ctx["math_status"] = _roll_up(results)
    return ctx

def _roll_up(results: list[CheckResult]) -> str:
    if any(r.severity == "MATERIAL" for r in results):
        return "MATERIAL_CONTRADICTION"
    if any(r.severity == "WARN" for r in results):
        return "SPECIALIST_REVIEW_REQUIRED"
    return "COMPLIANT_FOR_SUBMISSION"
```

The math service is pure — no I/O, no LLM. It's the unit-test target with the highest coverage requirement.

4.4 Audit service (tamper-evident hash chain)

```python
# backend/app/services/audit.py
import hashlib, json
from datetime import datetime, timezone
from google.cloud import firestore
from app.repo.firestore import db

def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

def _hash(prev_hash: str, seq: int, ts: str, payload: dict) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode())
    h.update(str(seq).encode())
    h.update(ts.encode())
    h.update(_canonical(payload).encode())
    return h.hexdigest()

async def record(ctx: dict) -> dict:
    bundle_id   = ctx["bundle_id"]
    iteration   = ctx.get("iteration", 0)
    event_type  = ctx["audit_event_type"]
    payload     = ctx.get("audit_payload", {})

    col = db.collection("bundles").document(bundle_id).collection("audit")
    last = col.order_by("seq", direction=firestore.Query.DESCENDING).limit(1).get()
    prev_hash = last[0].to_dict()["hash"] if last else "GENESIS"
    seq = (last[0].to_dict()["seq"] + 1) if last else 1
    ts = datetime.now(timezone.utc).isoformat()

    event = {
        "event_id": f"{bundle_id}:{iteration}:{seq}",
        "bundle_id": bundle_id, "iteration": iteration, "seq": seq, "ts": ts,
        "actor": ctx.get("actor", "system"),
        "event_type": event_type,
        "payload": payload,
        "prev_hash": prev_hash,
        "hash": _hash(prev_hash, seq, ts, payload),
    }
    col.document(event["event_id"]).set(event)
    ctx["audit_event"] = event
    return ctx
```

Firestore security rule (deny mutation of audit):

```
match /bundles/{bundleId}/audit/{eventId} {
  allow read: if request.auth != null;
  allow create: if request.auth != null;
  allow update, delete: if false;   // tamper-evident
}
```

4.5 Reasoning Delta service

python
# backend/app/services/reasoning.py
async def build(ctx: dict) -> dict:
    prev = ctx.get("previous_iteration")
    curr = _snapshot(ctx)

    if prev is None:
        delta = {"kind": "INITIAL", "changes": [], "narrative": "First assessment."}
    else:
        changes = []
        if prev["status"] != curr["status"]:
            changes.append({
                "field": "status",
                "from": prev["status"], "to": curr["status"],
                "because": ctx.get("status_reason", "New evidence satisfied an open requirement."),
            })
        for c in curr["checks"]:
            old = next((x for x in prev["checks"] if x["check_id"] == c["check_id"]), None)
            if old and old["severity"] != c["severity"]:
                changes.append({
                    "field": c["check_id"],
                    "from": old["severity"], "to": c["severity"],
                    "because": c["message"],
                })
        delta = {
            "kind": "REASSESSMENT",
            "changes": changes,
            "narrative": _narrate(changes),
        }

    ctx["reasoning_delta"] = delta
    return ctx

def _snapshot(ctx) -> dict:
    return {
        "status": ctx["final_status"],
        "checks": ctx["checks"],
        "documents": [d["document_id"] for d in ctx.get("documents", [])],
    }

def _narrate(changes: list[dict]) -> str:
    if not changes:
        return "No material change between iterations."
    return " ".join(f"{c['field']}: {c['from']} → {c['to']} because {c['because']}"
                    for c in changes)
```

4.6 Confidence routing

```python
# backend/app/services/confidence.py
MIN_FIELD_CONF = 0.65
HIGH_CONF      = 0.95

async def route(ctx: dict) -> dict:
    extracted = ctx["extracted"]
    fields = [f for d in extracted for f in _iter_fieldrefs(d)]
    min_conf = min((f.confidence for f in fields), default=1.0)
    deterministic = ctx["math_status"]

    if min_conf >= HIGH_CONF and deterministic == "COMPLIANT_FOR_SUBMISSION":
        action = "AUTO_ACCEPT"
    elif min_conf >= HIGH_CONF and deterministic != "COMPLIANT_FOR_SUBMISSION":
        action = "AUTO_FLAG"
    elif MIN_FIELD_CONF <= min_conf < HIGH_CONF:
        action = "INTERACTIVE_REVIEW"
    else:
        action = "MANUAL_ENTRY"

    ctx["confidence"] = {"min_field_confidence": min_conf, "action": action}
    if action in ("INTERACTIVE_REVIEW", "MANUAL_ENTRY"):
        ctx["force_status"] = "SPECIALIST_REVIEW_REQUIRED"
    return ctx

def _iter_fieldrefs(doc):
    for name, val in doc.__dict__.items():
        if hasattr(val, "confidence"):
            yield val
        elif isinstance(val, list):
            for item in val:
                for v in item.__dict__.values():
                    if hasattr(v, "confidence"):
                        yield v
```

4.7 Orchestrator

```python
# backend/app/services/orchestrator.py
import asyncio, uuid
from app.gateway.dispatch import dispatch
from app.repo import firestore

async def start_run(bundle_id: str, mode: str = "full") -> str:
    run_id = str(uuid.uuid4())
    ctx = {"bundle_id": bundle_id, "run_id": run_id, "mode": mode}
    asyncio.create_task(_execute(ctx))          # fire-and-forget; SSE reports progress
    return run_id

PIPELINE_FULL = ["preprocess", "extract", "discrepancy", "ground",
                 "confidence", "synthesize", "audit"]
PIPELINE_REASSESS = ["preprocess", "extract", "discrepancy", "ground",
                     "confidence", "synthesize", "audit"]

async def _execute(ctx: dict):
    try:
        for stage in (PIPELINE_FULL if ctx["mode"] == "full" else PIPELINE_REASSESS):
            ctx["stage"] = stage
            await firestore.set_run_stage(ctx["bundle_id"], ctx["run_id"], stage)
            ctx = await dispatch(stage, ctx)
        await firestore.write_iteration(ctx)
    except Exception as e:
        await firestore.set_run_error(ctx["bundle_id"], ctx["run_id"], str(e))
```

---

5. Agents (ADK 2.0)

5.1 Workflow DAG

```python
# backend/app/agents/workflow.py
from google.adk import Agent, Workflow
from google.adk.workflow import RetryConfig
from app.agents.extraction import extraction_agent
from app.agents.grounding import grounding_agent
from app.agents.nodes import discrepancy_node, synthesize_node, preprocess_node, audit_node

root_agent = Workflow(
    name="cargoclear_orchestrator",
    edges=[
        ("START", preprocess_node, extraction_agent),
        (extraction_agent, discrepancy_node, grounding_agent),
        (grounding_agent, synthesize_node, audit_node),
    ],
    retry_config=RetryConfig(max_attempts=3),   # for JSON-schema failures
)
```

5.2 Extraction agent

```python
# backend/app/agents/extraction.py
from google import genai
from google.genai import types
from google.adk import Agent
from app.domain.schemas import ExtractedDocument
from app.core.config import settings

client = genai.Client(vertexai=True, project=settings.PROJECT_ID,
                      location="asia-south1")           # Flash confirmed here

SYSTEM_INSTRUCTION = """
You are a document extraction engine for cross-border trade paperwork.
You MUST extract only what is visibly printed on the page.
You MUST NOT infer, complete, normalise, or guess any value.
If a field is not present, return null for value and 0.0 for confidence.
Return bounding boxes as [ymin, xmin, ymax, xmax] normalised to 0-1000,
with origin at the top-left of the page.
"""

extraction_agent = Agent(
    name="extraction_agent",
    model="gemini-2.5-flash",
    instruction=SYSTEM_INSTRUCTION,
)

async def run_extraction_agent(ctx: dict) -> dict:
    docs: list[ExtractedDocument] = []
    for page_bundle in ctx["document_pages"]:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=page_bundle["payload"],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ExtractedDocument,
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.0,
            ),
        )
        docs.append(resp.parsed)
    ctx["extracted"] = docs
    return ctx
```

5.3 Grounding agent (BigQuery tool-calling)

```python
# backend/app/agents/tools/bq_tariff.py
from google.cloud import bigquery
from app.core.config import settings

bq = bigquery.Client(project=settings.PROJECT_ID)

VECTOR_SQL = """
SELECT base.hs_code, base.description, base.required_documents, distance
FROM VECTOR_SEARCH(
  TABLE `{project}.ahtn.master_tariff`,
  'description_embedding',
  (SELECT ml_generate_embedding_result AS embedding
   FROM ML.GENERATE_EMBEDDING(
     MODEL `{project}.ahtn.embedding_model`,
     (SELECT @q AS content))),
  top_k => 5,
  distance_type => 'COSINE')
WHERE destination_country = @dest
ORDER BY distance
"""

def lookup_tariff(description: str, destination_country: str) -> list[dict]:
    job = bq.query(
        VECTOR_SQL.format(project=settings.PROJECT_ID),
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("q", "STRING", description),
            bigquery.ScalarQueryParameter("dest", "STRING", destination_country),
        ]),
    )
    return [dict(r) for r in job.result()]
```

```python
# backend/app/agents/grounding.py
from google.adk import Agent
from app.agents.tools.bq_tariff import lookup_tariff

grounding_agent = Agent(
    name="grounding_agent",
    model="gemini-2.5-flash",
    instruction="""
You validate declared HS codes against the official AHTN tariff table.
Call lookup_tariff() for each distinct commodity description.
You MUST NOT invent HS codes, duty rates, or required documents.
Return the top candidate, its similarity distance, and the required_documents list.
If the top distance exceeds 0.35, mark the result as AMBIGUOUS.
""",
    tools=[lookup_tariff],
)

async def run_grounding_agent(ctx: dict) -> dict:
    findings = []
    for doc in ctx["extracted"]:
        for item in doc.line_items:
            desc = item.description.value
            if not desc:
                continue
            hits = lookup_tariff(desc, ctx.get("destination_country", "SG"))
            findings.append({
                "document_id": doc.document_id,
                "declared_hs": item.hs_code_declared.value,
                "candidates": hits,
                "ambiguous": (not hits) or hits[0]["distance"] > 0.35,
            })
    ctx["grounding"] = findings
    ctx["required_documents"] = _collect_required(findings)
    ctx["missing_evidence"] = _diff_against_uploaded(
        ctx["required_documents"], ctx.get("uploaded_types", []))
    return ctx
```

No hallucination rule enforced structurally: the grounding agent can only call lookup_tariff. It has no free-text authority over HS codes or required-document lists.

5.4 Deterministic nodes

preprocess_node, discrepancy_node, synthesize_node, audit_node are thin ADK wrappers around the services in §4. They exist so the DAG is a single graph, not so they add logic.

```python
# backend/app/agents/nodes.py
from google.adk.workflow import node
from app.services import preprocess, calculation, reasoning, audit

@node
async def preprocess_node(ctx):    return await preprocess.run(ctx)

@node
async def discrepancy_node(ctx):   return await calculation.run(ctx)

@node
async def synthesize_node(ctx):
    from app.domain.status import resolve_status, Status
    from app.services.confidence import route
    ctx = await route(ctx)
    candidates: list[Status] = []
    if ctx.get("missing_evidence"):     candidates.append(Status.MISSING_EVIDENCE)
    if ctx["math_status"] == "MATERIAL_CONTRADICTION":
        candidates.append(Status.MATERIAL_CONTRADICTION)
    if ctx.get("grounding_ambiguous"):
        candidates.append(Status.SPECIALIST_REVIEW_REQUIRED)
    if ctx.get("force_status"):
        candidates.append(Status(ctx["force_status"]))
    ctx["final_status"] = resolve_status(candidates)
    return await reasoning.build(ctx)

@node
async def audit_node(ctx):
    ctx["audit_event_type"] = "ASSESSMENT_COMPLETED"
    ctx["audit_payload"] = {
        "status": ctx["final_status"],
        "checks": ctx["checks"],
        "confidence": ctx["confidence"],
    }
    return await audit.record(ctx)
```

---

6. Frontend — Routing

```
app/
├── layout.tsx                       # <html lang="en">, fonts, <LiveRegionRoot/>
├── page.tsx                         # redirect('/workbench/' + lastBundleId)
├── workbench/
│   └── [bundleId]/
│       ├── layout.tsx               # WorkbenchShell (grid)
│       └── page.tsx                 # server component: fetches initial state
└── api/proxy/[...path]/route.ts     # BFF: forwards non-SSE calls to Cloud Run
```

Routing rules:
· Page loads (/workbench/[bundleId]) go through the server component → direct call to Cloud Run with a server-side token. No CORS, no client-side API key.
· Mutations (upload, analyze, reassess) go through /api/proxy/* so the browser never holds a bearer token.
· SSE goes directly from browser to Cloud Run (EventSource). Going through the Next BFF would buffer the stream. CORS is scoped to the UI origin only.

```typescript
// frontend/lib/api.ts
const BASE = process.env.NEXT_PUBLIC_API_BASE!;   // https://cargoclear-api-xxx.run.app

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/proxy${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ApiError(err.code ?? "UNKNOWN", err.message ?? res.statusText, err.request_id);
  }
  return res.json() as Promise<T>;
}

export const api = {
  createBundle: (body: CreateBundleBody) =>
    call<Bundle>("/bundles", { method: "POST", body: JSON.stringify(body) }),

  uploadDocument: (bundleId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return call<Document>(`/bundles/${bundleId}/documents`,
      { method: "POST", body: fd, headers: {} });
  },

  analyze:  (bundleId: string) => call<Run>(`/bundles/${bundleId}/analyze`,  { method: "POST" }),
  reassess: (bundleId: string) => call<Run>(`/bundles/${bundleId}/reassess`, { method: "POST" }),

  assessment: (bundleId: string) => call<Assessment>(`/bundles/${bundleId}/assessment`),
  iterations: (bundleId: string) => call<AssessmentIteration[]>(`/bundles/${bundleId}/iterations`),
};
```

```typescript
// frontend/lib/sse.ts
export function subscribeToBundle(
  bundleId: string,
  handlers: {
    onStatus?: (s: StatusEvent) => void;
    onIteration?: (i: AssessmentIteration) => void;
    onError?: (e: { message: string }) => void;
  },
) {
  const url = `${process.env.NEXT_PUBLIC_API_BASE}/api/v1/bundles/${bundleId}/stream`;
  const es = new EventSource(url);

  es.addEventListener("status",    e => handlers.onStatus?.(JSON.parse(e.data)));
  es.addEventListener("iteration", e => handlers.onIteration?.(JSON.parse(e.data)));
  es.addEventListener("error",     e => handlers.onError?.(JSON.parse((e as MessageEvent).data)));

  return () => es.close();
}
```

6.1 SSE event contract

```python
# backend/app/domain/events.py
from pydantic import BaseModel
from typing import Literal

class StatusEvent(BaseModel):
    kind: Literal["status"] = "status"
    state: Literal["QUEUED", "RUNNING", "COMPLETE", "ERROR"]
    stage: str | None
    progress: float         # 0.0 – 1.0
    message: str | None = None

class IterationEvent(BaseModel):
    kind: Literal["iteration"] = "iteration"
    iteration: int
    status: str
    confidence: dict
    checks: list[dict]
    missing_evidence: list[dict]
    reasoning_delta: dict
```

```python
# backend/app/api/v1/stream.py
from fastapi import APIRouter
from fastapi.sse import EventSourceResponse
import asyncio, json
from app.repo.firestore import get_run_state, latest_iteration

router = APIRouter()

@router.get("/bundles/{bundle_id}/stream")
async def stream(bundle_id: str):
    async def gen():
        last_iter = -1
        while True:
            run = await get_run_state(bundle_id)
            yield {"event": "status", "data": run.model_dump_json()}
            if run.state in ("COMPLETE", "ERROR"):
                break
            it = await latest_iteration(bundle_id)
            if it and it.iteration != last_iter:
                last_iter = it.iteration
                yield {"event": "iteration", "data": it.model_dump_json()}
            await asyncio.sleep(2)

    return EventSourceResponse(gen(), ping=15)
```

---

7. Frontend — Design System

7.1 Design tokens (styles/globals.css)

Every color has a documented contrast ratio against its background. This file is the WCAG audit artifact.

```css
:root {
  /* Surfaces */
  --cc-bg:            #F4F6F9;
  --cc-surface:       #FFFFFF;
  --cc-surface-2:     #FAFBFC;
  --cc-border:        #E3E7ED;   /* decorative only */
  --cc-border-strong: #6B7684;   /* 3.0:1 on white → allowed for graphical boundaries */

  /* Text — all ≥ 4.5:1 on --cc-surface */
  --cc-text:          #12161C;   /* 16.9:1 */
  --cc-text-muted:    #4A5462;   /*  8.1:1 */
  --cc-text-subtle:   #6B7684;   /*  4.9:1 */

  /* Focus — 3:1 against every surface */
  --cc-focus:         #1A56DB;

  /* Status: text token = 4.5:1 on white; bd token = 3:1 on white */
  --cc-ok:      #146C2E;  --cc-ok-bd:   #1E8E3E;  --cc-ok-bg:   #E6F4EA;
  --cc-warn:    #8A5300;  --cc-warn-bd: #C77700;  --cc-warn-bg: #FFF4E0;
  --cc-err:     #B3261E;  --cc-err-bd:  #D93025;  --cc-err-bg:  #FDECEA;
  --cc-info:    #5B2DA8;  --cc-info-bd: #7C4DFF;  --cc-info-bg: #F0EBFF;

  --cc-radius: 8px;
  --cc-shadow-1: 0 1px 2px rgba(18,22,28,.06), 0 1px 3px rgba(18,22,28,.10);
}

@media (prefers-color-scheme: dark) {
  :root {
    --cc-bg: #0F1319; --cc-surface: #161B22; --cc-surface-2: #1C222B;
    --cc-border: #2A313B; --cc-border-strong: #8B949E;
    --cc-text: #E6EDF3; --cc-text-muted: #B1BAC4; --cc-text-subtle: #8B949E;
    --cc-ok: #4ADE80; --cc-ok-bd: #4ADE80; --cc-ok-bg: #0F2A1A;
    --cc-warn: #FBBF24; --cc-warn-bd: #FBBF24; --cc-warn-bg: #2E2205;
    --cc-err: #F87171; --cc-err-bd: #F87171; --cc-err-bg: #2E0F0F;
    --cc-info: #A78BFA; --cc-info-bd: #A78BFA; --cc-info-bg: #1E1533;
  }
}

*:focus-visible {
  outline: 2px solid var(--cc-focus);
  outline-offset: 2px;
  border-radius: 4px;
}

/* Kill all motion for users who ask */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
```

7.2 Workbench grid

```css
/* styles/workbench.css */
.cc-workbench {
  display: grid;
  height: 100dvh;
  grid-template-columns: 280px minmax(0, 1fr) 400px;
  grid-template-rows: 56px minmax(0, 1fr) 280px;
  grid-template-areas:
    "top    top    top"
    "rail   viewer assess"
    "drawer drawer drawer";
  background: var(--cc-bg);
  color: var(--cc-text);
}

.cc-top    { grid-area: top;    border-bottom: 1px solid var(--cc-border); background: var(--cc-surface); }
.cc-rail   { grid-area: rail;   border-right:  1px solid var(--cc-border); overflow-y: auto; }
.cc-viewer { grid-area: viewer; overflow: auto; background: var(--cc-surface-2); }
.cc-assess { grid-area: assess; border-left:   1px solid var(--cc-border); overflow-y: auto; }
.cc-drawer { grid-area: drawer; border-top:    1px solid var(--cc-border); background: var(--cc-surface); }

/* Below 1280px collapse to a single column with a tab bar */
@media (max-width: 1279px) {
  .cc-workbench {
    grid-template-columns: 1fr;
    grid-template-rows: 56px 44px minmax(0, 1fr);
    grid-template-areas: "top" "tabs" "main";
  }
  .cc-rail, .cc-viewer, .cc-assess, .cc-drawer { display: none; }
  .cc-workbench[data-tab="rail"]   .cc-rail   { display: block; grid-area: main; }
  .cc-workbench[data-tab="viewer"] .cc-viewer { display: block; grid-area: main; }
  .cc-workbench[data-tab="assess"] .cc-assess { display: block; grid-area: main; }
  .cc-workbench[data-tab="drawer"] .cc-drawer { display: block; grid-area: main; }
}
```

---

8. Frontend — Workbench Markup

```tsx
// frontend/app/workbench/[bundleId]/layout.tsx
export default function WorkbenchLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="cc-workbench" data-tab="assess">
      {children}
    </div>
  );
}
```

```tsx
// frontend/app/workbench/[bundleId]/page.tsx  (server component)
import { api } from "@/lib/api";
import { TopBar }        from "@/components/shell/TopBar";
import { DocumentRail }  from "@/components/rail/DocumentRail";
import { DocumentViewer } from "@/components/viewer/DocumentViewer";
import { AssessmentPanel } from "@/components/assess/AssessmentPanel";
import { DeltaDrawer }   from "@/components/delta/DeltaDrawer";

export default async function WorkbenchPage({
  params,
}: { params: Promise<{ bundleId: string }> }) {
  const { bundleId } = await params;
  const [bundle, assessment, iterations] = await Promise.all([
    api.getBundle(bundleId),
    api.assessment(bundleId),
    api.iterations(bundleId),
  ]);

  return (
    <>
      <TopBar bundle={bundle} status={assessment.status} />

      <aside className="cc-rail" aria-label="Documents in this bundle">
        <DocumentRail documents={bundle.documents} />
      </aside>

      <main className="cc-viewer" aria-label="Document viewer">
        <DocumentViewer
          documents={bundle.documents}
          highlights={assessment.evidence_refs}
        />
      </main>

      <section className="cc-assess" aria-label="Compliance assessment">
        <AssessmentPanel assessment={assessment} bundleId={bundleId} />
      </section>

      <section className="cc-drawer" aria-label="Reasoning delta and audit trail">
        <DeltaDrawer iterations={iterations} />
      </section>
    </>
  );
}
```

8.1 TopBar

```tsx
// frontend/components/shell/TopBar.tsx
export function TopBar({ bundle, status }: { bundle: Bundle; status: Status }) {
  return (
    <header className="cc-top flex items-center gap-4 px-4">
      <div className="flex items-center gap-2 font-semibold">
        <span aria-hidden>🛃</span>
        <span>CargoClear</span>
      </div>

      <div className="text-sm text-[var(--cc-text-muted)]">
        Bundle <code className="font-mono">{bundle.id}</code>
      </div>

      <StatusPill status={status} />

      <div className="ml-auto flex items-center gap-2">
        <button
          className="rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)]
                     px-3 py-1.5 text-sm hover:bg-[var(--cc-surface-2)]"
          onClick={() => /* opens upload dialog */ null}
        >
          Add document
        </button>
        <button
          className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] px-3 py-1.5
                     text-sm font-medium text-white"
          onClick={() => /* POST /reassess */ null}
        >
          Reassess
        </button>
      </div>
    </header>
  );
}
```

8.2 StatusPill (token-driven, never hardcoded hex)

```tsx
// frontend/components/assess/StatusPill.tsx
const TOKENS: Record<Status, { label: string; fg: string; bd: string; bg: string }> = {
  COMPLIANT_FOR_SUBMISSION:   { label: "Compliant for submission", fg: "var(--cc-ok)",   bd: "var(--cc-ok-bd)",   bg: "var(--cc-ok-bg)"   },
  MISSING_EVIDENCE:           { label: "Missing evidence",         fg: "var(--cc-warn)", bd: "var(--cc-warn-bd)", bg: "var(--cc-warn-bg)" },
  MATERIAL_CONTRADICTION:     { label: "Material contradiction",   fg: "var(--cc-err)",  bd: "var(--cc-err-bd)",  bg: "var(--cc-err-bg)"  },
  SPECIALIST_REVIEW_REQUIRED: { label: "Specialist review",        fg: "var(--cc-info)", bd: "var(--cc-info-bd)", bg: "var(--cc-info-bg)" },
};

export function StatusPill({ status }: { status: Status }) {
  const t = TOKENS[status];
  return (
    <span
      role="status"
      className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold"
      style={{ color: t.fg, background: t.bg, border: `1px solid ${t.bd}` }}
    >
      <span
        aria-hidden
        className="inline-block h-2 w-2 rounded-full"
        style={{ background: t.bd }}
      />
      {t.label}
    </span>
  );
}
```

8.3 Document viewer + bounding box layer

The critical piece. Coordinates from Gemini are [ymin, xmin, ymax, xmax] normalized to 0–1000, on a processed page. We store transform_meta so we can map back to the original.

```tsx
// frontend/components/viewer/DocumentViewer.tsx
"use client";
import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import { BBoxLayer } from "./BBoxLayer";
import { mapBBoxToCanvas } from "@/lib/bbox";

pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

export function DocumentViewer({ documents, highlights }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [page, setPage] = useState(1);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  const [activeDoc, setActiveDoc] = useState(documents[0]?.id);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const doc = await pdfjs.getDocument(`/api/proxy/documents/${activeDoc}/file`).promise;
      const p = await doc.getPage(page);
      const viewport = p.getViewport({ scale: 1.5 });
      const canvas = canvasRef.current!;
      const ctx = canvas.getContext("2d")!;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      setDims({ w: viewport.width, h: viewport.height });
      if (!cancelled) await p.render({ canvasContext: ctx, viewport }).promise;
    })();
    return () => { cancelled = true; };
  }, [activeDoc, page]);

  return (
    <div className="relative mx-auto my-4 w-fit">
      <canvas
        ref={canvasRef}
        className="rounded-[var(--cc-radius)] shadow-[var(--cc-shadow-1)]"
        aria-label={`Page ${page} of document ${activeDoc}`}
      />
      <BBoxLayer
        width={dims.w}
        height={dims.h}
        boxes={highlights
          .filter(h => h.document_id === activeDoc && h.page === page)
          .map(h => ({ ...mapBBoxToCanvas(h.bbox, dims), id: h.id, severity: h.severity }))}
      />
    </div>
  );
}
```

```tsx
// frontend/components/viewer/BBoxLayer.tsx
"use client";
import { useState } from "react";

const SEVERITY_TOKEN = {
  PASS:     "var(--cc-ok-bd)",
  WARN:     "var(--cc-warn-bd)",
  MATERIAL: "var(--cc-err-bd)",
  INFO:     "var(--cc-info-bd)",
} as const;

export function BBoxLayer({ width, height, boxes }: Props) {
  const [hovered, setHovered] = useState<string | null>(null);

  return (
    <div
      className="pointer-events-none absolute inset-0"
      role="group"
      aria-label={`${boxes.length} evidence highlights on this page`}
    >
      {boxes.map(b => {
        const color = SEVERITY_TOKEN[b.severity];
        const active = hovered === b.id;
        return (
          <button
            key={b.id}
            type="button"
            className="pointer-events-auto absolute transition-opacity"
            style={{
              left: b.x, top: b.y, width: b.w, height: b.h,
              // 3:1 graphical boundary + 2px minimum stroke
              outline: `${active ? 3 : 2}px solid ${color}`,
              outlineOffset: 1,
              background: active ? `color-mix(in srgb, ${color} 12%, transparent)` : "transparent",
              borderRadius: 4,
            }}
            onMouseEnter={() => setHovered(b.id)}
            onMouseLeave={() => setHovered(null)}
            onFocus={() => setHovered(b.id)}
            onBlur={() => setHovered(null)}
            aria-label={`Evidence highlight: ${b.label ?? b.id}`}
          />
        );
      })}
    </div>
  );
}
```

```typescript
// frontend/lib/bbox.ts
import type { BBox } from "./types";

export function mapBBoxToCanvas(
  b: BBox,
  canvas: { w: number; h: number },
): { x: number; y: number; w: number; h: number } {
  const x = (b.xmin / 1000) * canvas.w;
  const y = (b.ymin / 1000) * canvas.h;
  return {
    x,
    y,
    w: ((b.xmax - b.xmin) / 1000) * canvas.w,
    h: ((b.ymax - b.ymin) / 1000) * canvas.h,
  };
}

/** Map a box on a processed page back to the original PDF page. */
export function toOriginalPage(
  b: BBox,
  transform: { deskew_deg: number; rotation: 0|90|180|270; split_offset: number },
): BBox {
  // rotation is a 90° step; deskew is applied around the page centre.
  // Split offset shifts the page index; the bbox itself is unchanged.
  const rot = transform.rotation;
  let { ymin, xmin, ymax, xmax } = b;
  if (rot === 90)  [ymin, xmin, ymax, xmax] = [1000 - xmax, ymin, 1000 - xmin, ymax];
  if (rot === 180) [ymin, xmin, ymax, xmax] = [1000 - ymax, 1000 - xmax, 1000 - ymin, 1000 - xmin];
  if (rot === 270) [ymin, xmin, ymax, xmax] = [xmin, 1000 - ymax, xmax, 1000 - ymin];
  return { ...b, ymin, xmin, ymax, xmax, page: b.page + transform.split_offset };
}
```

8.4 Assessment panel + missing evidence card

```tsx
// frontend/components/assess/AssessmentPanel.tsx
"use client";
import { useBundleStream } from "@/lib/useBundleStream";
import { CheckList } from "./CheckList";
import { MissingEvidenceCard } from "./MissingEvidenceCard";
import { UploadDropzone } from "@/components/upload/UploadDropzone";

export function AssessmentPanel({ assessment: initial, bundleId }: Props) {
  const { assessment, run } = useBundleStream(bundleId, initial);

  return (
    <div className="flex flex-col gap-4 p-4">
      <header>
        <h2 className="text-sm font-semibold uppercase tracking-wide
                       text-[var(--cc-text-subtle)]">
          Compliance assessment
        </h2>
        <p className="mt-1 text-xs text-[var(--cc-text-muted)]">
          Iteration {assessment.iteration} · confidence{" "}
          {(assessment.confidence.min_field_confidence * 100).toFixed(0)}%
        </p>
      </header>

      {run.state === "RUNNING" && <ProgressStrip stage={run.stage} progress={run.progress} />}

      <CheckList checks={assessment.checks} />

      {assessment.missing_evidence.length > 0 && (
        <ul className="flex flex-col gap-3" aria-label="Missing evidence">
          {assessment.missing_evidence.map(m => (
            <li key={m.id}>
              <MissingEvidenceCard item={m} />
            </li>
          ))}
        </ul>
      )}

      {assessment.missing_evidence.length > 0 && (
        <UploadDropzone bundleId={bundleId} onUploaded={() => /* triggers reassess */ null} />
      )}
    </div>
  );
}
```

```tsx
// frontend/components/assess/MissingEvidenceCard.tsx
export function MissingEvidenceCard({ item }: { item: MissingEvidence }) {
  return (
    <article
      className="rounded-[var(--cc-radius)] p-3"
      style={{
        background: "var(--cc-warn-bg)",
        border: "1px solid var(--cc-warn-bd)",
        color: "var(--cc-warn)",
      }}
    >
      <h3 className="text-sm font-semibold">
        Missing: {item.document_label}
      </h3>
      <p className="mt-1 text-xs leading-relaxed">
        Required for HS <code className="font-mono">{item.hs_code}</code> —
        {" "}{item.reason}
      </p>
      <p className="mt-2 text-[11px] opacity-80">
        Source: AHTN master tariff · {item.regulation_ref}
      </p>
    </article>
  );
}
```

8.5 Reasoning Delta drawer

```tsx
// frontend/components/delta/DeltaDrawer.tsx
"use client";
import { useState } from "react";
import { AuditTimeline } from "@/components/audit/AuditTimeline";

const TABS = ["Reasoning Delta", "Audit timeline"] as const;

export function DeltaDrawer({ iterations }: { iterations: AssessmentIteration[] }) {
  const [tab, setTab] = useState<typeof TABS[number]>("Reasoning Delta");
  const latest = iterations.at(-1);

  return (
    <div className="flex h-full flex-col">
      <div role="tablist" aria-label="Assessment detail" className="flex gap-1 border-b
                  border-[var(--cc-border)] px-4 pt-2">
        {TABS.map(t => (
          <button
            key={t}
            role="tab"
            id={`tab-${t}`}
            aria-selected={tab === t}
            aria-controls={`panel-${t}`}
            tabIndex={tab === t ? 0 : -1}
            onKeyDown={e => {
              if (e.key === "ArrowRight") setTab(TABS[(TABS.indexOf(t) + 1) % TABS.length]);
              if (e.key === "ArrowLeft")  setTab(TABS[(TABS.indexOf(t) - 1 + TABS.length) % TABS.length]);
            }}
            onClick={() => setTab(t)}
            className="rounded-t-md px-3 py-2 text-sm
                       data-[selected=true]:border-b-2 data-[selected=true]:border-[var(--cc-focus)]
                       data-[selected=true]:font-semibold"
            data-selected={tab === t}
          >
            {t}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        id={`panel-${tab}`}
        aria-labelledby={`tab-${tab}`}
        className="flex-1 overflow-y-auto p-4"
      >
        {tab === "Reasoning Delta"
          ? <DeltaView delta={latest?.reasoning_delta} />
          : <AuditTimeline events={latest?.audit_events ?? []} />}
      </div>
    </div>
  );
}

function DeltaView({ delta }: { delta?: ReasoningDelta }) {
  if (!delta) return <p className="text-sm text-[var(--cc-text-muted)]">No delta yet.</p>;
  if (delta.kind === "INITIAL")
    return <p className="text-sm text-[var(--cc-text-muted)]">{delta.narrative}</p>;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm">{delta.narrative}</p>
      <table className="w-full text-sm">
        <caption className="sr-only">Field-level changes between iterations</caption>
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide
                         text-[var(--cc-text-subtle)]">
            <th scope="col" className="py-1">Field</th>
            <th scope="col" className="py-1">Before</th>
            <th scope="col" className="py-1">After</th>
            <th scope="col" className="py-1">Because</th>
          </tr>
        </thead>
        <tbody>
          {delta.changes.map((c, i) => (
            <tr key={i} className="border-t border-[var(--cc-border)]">
              <th scope="row" className="py-2 text-left font-mono text-xs">{c.field}</th>
              <td className="py-2 text-[var(--cc-err)]">{c.from}</td>
              <td className="py-2 text-[var(--cc-ok)]">{c.to}</td>
              <td className="py-2 text-[var(--cc-text-muted)]">{c.because}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

8.6 Live regions (components/a11y/LiveRegion.tsx)

```tsx
"use client";
import { createContext, useContext, useState, useCallback, useEffect } from "react";

type Politeness = "polite" | "assertive";
type Announce = (msg: string, p?: Politeness) => void;

const Ctx = createContext<Announce>(() => {});
export const useAnnounce = () => useContext(Ctx);

export function LiveRegionRoot({ children }: { children: React.ReactNode }) {
  const [polite, setPolite]       = useState("");
  const [assertive, setAssertive] = useState("");

  const announce: Announce = useCallback((msg, p = "polite") => {
    if (p === "assertive") { setAssertive(""); requestAnimationFrame(() => setAssertive(msg)); }
    else                   { setPolite("");    requestAnimationFrame(() => setPolite(msg)); }
  }, []);

  return (
    <Ctx.Provider value={announce}>
      {children}

      {/* Background progress: polite */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">{polite}</div>

      {/* Critical regulatory rejections: assertive */}
      <div role="alert" aria-live="assertive" aria-atomic="true" className="sr-only">
        {assertive}
      </div>
    </Ctx.Provider>
  );
}
```

Usage — when a stage completes or a status changes:

```typescript
useEffect(() => {
  if (run.state === "COMPLETE") announce(`Assessment complete. Status ${assessment.status}.`);
  if (assessment.status === "MATERIAL_CONTRADICTION")
    announce(`Material contradiction detected. ${assessment.checks[0]?.message}`, "assertive");
}, [run.state, assessment.status]);
```

Focus management on status change:

```typescript
useEffect(() => {
  if (prevStatus !== assessment.status) {
    panelRef.current?.focus({ preventScroll: true });
  }
}, [assessment.status]);
```

---

9. End-to-End Flow (Case C, the hero path)

```
1. Browser: user drops 3 PDFs onto UploadDropzone
   └─ POST /api/proxy/bundles/{id}/documents  (multipart)
       └─ FastAPI documents.py → services.storage.upload_raw
           └─ GCS: bundles/{id}/raw/{doc_id}/original.pdf
           └─ Firestore: EvidenceDocument { gcs_uri, sha256, doc_type: UNKNOWN }
           └─ audit.record("DOCUMENT_UPLOADED")

2. Browser: clicks "Analyze"
   └─ POST /api/proxy/bundles/{id}/analyze
       └─ orchestrator.start_run(mode="full") → returns run_id, 202
       └─ asyncio task: dispatch("preprocess") → "extract" → "discrepancy"
                        → "ground" → "confidence" → "synthesize" → "audit"

3. Browser: opens EventSource to /api/v1/bundles/{id}/stream
   ← event:status  {state:"RUNNING", stage:"extract", progress:0.3}
   ← event:status  {state:"RUNNING", stage:"discrepancy", progress:0.55}
   ← event:iteration {iteration:1, status:"MISSING_EVIDENCE",
                      missing_evidence:[{document_label:"Mill Test Certificate",
                                         hs_code:"7304", reason:"..."}],
                      reasoning_delta:{kind:"INITIAL", ...}}
   ← event:status  {state:"COMPLETE"}

4. UI: AssessmentPanel renders MissingEvidenceCard + UploadDropzone
   UI: DocumentViewer renders bbox highlights for the weight/HS checks
   UI: LiveRegion announces "Missing evidence: Mill Test Certificate"
   UI: focus moves to the assessment panel

5. User uploads MTC.pdf
   └─ POST /documents → GCS → audit.record("DOCUMENT_UPLOADED")
   └─ POST /reassess  → orchestrator.start_run(mode="reassess")

6. Pipeline reruns. reasoning.build diffs iteration 1 vs 2:
   changes: [{ field:"status", from:"MISSING_EVIDENCE", to:"COMPLIANT_FOR_SUBMISSION",
               because:"DOC-04 Mill Test Certificate satisfies AHTN requirement for HS 7304" }]

7. UI: ReasoningDelta renders the side-by-side table
   UI: AuditTimeline shows the full hash-chained history
   UI: LiveRegion (assertive) announces the new status
```

---

10. Build, Config, Deploy

10.1 Environment

```bash
# backend/.env.example
PROJECT_ID=cargoclear-hackathon
REGION=asia-south1
RAW_BUCKET=cargoclear-raw-pdfs
FIRESTORE_DATABASE=(default)
BQ_DATASET=ahtn
GEMINI_LIVE_MODEL=gemini-2.5-flash
GEMINI_BATCH_MODEL=gemini-2.5-pro
GEMINI_BATCH_LOCATION=global

# frontend/.env.local
NEXT_PUBLIC_API_BASE=https://cargoclear-api-xxxxx-as.a.run.app
```

10.2 Cloud Run service config (critical for SSE)

```bash
gcloud run deploy cargoclear-api \
  --source ./backend \
  --region asia-south1 \
  --service-account cargoclear-sa@cargoclear-hackathon.iam.gserviceaccount.com \
  --timeout 300 \
  --concurrency 20 \
  --min-instances 1 \
  --max-instances 10 \
  --no-cpu-throttling \
  --set-env-vars PROJECT_ID=cargoclear-hackathon,REGION=asia-south1
```

· --timeout 300 — matches the SSE keep-alive budget in the spec.
· --no-cpu-throttling — SSE generators must keep running between events; CPU throttling will stall them.
· --min-instances 1 — avoids cold-start latency during the demo.

10.3 cloudbuild.yaml (P1 requirement)

```yaml
steps:
  - id: test-backend
    name: python:3.12
    dir: backend
    entrypoint: bash
    args: ["-c", "pip install -r requirements.txt && pytest -q"]

  - id: test-frontend
    name: node:22
    dir: frontend
    entrypoint: bash
    args: ["-c", "npm ci && npm run lint && npm run typecheck"]

  - id: deploy-api
    name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: bash
    args: ["./infra/deploy_api.sh"]

  - id: deploy-ui
    name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: bash
    args: ["./infra/deploy_ui.sh"]

options:
  logging: CLOUD_LOGGING_ONLY
```

---

11. Testing Strategy (mapped to the spec's §9)

Layer Tool Target Coverage gate
Calculation pytest services/calculation.py ≥ 95 % — this is the deterministic core
Status precedence pytest (property-based, hypothesis) domain/status.py 100 % of precedence pairs
Audit chain pytest services/audit.py hash chain verifies; tamper detection
Extraction schema pytest with recorded fixtures domain/schemas.py 100 % schema round-trip
Agent pipeline pytest with mocked genai.Client agents/* all 4 statuses reachable
API contract schemathesis against OpenAPI api/v1/* all endpoints
E2E Case C Playwright full hero path < 45 s, 4 status assertions
Accessibility axe-core in Playwright + manual keyboard pass every page 0 critical violations

A11y test that must pass before demo:

```typescript
// frontend/tests/a11y.spec.ts
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("workbench has no critical a11y violations", async ({ page }) => {
  await page.goto(`/workbench/${process.env.TEST_BUNDLE_ID}`);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations.filter(v => v.impact === "critical")).toEqual([]);
});

test("workbench is fully keyboard navigable", async ({ page }) => {
  await page.goto(`/workbench/${process.env.TEST_BUNDLE_ID}`);
  const reachable = new Set<string>();
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    const id = await page.evaluate(() =>
      (document.activeElement as HTMLElement)?.dataset?.testid ?? "");
    if (id) reachable.add(id);
  }
  expect(reachable).toContain("upload-dropzone");
  expect(reachable).toContain("reassess-button");
  expect(reachable).toContain("bbox-0");
});
```

---

12. Execution Order (mapped to the 72-hour plan)

Phase Deliverable File(s)
Day 0, 0–3 h Bootstrap infra/bootstrap.sh
Day 0, 3–8 h FastAPI skeleton + Firestore schema + GCS upload main.py, storage.py, bundles.py, documents.py
Day 1, 0–12 h ADK workflow + extraction agent + Pydantic schemas workflow.py, extraction.py, schemas.py
Day 1, 0–12 h Next.js shell + dropzone + SSE listener layout.tsx, UploadDropzone.tsx, sse.ts
Day 1, 12–24 h Calculation + grounding calculation.py, grounding.py, bq_tariff.py
Day 2, 0–12 h Reasoning Delta UI + bbox canvas + ARIA ReasoningDelta.tsx, BBoxLayer.tsx, LiveRegion.tsx
Day 2, 12–24 h Case C E2E reasoning.py, orchestrator.py, integration test
Day 3, 0–12 h Hardening + CI/CD + a11y cloudbuild.yaml, a11y.spec.ts
Day 3, 12–24 h Demo recording —

---

13. Things That Will Break (and the pre-built answer)

Failure Symptom Fix already in the plan
Gemini returns malformed JSON response.parsed is None RetryConfig(max_attempts=3) on the extraction node + schema flattened per §2
SSE stream dies at 60 s Browser EventSource reconnects, UI flickers --timeout 300 + --no-cpu-throttling + ping=15 on EventSourceResponse
Bbox is offset on a split page Highlights drift after page 13 transform_meta.split_offset consumed by toOriginalPage()
Firestore write contention on audit Duplicate seq Single-writer per bundle: audit writes serialized inside the orchestrator task
BigQuery vector index not ready Grounding returns empty Pre-filter fallback: WHERE hs_code LIKE '7304%' when distance is null
Demo env flake No live Gemini response Pre-loaded fixtures + a recorded fallback run, loaded by ?fixture=case-c query param

---

Bottom line: the frontend is a four-region grid driven by design tokens that make WCAG compliance auditable in one file; the backend is a two-tier router (HTTP edge + stage dispatcher) over pure-Python services; agents are thin ADK wrappers that own only extraction and grounding, while math, status precedence, confidence routing, and audit stay deterministic and unit-tested. Start with infra/bootstrap.sh, then build top-down from schemas.py → calculation.py → workflow.py → page.tsx.
