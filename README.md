# CargoClear-JAPAC

CargoClear is a pre-submission, evidence-oriented customs assessment workbench for JAPAC trade bundles. It is **decision support only**: it does not submit to government portals, make legal determinations, calculate/pay duty, or replace the authorised Custom House Agent.

## What is implemented

- A Next.js workbench for upload, assessment, PDF evidence viewing, Reasoning Delta, and the hash-verified audit chain.
- A FastAPI pipeline that preprocesses PDFs, extracts evidence, performs deterministic checks, grounds HS requirements, and creates immutable assessment iterations.
- A Case C demo: Invoice + Bill of Lading + Packing List initially produce `MISSING_EVIDENCE`; adding the sample Mill Test Certificate reassesses to `COMPLIANT_FOR_SUBMISSION`.
- Demo extraction is deliberately synthetic and filename-keyed. It does **not** read the sample PDFs. Live mode uses GCS, Firestore, BigQuery, and Gemini instead.

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

Open `http://localhost:3000`, choose **Start Case C demo**, then:

1. Confirm the fresh workbench contains three documents and no assessment.
2. Select **Run analysis** and observe `MISSING_EVIDENCE`, including the Mill Test Certificate requirement.
3. Select **Use sample MTC (demo)**. The bundle reassesses to `COMPLIANT_FOR_SUBMISSION`.
4. Open the Reasoning Delta and Audit Chain tabs; the audit chain should show as verified.

The browser uses same-origin `/api/proxy/...` for ordinary API calls and SSE. `API_BASE` is server-only; do not configure or expose a browser-facing API URL.

## Verification

```bash
cd backend
.venv/bin/python -m pytest tests/unit tests/integration -p no:cacheprovider -o addopts='' -q

cd ../frontend
npm run typecheck
npm run lint
npm run build
```

`npm test` runs the current Playwright Case C and accessibility journeys. It starts local backend and frontend servers. In restricted sandboxes that prohibit local port binding or lack a browser runtime, report that limitation rather than treating it as a product failure.

## Deployment boundary

Deployment is intentionally not a local-demo prerequisite. The checked-in Cloud Run configuration is statically guarded but has not been verified against a real project in this repository:

- The API is deployed with `--max-instances 1`, `--min-instances 1`, `--concurrency 80`, a 300-second request timeout, and CPU retained for background analyses. The application uses process-local coordination and is not horizontally safe.
- The UI discovers the deployed API service URL during deployment and supplies it as runtime-only `API_BASE`; browser traffic remains BFF-proxied, including SSE.
- `RUNTIME_SERVICE_ACCOUNT` is mandatory for API deployment. The deployer needs `iam.serviceAccounts.actAs`; the runtime identity needs the checked-in least-privilege Vertex AI, Storage, BigQuery, and Firestore roles.
- The API deploy sets `APP_MODE=live` and disables API docs. Demo endpoints are therefore unavailable in that deployment.

Do not run Docker, Cloud Build, `gcloud`, or deployment commands without authorised project access. See [docs/HOW_TO_RUN_AND_DEMO.md](docs/HOW_TO_RUN_AND_DEMO.md) for the operational walkthrough and [docs/FAQ_ONBOARDING.md](docs/FAQ_ONBOARDING.md) for boundaries and troubleshooting.
