# CargoClear onboarding FAQ

## What is CargoClear?

A pre-submission trade-document assessment aid. It presents evidence, deterministic checks, and audit history so an authorised CHA can decide what to do. It does not submit to government systems, make a legal ruling, process payments, or implement authentication/SSO.

## How do I open the Case C demo?

Run the backend with `APP_MODE=demo`, run the frontend, open `/`, and select **Start Case C demo**. The action creates a new bundle; there is no supported fixed Case C workbench URL.

## Does the demo read PDFs with Gemini?

No. Demo extraction is synthetic and keyed by filename. The demo banner and sample-PDF text disclose this. `APP_MODE=live` is the mode that uses real Gemini/GCS/Firestore/BigQuery services and it never falls back to fixtures.

## What should the Case C journey show?

Three documents and no assessment first; then `MISSING_EVIDENCE` with a Mill Test Certificate requirement; then `COMPLIANT_FOR_SUBMISSION` after **Use sample MTC (demo)**. Reasoning Delta and Audit Chain should be available, with a verified chain.

## Which local environment should I use?

Use `backend/.venv` with Python 3.12 and `frontend/package-lock.json` with `npm ci --legacy-peer-deps`. See [HOW_TO_RUN_AND_DEMO.md](HOW_TO_RUN_AND_DEMO.md) for commands.

## Why does the browser not contain the API URL?

The UI uses same-origin `/api/proxy/...` for both API traffic and SSE. Next.js reads `API_BASE` on the server at runtime. This avoids a build-time public API URL and keeps browser connectivity the same locally and on Cloud Run.

## How are evidence boxes mapped to the displayed PDF?

The backend persists document-scoped preprocessing metadata. The frontend fetches it through:

`GET /api/v1/bundles/{bundle_id}/documents/{document_id}/transform-metadata`

The response is `{ "document_id": "…", "transform_meta": [ … ] }`. It maps source pages and supported rotations back to the original viewer. The metadata storage URI is not fetched by the browser.

## Does preprocessing fully deskew documents?

No. The current pipeline renders 200-DPI B&W pages, can apply conservative quarter-turn rotation, and records source/artifact provenance. Deskew may be detected diagnostically but is not applied because a reversible deskew transform has not yet been implemented. Coordinate mapping safely falls back when metadata is absent or not usable.

## Why is the API single-instance in Cloud Run?

Run locks, rate limits, and SSE coordination are process-local. The checked-in deployment therefore configures `max-instances=1` rather than claiming horizontal safety. This is a deliberate current limitation.

## What is needed before an authorised deployment?

Provide `PROJECT_ID` and `RUNTIME_SERVICE_ACCOUNT`; grant the deployer `iam.serviceAccounts.actAs`; provision the runtime identity with the configured Vertex AI, Storage, BigQuery, and Firestore permissions. The API must be deployed first so the UI deployment can discover its URL and inject runtime `API_BASE`.

No Docker build, Cloud Build run, Cloud Run deployment, or live GCP connection is verified by the local documentation workflow.

## Can I run Playwright locally?

Yes, with `cd frontend && npm test` when its browser runtime and local port binding are available. The suite starts both servers and creates its own Case C bundle. Restricted sandboxes may block that setup; record the sandbox error instead of changing the test to a hardcoded route.
