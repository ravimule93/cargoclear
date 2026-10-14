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

To regenerate the sample PDFs after changing a fixture (then copy `fixtures/case_c` and `fixtures/case_d` to `backend/app/fixtures/`):

```bash
backend/.venv/bin/python scripts/generate_case_c_pdfs.py
```

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

## 4b. Case D demo script (India import)

1. On `/`, select **Start Case D demo (India import)**. The workbench holds four documents; the status is **Not assessed yet**.
2. Select **Run analysis**. Observe **Material Contradiction**.
3. In the checklist, open **Alloy Status vs Declared HS Code**: heat `TH-77121`, chromium 0.35 %, the 0.30 % threshold of HS Note 1(f), the subheading the chemistry points to (7304.51). The evidence chip `TH-77121: Cr 0.35%` is the printed value; the green box on the certificate page marks where.
4. Open **Anti-Dumping Exposure** (a warning) and the **Indicative duty exposure** card. Expand **What this estimate assumed**: the default insurance, the illustrative exchange rate, the illustrative anti-dumping rate, the unverified tables.
5. Open **Audit Chain Timeline**: **Chain verified**.

## 4c. Corrections and pre-fill script (Case D)

1. After step 5 of the Case D script, in the **Alloy Status vs Declared HS Code** card press **Edit** on the evidence chip for the certificate cell. The editor shows what the model read (`0.35 %`).
2. Enter `0.28` as the value, a reason such as "certificate prints 0.28 in the Cr column", and **Save correction**. The **Corrections (1)** card appears with *Pending recompute*; the status has not moved.
3. Press **Recompute with corrections**. The run reads no document and calls no model, so it is much shorter than an analysis (measured times: `MEASURED_RESULTS.md`). `M-001` passes and the status becomes **Specialist Review Required** (the anti-dumping warning remains). The Reasoning Delta names the correction, the value it replaced and your reason; the Audit Chain tab shows `FIELD_CORRECTED`.
4. In the **Declaration pre-fill** card, **Download JSON** and **Download PDF summary**. The pack leads with `NOT CLEARED` (the warning remains), lists the findings that block it, gives every value with its source document and page, and lists what the declarant must still supply.
5. **Undo** the correction and recompute: the contradiction returns. Saving the value *as it was read* instead records a confirmation (`FIELD_CONFIRMED`).

Through the API: `POST /bundles/{id}/corrections`, `GET /bundles/{id}/corrections`, `POST /bundles/{id}/corrections/{cor-n}/revert`, `POST /bundles/{id}/recompute`, `GET /bundles/{id}/prefill[.pdf]`. Scripted: `python3 scripts/live_e2e_hosted.py --base-url ... --case d --corrections`.

## 4d. Audit signature and the model's view (Case D)

1. After the analysis, open **Audit Chain Timeline**: **Chain verified**, and beside it **Head signed through #N (demo key, not KMS)**. Expand **What a signature means here**: tamper-evident under the operator's key; not legal non-repudiation.
2. Make a correction and recompute (script 4c) and reopen the tab: the recompute's own completion signs the head again. Between the correction and the recompute the badge reads **Signed through #N; 1 later event not signed yet** with a **Sign now** button.
3. In the document viewer, **What the model saw** opens the page image the extraction was given. (Demo mode renders the PDFs with poppler; without it the document is passed through as a PDF and the link is absent.)
4. Local switches (`backend/.env.example`): `AUDIT_SIGNING=false`, `PAGE_IMAGE_MODE=gray`, `PREPROCESS_DESKEW=true` (then a skewed page shows **straightened N°**), `PERSIST_PROCESSED_PAGES=false`. Degraded sample copies: `backend/.venv/bin/python scripts/make_degraded_scans.py`.

## 4e. The live-mode route: choose a destination and upload

A live stack has no demo buttons. The same journeys run by hand: on `/` choose the **Destination** (Singapore for Case C, India for Case D),
**New empty bundle**, then **Add Document** (or drop files) with `fixtures/case_c/*.pdf` or `fixtures/case_d/*.pdf`, and **Run analysis**. The top
bar shows the destination ("To IN"). In demo mode the file names key the synthetic extraction, so the same upload reaches the same verdicts;
`frontend/tests/destination_journey.spec.ts` does exactly this. With nothing chosen, the viewer opens the document the first material finding is about.

## 4f. Recording the walkthrough (the fallback demo)

`scripts/record_demo.sh` records the whole walkthrough (Case C, Case D, a correction, the pre-fill, the signed audit trail) as a captioned video,
a still per step and a manifest that says which mode it was. `scripts/record_demo.sh --live https://<ui>.run.app` records a deployed stack. The talk track,
the fallback ladder and what not to say are in [DEMO_SCRIPT.md](DEMO_SCRIPT.md); the video needs Playwright's ffmpeg once (`npx playwright install ffmpeg`),
`--no-video` records stills only. Output goes to `demo-recordings/` (git-ignored).

### Demo honesty

Demo mode uses synthetic extraction fixtures keyed by filename. The sample documents are illustrative and the UI displays a demo banner. This journey demonstrates the interaction and assessment flow, not live document reading.

## 5. Local verification

```bash
cd backend
.venv/bin/python -m pytest tests/unit tests/integration -p no:cacheprovider -o addopts='' -q

cd ../frontend
npm run typecheck
npm run lint
npm run test:unit
npm run build
```

`npm run test:unit` runs the pure unit specs (`tests/*.unit.spec.ts`, today the server-side proxy) with no browser and no servers. The Playwright suite is current and creates its own Case C bundle:

```bash
cd frontend
npm test
```

It starts backend and frontend development servers. It cannot run in an environment that disallows local port binding, lacks the Playwright browser, or otherwise blocks browser-server execution. Record that exact environment blocker; do not replace the journey with a hardcoded route.

## 6. Live-mode boundary

`APP_MODE=live` disables the demo endpoints and requires real GCP credentials/services. It uses GCS, Firestore, BigQuery, and Gemini; it does not fall back to synthetic fixtures.

For an authorised Cloud Run deployment, the static configuration expects:

- a **private** API: only the UI's service account may invoke it, and the UI's proxy sends a Google ID token (`API_AUTH_MODE=google-id-token`);
- one API instance by default (`max-instances=1`, `RUN_DISPATCH=local`); a scale-out needs `RUN_DISPATCH=cloudtasks` and is untested on Google Cloud;
- API/UI request timeouts of 300 seconds and API CPU retained for background work;
- runtime-only `API_BASE` supplied to the UI after the API service URL exists;
- supplied `RUNTIME_SERVICE_ACCOUNT` and `UI_SERVICE_ACCOUNT`, with the deployer authorised to act as both;
- live mode and API documentation disabled.

Verification against a real project is a separate, credentialed job: [GCP_VERIFICATION.md](GCP_VERIFICATION.md). You can already run the same end-to-end checks against a local stack, for example `python3 scripts/live_e2e_hosted.py --base-url http://localhost:3000 --expect-mode demo`.

These settings are statically tested only. Docker build, Cloud Build, Cloud Run networking, service-account permissions, and live SSE reconnect behavior still require an authorised GCP verification.
