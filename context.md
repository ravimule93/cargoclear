# CargoClear-JAPAC current working context

This is an operational pointer, not a substitute for the code and tests. Historical work remains in `Handoff.md`; do not treat historical notes as the current contract.

## Repository and local environments

- `backend/`: FastAPI/Python 3.12. The standard local environment is `backend/.venv`.
- `frontend/`: Next.js 15.1.3/React 19. Use the checked-in `frontend/package-lock.json` with `npm ci --legacy-peer-deps`.
- `fixtures/case_c/`: canonical Case C PDFs. `backend/app/fixtures/case_c/` is the packaged container copy; do not regenerate or edit either casually.
- `infra/` and `cloudbuild.yaml`: static deployment configuration. Do not use them without authorised GCP access.

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
- The API is intentionally single-instance. Its run locks, rate limiting, SSE wakeups, and some lifecycle coordination are process-local.
- The checked-in Cloud Run API settings are `min-instances=1`, `max-instances=1`, `concurrency=80`, 300-second request timeout, and no CPU throttling. The run deadline is 1,200 seconds; SSE reconnects through the BFF as needed.
- Deployment requires `PROJECT_ID` and `RUNTIME_SERVICE_ACCOUNT`; no project, service-account email, or API URL is hardcoded. The deployer needs permission to act as the runtime service account.

## Evidence coordinates

Preprocessing persists private transform metadata per document. The scoped transform endpoint returns JSON to the BFF/UI; it does not expose storage credentials. Source-page and rotation provenance map processed evidence boxes to the original viewer page. A reversible deskew transform is deliberately not implemented: detection can be recorded, but `deskew_applied` remains false.

## Product boundaries

CargoClear is decision support only. No government submission, legal determination, payment, authentication, or SSO is implemented.
