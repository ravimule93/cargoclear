# CargoClear-JAPAC

CargoClear is a pre-submission, evidence-oriented customs assessment workbench for JAPAC trade bundles. It is **decision support only**: it does not submit to government portals, make legal determinations, collect or pay duty, or replace the authorised Custom House Agent. It does give an **indicative duty estimate** (an assessable value and the duties on it, with every assumption listed); that estimate is information, never an amount payable and never the assessment status.

## What is implemented

- A Next.js workbench for upload, assessment, PDF evidence viewing, Reasoning Delta, and the hash-verified audit chain.
- A FastAPI pipeline that preprocesses PDFs, extracts evidence, performs deterministic checks, grounds HS requirements, and creates immutable assessment iterations.
- Deterministic checks beyond weights and HS codes: invoice arithmetic (quantity × price, totals, currency), the **Mill Test Certificate against the declaration** (alloy status under HS Chapter 72 Note 1, carbon equivalent, chemistry and strength limits of the certificate's own standard, heat-number traceability to the packing list), country-of-origin consistency, and anti-dumping / circumvention flags. The rules come from curated tables in `backend/app/reference/` (labelled `demo-curated`, unverified until a reviewer says otherwise: see its README).
- Two demo journeys. **Case C** (India → Singapore): Invoice + Bill of Lading + Packing List give `MISSING_EVIDENCE`; adding the sample Mill Test Certificate reassesses to `COMPLIANT_FOR_SUBMISSION`. **Case D** (an import into India): all four documents are loaded and the certificate's chemistry (0.35 % chromium) contradicts the declared non-alloy HS code, giving `MATERIAL_CONTRADICTION`, an anti-dumping warning and an indicative duty estimate.
- **Corrections by the authorised agent.** Edit a value the model read in place (on any evidence row); the correction is an audited, hash-chained entry (`FIELD_CORRECTED` / `FIELD_CONFIRMED` / `CORRECTION_REVERTED`) and changes nothing until **Recompute**, which re-runs every check on the stored extraction with no document read and no model call. A reassessment keeps the corrections; the Reasoning Delta names each one, the value it replaced and the reason.
- **Declaration pre-fill pack.** The values of an assessment, with the document and page each came from, what the other documents say, what needs a person's eyes and what the declarant must still supply, as documented JSON and a printable PDF (`docs/PREFILL_PACK.md`). It says first when a bundle is not cleared and is never "ready to file"; it is not a government format.
- **Scales past one instance, safely.** Who may analyse a bundle is a Firestore lease with a fence (two instances cannot both run it; a paused executor cannot write); with `RUN_DISPATCH=cloudtasks` each run is a Cloud Task executed inside a worker request, so scale-in cannot kill it and a dead executor's run is taken over. Rate limits can be shared by all instances. Default unchanged: one always-on instance. Design: `docs/SCALING_AND_INTEGRITY.md`.
- **A signed audit trail.** After each completed assessment the head of the hash-chained audit trail is signed (Cloud KMS; a labelled throwaway key in demo mode). With a KMS key, a history rewritten consistently still fails verification (the demo key proves less and is refused where KMS is configured). Tamper-evident under the operator's key; not legal non-repudiation.
- **Better page preparation.** A sideways scan is turned (even a crooked one), an optional reversible deskew straightens skewed pages while evidence boxes still land on the original page, the model's input can be 1-bit or grayscale (an A/B is tooled), and the page image the model was shown is kept and linked ("What the model saw").
- Demo extraction is deliberately synthetic and filename-keyed. It does **not** read the sample PDFs. Live mode uses GCS, Firestore, BigQuery, and Gemini instead.

## What may be claimed, and the numbers

[`docs/CLAIMS.md`](docs/CLAIMS.md) labels every claim about this project PROVEN, STUBBED or ASSUMED, with its evidence, and a test keeps it honest. Speed and accuracy numbers come from one generated page, [`docs/MEASURED_RESULTS.md`](docs/MEASURED_RESULTS.md); today it holds demo-mode runs only (which are **not** the live product's latency) and lists what has not been measured. The pitch material is [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) and [`docs/REDTEAM.md`](docs/REDTEAM.md).

## Local setup

Prerequisites: Python 3.12, Node.js 22, and npm. Poppler is optional locally; the backend container installs it for PDF rendering.

Create the standard backend environment from the repository root:

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

If your team uses `uv`, the equivalent supported setup is:

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
```

Install the locked frontend dependencies:

```bash
cd frontend
npm ci --legacy-peer-deps
```

## Run the local demo

In one terminal:

```bash
cd backend
APP_MODE=demo .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

In another:

```bash
cd frontend
API_BASE=http://127.0.0.1:8080 npm run dev
```

Open `http://localhost:3000`, choose **Start Case C demo** (or **Start Case D demo (India import)**, described below), then:

1. Confirm the fresh workbench contains three documents and no assessment.
2. Select **Run analysis** and observe `MISSING_EVIDENCE`, including the Mill Test Certificate requirement.
3. Select **Use sample MTC (demo)**. The bundle reassesses to `COMPLIANT_FOR_SUBMISSION`.
4. Open the Reasoning Delta and Audit Chain tabs; the audit chain should show as verified.

**Case D:** choose **Start Case D demo (India import)** and **Run analysis**. Expect `MATERIAL_CONTRADICTION`: the Alloy Status check names heat `TH-77121`, chromium 0.35 %, and the subheading it points to (7304.51); every other rule passes; `SEC-002` warns about anti-dumping duty; the **Indicative duty exposure** card shows the estimate and, one click away, everything it assumed.

**Corrections and the pre-fill pack (Case D):** after the analysis, press **Edit** on the evidence chip `TH-77121: Cr 0.35%`, state `0.28` with a reason, **Save correction**, then **Recompute with corrections**. `M-001` passes, the status moves to `SPECIALIST_REVIEW_REQUIRED` (the anti-dumping warning remains), the Reasoning Delta names the correction, and the Audit Chain lists it. **Undo** and recompute brings the contradiction back. The **Declaration pre-fill** card downloads the pack as JSON or PDF.

The browser uses same-origin `/api/proxy/...` for ordinary API calls and SSE. `API_BASE` is server-only; do not configure or expose a browser-facing API URL.

## Verification

```bash
cd backend
.venv/bin/python -m pytest tests/unit tests/integration -p no:cacheprovider -o addopts='' -q

cd ../frontend
npm run typecheck
npm run lint
npm run test:unit   # pure unit specs (the server-side proxy); no browser or servers
npm run build
```

`npm test` runs the current Playwright Case C and accessibility journeys. It starts local backend and frontend servers. In restricted sandboxes that prohibit local port binding or lack a browser runtime, report that limitation rather than treating it as a product failure.

## Deployment status

- **Backend API**: `https://cargoclear-api-448522365737.asia-south1.run.app`
- **Frontend UI**: `https://cargoclear-app.web.app` (or `https://cargoclear-ui-448522365737.asia-south1.run.app`)
- **API configuration**: Deployed with `--max-instances 10`, `--min-instances 1`, `--concurrency 80`, a 300-second request timeout, and CPU always allocated.
- **UI configuration**: Runs with Next.js BFF proxy routing `/api/proxy/...` directly to the backend API, preserving same-origin semantics for both HTTP requests and SSE event streams, with dual cookie handling (`__session` and `cargoclear_session_token`) for Firebase Hosting CDN rewrites.
- **Live GCP Integrations**: BigQuery vector search on tariff dataset `cargoclear-hackathon:ahtn`, Firestore hash-chained audit logging, GCS PDF storage (`cargoclear-raw-pdfs`), and multimodal extraction with Vertex AI `gemini-2.5-flash`.
- **Prompt-Injection Guard**: Prompt-injection guard tested and verified across synthetic fixtures and attack variants ([docs/INJECTION_TEST.md](docs/INJECTION_TEST.md), [docs/MEASURED_RESULTS.md](docs/MEASURED_RESULTS.md)).
- See [docs/01_analysis_and_roadmap.md](docs/01_analysis_and_roadmap.md) for the verified roadmap, [docs/HOW_TO_RUN_AND_DEMO.md](docs/HOW_TO_RUN_AND_DEMO.md) for the operational walkthrough, and [docs/GCP_VERIFICATION.md](docs/GCP_VERIFICATION.md) for verification procedures.

Do not run Docker, Cloud Build, `gcloud`, or deployment commands without authorised project access. See [docs/HOW_TO_RUN_AND_DEMO.md](docs/HOW_TO_RUN_AND_DEMO.md) for the operational walkthrough and [docs/FAQ_ONBOARDING.md](docs/FAQ_ONBOARDING.md) for boundaries and troubleshooting.
