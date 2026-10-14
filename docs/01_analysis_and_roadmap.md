# CargoClear: roadmap and current state

Last updated: 2026-10-14, end of Phase 2. This file is the working plan; `Handoff.md` is the session-by-session log.

Status words used below, and what they promise:

* **Done** — implemented, unit-tested, and (for UI/proxy work) exercised in a real local browser.
* **Done, awaiting GCP** — implemented and unit-tested against fakes; **has not run against a real Google Cloud project**.
  [GCP_VERIFICATION.md](GCP_VERIFICATION.md) is the runbook for whoever has credentials.
* **Planned** — not started.

## Decisions (2026-10-13)

| Topic | Decision |
|---|---|
| Deadline | None. The target is a polished, production-grade product, not a demo cut. |
| Lanes | Keep **Case C** (India → Singapore, the regression and demo journey). Add **Case D**: an **India import**, where anti-dumping, basic customs duty and IGST apply. |
| Duty | **In scope as an indicative estimate** (duty exposure with provenance and disclaimers, never "duty payable"). `Product.md`, the README, the FAQ and the UI copy change when this lands. |
| Horizontal scaling | **Firestore leases + Cloud Tasks.** Not Redis/Redlock + Pub/Sub. |
| Domain data | Curated rule tables (HS notes, spec limits, duty rates, exchange rates, anti-dumping entries) are verified by the product owner before they are relied on. Each carries `rule_set` + `regulation_ref`; none is presented as official. |
| Cloud access | Code is written to be verified later by someone with credentials. Nothing is "verified live" until [GCP_VERIFICATION.md](GCP_VERIFICATION.md) has been run. |
| Git | The assistant makes no git changes; the owner reviews and commits. |

## Status of earlier claims

The previous version of this file listed items as "Complete & Verified Live" (live Cloud Run URLs, BigQuery grounding,
Gemini extraction, "96 tests"). Those were reported by an earlier session against a **previous, public deployment** and
were not re-checked here. Re-state them only after the runbook has passed. Verified in this review, locally:

| Check | Result |
|---|---|
| Backend tests (`tests/unit`, `tests/integration`) | all pass (the "96 tests" figure was long stale) |
| Frontend `tsc`, ESLint, production build, proxy unit specs | pass |
| Playwright: Case C journey + WCAG axe scan + keyboard | **4 of 4 pass** after three accessibility fixes (the axe scan failed before: see Phase 0) |
| Local end-to-end through the real Next.js proxy (`scripts/live_e2e_hosted.py`, demo mode) | passes |

## Phase 0: floor — **done** (live parts awaiting GCP)

| Item | Status | Notes |
|---|---|---|
| Event loop not blocked by BigQuery / Cloud Storage | Done | Every blocking call runs in a worker thread. Tariff lookups run concurrently (bounded by `TARIFF_LOOKUP_CONCURRENCY`), identical descriptions are looked up once, results keep input order, a failure surfaces as its own error. Proven by tests that fail (0 ticks) when the offload is removed. |
| Vector search pre-filter | Done, awaiting GCP | The destination filter moved inside the `VECTOR_SEARCH` base-table subquery; before, `top_k` was chosen across all destinations and filtered afterwards. |
| Next.js upgrade | Done | 15.1.3 → 15.5.27: clears every Next.js advisory `npm audit` reported (it had a critical one). What remains is a build-time PostCSS advisory inside Next that only Next 16 fixes. |
| Private API | Done, awaiting GCP | `--no-allow-unauthenticated`; the UI runs as its own service account with `roles/run.invoker` on the API only; the proxy sends a Google ID token. A leftover public binding is removed on deploy. |
| Hardened proxy | Done | GET/POST only; header allowlist (no cookies, no client `Authorization`); path confined to `/api/v1`; client disconnect aborts the upstream request (SSE no longer lingers); fixed error texts. |
| Per-user rate limits | Done, awaiting GCP | The proxy sets `X-CargoClear-Client-IP` from the trusted hop; the API keys on it (`CLIENT_IP_HEADER`). Before, every user behind the proxy shared one bucket. |
| IAM gap | Done, awaiting GCP | Runtime identity gained `roles/bigquery.jobUser`: without it the tariff query cannot start under a dedicated service account. |
| Reproducible BigQuery | Done, awaiting GCP | `infra/bigquery/setup_tariff.sh` creates the connection, table, remote embedding model, seed and (when large enough) index, then self-checks. No default embedding model, on purpose. |
| Model lifecycle | Done (configuration), awaiting GCP | `gemini-2.5-flash` and the embedding model are configuration; `GEMINI_LIVE_MODEL` etc. are read at deploy time. **Check retirement dates first** (GCP_VERIFICATION.md section 0). |
| Verification tooling | Done | `scripts/preflight_gcp.py` (credentials, real extraction request, BigQuery, Firestore, GCS) and `scripts/live_e2e_hosted.py` (full Case C journey + latency). |
| Accessibility defects | Done | The axe scan failed on the original code: tablist contained a button, demo badge contrast 1.59:1, a text token at 4.45:1. Fixed; the scan passes. |
| Container | Done, awaiting GCP | UI image runs as the unprivileged `node` user. |
| Dead code | **Open** | `backend/app/repo/bigquery.py`, `backend/app/domain/events.py`, `frontend/lib/sse.ts` are unused and safe to delete (nothing imports them). The assistant's attempt to delete them was blocked; the owner to remove. |
| Closing the live E2E P0 | **Open** | Needs credentials: run the runbook. |

## Phase 1: domain depth: **done** (live parts awaiting GCP; reference data awaiting your review)

| Item | Status | Notes |
|---|---|---|
| Batched extraction schema | Done, awaiting GCP | Certificates: `specification`, `heat_numbers`, `test_results` (flat `LabResult` rows). Documents: `incoterm`, `country_of_origin`, freight/insurance and their currencies. Lines: `unit_price_basis`. The Gemini schema grew about 45 %: **whether Vertex accepts it is the first thing to verify** (GCP_VERIFICATION.md, section 7). Old iterations and extractions still load. |
| Invoice arithmetic (I-001..I-003) | Done | Quantity × price = line total (a printed basis makes a mismatch MATERIAL; an unprinted basis that reconciles another way is a WARN that names it), invoice total vs lines, one currency. Closes the spec's US 3.2 "invoice totals" and the roadmap's currency claim. |
| Material engine (M-001..M-004) | Done | Alloy status under HS Chapter 72 Note 1 against the declared code; CE(IIW) / Pcm against the certificate's own standard; chemistry and strength limits; heat traceability. Independent on purpose: ASTM A106 allows 0.40 % Cr, Note 1(f) makes steel alloy at 0.30 %. |
| Case D (India import) | Done | `POST /demo/case-d`, four fixture PDFs, India tariff rows (JSON and BigQuery seed, composite key, drift-guarded), a UI button, an end-to-end test and a Playwright journey. Case C unchanged in outcome. |
| Origin and trade remedies (E-origin, SEC-001, SEC-002) | Done | Origin laundering (MATERIAL), near-threshold alloy evasion heuristic (WARN), anti-dumping applicability (always WARN: producer-specific). Deterministic: no second LLM verdict. |
| Indicative valuation | Done | CIF basis from the Incoterm, stated or statutory freight and insurance, exchange rate, India BCD/SWS/ADD/IGST, Singapore GST, the same estimate under the code the chemistry implies; every guess listed. Never changes the status. UI card. |
| Reference data | Done, **awaiting your review** | `backend/app/reference/*.json` + README checklist. All `demo-curated`; exchange rates and the anti-dumping entry are illustrative placeholders; no invented notification numbers. A broken table stops the service at start-up; iterations store a fingerprint of the tables used. |
| Live smoke test | Done | Now gates on the specification, every heat and every chemistry/strength cell. |

Not in Phase 1 (deliberate): dates on documents (an invoice date is not extracted), the Reasoning Delta does not yet narrate a
change of estimate between iterations, wall thickness is not extracted (the CE limit says so as an assumption), a government
declaration export (Phase 2).

## Phase 2: workflow: **done** (live parts awaiting GCP)

| Item | Status | Notes |
|---|---|---|
| Corrections by the authorised agent | Done | `POST /bundles/{id}/corrections` records a correction or a confirmation; `POST .../corrections/{cor-n}/revert` undoes one; `GET .../corrections` lists the history, the overlay in force and how many changes the latest assessment lacks. **The audit chain is the store** (`FIELD_CORRECTED` / `FIELD_CONFIRMED` / `CORRECTION_REVERTED`): one atomic write, so the overlay cannot disagree with the audit trail. The stored extraction is never edited. |
| Addresses, validation, anchors | Done | A closed grammar over explicit field tables (header fields, line-item fields, heat numbers, certificate cells, document type); tables pinned to the schema, the frontend's copy pinned to them. A value the engines could not read without guessing is refused (ambiguous number, weight without a unit, lab value that is not a number). Row addresses carry an anchor: found again after a re-read in another order; **skipped, never mis-applied** when the row is gone. |
| `recompute` run mode | Done | `POST /bundles/{id}/recompute`: skips preprocessing and extraction (copies the stored extraction under the new iteration), applies the corrections, re-runs discrepancy → synthesize. 409 with no assessment, or when documents were added since (use Reassess). The overlay is applied after `extract` in **every** mode, so a reassessment keeps the corrections. Iterations store `corrections` and `run_mode`. |
| Reasoning Delta | Done | Names each new (or undone) correction with the value it replaced and the reason; a status change after a recompute is attributed to the corrections. |
| Edit-in-place UI | Done | **Edit** on evidence rows (value, unit, reason; "does not state this value"; confirm as read), a Corrections card (pending / in this assessment / not used, Undo, Recompute), audit timeline detail. Weight evidence now carries its printed value and unit (it showed as a "gap" before). |
| Declaration pre-fill pack | Done | `GET /bundles/{id}/prefill` (JSON) and `/prefill.pdf`: one value per field from the best document with its source, the other documents' values, conflicts, low-confidence and finding flags, a "NOT CLEARED" banner, what the declarant must supply (curated, **unverified**: `declaration_inputs.json`), the audit head and a recomputable content hash. JSON Schema committed (`docs/schemas/`), format documented in `docs/PREFILL_PACK.md`. |
| Government format | **Not targeted** | No public official schema was confirmed for ICEGATE (India) or TradeNet (Singapore): only secondary sources describing an EDI/XML Bill of Entry message and vendor-mediated TradeNet access. Recorded with sources in `docs/PREFILL_PACK.md`. A mapping is a small separate step once a specification is in hand. |
| Runtime dependency | Done | `reportlab==5.0.1` moved from the dev tools into the runtime lock (the PDF summary); both locks regenerated. |
| Live verification | Done, awaiting GCP | `scripts/live_e2e_hosted.py --case d --corrections` corrects the chromium cell, recomputes, downloads the pack (hash recomputed from the file), undoes it. |

Not in Phase 2 (deliberate): `heat_number` / `parameter` of a certificate row and row insertion or deletion cannot be corrected (a
value or unit can); the Reasoning Delta does not narrate a change of duty estimate; no user authentication, so the audit actor of a
correction is the literal `user`; recompute is a normal write-path run on this one instance (Phase 3 lifts that); the pre-fill is not
a government format.

## Phase 3: scale and integrity: **done** (live parts awaiting GCP)

Design: [SCALING_AND_INTEGRITY.md](SCALING_AND_INTEGRITY.md). Locally proven; the live parts are
[GCP_VERIFICATION.md](GCP_VERIFICATION.md) sections 9 to 11.

| Item | Status | Notes |
|---|---|---|
| Lease per bundle | Done, awaiting GCP | `bundles/{id}/control/lease`: claimed atomically across instances (twelve contenders, one winner), with a **fence** that counts executions. Pure decision functions shared by the in-memory and Firestore stores; Firestore path tested on a fake with real optimistic-transaction semantics. |
| Fenced writes | Done, awaiting GCP | The iteration (plus bundle status) and the terminal state (plus lease release) are transactions that read the lease first: a stale executor cannot write. Heartbeat extends the lease; a lost lease stops the run. |
| Reaping across instances | Done | An expired lease is deleted and returned to exactly one caller, which marks the run failed and audits it once. Legacy RUNNING records still reap by timestamp. |
| Cloud Tasks dispatch | Done, awaiting GCP | `RUN_DISPATCH=cloudtasks`: a QUEUED lease, one task per run, a worker endpoint that runs the pipeline inside its request (scale-in cannot kill it), at-least-once safe (busy / take-over / obsolete / done). Verified OIDC token, only the tasks account. Default stays `local`. |
| Service-wide run cap | Done (by design) | The queue's `max-concurrent-dispatches`; a run beyond it waits QUEUED. `MAX_CONCURRENT_RUNS` stays the per-process cap for local dispatch. |
| Shared rate limits | Done, awaiting GCP | `RATE_LIMIT_BACKEND=firestore`: counted in a transaction, shared by all instances, client hashed, TTL field; falls back to the in-process limiter when Firestore is down or slow. |
| Infra | Done, awaiting GCP | `infra/tasks/setup_queue.sh`, `infra/firestore/setup_ttl.sh`, `infra/kms/setup_signing_key.sh`; `deploy_api.sh` takes `RUN_DISPATCH`, `MAX_INSTANCES`, `TASKS_SERVICE_ACCOUNT`, `SIGNING_KEY_VERSION` (refuses a scale-out without Cloud Tasks); IAM manifest and Firestore rules updated. |
| Emulator concurrency tests | Written, **not run** | `backend/tests/emulator/` (skipped unless `FIRESTORE_EMULATOR_HOST` is set): real `async_transactional`, real contention. |
| KMS audit signing | Done, awaiting GCP | The chain head is signed after each completed assessment (ECDSA P-256) and the signature is an `AUDIT_HEAD_SIGNED` event; verified against the KMS public key; every rewrite attack tested; `POST /audit/sign`; UI badge ("tamper-evident under the operator's key", never non-repudiation). Demo signs with a labelled throwaway key. |
| Preprocessing: deskew | Done, **off by default** | Projection-profile skew estimate; reversible, aspect-aware affine composed with the orientation rotation; the viewer maps boxes through it (golden vectors shared with the frontend); a skew outside 0.3 to 10 degrees is left alone. |
| Preprocessing: orientation | Done | Rewritten: axis first (judged at every small tilt, so a crooked scan is not read as sideways), then polarity. Sideways pages are turned through every degradation; an upside-down page only when clearly bottom-heavy. |
| Preprocessing: grayscale A/B | Done (tooling), awaiting GCP | `PAGE_IMAGE_MODE=bw|gray`; `live_smoke_extraction.py --page-mode/--deskew/--as-fixtures`, `make_degraded_scans.py`, `compare_smoke_reports.py`. **The A/B result decides the defaults; it needs the real model.** |
| Persisted processed pages | Done | The page image the model was shown is stored and served (`GET .../documents/{id}/pages/{n}`); the viewer links to it. |
| Degraded-scan corpus | Done | `backend/tests/support/scans.py`: seeded, deterministic; used by 52 deskew / orientation tests. |
| Smoke test gap (found) | Fixed | `live_smoke_extraction.py` graded only Case C files; the Case D certificate was extracted but never gated. Both fixture folders are graded now. |

Not in Phase 3 (deliberate): the SSE wake-up and the per-bundle document count stay process-local (documented); no OCR, so an
upside-down page is only turned on a strong signal; no automatic choice between grayscale and 1-bit (the A/B on the real model
decides); the audit actor is still the literal `user` (no authentication).

## Phase 4: pitch: **done** (the live measurements await GCP)

Documents: [CLAIMS.md](CLAIMS.md) (the register), [MEASURED_RESULTS.md](MEASURED_RESULTS.md) (generated), [REDTEAM.md](REDTEAM.md), [DEMO_SCRIPT.md](DEMO_SCRIPT.md).

| Item | Status | Notes |
|---|---|---|
| Claim audit | Done | `docs/CLAIMS.md`: every claim labelled PROVEN / STUBBED / ASSUMED / DELETED with its evidence; a test (`backend/tests/unit/test_claims.py`) checks that evidence exists, scans the README, Product.md, FAQ, runbooks and UI copy for invented statistics, superlatives and unmeasured latencies, keeps the deleted claims out, and moves a label only with the data. The audit found and fixed five stale documents (written before Phase 3), a skew-accuracy figure the tests did not support, a recompute time nobody had measured, and the word "adjudicator". |
| Measured numbers | Tooling done, **live numbers awaiting GCP** | `scripts/measured_results.py ingest|render` turns raw `live_e2e_hosted.py` / `live_smoke_extraction.py` reports into sanitized files in `docs/measurements/` and the generated `docs/MEASURED_RESULTS.md` (a test fails if the page is not what the data renders to). It will not offer a demo-mode run as the product's latency, shows a pass rate beside every latency, counts failed runs and keeps them out of the timings, gives a p95 only from 20 runs, and lists what has not been measured. Ten demo-mode runs of Case C, Case D and Case D with corrections are recorded (all 10 of 10; not quotable). |
| Red-team | Done | `docs/REDTEAM.md`: deliverables inventory, a clean-clone gate (only the files git would ship, a fresh environment: passed), a live walk (10 defects found and fixed, among them: the UI could not create an India-destination bundle in live mode, so the India journey could not be run from the browser), pitch defense, judge's-eye score, fix list. |
| Fallback demo | Done (demo mode); live and video need the owner | `scripts/record_demo.sh` records a captioned walkthrough (Case C, Case D, correction + recompute, pre-fill, signed audit trail) as video, stills and a manifest; `--live <url>` records a deployed stack; `docs/DEMO_SCRIPT.md` has the talk track and the four-rung fallback ladder. Stills and manifest were recorded in demo mode; the video needs Playwright's ffmpeg (`npx playwright install ffmpeg`). |
| Product changes found by the red-team | Done | A destination selector on the home page (and "To IN" in the top bar) so a live stack can run the India import; the viewer opens the document the first material finding is about; the Reasoning Delta names a correction as "certificate cell 21 of case_d_mtc_test_cert.pdf" with statuses in words; "Lowest reported confidence" instead of "Extraction Confidence". |
| Measurement tool bugs found | Fixed | The recompute after an undo overwrote the first recompute's time and status in the report; the summary printed a "p95" of ten runs (it was the maximum). Recomputes are reported apart (`recompute`, `recompute_after_undo`) and a p95 needs 20 runs. |

Not in Phase 4 (deliberate): a slide deck, a cover image, a written description and an architecture diagram (the owner decides which the submission needs); a live recording and live
numbers (they need the deployed stack: `docs/GCP_VERIFICATION.md` section 12); authentication; a model comparison.

## Still out of scope

Government portal auto-filing; payment; authentication/SSO (the audit `actor` is the literal string "user"); a batch API for 50+ document containers.
