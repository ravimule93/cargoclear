# CargoClear-JAPAC current working context

This is an operational pointer, not a substitute for the code and tests. Historical work remains in `Handoff.md`; do not treat historical notes as the current contract.

## Repository and local environments

- `backend/`: FastAPI/Python 3.12. The standard local environment is `backend/.venv`.
- `frontend/`: Next.js 15.1.3/React 19. Use the checked-in `frontend/package-lock.json` with `npm ci --legacy-peer-deps`.
- `fixtures/case_c/`: canonical Case C PDFs. `backend/app/fixtures/case_c/` is the packaged container copy; do not regenerate or edit either casually.
- `infra/` and `cloudbuild.yaml`: static deployment configuration. Do not use them without authorised GCP access. `infra/bigquery/setup_tariff.sh` creates the tariff table and embedding model; `scripts/preflight_gcp.py` and `scripts/live_e2e_hosted.py` verify the live path.

Local demo commands:

```bash
cd backend
APP_MODE=demo .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080

cd frontend
API_BASE=http://127.0.0.1:8080 npm run dev
```

The frontend sends browser API and EventSource traffic to same-origin `/api/proxy/...`. The Next.js server forwards those requests to the server-only runtime `API_BASE`. `NEXT_PUBLIC_API_BASE` is retired and must not be used for deployed connectivity.

## Verification baseline

```bash
cd backend
.venv/bin/python -m pytest tests/unit tests/integration -p no:cacheprovider -o addopts='' -q

cd ../frontend
npm run typecheck
npm run lint
npm run build
```

Current Playwright tests create a new Case C bundle from `/`; they do not depend on retired hardcoded workbench routes. They require local backend/frontend servers and a usable browser runtime. A sandbox that blocks local port binding is an environment limitation, not evidence that the journey is stale.

## Runtime boundaries

- Demo mode uses synthetic filename-keyed extraction fixtures and local/in-memory fallbacks. It is not live PDF reading.
- Live mode requires GCP clients and never falls back to fixtures. Cloud Run service identity counts as live credentials.
- The default deployment is a single API instance (`RUN_DISPATCH=local`): runs are background tasks of that instance. Firestore leases + Cloud Tasks (`RUN_DISPATCH=cloudtasks`, Phase 3, see below) allow more, but are tested on a fake Firestore only. SSE wake-ups and the per-bundle upload count stay process-local by design.
- The API is a **private** Cloud Run service; only the UI's service account may invoke it, via a Google ID token the Next.js proxy attaches (`API_AUTH_MODE=google-id-token`). The proxy forwards a fixed list of request headers, only GET/POST, and only paths below `/api/v1`; it sets `X-CargoClear-Client-IP` and the API reads it (`CLIENT_IP_HEADER`) for per-user rate limits.
- BigQuery and Cloud Storage clients are blocking: every call runs in a worker thread (`asyncio.to_thread`). Never call them directly from an `async def`. Tariff lookups are de-duplicated per run and bounded by `TARIFF_LOOKUP_CONCURRENCY`.
- The checked-in Cloud Run API defaults are `min-instances=1`, `max-instances=1` (more only with `RUN_DISPATCH=cloudtasks`), `concurrency=80`, 300-second request timeout (1,500 for the worker path), and no CPU throttling. The run deadline is 1,200 seconds; SSE reconnects through the BFF as needed.
- Deployment requires `PROJECT_ID`, `RUNTIME_SERVICE_ACCOUNT` and `UI_SERVICE_ACCOUNT`; no project, service-account email, or API URL is hardcoded. The deployer needs permission to act as both service accounts.
- Live GCP code is unit-tested against fakes only. `docs/GCP_VERIFICATION.md` is how someone with credentials verifies it; model IDs (`GEMINI_LIVE_MODEL`, the BigQuery embedding endpoint) are configuration because Google retires models.

## Rules and reference data

- Deterministic engines (pure Python, no I/O, no LLM): `services/calculation.py` (weights, HS, entities; calls the others), `services/invoice_checks.py` (I-*), `services/metallurgy.py` (M-*), `services/trade_remedies.py` (E-origin, SEC-*), `services/valuation.py` (the estimate). The model only READS documents; it never decides a classification, a limit or a duty.
- Curated tables: `backend/app/reference/*.json` (see its README, the reviewer's checklist). Strict pydantic models (`reference/loader.py`) stop the service at start-up if a table is malformed. Every iteration stores a fingerprint of the tables it used (`reference_data`). Tables are `demo-curated` until a reviewer relabels them; checks name the rule set they used.
- A check whose result depends on an assumption is a WARN (`assumptions` lists them); PASS / MATERIAL come from stated values only.
- Extraction schema (`domain/schemas.py`): certificates carry `specification`, `heat_numbers` and `test_results` (flat rows: `LabResult`, one per heat and parameter), documents carry `incoterm`, `country_of_origin`, `freight_*`, `insurance_*`, lines carry `unit_price_basis`. Flat on purpose (no nested arrays). Changing it changes the Gemini request schema: regenerate the snapshot with `UPDATE_GEMINI_SCHEMA_SNAPSHOT=1` and review the diff.
- Demo fixtures: `fixtures/case_c/` and `fixtures/case_d/` (generated by `scripts/generate_case_c_pdfs.py` from `agents/extraction._generate_fixture_for_file`; drift-guard tests compare the committed PDFs). `backend/app/fixtures/` holds the copies the container image carries: after regenerating, copy both directories there.

## Evidence coordinates

Preprocessing persists private transform metadata per document. The scoped transform endpoint returns JSON to the BFF/UI; it does not expose storage credentials. Source-page and rotation provenance map processed evidence boxes to the original viewer page. A skewed page is straightened only with `PREPROCESS_DESKEW=true` (off by default); the reversible transform is `processed_to_source_affine` and `deskew_applied` says whether it was used (Phase 3, below).

## Corrections and the pre-fill pack (Phase 2)

- **The audit chain is the store of corrections.** A correction is one audit event (`FIELD_CORRECTED`, `FIELD_CONFIRMED`, `CORRECTION_REVERTED`); `domain/corrections.py` turns the events back into the overlay (the newest non-reverted entry per address). One atomic write, so the overlay cannot disagree with the audit trail. The stored extraction (`bundles/{id}/extractions/{n}`) is never edited: it is what the model read.
- **Addresses** are a closed grammar over explicit field tables (`consignee`, `line_items[2].hs_code_declared`, `heat_numbers[0]`, `test_results[7]`, `doc_type`); a test pins the tables to the schema and another pins the frontend's copy to them. A row address carries an **anchor** (heat + parameter, line description, heat number) so a correction is found again if a table is read in another order, and **skipped, never mis-applied** when its row is gone.
- **The overlay is applied after the `extract` stage in every run mode** (`services/corrections.apply_to_ctx`). `recompute` mode skips preprocessing and extraction (it copies the stored extraction under the new iteration number) and re-runs discrepancy → synthesize; it needs a previous assessment over the same documents (else 409 → use Reassess). Iterations store `corrections` (applied / skipped) and `run_mode`.
- **A corrected value** has confidence 1.0 and keeps the box of the printed value it replaces. Validation refuses a number that needs an assumption to be read, a weight without a unit, a lab value that is not a number / `<n` / `ND`.
- **The pre-fill pack** (`services/prefill.py`, pure `assemble`) picks each value from the best document, lists the others, flags conflicts, low confidence and values an open finding cites, and carries a banner when not cleared. `integrity.content_sha256` is recomputable from the file; `provenance` carries the audit head. Read-only: a download writes nothing to the audit chain. Format: `docs/PREFILL_PACK.md`, schema in `docs/schemas/`.

## Scaling, signing and preprocessing (Phase 3)

- **Lease per bundle** (`repo/leases.py`): `bundles/{id}/control/lease` with `run_id`, `state` QUEUED|RUNNING, `mode`, `iteration`, `owner`, `fence`, `expires_at`. Every operation is one atomic read-modify-write whose decision is a pure function (`decide_*`) shared by the in-memory and Firestore stores. **Fencing:** the iteration write and the terminal write are transactions that read the lease (`fenced_transaction`); `set_run_state(..., fence=)` also releases the lease in the same step. `_ensure_claim` verifies the lease between stages. `reap_stale` takes an expired lease out (one reaper wins) and marks that run failed once; the record-timestamp reap remains for legacy records.
- **Dispatch:** `RUN_DISPATCH=local` (default: a background task) or `cloudtasks` (`services/run_queue.py` enqueues one task per run, named by the run id; `api/internal.py` is the worker endpoint, `orchestrator.execute_queued` runs the pipeline inside the request). The worker verifies the OIDC token itself and accepts only `INTERNAL_CALLER_EMAIL`. Answers: 200 done|obsolete, 409 busy. A dead executor's run is taken over on the next delivery (fence + 1, `ANALYSIS_STARTED` again with `attempt`). A dispatched run cancelled by shutdown is not failed. The stage-dispatch function in the orchestrator is still named `dispatch`; the Cloud Tasks module is `run_queue` to avoid shadowing it.
- **Shared limits:** `RATE_LIMIT_BACKEND=firestore` (`gateway/limits.py::SharedRateLimiter`): transaction per request, client hashed, TTL field, in-process fallback. Service-wide run cap = the queue's max-concurrent-dispatches.
- **Audit signing** (`services/signing.py`): after `ASSESSMENT_COMPLETED` the head `{purpose, bundle_id, seq, hash}` is signed (KMS EC P-256 via `SIGNING_KEY_VERSION`; demo: a labelled in-process key) and appended as `AUDIT_HEAD_SIGNED`; failures become `AUDIT_SIGNING_FAILED` and never fail a run. `GET /audit` carries `signature` (SIGNED / PARTIAL / UNSIGNED / INVALID / UNVERIFIED / NOT_CONFIGURED); verification fetches the KMS public key and requires the signed head to be in the chain. `tests/conftest.py` turns signing OFF so the other tests' exact event sequences hold.
- **Preprocessing** (`services/preprocess.py`): orientation = axis (row-profile unevenness at the best small tilt) then polarity; skew = projection profile; `deskew_image` + `deskew_to_source_affine` (aspect-aware, normalized 0-1000) composed with the rotation affine into `processed_to_source_affine`; the viewer maps boxes through it when `deskew_applied` (`frontend/lib/transform-bbox.ts`, golden vectors shared with `backend/tests/unit/test_deskew.py`). `PAGE_IMAGE_MODE`, `PREPROCESS_DESKEW` (off), `PERSIST_PROCESSED_PAGES` (on). Corpus: `backend/tests/support/scans.py`.

## Claims, measurements and the demo (Phase 4)

- **`docs/CLAIMS.md`** is the register of what may be said (PROVEN / STUBBED / ASSUMED / DELETED, each with evidence). `backend/tests/unit/test_claims.py` enforces it: evidence exists, the outward-facing files (README, Product.md, FAQ, runbooks, UI) carry no invented statistic or superlative, deleted/stale claims stay out, C-08/C-09 move only with a live measurement, and the backend imports no HTTP client and has no route that files or pays. When a document needs a number, it goes through the measurement tool, not into prose.
- **`docs/MEASURED_RESULTS.md`** is generated by `scripts/measured_results.py render` from `docs/measurements/*.json` (sanitized copies made by `ingest`; the raw `live-e2e-report*.json` stay git-ignored). A test fails if the page differs from the data. Demo-mode runs are shown but never quotable; a p95 needs 20 runs; failed runs are counted and kept out of timings. `live_e2e_hosted.py` reports `recompute` and `recompute_after_undo` separately.
- **Recording**: `scripts/record_demo.sh [--live URL] [--no-video]` drives `frontend/demo/walkthrough.spec.ts` with `frontend/playwright.demo.config.ts` (not part of `npm test`); output in git-ignored `demo-recordings/` with a manifest naming the mode. Talk track and ladder: `docs/DEMO_SCRIPT.md`. The red-team pass and pitch Q&A: `docs/REDTEAM.md`.
- The home page has a **destination selector** (SG/IN) and the top bar shows it; with nothing chosen the viewer opens the document the first MATERIAL finding cites last (`findingDocumentId` in `useWorkbench`).

## Product boundaries

CargoClear is decision support only. No government submission, legal determination, duty collection or payment, authentication, or SSO is implemented. The **indicative duty estimate** (`services/valuation.py`) is information: it never changes the status and lists every assumption it made.
