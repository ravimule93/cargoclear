# GCP verification runbook

Everything that touches Google Cloud in this repository was written and unit-tested **without cloud access**: the code
passes its tests against fakes, but none of it has run against a real project since the last change. This runbook is how
the person who *has* credentials closes that gap, in an order that fails fast and tells you what is missing.

Run it top to bottom. Each step says what a good result looks like and what to send back. Nothing here needs customer
data: every document is the synthetic Case C bundle in `fixtures/case_c/`.

| Step | What | Tool | Proves |
|---|---|---|---|
| 0 | Check model lifecycles | browser | the models the code names are still served |
| 1 | Bootstrap identities and APIs | `infra/bootstrap.sh` | the dedicated service accounts and roles exist |
| 2 | Tariff table and embedding model | `infra/bigquery/setup_tariff.sh` | grounding has data and a working embedder |
| 3 | Preflight, **as the runtime identity** | `scripts/preflight_gcp.py` | least-privilege IAM is sufficient; models accept the real request |
| 4 | Deploy API (private), then UI | `infra/deploy_api.sh`, `infra/deploy_ui.sh` | the deployment contract |
| 5 | Check the API is private | `curl` | the front door is the UI only |
| 6 | End-to-end Case C | `scripts/live_e2e_hosted.py` | the product works live, and how fast |
| 7 | Phase 1 specifics | smoke test, `--case d` | response schema accepted; certificate tables read correctly |
| 8 | Phase 2 specifics | `--case d --corrections` | corrections, recompute and the pre-fill pack work live |
| 9 | Scaling | queue, `deploy_api.sh`, emulator tests | leases, Cloud Tasks dispatch and shared limits hold on real Firestore |
| 10 | Audit signing | KMS key, `--expect-signer kms` | a real KMS signature verifies |
| 11 | Preprocessing A/B | smoke test on degraded scans | whether grayscale and deskew help on the real model |

## 0. Model lifecycles (do this first, and before every deployment)

Google retires model versions on a schedule, and the dates move. As of 2026-10-13, from secondary sources that
**disagree with each other** (so read Google's own pages, not this summary):

| Model | What was reported | Where to check |
|---|---|---|
| `gemini-2.5-flash` on Vertex AI (the default `GEMINI_LIVE_MODEL`) | retirement listed as **2026-10-20** (was June 2026, then extended) | Vertex AI "Model versions" page: <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions> |
| `text-embedding-004` (the embedding the earlier BigQuery setup used) | shut down (Gemini API table: 2026-01-14) | <https://ai.google.dev/gemini-api/docs/deprecations> |
| `gemini-embedding-001` | shutdown date on the Gemini API table: 2026-07-14 (successor named there) | same page; Vertex's own page may differ |

What to decide, and where to record it:

1. **Which Gemini model and location** to use today. Set `GEMINI_LIVE_MODEL` / `GEMINI_LIVE_LOCATION` when deploying
   (`infra/deploy_api.sh` reads them from the environment; nothing is edited in the repo).
2. **Which embedding endpoint** to put behind the BigQuery remote model. `infra/bigquery/setup_tariff.sh` has no default
   for `EMBEDDING_ENDPOINT` on purpose.
3. **Data residency.** The product commits to `asia-south1` (MeitY). A newer model may be served only from a `global`
   endpoint. If so, that is a decision for the product owner, not a config change: write it down before deploying.
4. Newer Gemini models can reject request settings older ones accepted (for example the thinking setting, the
   temperature, or the response schema). Step 3 sends the real extraction request, with an image part as every real request
   has (a thinking budget is refused by `gemini-3.x` only when a request carries an image), so it tells you.

## 1. Bootstrap

```bash
export PROJECT_ID=<project>   REGION=asia-south1
bash infra/bootstrap.sh
```

It creates two service accounts and prints the exports to use afterwards:

* `cargoclear-sa` (**API runtime**): `roles/aiplatform.user`, `roles/storage.objectAdmin`, `roles/bigquery.dataViewer`,
  `roles/bigquery.jobUser`, `roles/datastore.user`. `jobUser` is new: without it the tariff query cannot start.
* `cargoclear-ui-sa` (**UI runtime**): no project role at all. It is later given `roles/run.invoker` on the API only.

## 2. Tariff table and embedding model

```bash
export EMBEDDING_ENDPOINT=<a Vertex AI embedding model that step 0 says is served>
export RUNTIME_SERVICE_ACCOUNT=cargoclear-sa@${PROJECT_ID}.iam.gserviceaccount.com
bash infra/bigquery/setup_tariff.sh
```

Good result: the last two queries print an embedding dimension and then HS `73041900` first, `required_documents`
`[MILL_TEST_CERTIFICATE]`, a distance well under `0.35`. If you change `EMBEDDING_ENDPOINT` later, re-run the script:
stored vectors and query vectors must come from the same model (step 3 checks it).

## 3. Preflight, as the runtime identity

Run it **impersonating the runtime service account**, so that it exercises exactly the permissions the API will have:

```bash
gcloud auth application-default login --impersonate-service-account="$RUNTIME_SERVICE_ACCOUNT"
cd backend && APP_MODE=live .venv/bin/python ../scripts/preflight_gcp.py
```

(You need `roles/iam.serviceAccountTokenCreator` on that account. Running it as yourself proves much less: an owner can
do things the service account cannot.) It checks credentials, Gemini (plain call **and** the real extraction request
shape), BigQuery (rows, embedding, matching dimensions, the API's own `VECTOR_SEARCH`), Firestore and Cloud Storage
read/write/delete. Every failure prints the role that is probably missing.

Good result: `RESULT: PASS`, and a `preflight-report.json` (git-ignored). **Send it back.**

## 4. Deploy

```bash
export UI_SERVICE_ACCOUNT=cargoclear-ui-sa@${PROJECT_ID}.iam.gserviceaccount.com
export DAILY_TOKEN_BUDGET=<model tokens the whole service may spend per UTC day; 0 = no limit>   # required: your number, not a default
# optional: GEMINI_LIVE_MODEL, GEMINI_LIVE_LOCATION, BQ_MODEL_EMBEDDING, MEMORY, CPU
bash infra/deploy_api.sh      # private; also removes a leftover public (allUsers) binding
bash infra/deploy_ui.sh       # grants the UI identity roles/run.invoker on the API, then deploys the UI
```

The deployer needs `iam.serviceAccounts.actAs` on both service accounts and `run.services.setIamPolicy` on the API.
`cloudbuild.yaml` takes `_RUNTIME_SERVICE_ACCOUNT` and `_UI_SERVICE_ACCOUNT`.

`deploy_api.sh` sets the instance size explicitly: `MEMORY` (default `4Gi`) and `CPU` (default `2`). Cloud Run's default for a service
is 512 MiB, which one ordinary multi-page document exceeds. The size comes from a measurement on one machine (the heaviest document
the page caps allow peaked at 673 MB for one render, and up to `MAX_CONCURRENT_RUNS=4` renders can overlap), not from Cloud Run: if the
instance is ever restarted for running out of memory, raise `MEMORY` first (`docs/input-gating-audit.md`, section 16). Always-on
`4Gi`/`2` costs more than the default; check the price in the console before deploying.

### 4a. Budget alert and the daily token budget (written, not yet run)

Two independent lines against a runaway cost. Neither replaces the other.

```bash
# the limit the application enforces: tokens per UTC day for the whole service (default 5,000,000; 0 = off). A placeholder, not a quota:
# 5,000,000 is about 180 four-document analyses. Set what you are willing to spend: deploy_api.sh REQUIRES DAILY_TOKEN_BUDGET (0 = off),
# and a live service that was never told one logs daily_token_budget_is_the_default at start.
# the alert: a budget on the billing account (emails at 50 %, 90 %, 100 % and when the forecast reaches 100 %; it stops NOTHING)
export BILLING_ACCOUNT_ID=...   BUDGET_AMOUNT=100USD      # the amount per month, in the billing account's currency
bash infra/budget/setup_budget_alert.sh --dry-run         # prints the commands and calls nothing
bash infra/budget/setup_budget_alert.sh                   # needs a role that may manage budgets on the billing account
bash infra/firestore/setup_ttl.sh                         # lets Firestore delete old counters (ratelimits, token_budget) and kept answers (extraction_cache)
```

`GET /api/v1/token-budget` shows the limit, today's spend and the reset time. At the limit a new analysis or reassessment is refused
with `429 TOKEN_BUDGET_EXCEEDED` and `Retry-After`; a recompute is not. A run that already started finishes, so a day can overshoot
by the runs in flight. The counter is Firestore (`token_budget/<YYYYMMDD>`); if it cannot be read the budget is not enforced (logged).

## 5. The API must be private

```bash
API_URL=$(gcloud run services describe cargoclear-api --region "$REGION" --format='value(status.url)')
curl -s -o /dev/null -w '%{http_code}\n' "$API_URL/healthz"                       # expect 403
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences="$API_URL")" "$API_URL/healthz"   # 200 only if YOUR identity holds run.invoker
gcloud run services get-iam-policy cargoclear-api --region "$REGION"              # expect only the UI service account; no allUsers
```

**Send back** the `get-iam-policy` output.

## 6. End-to-end Case C

```bash
UI_URL=$(gcloud run services describe cargoclear-ui --region "$REGION" --format='value(status.url)')
python3 scripts/live_e2e_hosted.py --base-url "$UI_URL" --expect-mode live --runs 10
```

It uploads the three documents, analyzes (expects `MISSING_EVIDENCE` with the Mill Test Certificate requirement),
uploads the certificate, reassesses (expects `COMPLIANT_FOR_SUBMISSION` and a Reasoning Delta that names the certificate),
verifies the audit chain, and times every step. Stage times come from the 1 Hz SSE stream, so a stage shorter than about a
second may be attributed to its neighbour; the analysis totals are exact.

Good result: exit code 0 on all ten runs. **Send back** `live-e2e-report.json`, and record it with
`python3 scripts/measured_results.py ingest live-e2e-report.json --label hosted-case-c --model <GEMINI_LIVE_MODEL>` followed by
`python3 scripts/measured_results.py render`: the sanitized copy in `docs/measurements/` and the generated `docs/MEASURED_RESULTS.md`
are the only place latency numbers may be quoted from (median and slowest; a p95 from 20 runs). Fewer than 5 runs are shown but never
offered as a sentence. Repeat for `--case d` and `--case d --corrections`.

## 7. Phase 1 specifics (after steps 3 to 6 pass)

Phase 1 added a certificate table and sale terms to what Gemini is asked to read. Four things only a live run can show:

1. **Is the response schema accepted?** Vertex AI refuses a response schema whose constrained-decoding grammar has too many
   states ("too many states for serving", HTTP 400). Phase 1's nested schema (every header field an object holding a value, a
   confidence and a box) was refused by `gemini-2.5-flash` and `gemini-3.5-flash`. It was replaced on 2026-10-14: the model now
   returns lists of entries with the field name as an enum (`backend/app/agents/extraction_wire.py`), and the document model is
   rebuilt from them in Python. Both models accepted the new schema in `asia-south1`, and the synthetic fixtures were read
   correctly (`docs/MEASURED_RESULTS.md`, C-57). Step 3's `gemini` check sends the real request, schema included: a PASS means it
   is accepted, on whatever model and region you set. `tests/unit/test_gemini_request_schema.py` keeps the schema small enough to
   stay far from the limit; it is a tripwire, not a substitute for this check. If a model refuses it, the message names the cause.
   `gemini-3.5-flash` refuses `thinking_budget` of any value on a request with an image ("thinking budget is not supported for
   this model"), so for the `gemini-3` family the application sends `thinking_level` instead: `GEMINI_THINKING_LEVEL`, default
   `MINIMAL` (no thinking tokens); `DEFAULT` sends nothing, as `GEMINI_THINKING_BUDGET=-1` did. `GEMINI_THINKING_BUDGET` has no
   effect on that family. `gemini-2.5-pro` cannot switch thinking off: a budget below 128 is raised to 128.
2. **Does it read a certificate's table correctly?** Run the smoke test on the synthetic certificates:

   ```bash
   cd backend && APP_MODE=live .venv/bin/python ../scripts/live_smoke_extraction.py --overlay \
       --docs ../fixtures/case_c/mtc_pipe_test_cert.pdf ../fixtures/case_d/case_d_mtc_test_cert.pdf --runs 3
   ```

   It now gates the exit code on the specification, every heat number and **every chemistry and strength cell** (matched by
   heat and parameter, any order, strengths within 0.1 % after unit conversion), and reports agreement across runs. Send back
   the report. A misread digit in a chemistry cell is exactly the failure that would turn a verdict wrong, so this is the
   number to watch. The PDFs are rendered text, not scans: say so when quoting any accuracy figure.
3. **Case D live.** One command (after `infra/bigquery/setup_tariff.sh` has been re-run, so the India tariff rows exist):

   ```bash
   python3 scripts/live_e2e_hosted.py --base-url "$UI_URL" --expect-mode live --case d --runs 10
   ```

   It creates a bundle with destination `IN`, uploads `fixtures/case_d/*.pdf`, runs ONE analysis and expects
   `MATERIAL_CONTRADICTION` (M-001 naming heat TH-77121 and chromium 0.35), the invoice, specification, traceability and origin
   checks PASS, SEC-002 a WARN, an `ESTIMATED` valuation that lists its assumptions, and a verified audit chain. It also
   times the analysis; send back `live-e2e-report.json` (and ingest it: section 12).
4. **Does the prompt guard hold?** Text printed on a document must not change what the model reads (C-55, C-56,
   [INJECTION_TEST.md](INJECTION_TEST.md)). The test sends clean Case D documents and variants carrying an injected instruction
   aimed at one printed cell, three runs each (synthetic documents only, a few cents per run). By default the cell is the
   chromium cell of the certificate; `--targets all` attacks eleven cells on the certificate, the invoice and the bill of lading:

   ```bash
   cd backend && APP_MODE=live .venv/bin/python ../scripts/live_injection_test.py --dry-run     # no network, no credentials
   cd backend && APP_MODE=live .venv/bin/python ../scripts/live_injection_test.py                # the shipped prompt and schema
   cd backend && APP_MODE=live .venv/bin/python ../scripts/live_injection_test.py --without-guard   # the comparison
   cd backend && APP_MODE=live .venv/bin/python ../scripts/live_injection_test.py --targets all \
       --variants v2_visible_override v3_tiny_grey_override v5_cell_only_override v6_cell_only_fine_print   # the other cells
   cd backend && APP_MODE=live .venv/bin/python ../scripts/live_injection_test.py --guard-aware --targets all   # an attacker who has read the guard
   cd backend && .venv/bin/python ../scripts/live_injection_test.py --summary data/live_injection/injection-report-<time>.json
   ```

   It exits 0 only if every control was read correctly and every run of every variant read the printed value. Send back the reports
   (`backend/data/live_injection/`) and update `docs/INJECTION_TEST.md` and C-56. A *poisoned* run is the injection effect; a
   *dropped* run on `v4_white_text_layer` or on a control is a model flake (their page images are identical). A run that loses the
   network records errors and fails: re-run the affected cells and count each cell once, as `docs/INJECTION_TEST.md` does. For every poisoned run
   the report says what the deterministic engines would have done with the reading, against the model's own clean reading of that
   document: a reading nothing contradicts is *silent*. Run it again on any replacement model, since a retired model's result says
   nothing about the next one.

## 8. Phase 2 specifics (after steps 3 to 7 pass)

Phase 2 adds corrections by the authorised agent, a `recompute` run mode and the declaration pre-fill pack. What only a live run can show:

1. **The image builds.** `reportlab==5.0.1` is new in the runtime lock (the PDF summary). `infra/deploy_api.sh` rebuilds the image; the first
   `GET /prefill.pdf` proves the dependency is in it.
2. **Corrections work against real Firestore.** A correction is an audit event, so there is no new collection and no new index; the
   extraction record (`bundles/{id}/extractions/{n}`) gained `extraction_source` and `derived_from`, and iterations gained `corrections`
   and `run_mode`. Old documents still load. Check that the chain stays verified after corrections (the script does).
3. **Recompute reads the stored extraction, not the documents.** It must not call Gemini or touch Cloud Storage: look in the Cloud Run logs
   for a `recompute` run (`pipeline_started ... mode=recompute`) and confirm there is no `gemini_extraction_document` line and no
   `preprocess` work for it. Its duration (`recompute_seconds` in the report) should be about a second or two.
4. **The pre-fill downloads through the UI.** The UI's proxy must pass `Content-Disposition` and the binary PDF; the script checks both.

```bash
python3 scripts/live_e2e_hosted.py --base-url "$UI_URL" --expect-mode live --case d --corrections --runs 10
```

It runs Case D, corrects the chromium cell of heat TH-77121 to 0.28 (it finds the cell by heat and parameter, whatever the model's
row order), recomputes, expects `M-001` to pass and the Reasoning Delta to name the correction, downloads the pack as JSON (the
`content_sha256` is recomputed from the file alone; the audit chain must verify) and as PDF, undoes the correction and expects the
contradiction back. **Send back** `live-e2e-report.json`; quote the `recompute` time only from the ingested measurement (section 12). The
report keeps the recompute after the correction (`recompute`, status `SPECIALIST_REVIEW_REQUIRED`) apart from the one after the undo
(`recompute_after_undo`, `MATERIAL_CONTRADICTION`).

In the report, `corrected_cell.model_read` is what Gemini read in that cell: if it is not `0.35`, the certificate table was misread
(see section 7.2). If the script says the extraction has no Cr cell for TH-77121, the same is true.

## 9. Scaling beyond one instance (Phase 3)

The default deployment is unchanged: one always-on instance, runs as background tasks (`RUN_DISPATCH=local`). Everything below is
for running more than one instance. Design: [SCALING_AND_INTEGRITY.md](SCALING_AND_INTEGRITY.md).

1. **Prove the transaction code on a real Firestore first (no deployment needed).** The unit tests run it on a fake with
   Firestore-like optimistic transactions; this is the check that the fake is faithful. With any Firestore emulator
   (`gcloud components install cloud-firestore-emulator`, or `firebase emulators:start --only firestore`):

   ```bash
   gcloud emulators firestore start --host-port=localhost:8686 &
   cd backend && FIRESTORE_EMULATOR_HOST=localhost:8686 .venv/bin/python -m pytest tests/emulator -q -p no:cacheprovider --no-cov
   ```

   Four tests: fifteen contenders claim one bundle (one winner), a queued run is acquired by one of six workers and a stale
   executor is fenced out of its write, expiry and take-over on the real clock, and a burst of twelve rate-limited requests is
   counted exactly. **Send back** the output; a failure here is a bug in the lease code or in the fake, either way worth knowing first.
2. **Queue, identity and bindings** (idempotent):

   ```bash
   export RUNTIME_SERVICE_ACCOUNT=cargoclear-sa@${PROJECT_ID}.iam.gserviceaccount.com
   bash infra/tasks/setup_queue.sh          # queue cargoclear-runs, cargoclear-tasks-sa, enqueue + act-as bindings
   bash infra/firestore/setup_ttl.sh        # TTL on ratelimits.expires_at
   bash infra/storage/setup_artifact_retention.sh  # preview the approved 90-day evidence-artifact lifecycle
   ```
3. **Deploy with dispatch** (the script refuses `MAX_INSTANCES` above 1 without it, sets a 1500 s request timeout, gives the tasks
   identity `roles/run.invoker` on the private API, and sets `API_URL` on a second revision):

   ```bash
   export RUN_DISPATCH=cloudtasks MAX_INSTANCES=3 TASKS_SERVICE_ACCOUNT=cargoclear-tasks-sa@${PROJECT_ID}.iam.gserviceaccount.com
   bash infra/deploy_api.sh && bash infra/deploy_ui.sh
   ```
4. **Check it:**

   ```bash
   gcloud tasks queues describe cargoclear-runs --location "$REGION"            # max-concurrent-dispatches, retry config
   gcloud run services describe cargoclear-api --region "$REGION" --format='yaml(spec.template.spec.timeoutSeconds, spec.template.metadata.annotations)'
   python3 scripts/live_e2e_hosted.py --base-url "$UI_URL" --expect-mode live --case d --corrections --runs 3
   ```

   In Cloud Logging, for each run: `run_task_enqueued`, then `run_task_received` on SOME instance, then `pipeline_finished_successfully`
   on the same one; no `run_taken_over`, `run_reaped` or `run_lease_lost` in a healthy run.
5. **Chaos check (once):** start an analysis, and while it is in the extract stage delete the instance serving it
   (`gcloud run revisions` / redeploy the API). Expect: the run is delivered again after the retry backoff (30 s or more), its lease
   has expired by then, a worker logs `run_taken_over`, the audit shows `ANALYSIS_STARTED` twice (`attempt` 1 and 2), and the run
   completes with ONE iteration. Send back the audit events of that bundle.
6. **Shared limits:** with `RATE_LIMIT_BACKEND=firestore` (the default with cloudtasks) send 12 bundle creations in a minute through
   the UI from one address with `RATE_LIMIT_WRITES_PER_MINUTE=10`: the 11th is a 429 whichever instance serves it, and a
   `ratelimits` collection appears in Firestore (documents carry `expires_at`; the TTL policy removes them within about a day).
   Apply the separately approved 90-day artifact lifecycle only after reviewing the dedicated bucket's existing rules:
   `APPLY_RETENTION_POLICY=yes bash infra/storage/setup_artifact_retention.sh`. Audit records have no TTL while legal hold applies.

**Two numbers to choose, with the data this gives you:** `RUN_STALE_AFTER_SECONDS` (lease TTL, 90) against the queue's
`--min-backoff` (30 s) and attempts (5): a dead executor's run is taken over on the first delivery after its lease expired, so
the retry budget must outlast the TTL (it does: 30 + 60 + 120 s). And `MAX_INSTANCES` against the queue's
`max-concurrent-dispatches` (4): that is the service-wide run cap.

## 10. Audit signing with Cloud KMS (Phase 3)

```bash
export RUNTIME_SERVICE_ACCOUNT=cargoclear-sa@${PROJECT_ID}.iam.gserviceaccount.com
bash infra/kms/setup_signing_key.sh              # key ring + EC P-256 key + signerVerifier on THAT key; prints SIGNING_KEY_VERSION
export SIGNING_KEY_VERSION=<printed value>
bash infra/deploy_api.sh
python3 scripts/live_e2e_hosted.py --base-url "$UI_URL" --expect-mode live --case d --expect-signer kms
```

Good result: `audit_signature.status` is `SIGNED`, signer `kms`, key = your version; the UI's audit tab shows "Head signed through #N
(Cloud KMS key)". The API verified the signature against the PUBLIC key it fetched from KMS, so this is a real round trip
(KMS signed the digest, KMS returned the public key, `cryptography` verified). Also check once that the chain is
**actually** tamper-evident: in the Firestore console edit the `payload` of any event of that bundle, reload the audit tab: "Chain
BROKEN". (Do it on a throwaway bundle.) Quote nothing about signatures beyond "tamper-evident under the operator's key".

If `AUDIT_SIGNING_FAILED` appears in a bundle's chain: `PermissionDenied` means the runtime account lacks
`roles/cloudkms.signerVerifier` on the key; `NotFound`/`InvalidArgument` means a wrong `SIGNING_KEY_VERSION` or a key that is not an
`EC_SIGN_P256_SHA256` signing key (the API supports that algorithm only). `POST /api/v1/bundles/{id}/audit/sign` (or "Sign now" in the
UI) signs the head once it is fixed.

## 11. Preprocessing: grayscale and deskew on the real model (Phase 3)

Two switches change what Gemini is shown (`PAGE_IMAGE_MODE`, `PREPROCESS_DESKEW`) and both default to the original behaviour. The
tooling to decide with data:

```bash
cd backend
python ../scripts/make_degraded_scans.py --out data/degraded_scans            # skew, noise, blur, faded, jpeg, uneven light, sideways
for MODE in bw gray; do
  APP_MODE=live .venv/bin/python ../scripts/live_smoke_extraction.py --as-fixtures --page-mode $MODE --runs 3 \
      --docs data/degraded_scans/skew3/*.pdf data/degraded_scans/noise/*.pdf data/degraded_scans/jpeg/*.pdf data/degraded_scans/blur/*.pdf
done
python ../scripts/compare_smoke_reports.py data/live_smoke/report-<bw>.json data/live_smoke/report-<gray>.json
# and the same for deskew, on the skewed and sideways sets:
APP_MODE=live .venv/bin/python ../scripts/live_smoke_extraction.py --as-fixtures --deskew --runs 3 --docs data/degraded_scans/skew3/*.pdf data/degraded_scans/skew-6/*.pdf data/degraded_scans/sideways90/*.pdf
```

The smoke test grades every chemistry cell, heat, weight and HS code (the Case D certificate is graded too: it was not before
this phase). **Decide** on the failure counts the comparison prints: change a default only if a mode fails fewer expectations on the
degraded set AND is no worse on the clean files; say so in `Handoff.md`. Look at a few pages with `--overlay` and with the viewer's
"What the model saw" link: the boxes must sit on the printed values on the ORIGINAL page, for a straightened one too (the viewer says
"straightened N°"). Quote an accuracy figure only with its corpus ("synthetic, rendered, degraded copies of three documents").

### If something fails

| Symptom | Likely cause |
|---|---|
| Preflight `gemini` fails with 404 / "not found" | the model is retired or not served in that location: step 0 |
| Preflight `gemini` fails with 400 | the model rejects the request shape (thinking config, schema): the message names it; a model of a new family may need its own thinking knob (`thinking_config` in `agents/extraction.py`) |
| Preflight `bigquery` 403 | `roles/bigquery.jobUser` or `connectionUser` missing |
| Preflight `bigquery` "dimensions" mismatch | the table was embedded with another model: re-run `setup_tariff.sh` |
| Preflight `bigquery` WARN on distance | the 0.35 ambiguity threshold was tuned on another embedding model: recalibrate (`AMBIGUITY_THRESHOLD` in `bq_tariff.py`) |
| E2E: first status is not `MISSING_EVIDENCE` | extraction read the PDFs differently: run `scripts/live_smoke_extraction.py --overlay` to see which field |
| E2E: `PROXY_AUTH_ERROR` (502) | the UI cannot get an ID token from the metadata server: it must run on Cloud Run as `cargoclear-ui-sa` |
| E2E: 403 from the API through the UI | `cargoclear-ui-sa` lacks `roles/run.invoker` on `cargoclear-api` (step 4) |
| Preflight `gemini` 400 mentioning the schema or "too many states" | the response schema is too complex for the model (the shipped one is accepted by both models above; was a field added as a nested object?): section 7.1 |
| Smoke test: chemistry cells mismatch | the model misread the table: `--overlay` shows which cell; section 7.2 |
| Case D live: no India grounding / G-001 warns | `infra/bigquery/setup_tariff.sh` was not re-run after the India rows were added |
| E2E: stream never finishes | check Cloud Run logs for `pipeline_failed` / `run_reaped` with the run id |
| Run stays QUEUED, then fails as interrupted | the task never reached a worker: check the queue (`gcloud tasks queues describe`), that the tasks account holds `roles/run.invoker` on the API, and `API_URL` (the worker logs `internal_token_rejected` / `internal_caller_refused` when it got the call and refused it) |
| Worker answers 401/403 to Cloud Tasks | the OIDC audience is not `API_URL` exactly (no trailing slash), or `INTERNAL_CALLER_EMAIL` is not the tasks account; the log line names which |
| Worker answers 404 | `RUN_DISPATCH` is not `cloudtasks` on that revision (the endpoint does not exist in local mode) |
| `run_lease_lost` in the logs | an executor outlived its lease (a long pause, or a clock far off): its writes were refused; the run was taken over. Check Cloud Run CPU allocation and `RUN_STALE_AFTER_SECONDS` |
| 429 for everybody in a multi-instance deployment | `RATE_LIMIT_BACKEND` is `memory` per instance, or the Firestore counters fell back (`shared_rate_limit_unavailable` in the logs) |
| `AUDIT_SIGNING_FAILED` in a chain | section 10: the error type says what (PermissionDenied, NotFound, ...) |
| Audit tab: signature `UNVERIFIED` | the public key could not be fetched from KMS (permission or outage); not a failed signature |
| `--corrections`: 409 on recompute | the bundle gained a document, or the last assessment has no stored extraction: the message says which |
| `--corrections`: `/prefill.pdf` 500 | `reportlab` is not in the image (stale build): rebuild the API |
| `--corrections`: the pack's hash cannot be recomputed | something between the API and the script re-encodes the JSON: compare the raw bytes through the UI and the API |

## Security follow-up for the *previous* deployment

The earlier UI deployment ran Next.js 15.1.3 (affected by CVE-2025-66478, remote code execution in the React Server
Components protocol) on a **public** service, and `deploy_ui.sh` set no service account, so Cloud Run used the project's
**default compute service account**. Treat that deployment as possibly compromised: review Cloud Audit Logs for activity
by that service account, and rotate anything it could read. The new design limits the blast radius: the patched Next.js,
a UI identity that can only invoke the API, and a private API.

## 12. Recording the measurements (Phase 4)

Nothing about speed or accuracy may be quoted unless it is in [MEASURED_RESULTS.md](MEASURED_RESULTS.md), which is **generated** from the
sanitized reports in `docs/measurements/` (no project id, host or bundle id; the raw `live-e2e-report*.json` stay git-ignored). The
page lists what has not been measured yet; the goal of this section is to empty that list.

```bash
# 1. the end-to-end runs (10 each; fewer than 5 are shown but never offered as a sentence)
python3 scripts/live_e2e_hosted.py --base-url "$UI_URL" --expect-mode live --case c --runs 10 --out live-e2e-report-c.json
python3 scripts/live_e2e_hosted.py --base-url "$UI_URL" --expect-mode live --case d --runs 10 --out live-e2e-report-d.json
python3 scripts/live_e2e_hosted.py --base-url "$UI_URL" --expect-mode live --case d --corrections --runs 10 --out live-e2e-report-dc.json
# 2. the extraction accuracy of the real model (section 7.2; one report per setting you want to quote)
cd backend && APP_MODE=live .venv/bin/python ../scripts/live_smoke_extraction.py --as-fixtures --runs 3 \
    --docs ../fixtures/case_c/*.pdf ../fixtures/case_d/*.pdf && cd ..
# 3. record them (the model id is the stack's GEMINI_LIVE_MODEL: an e2e report cannot know it)
python3 scripts/measured_results.py ingest live-e2e-report-c.json  --label hosted-case-c  --model <GEMINI_LIVE_MODEL> --note "<instance settings>"
python3 scripts/measured_results.py ingest live-e2e-report-d.json  --label hosted-case-d  --model <GEMINI_LIVE_MODEL>
python3 scripts/measured_results.py ingest live-e2e-report-dc.json --label hosted-case-d-corrections --model <GEMINI_LIVE_MODEL>
python3 scripts/measured_results.py ingest backend/data/live_smoke/report-<timestamp>.json --label smoke-fixtures-bw
python3 scripts/measured_results.py render
```

Each ingest writes `docs/measurements/<date>T<time>-<kind>-<label>.json`; **a measurement is never overwritten** (a second report with the same label and time but other content is refused), so a re-run that passes does not erase the run that failed: both are on the page. Then send back the new files in `docs/measurements/` and `docs/MEASURED_RESULTS.md`. Four rules the generator enforces and you should
not work around: a demo-mode run is never offered as the product's latency; a p95 appears only from 20 runs; failed runs are counted
beside every latency and kept out of the timings (never silently dropped); and the only accuracy sentence it will print says the
documents were synthetic and rendered, not scanned.

After the numbers are in, `docs/CLAIMS.md` entries that say "waits for a live measurement" can be moved to PROVEN, with the measurement
file as the evidence (`backend/tests/unit/test_claims.py` checks that the evidence file exists). Run `scripts/record_demo.sh --live`
(`docs/DEMO_SCRIPT.md`) to record the walkthrough of the live stack.
