# CargoClear onboarding FAQ

## What is CargoClear?

A pre-submission trade-document assessment aid. It presents evidence, deterministic checks, and audit history so an authorised CHA can decide what to do. It does not submit to government systems, make a legal ruling, collect or process duty payments, or implement authentication/SSO. It does give an indicative duty estimate (see below).

## What does it check besides weights?

Invoice arithmetic, the certificate's chemistry against the declared HS code (alloy status under HS Chapter 72 Note 1, carbon equivalent, the certificate's own standard, heat-number traceability), origin consistency, and anti-dumping / circumvention flags. See `README.md` ("Key Differentiators").

## Where do the rules and rates come from, and are they official?

From curated tables in `backend/app/reference/`. They are labelled `demo-curated`, were written for the prototype, and are **not verified or official**; the exchange rates and the anti-dumping entry are explicitly illustrative placeholders. Each check that uses a table names it, the UI shows the rule set beside it, and `backend/app/reference/README.md` is the checklist for the person who verifies them. Verified tables are relabelled by that reviewer; nothing in the application promotes them on its own.

## Is the duty figure a customs determination?

No. It is an indicative estimate for the authorised agent: it lists every assumption (defaults for freight and insurance, the exchange rate, unverified rates), it never changes the assessment status, and it is never an amount payable. For India the rate that applies is the one in force when the Bill of Entry is presented; the estimate applies no date.

## How do I open the Case C demo?

Run the backend with `APP_MODE=demo`, run the frontend, open `/`, and select **Start Case C demo**. The action creates a new bundle; there is no supported fixed Case C workbench URL.

## What is Case D?

An import into India: Chinese-origin seamless tubes declared under a non-alloy HS code whose certificate shows 0.35 % chromium. Open it with **Start Case D demo (India import)**; it loads all four documents and the first analysis is a `MATERIAL_CONTRADICTION` with an anti-dumping warning and a duty estimate.

## What happens when I correct a value?

You press **Edit** on an evidence row and state what the document actually says (or confirm what the model read). The entry is recorded in the audit chain with the value it replaced and your reason, and listed in the **Corrections** card as *pending*. Nothing else changes until you press **Recompute with corrections**: that re-runs every check on the stored extraction (no document is read again, no model is called) and produces a new assessment whose Reasoning Delta names each correction. **Undo** removes a correction the same way (the history is kept). A reassessment after uploading a document keeps your corrections; one that cannot be placed (the table was read in another order and the row is gone) is shown as *not used*, never applied to the wrong row.

## What is the declaration pre-fill?

The values of an assessment for the person who keys the declaration: JSON and a printable PDF from the **Declaration pre-fill** card. Every value says which document and page it was read from, what the other documents state, whether you corrected it and whether it needs a look. A bundle that is not cleared says so at the top. It is CargoClear's own documented format (`docs/PREFILL_PACK.md`), not a government one, and never "ready to file".

## Can the API run on more than one instance?

Yes, with `RUN_DISPATCH=cloudtasks` (docs/GCP_VERIFICATION.md section 9). Who may analyse a bundle is a lease in Firestore, so two instances cannot run the same bundle; each run is a Cloud Task executed inside a worker request, so scaling in cannot kill it, and if its executor dies the next delivery takes the run over. Without it the default is unchanged: one always-on instance running each analysis as a background task. The in-process caches that stay per instance (SSE wake-ups, the per-bundle upload count) are listed in docs/SCALING_AND_INTEGRITY.md.

## What does the signature on the audit trail mean?

After each completed assessment the head of the hash-chained audit trail is signed with a key the database does not hold (Cloud KMS in a deployment; a labelled throwaway key in demo mode). The hash chain alone cannot catch someone who rewrites the whole history consistently; a KMS signature can. A demo signature is checked only against the key its own process holds and proves less (the chain was not edited after it was signed, in that session); a demo signature is refused when a KMS key is configured or the service is live. It is tamper-evident under the operator's key. It is **not** legal non-repudiation: there is no user authentication, so the signer is the service, not a person.

## What did the model actually see?

The viewer's **What the model saw** link opens the exact page image the extraction was given (after orientation correction, optional straightening and the 1-bit or grayscale mode). A straightened page says so in the viewer, and the evidence boxes are mapped back onto the original page.

## How do I run Case D when there are no demo buttons (a live stack)?

On `/` choose **Destination: India (IN)**, press **New empty bundle**, add the four PDFs from `samples/case_d/`, and run the analysis. The destination decides
which rules and duty structure apply, so a Case D bundle created with the Singapore default would not be assessed as an India import.

## What is the "Lowest reported confidence" figure?

The lowest confidence the extraction model reported among the values the checks rest on. It is a score the model gives itself, not a measured accuracy; no accuracy of the
live model has been measured yet (`docs/MEASURED_RESULTS.md`).

## Where do the speed and accuracy numbers come from?

Only from `docs/MEASURED_RESULTS.md`, which is generated from recorded runs (`scripts/measured_results.py`). Demo-mode timings are shown there but are labelled not quotable: no model is called. What may be said
about the product, and with what evidence, is `docs/CLAIMS.md`.

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

## Can I take a document out of a bundle?

Yes. In the web app select the document in the left rail and use **Remove** (then confirm); through the API it is `DELETE /api/v1/bundles/{bundle_id}/documents/{document_id}` (not while a run is in progress). It removes the stored PDF, its processed pages, the model's kept answers for it and its record, and the audit chain records a `DOCUMENT_DELETED` event. It does not rewrite history: earlier assessments and the audit chain still describe the document. The web app then reassesses the bundle if the newest assessment used the document; through the API the newest assessment changes only when you reassess. The Android app does not have a screen for it yet (see `docs/input-gating-audit.md`, sections 17 and 19).

## What if a file is not what I uploaded it as, or is not in English?

Say what the next file is with the type menu beside **+ Add Document** (or send `declared_type` through the API); if the model reads another type the assessment warns (`T-001`). A document whose values are mostly not Latin script is flagged too (`L-001`). Names and units are still compared as printed: the warning says a finding about them may be a difference of language. A Latin-script document in another language (Spanish, French) is not flagged. See `docs/input-gating-audit.md`, sections 18 and 19.

## Does preprocessing fully deskew documents?

Only if you ask it to. By default the pipeline renders 200-DPI 1-bit pages and turns a sideways page by a quarter turn when the evidence is strong. `PREPROCESS_DESKEW=true` also straightens a page that is skewed by 0.3 to 10 degrees, using a reversible, aspect-aware transform: the viewer maps every evidence box back onto the original page. Whether straightening (or `PAGE_IMAGE_MODE=gray`) helps extraction on the real model has not been measured yet; both are off by default until it has (`docs/GCP_VERIFICATION.md`, section 11). Coordinate mapping safely falls back when metadata is absent or not usable.

## Why does the default deployment run a single API instance?

With the default `RUN_DISPATCH=local` a run is a background task of the instance that accepted it, so `deploy_api.sh` configures `max-instances=1` and refuses more. `RUN_DISPATCH=cloudtasks` (Firestore lease + Cloud Tasks, `docs/SCALING_AND_INTEGRITY.md`) lifts that, but it has been exercised only on a fake Firestore, not on Google Cloud, so it is not the default. The SSE wake-up and the per-bundle upload count stay per instance by design.

## Who can call the API?

Only the UI. The API is a private Cloud Run service; the UI runs as its own service account, which alone holds `roles/run.invoker` on it, and the UI's server-side proxy attaches a Google ID token to every call. Calling the API URL directly without such a token returns 403.

## What is needed before an authorised deployment?

Provide `PROJECT_ID`, `RUNTIME_SERVICE_ACCOUNT` and `UI_SERVICE_ACCOUNT`; grant the deployer `iam.serviceAccounts.actAs` on both; provision the runtime identity with the configured Vertex AI, Storage, BigQuery (`dataViewer` and `jobUser`), and Firestore permissions; create the tariff table and embedding model with `infra/bigquery/setup_tariff.sh`. The API must be deployed first so the UI deployment can discover its URL and inject runtime `API_BASE`.

No Docker build, Cloud Build run, Cloud Run deployment, or live GCP connection has been verified since the latest changes. Follow [GCP_VERIFICATION.md](GCP_VERIFICATION.md).

## Which Gemini model does it use, and will it keep working?

`GEMINI_LIVE_MODEL` (default `gemini-2.5-flash`) in `GEMINI_LIVE_LOCATION`. Google retires model versions on a schedule; the Vertex AI page lists a retirement date for this default. The model is configuration, not code: check the lifecycle page, set the variable at deploy time, and run `scripts/preflight_gcp.py`, which sends the real extraction request and reports whether the model accepts it.

## Can I run Playwright locally?

Yes, with `cd frontend && npm test` when its browser runtime and local port binding are available. The suite starts both servers and creates its own Case C bundle. Restricted sandboxes may block that setup; record the sandbox error instead of changing the test to a hardcoded route.
