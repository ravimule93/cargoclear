# How to run and demo CargoClear

This guide covers verified local behavior. It does not authorize Docker builds, GCP access, Cloud Build, or deployment.

## 1. Prerequisites

- Python 3.12
- Node.js 22 and npm
- Optional local Poppler (`pdftoppm`) for actual PDF rasterization. The backend handles the supported fallback when it is absent; the backend container installs Poppler.

## 2. Install local dependencies

From the repository root:

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt

cd ../frontend
npm ci --legacy-peer-deps
```

`uv` may be used instead of `venv`/`pip`:

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
```

## 3. Start the local demo

Terminal A:

```bash
cd backend
APP_MODE=demo .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Terminal B:

```bash
cd frontend
API_BASE=http://127.0.0.1:8080 npm run dev
```

Open `http://localhost:3000`.

The Next.js application proxies both ordinary API requests and SSE through same-origin `/api/proxy/...`. `API_BASE` is server-only. Do not use the retired `NEXT_PUBLIC_API_BASE` setting or configure a direct browser-to-backend URL.

## 4. Case C demo script

1. On `/`, select **Start Case C demo**.
2. Confirm the new workbench contains exactly three documents: Commercial Invoice, Bill of Lading, and Packing List. The status is **Not assessed yet**.
3. Select **Run analysis**.
4. Observe **Missing Evidence** and the Mill Test Certificate requirement.
5. Select **Use sample MTC (demo)**.
6. Observe reassessment to **Compliant For Submission**.
7. Open **Reasoning Delta** and **Audit Chain**. Confirm the audit badge reads **Chain verified**.

Each invocation creates its own bundle. Do not navigate to retired routes such as `/workbench/HERO-CASE-C-7304`, and do not rely on a pre-existing bundle ID.

### Demo honesty

Demo mode uses synthetic extraction fixtures keyed by filename. The sample documents are illustrative and the UI displays a demo banner. This journey demonstrates the interaction and assessment flow, not live document reading.

## 5. Local verification

```bash
cd backend
.venv/bin/python -m pytest tests/unit tests/integration -p no:cacheprovider -o addopts='' -q

cd ../frontend
npm run typecheck
npm run lint
npm run build
```

The Playwright suite is current and creates its own Case C bundle:

```bash
cd frontend
npm test
```

It starts backend and frontend development servers. It cannot run in an environment that disallows local port binding, lacks the Playwright browser, or otherwise blocks browser-server execution. Record that exact environment blocker; do not replace the journey with a hardcoded route.

## 6. Live-mode boundary

`APP_MODE=live` disables the demo endpoints and requires real GCP credentials/services. It uses GCS, Firestore, BigQuery, and Gemini; it does not fall back to synthetic fixtures.

For an authorised Cloud Run deployment, the static configuration expects:

- one API instance (`max-instances=1`) because run coordination is process-local;
- API/UI request timeouts of 300 seconds and API CPU retained for background work;
- runtime-only `API_BASE` supplied to the UI after the API service URL exists;
- a supplied `RUNTIME_SERVICE_ACCOUNT`, with the deployer authorised to act as it;
- live mode and API documentation disabled.

These settings are statically tested only. Docker build, Cloud Build, Cloud Run networking, service-account permissions, and live SSE reconnect behavior still require an authorised GCP verification.
