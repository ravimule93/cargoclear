# CargoClear implementation roadmap and current state

This roadmap tracks the verified implementation progress against the Hackathon MVP goals and outlines the remaining work and post-MVP enhancements.

---

## 1. Completed & Verified Work

| Area | Status | Evidence & Details |
|---|---|---|
| **Live Cloud Run Deployment** | **Complete & Verified Live** | • Backend API: `https://cargoclear-api-448522365737.asia-south1.run.app`<br>• Frontend UI: `https://cargoclear-ui-5ho4zmc74q-el.a.run.app`<br>• Region: `asia-south1` (MeitY compliant)<br>• Integrated with Next.js BFF proxy to eliminate CORS. |
| **BigQuery AHTN Vector Grounding** | **Complete & Verified Live** | • Dataset: `cargoclear-hackathon:ahtn`<br>• Table: `master_tariff`<br>• Embedding Model: `text-embedding-004`<br>• Live cosine distance vector search (`VECTOR_SEARCH`) matches HS 7304 and mandates `MILL_TEST_CERTIFICATE`. |
| **Multimodal Extraction (Gemini 2.5 Flash)** | **Complete & Verified Live** | • Layout-aware extraction via Vertex AI `gemini-2.5-flash` in `asia-south1`.<br>• `GEMINI_MAX_OUTPUT_TOKENS` tuned to `65536`.<br>• Strict Pydantic JSON schema with normalized bounding boxes `[ymin, xmin, ymax, xmax]`. |
| **Deterministic Math & Semantic Engine** | **Complete & Verified** | • Weight parity check (`W-001`) with configurable tolerance (max 0.5% or 5 kg).<br>• Cross-document HS code consistency check (`H-002`).<br>• Entity and currency consistency checks. |
| **Cryptographic Audit Trail & Reassessment** | **Complete & Verified** | • Append-only Firestore log with SHA-256 hash chaining (`✓ Chain verified`).<br>• Differential Reasoning Delta between iterations. |
| **Investigator UI & A11y Workbench** | **Complete & Verified** | • 4-panel responsive investigator workbench (document rail, PDF canvas viewer, assessment panel, reasoning delta drawer).<br>• `ModeBadge` dynamic indicator (`● LIVE GCP` vs `● DEMO MODE`). |
| **Upload & Error UX Feedback** | **Complete & Verified** | • Real-time batch upload progress (`Uploading 1/3: invoice.pdf`) on top bar and dropzone.<br>• Responsive `ActionErrorBanner` in Assessment panel for immediate error diagnostics. |
| **Case C Browser Demo Flow** | **Complete & Verified** | • Dedicated fixture demo path with zero cloud dependency (`APP_MODE=demo`). |

---

## 2. Remaining Work for Hackathon MVP Completion

| Item | Priority | Current State | Action Needed to Close |
|---|---|---|---|
| **End-to-End Live Extraction Verification** | **P0** | Gemini extraction and BigQuery search work individually. | Conduct final live run via [Hosted UI](https://cargoclear-ui-5ho4zmc74q-el.a.run.app) with sample Case C files to confirm end-to-end `MISSING_EVIDENCE` (flagging MTC) and reassessment. |
| **Reversible Deskew Coordinate Mapping** | **P1** | Diagnostic only (`deskew_applied=false`). Rotation (0/90/180/270°) is applied. | Persist affine inverse matrix for sub-degree deskew if required for scanned carbon copies. |
| **Comprehensive Live E2E Smoke Script** | **P1** | Unit tests pass (96 tests); manual live calls verified. | Run `scripts/live_smoke_extraction.py` with non-customer synthetic inputs in CI pipeline. |

---

## 3. Deliberately Deferred / Post-MVP Roadmap (P2)

The following items are intentionally out of scope for the pre-submission Hackathon MVP:

- **Government Portal Auto-Filing**: Automated submission to ICEGATE / e-SANCHIT or ASEAN Single Window (system is decision support for human CHA).
- **Payment & Duty Calculation**: Customs duty payments, GST ITC calculations, and bank gateways.
- **Horizontal API Scaling**: The API is currently pinned to `max-instances=1` (with concurrency=80 and retained CPU) because locks and SSE wakeups are in-process. Scaling to multiple replicas requires Cloud Pub/Sub or Redis Pub/Sub.
- **Authentication & Single Sign-On (SSO)**: Multi-tenant CHA authentication and OAuth/SAML integration.
- **Batch Processing API**: Asynchronous Vertex AI batch pipeline for 50+ document shipping containers.

---

## 4. Cloud Run Live Infrastructure Status

| Service | Environment / Resource | Configured Settings |
|---|---|---|
| `cargoclear-api` | `asia-south1` / Cloud Run | • Identity: `448522365737-compute@developer.gserviceaccount.com`<br>• Instances: `min=1, max=1, concurrency=80`<br>• Timeout: `300s`<br>• CPU: Always allocated (no CPU throttling)<br>• Model: `gemini-2.5-flash`<br>• Output Tokens: `65536` |
| `cargoclear-ui` | `asia-south1` / Cloud Run | • URL: `https://cargoclear-ui-5ho4zmc74q-el.a.run.app`<br>• Routing: Server-side BFF proxy (`API_BASE`) forwarding to `cargoclear-api`<br>• Client: Same-origin `/api/proxy/...` |
| BigQuery | `cargoclear-hackathon:ahtn` | • Location: `asia-south1`<br>• Table: `master_tariff`<br>• Model: `embedding_model` |
| Firestore & GCS | `(default)` & `cargoclear-raw-pdfs` | • Location: `asia-south1` / Mumbai |

