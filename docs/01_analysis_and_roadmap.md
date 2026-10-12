# CargoClear implementation roadmap and current state

This roadmap tracks the verified implementation progress against the Hackathon MVP goals, documents recent architecture and UI enhancements, and outlines remaining work and post-MVP enhancements.

---

## 1. Executive Summary & Verified Deliverables

| Deliverable Area | Current Status | Verification Details |
|---|---|---|
| **Live Cloud Run Deployment** | **Production Live** | • Backend API: `https://cargoclear-api-448522365737.asia-south1.run.app`<br>• Frontend UI: `https://cargoclear-ui-5ho4zmc74q-el.a.run.app`<br>• Hosted in `asia-south1` (Mumbai, MeitY compliant).<br>• Fully integrated with Next.js BFF proxy (`/api/proxy/...`) resolving cross-origin and SSE streaming cleanly. |
| **BigQuery AHTN Vector Grounding** | **Production Live** | • Dataset: `cargoclear-hackathon:ahtn`, Table: `master_tariff`<br>• Embedding Model: `text-embedding-004`<br>• Live cosine distance vector search (`VECTOR_SEARCH`) matches HS 7304 and mandates `MILL_TEST_CERTIFICATE`.<br>• Query constructed using description only to avoid bias from declared codes. |
| **Multimodal Extraction (Gemini 2.5 Flash)** | **Production Live** | • Vertex AI `gemini-2.5-flash` in `asia-south1`.<br>• Configured with `GEMINI_MAX_OUTPUT_TOKENS=65536` to prevent truncation on large documents.<br>• Normalized bounding box coordinates `[ymin, xmin, ymax, xmax]` on a 0–1000 scale.<br>• Sanitizer strips code fences and clamps invalid confidence or out-of-bound box values. |
| **Deterministic Math & Semantic Engine** | **Complete & Verified** | • Weight parity check (`W-001`) with configurable tolerance (max 0.5% or 5 kg).<br>• Explicit units normalization (`units.py`) supporting KG, MT, LB, G without silent assumptions.<br>• Cross-document HS code consistency check (`H-002`) and certificate subset check (`H-003`).<br>• Cross-document entity consistency checks (`E-consignee`, `E-consignor`, `E-vessel`) across all uploaded documents. |
| **Multi-Document Processing ($N$ Files)** | **Complete & Verified** | • Configurable capacity via `MAX_DOCUMENTS_PER_BUNDLE=20` (not hardcoded to 4 files).<br>• Dynamic duplicate document handling (`D-DUP-<DOCTYPE>`).<br>• Scales dynamically to arbitrary multi-document bundles. |
| **Investigator UI & A11y Workbench** | **Production Live** | • Responsive 4-panel layout (document rail, PDF canvas viewer, assessment panel, reasoning delta drawer).<br>• Fixed left rail visibility across diverse screen breakpoints.<br>• Document health badges on rail (`● N Conflicts`, `▲ N Gaps`, `✓ Clean`).<br>• Structured document attribution on check cards displaying filename, doc type, stated value, and page citations.<br>• Gap highlighting (`⚠️ Field Omitted / Absent (Gap)`) for omitted evidence.<br>• Floating canvas tooltips showing field name, value, and severity on bounding boxes. |
| **Upload & Error Feedback UX** | **Production Live** | • Real-time batch upload progress (`Uploading 1/3: invoice.pdf`) on top bar and dropzone.<br>• Responsive `ActionErrorBanner` in Assessment panel for immediate error diagnostics. |
| **Cryptographic Audit Trail** | **Complete & Verified** | • Append-only Firestore log with SHA-256 hash chaining (`✓ Chain verified`).<br>• Sequence numbering `{seq:010d}` with retry on `AlreadyExists`. |
| **Case C Browser Demo Flow** | **Complete & Verified** | • Dedicated fixture demo path with zero cloud dependency (`APP_MODE=demo`).<br>• `ModeBadge` dynamic indicator (`● LIVE GCP` vs `● DEMO MODE`). |

---

## 2. Recent Implementation & Architecture Updates

### 2.1 Multi-Document Handling Architecture
- **Configurable Bundle Limit**: Defined in `backend/app/core/config.py` (`MAX_DOCUMENTS_PER_BUNDLE = 20`).
- **Dynamic Check Engine**:
  - `calculation.py` iterates across all $N$ uploaded documents for cross-document entity alignment (`E-consignee`, `E-consignor`, `E-vessel`).
  - Emits non-blocking warnings (`D-DUP-<DOCTYPE>`) when multiple documents of the same type are present.
  - Dynamically runs certificate checks (`H-003-<DOCTYPE>`) for every uploaded certificate type (`MILL_TEST_CERTIFICATE`, `PHYTOSANITARY_CERTIFICATE`, `CERTIFICATE_OF_ORIGIN`).

### 2.2 Investigator UI Enhancements
- **Document Attribution Cards**: `frontend/components/assess/CheckList.tsx` maps check evidence directly to source document filenames, document types, stated values, and page numbers.
- **Visual Gap Tagging**: Stated values that are missing or omitted are tagged with prominent warning badges.
- **Document Rail Health Badges**: `DocumentRail.tsx` computes status per document based on check results, displaying badge chips for conflicts, gaps, or clean statuses.
- **Drawer Controls**: `DeltaDrawer.tsx` includes an expand/collapse toggle for easier viewing on smaller laptop screens.
- **Canvas Hover Tooltips**: `BBoxLayer.tsx` displays floating tooltips over bounding boxes on hover.

### 2.3 Production Robustness & Token Tuning
- `GEMINI_MAX_OUTPUT_TOKENS` raised from `16384` to `65536` in `backend/app/core/config.py` to support dense commercial documents without truncation errors.
- BigQuery vector query parameterized and post-filtered by destination to ensure accurate tariff matches.

---

## 3. Remaining Work for Hackathon Submission (P0 / P1)

| Item | Priority | Current State | Action Needed to Close |
|---|---|---|---|
| **Live Extraction E2E Validation** | **P0** | Gemini extraction and BigQuery search work individually and in live Cloud Run. | Perform end-to-end user evaluation with sample files on the live URL to verify full cycle from upload to `COMPLIANT_FOR_SUBMISSION`. |
| **Reversible Deskew Coordinate Mapping** | **P1** | Diagnostic only (`deskew_applied=false`). Rotation (0/90/180/270°) is applied. | Persist affine inverse matrix for sub-degree deskew if needed for scanned carbon copies. |
| **Automated Live Smoke CI Script** | **P1** | Unit tests pass (1581 passed); manual live calls verified. | Run `scripts/live_smoke_extraction.py` with synthetic inputs in CI pipeline. |

---

## 4. Winning Improvement Roadmap & Next Enhancements

To advance CargoClear beyond the Hackathon MVP into an enterprise-grade, winning solution, comprehensive critique and transformation blueprints have been authored:

* **Detailed Improvement Blueprint & Architecture**: See [`docs/02_judge_critique_and_improvement_roadmap.md`](02_judge_critique_and_improvement_roadmap.md) for judge critique resolutions, GATT valuation (`VAL-001`), deep MTC metallurgy checks (`H-003-ADV`), and horizontal scaling with Cloud Pub/Sub.
* **Market Landscape, Differentiation & USP**: See [`docs/03_market_comparison_and_usp.md`](03_market_comparison_and_usp.md) for head-to-head comparisons against CargoWise, Google Document AI, Traydstream, and Indian customs copilot **Broto AI**.

### Deliberately Deferred / Post-MVP Roadmap (P2)
The following items are scheduled for Phase 2/Phase 3 development per the improvement roadmap:
- **Government Portal Auto-Filing**: Automated declaration export to Indian ICEGATE Bill of Entry JSON and ASEAN Single Window CUSDEC XML.
- **Payment & Duty Calculation**: Customs duty payments, GST ITC calculations, and bank gateways (GATT assessable valuation engine).
- **Horizontal API Scaling**: Distributed Redis Locks (Cloud Memorystore) and Google Cloud Pub/Sub SSE message mesh to remove the `max-instances=1` barrier.
- **Authentication & Single Sign-On (SSO)**: Multi-tenant CHA authentication and OAuth/SAML integration.
- **Batch Processing Pipeline**: Asynchronous Vertex AI batch pipeline for 50+ document shipping containers.


---

## 5. Cloud Run Infrastructure & Configuration Reference

| Component | Target / Environment | Configuration Details |
|---|---|---|
| **API Service** | `cargoclear-api` (`asia-south1`) | • Image: Artifact Registry `asia-south1-docker.pkg.dev/cargoclear-hackathon/cargoclear/api`<br>• Identity: `448522365737-compute@developer.gserviceaccount.com`<br>• Instances: `min=1, max=1, concurrency=80`<br>• Timeout: `300s`<br>• CPU: Always allocated (no CPU throttling)<br>• Model: `gemini-2.5-flash`<br>• Max Output Tokens: `65536` |
| **UI Service** | `cargoclear-ui` (`asia-south1`) | • Image: Artifact Registry `asia-south1-docker.pkg.dev/cargoclear-hackathon/cargoclear/ui`<br>• URL: `https://cargoclear-ui-5ho4zmc74q-el.a.run.app`<br>• Runtime BFF routing: `/api/proxy/...` forwards to `cargoclear-api` |
| **BigQuery** | `cargoclear-hackathon:ahtn` | • Location: `asia-south1` (Mumbai)<br>• Table: `master_tariff`<br>• Model: `text-embedding-004` |
| **Storage & Database** | Cloud Storage & Firestore | • GCS: `cargoclear-raw-pdfs` (`asia-south1`)<br>• Firestore: `(default)` in Native mode (`asia-south1`) |
