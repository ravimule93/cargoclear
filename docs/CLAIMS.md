# Claim register

What CargoClear may say about itself, and on what evidence. Written for the `claim-audit` rule: **no performance claim without a
measured number behind it, no factual claim without a source, and an unlabeled claim is a defect.** Every claim has exactly one label:

* **PROVEN**: reproduced from a clean state, with the evidence named (a test that fails if it stops being true, a measurement in
  [MEASURED_RESULTS.md](MEASURED_RESULTS.md), or a cited source).
* **STUBBED**: built and tested against a fake or in demo mode, **not** verified end to end where it matters. Say so wherever it is claimed.
* **ASSUMED**: believed, not checked. Verify it, delete it, or label it visibly. It is never to be stated as a fact.
* **DELETED**: a claim that was made (or was in a draft) and is no longer made. Kept here so it does not come back.

`backend/tests/unit/test_claims.py` keeps this page honest: every PROVEN row must name evidence that exists, the outward-facing files
(README, Product.md, the FAQ, the UI) are scanned for the phrases a judge punctures (invented statistics, superlatives, unmeasured
latencies), the deleted claims are checked absent, and the counts below must match the table.

```
CLAIM AUDIT — CargoClear-JAPAC (README, Product.md, docs/, UI copy) — 2026-10-14
PROVEN: 28 | STUBBED: 9 | ASSUMED: 12 | DELETED: 8
Blocking (must fix before ship): none open. Fixed in this audit: five documents that still said deskew is not applied and the API
  must stay single-instance (stale after Phase 3); "about 0.1 degree" skew accuracy (tests asserted 0.3; measured 0.05 on synthetic
  pages, now pinned); "the run takes about a second" for a recompute (measured tens of milliseconds in demo mode, unmeasured live);
  the word "adjudicator" in the UI title and API description (the product is decision support); a measurement tool that overwrote the
  first recompute with the second.
Non-blocking: the live-dependent rows below stay STUBBED until the hosted runs are ingested (docs/GCP_VERIFICATION.md section 12).
  C-56 (the prompt-injection guard) was run live on the shipped schema on both models: exploratory, near-duplicate runs, eleven
  cells of one bundle, one attempt per guard-aware attack (it got through on gemini-2.5-flash: 4 of 165 runs), and it is not on the
  measurements page (docs/INJECTION_TEST.md). C-53 had said "no explicit guard"
  and "ASSUMED": a one-sentence guard existed, and the claim itself was false in that run, so it is DELETED.
Verdict: FIX-THEN-SHIP, where "fix" = the live measurements. Everything that can be proven without Google Cloud is. The product may be
  shown with the wording in the last column; nothing marked STUBBED or ASSUMED may be stated as a fact.
```

## 1. What the product is and is not

| ID | Claim | Label | Evidence | How to say it |
|---|---|---|---|---|
| C-01 | It is decision support: nothing is submitted to a government system, nothing is a legal determination, no duty is collected or paid. | PROVEN | `backend/tests/unit/test_claims.py::test_the_backend_has_no_outbound_http_client_and_no_route_files_or_pays` | "Decision support for the authorised agent." Never "files", "clears" or "approves". |
| C-02 | The model only reads documents. Statuses, limits, the alloy test and the duty estimate come from deterministic code and curated tables. | PROVEN | `backend/tests/unit/test_gemini_request_schema.py`, `backend/tests/unit/gemini_request_schema_snapshot.json`, `backend/tests/unit/test_calculation.py`, `backend/tests/unit/test_metallurgy.py` | "The model reads; rules decide." The request schema the model is given has no verdict, limit or duty field. |
| C-03 | A result that rests on an assumption is a warning, never a pass. | PROVEN | `backend/tests/unit/test_metallurgy.py`, `backend/tests/unit/test_invoice_checks.py`, `backend/tests/unit/test_valuation.py` | "Assumptions are listed and downgrade the result." |
| C-04 | The rule tables (alloy thresholds, standards' limits, duty rates, exchange rates, the anti-dumping entry, declaration inputs) are demo-curated, unverified, and partly placeholders. | PROVEN | `backend/tests/unit/test_reference_data.py`, `backend/app/reference/README.md` | Say it every time a rate, limit or duty figure is shown. |
| C-05 | The demo extraction is synthetic and keyed by file name; it does not read the sample PDFs. | PROVEN | `backend/tests/unit/test_data_source.py`, `frontend/tests/hero_journey.spec.ts` | The demo banner says so on every demo screen; so must any recording. |

## 2. The checks and the journeys

| ID | Claim | Label | Evidence | How to say it |
|---|---|---|---|---|
| C-06 | Case C (demo mode): three documents give `MISSING_EVIDENCE` with the certificate requirement; adding the certificate reassesses to `COMPLIANT_FOR_SUBMISSION` with a Reasoning Delta naming it. | PROVEN | `backend/tests/integration/test_case_c_e2e.py`, `frontend/tests/hero_journey.spec.ts`, `docs/measurements/20261013-e2e-local-demo-case-c.json` | "In demo mode (synthetic extraction): 10 of 10 runs." Not a statement about reading real documents. |
| C-07 | Case D (demo mode): the certificate's 0.35 % chromium contradicts the declared non-alloy code (`MATERIAL_CONTRADICTION`), with an anti-dumping warning and an indicative duty estimate. | PROVEN | `backend/tests/integration/test_case_d_e2e.py`, `frontend/tests/case_d_journey.spec.ts`, `docs/measurements/20261013-e2e-local-demo-case-d.json` | Same wording as C-06. |
| C-08 | On the live stack, with Gemini reading the PDFs, Cases C and D reach the same statuses. | STUBBED | `scripts/live_e2e_hosted.py`, `backend/tests/unit/test_live_e2e_script.py`; no live run is recorded in `docs/MEASURED_RESULTS.md` | Do not claim it. After `--case c|d --runs 10 --expect-mode live` is ingested: "N of 10 live runs reached the expected status." |
| C-09 | Gemini reads the synthetic certificate table (every heat and every chemistry/strength cell) correctly. | PROVEN | `docs/measurements/20261014T113751-extraction-smoke-8docs-x3-full-schema.json` and `docs/measurements/20261014T115212-extraction-smoke-8docs-x1-replacement-model.json`, quoted on `docs/MEASURED_RESULTS.md`; graded by `scripts/live_smoke_extraction.py` | "On the two synthetic rendered certificates (text PDFs, not scans), gemini-2.5-flash read every heat and every chemistry and strength cell correctly in every run (3 per certificate), and gemini-3.5-flash in its single run of each." Always with "synthetic, rendered, not scans" (C-37). |
| C-10 | The Chapter 72 Note 1(f) threshold for chromium is 0.3 % by weight (at 0.3 % or more, a steel that is not stainless is "other alloy steel"). | PROVEN | [CBSA Customs Tariff, Chapter 72](https://cbsa-asfc.gc.ca/trade-commerce/tariff-tarif/2024/html/00/ch72-eng.html), [USITC HTS archive, Chapter 72](https://usitc.gov/tata/hts/archive/9010/c72.pdf) (checked 2026-10-14) | "Per the HS Chapter 72 notes (checked against the Canadian and US editions)." The product's table is demo-curated (C-04). |
| C-11 | ASTM A106 Grade B allows up to 0.40 % chromium, so a certificate can satisfy its standard and still contradict a non-alloy code. | PROVEN | [Project Materials: A106 Grade B](https://www.blog.projectmaterials.com/quick-answers/pipes/what-is-astm-a106-grade-b/), [HB Steel: A106 B vs A53 B](https://blog.hb-steel.com/astm-a106-grade-b-vs-a53-grade-b-chemical-composition-and-weldability-compared), [Total Materia](https://www.totalmateria.com/en-us/material/1260067) (secondary sources, checked 2026-10-14) | "Published summaries of ASTM A106 give 0.40 % maximum chromium." The standard itself is paywalled and was not read. |
| C-12 | Invoice arithmetic (quantity x price, totals, one currency), weights, HS consistency, entity alignment, origin consistency, certificate chemistry/CE/limits/heat traceability, near-threshold and anti-dumping flags are checked deterministically. | PROVEN | `backend/tests/unit/test_invoice_checks.py`, `backend/tests/unit/test_weight_rules.py`, `backend/tests/unit/test_hs_rules.py`, `backend/tests/unit/test_calculation.py`, `backend/tests/unit/test_metallurgy.py`, `backend/tests/unit/test_trade_remedies.py` | List the check ids (W-, H-, E-, I-, M-, SEC-). "Checked against the curated tables" (C-04). |
| C-13 | The duty estimate is indicative: it never changes the status, never claims to be payable, and lists every assumption. | PROVEN | `backend/tests/unit/test_valuation.py::test_the_estimate_never_exceeds_what_it_claims_to_be` | "Indicative estimate with its assumptions." Never "duty payable", never a figure without "illustrative rates". |
| C-14 | The duty estimate's amounts are correct for a real shipment. | ASSUMED | none: the rates, the exchange rate and the anti-dumping entry are placeholders (C-04) | Not claimed. Becomes possible only after the reviewer verifies the tables. |
| C-15 | Anti-dumping findings are always a warning, because the rate and scope are producer-specific. | PROVEN | `backend/tests/unit/test_trade_remedies.py` | As stated. |
| C-16 | Evidence boxes shown on the PDF are where the value is printed. | STUBBED | geometry is proven (C-33); the model's own boxes were measured live (`docs/MEASURED_RESULTS.md`, "box overlap"): every populated field carried a box, and the mean overlap with the printed value's box was well under half on the synthetic pages | "Boxes are mapped back onto the original page exactly; the model's own boxes overlap the printed value only partly (see the table on the measurements page)." Never "exactly where the value is printed". |

## 3. Corrections and the declaration pre-fill

| ID | Claim | Label | Evidence | How to say it |
|---|---|---|---|---|
| C-17 | A correction is an audited, reversible entry; nothing changes until Recompute; a correction whose row is gone is skipped, never applied to the wrong row; a value the engines could not read without guessing is refused. | PROVEN | `backend/tests/unit/test_corrections_domain.py`, `backend/tests/integration/test_corrections_e2e.py::test_what_cannot_be_corrected_is_refused_with_a_reason_and_records_nothing` | "The agent states what the document says; the product records it and re-checks." |
| C-18 | A recompute reads no document and calls no model. | PROVEN | `backend/tests/integration/test_corrections_e2e.py::test_a_recompute_reads_no_document_and_runs_no_extraction_but_a_reassessment_does` | As stated. |
| C-19 | A recompute is fast. | STUBBED | `docs/measurements/20261013-e2e-local-demo-case-d-corrections.json` (demo mode: milliseconds); no live number | In demo: the measured milliseconds, labelled demo. Live: after ingest. Never "instant" or a number from memory. |
| C-20 | The pre-fill pack gives each value with its source document and page, the other documents' values, conflicts and flags, leads with `NOT CLEARED` when the bundle is not cleared, and carries a hash anyone can recompute. | PROVEN | `backend/tests/unit/test_prefill.py`, `backend/tests/unit/test_prefill_schema.py`, `backend/tests/integration/test_prefill_e2e.py`, `docs/schemas/declaration-prefill.schema.json` | "CargoClear's own documented format; not a government format; never ready to file." |
| C-21 | The pre-fill pack matches ICEGATE's or TradeNet's format. | DELETED | no official public schema was found (`docs/PREFILL_PACK.md`, sources dated 2026-10-14) | Not claimed. |

## 4. Integrity and scale

| ID | Claim | Label | Evidence | How to say it |
|---|---|---|---|---|
| C-22 | Editing an audit event breaks the hash chain and the UI says so. | PROVEN | `backend/tests/unit/test_audit_chain.py::test_audit_chain_detects_tampered_payload` | "Tamper-evident." |
| C-23 | A history rewritten consistently (every hash recomputed) is still caught by the signature over the chain head, when the head is signed with a KMS key. A demo signature (a throwaway key held by one process) is checked only against that key, never against a key written into the event, and is refused in live mode or when a KMS key is configured. | PROVEN | `backend/tests/unit/test_signing.py::test_a_history_rewritten_consistently_is_caught_by_the_signature`, `backend/tests/unit/test_signing.py::test_a_demo_signature_with_the_attackers_own_key_is_not_a_valid_signature`, `backend/tests/unit/test_signing.py::test_a_demo_signature_is_refused_where_only_kms_signatures_count` | "Tamper-evident under the operator's key." In demo mode the key is a labelled throwaway that proves only that the chain was not edited after it was signed; the claim in full needs the KMS key (C-24). |
| C-24 | The head is signed with a real Cloud KMS key and verifies under the key's public half. | STUBBED | `backend/tests/unit/test_signing.py::test_a_kms_signature_is_requested_with_integrity_checks_and_verifies_under_the_kms_public_key` uses a fake KMS | Say "KMS signing is built and unit-tested against a fake KMS". After `live_e2e_hosted.py --expect-signer kms` passes: proven. |
| C-25 | The audit trail gives legal non-repudiation. | DELETED | there is no user authentication: the signer is the service, not a person (`docs/SCALING_AND_INTEGRITY.md`, section 3) | Never say it. |
| C-26 | Two instances cannot analyse one bundle; a paused executor cannot overwrite a newer run; a dead executor's run is taken over. | STUBBED | `backend/tests/unit/test_leases.py`, `backend/tests/unit/test_run_leases.py` (in-memory store and a Firestore-like fake with optimistic transactions); `backend/tests/emulator/test_firestore_emulator.py` was written and never run | "Designed and tested on a faithful fake; not yet run on Firestore." |
| C-27 | Cloud Tasks delivers each run to a worker that executes it, safely under at-least-once delivery. | STUBBED | `backend/tests/unit/test_run_queue.py`, `backend/tests/unit/test_internal_worker.py` (task shape, token checks, answers) | As C-26. Default stays one instance. |
| C-28 | Rate limits are shared by all instances. | STUBBED | `backend/tests/unit/test_shared_rate_limit.py` (two limiters over one fake store) | As C-26. |
| C-29 | CargoClear scales to N instances / handles N concurrent bundles / N documents per hour. | ASSUMED | no load test exists anywhere | Never state a throughput or scale number. |
| C-30 | The API is private; only the UI's service account may call it, with an ID token the proxy attaches. | STUBBED | `backend/tests/unit/test_deployment_contract.py`, `frontend/tests/proxy.unit.spec.ts`, `infra/deploy_api.sh`; the API was deployed privately on 2026-10-13 but the UI was not, so the full path has not run | "Configured and tested statically." |
| C-31 | Storage, database and model are in `asia-south1` (Mumbai) by default. | PROVEN | `infra/deploy_api.sh` (`REGION` default), `backend/app/core/config.py` | "Defaults to asia-south1." Not a compliance statement. |
| C-32 | The deployment meets MeitY data-residency rules and uses customer-managed encryption keys (CMEK). | ASSUMED | no CMEK is configured anywhere in `infra/`; "MeitY-empanelled" is an unsourced statement in the 4.0 spec | Not claimed. The spec states it as an intent (see section 6). |

## 5. Pages, geometry and accessibility

| ID | Claim | Label | Evidence | How to say it |
|---|---|---|---|---|
| C-33 | An evidence box on a processed page maps back onto the original page within 0.4 % of the page, through straightening and a sideways feed, on a non-square page. | PROVEN | `backend/tests/unit/test_deskew.py`, `frontend/tests/transform-bbox.unit.spec.ts` | "Exact geometry on synthetic pages." |
| C-34 | The skew estimate is within 0.05 degree of the true tilt (the search grid is 0.1 degree) on the synthetic pages, through noise, blur, fading, JPEG artifacts and uneven light. | PROVEN | `backend/tests/unit/test_deskew.py::test_the_skew_is_found_to_the_nearest_tenth_of_a_degree_on_the_synthetic_corpus` | Always with "synthetic pages". On real scans it is unmeasured (C-37). |
| C-35 | A sideways page is turned (even a crooked one); an upside-down page is turned only when clearly bottom-heavy. | PROVEN | `backend/tests/unit/test_deskew.py`, `backend/tests/unit/test_preprocess.py` | Include the limit: no OCR, so upside-down is not reliably detected. |
| C-36 | The page image the model was shown is kept and viewable. | PROVEN | `backend/tests/unit/test_processed_pages.py`, `frontend/tests/preprocessing_journey.spec.ts` | "What the model saw." |
| C-37 | Grayscale input or straightening improves extraction on real scans; the product works on skewed, stamped, low-quality real-world PDFs. | ASSUMED | the A/B is tooled (`scripts/make_degraded_scans.py`, `scripts/compare_smoke_reports.py`) and not run; nothing was run on a real scan | Not claimed. Both switches are off by default for this reason. |
| C-38 | The main workbench screen has no critical or serious automated accessibility violation (WCAG 2.2 AA rule set) and its shell is reachable by keyboard. | PROVEN | `frontend/tests/a11y.spec.ts` | "Passes an automated axe scan on the Case C screen." Automated scans do not prove full accessibility. |

## 6. Numbers and phrases from the original pitch and spec

| ID | Claim | Label | Evidence | How to say it |
|---|---|---|---|---|
| C-39 | "Orphan imports are 8.9 % of global import declarations; lost exports 5.6 %" (spec section 1). | ASSUMED | unsourced | Do not use without a source. |
| C-40 | "CHAs run 3 to 6 % net margins; a 3-day hold turns $150 profit on a $3,000 container into a $300 loss through $450 demurrage" (spec). | ASSUMED | unsourced; illustrative arithmetic | Use only as "for illustration", never as a statistic. |
| C-41 | "Reduces pre-submission audit time from hours to minutes." | ASSUMED | machine time is measurable (MEASURED_RESULTS.md); a CHA's time was never measured, and there is no baseline study | Do not claim. Say what was measured: the machine's time, with its mode and run count. |
| C-42 | "End-to-end analysis of a typical bundle takes under 45 seconds." | ASSUMED | a design target (spec); demo mode takes about 1 to 2 seconds because no model is called, so it proves nothing about the live product | Not claimed. After the hosted Case C runs are ingested, quote the measured median and slowest, with the run count. |
| C-43 | "Zero-hallucination grounding." | DELETED | the model still reads documents; grounding limits what the tariff lookup may return (`backend/tests/unit/test_grounding_policy.py`) but no accuracy of reading is claimed | Say "grounded against the tariff table", not "zero hallucination". |
| C-44 | "$42B market", "80 % of paperwork", "world's first", "files fraud faithfully", "45 seconds" as an achieved result. | DELETED | removed from README, Product.md and the UI in Phase 0; absence checked by `backend/tests/unit/test_claims.py::test_deleted_claims_do_not_come_back` | Never say any of these. |
| C-45 | "Adversarial customs adjudicator" (UI title, API description, spec). | DELETED | the product does not adjudicate: the authorised agent decides. UI and API wording changed in this audit; the spec carries a status note | "Pre-submission customs document assessment." |
| C-46 | "Real-world skewed / stamped / low-quality PDFs with no brittle OCR templates" (spec value proposition). | ASSUMED | only synthetic rendered PDFs were used (C-37) | Intent, not a result. |
| C-47 | "Respects MeitY residency and CMEK." | DELETED | see C-32 | Not claimed. |
| C-48 | "Higher ASW / ATIGA utilisation", "immediate economic ROI" (spec). | ASSUMED | no study; no user was observed | Not claimed. |

## 7. Counts and runs

| ID | Claim | Label | Evidence | How to say it |
|---|---|---|---|---|
| C-49 | The automated suite passes: backend unit and integration tests, frontend type check, lint, build, unit specs and 18 browser journeys. | PROVEN | run on 2026-10-14: `cd backend && .venv/bin/python -m pytest tests/unit tests/integration -p no:cacheprovider -o addopts='' -q`; `cd frontend && npm run typecheck && npm run lint && npm run test:unit && npm run build && npm test` | Give the date and the command. Counts drift: keep them out of the README. |
| C-50 | The current code passes the same suite in Cloud Build's clean container. | ASSUMED | `cloudbuild.yaml` runs the backend tests and the frontend lint, type check and build before it builds images; it last ran on 2026-10-13, on a revision before Phases 2 and 3 | Not claimed for the current code until it is re-run (`gcloud builds submit`, run by someone with access). |
| C-51 | The confidence percentage in the workbench is how accurate the reading is. | DELETED | it is the lowest confidence the model reported for the values the checks rest on (`backend/app/services/confidence.py`); the UI now says "Lowest reported confidence" with an explanation | "A self-reported score, not a measured accuracy." |
| C-52 | Customer documents are private to the user who uploaded them. | ASSUMED | there is no authentication; a bundle is reachable by anyone who has its address (`bnd-` plus 12 random hex digits, `backend/app/api/v1/bundles.py`), and the UI is the only public service | Not claimed. "No user authentication in this MVP." |
| C-53 | Text inside a document cannot steer the system (prompt injection). | DELETED | it can: in the live test a visible instruction on a synthetic certificate changed the chromium reading, the confidence the model reported and so the engine's verdict, under the prompt as it was (`docs/INJECTION_TEST.md`). The guard of C-55 reduced it in that test (C-56) and does not remove the class | Never say it. Say what the architecture does: the verdicts come from deterministic code over what was read, so a changed reading changes the verdict; the prompt carries a guard (C-55) and it held in an exploratory test (C-56). Not "immune". |
| C-54 | A clean copy of the files git would ship (tracked and not ignored) installs from its lock files, passes the backend suite and the frontend type check, lint, unit specs and production build. | PROVEN | run on 2026-10-14, see `docs/REDTEAM.md` section 2 for the commands and results | Give the date; it covers the working tree as of that run. |
| C-55 | The extraction prompt carries an explicit guard against instructions printed on a document: a security paragraph at the end of the system instruction and a reminder in the turn that follows the page images. | PROVEN | `backend/tests/unit/test_extraction_prompt.py::test_the_injection_guard_is_in_the_system_instruction_and_after_the_page`, `backend/app/agents/extraction.py` | "The guard text is in every request." It says nothing about whether the guard works: that is C-56. |
| C-56 | With that guard, injected instructions did not change what the model read, except against an attacker who has read the guard. | STUBBED | exploratory live runs on 2026-10-14, `docs/INJECTION_TEST.md`: `scripts/live_injection_test.py`, `scripts/make_injection_docs.py` (tested against a fake model in `backend/tests/unit/test_live_injection_script.py` and `backend/tests/unit/test_make_injection_docs.py`); shipped schema and prompt, gemini-2.5-flash and gemini-3.5-flash, eleven cells on the certificate, the invoice and the bill of lading (four variants each) and six variants on the chromium cell, then five guard-aware variants on all eleven cells (165 runs per arm), 3 near-duplicate runs per document, the authors' own attacks; not in `docs/MEASURED_RESULTS.md` | "In an exploratory live test on synthetic documents (eleven cells, three runs per document, both models) the guarded prompt read the printed value in every run of attacks written without knowledge of the guard. With only the original one-sentence guard gemini-2.5-flash was steered in 41 of 132 runs (in each of two runs of the test), mostly on the certificate's table cells; gemini-3.5-flash held either way. **Against five attacks written after reading the guard, the guarded prompt was steered in 4 of 165 runs on gemini-2.5-flash** (the bill of lading's freight, which changes silently, and its gross weight; all from one variant that combines a forged second cell with text that imitates the guard) and in 0 of 165 on gemini-3.5-flash." Reported confidence does not flag a steered reading, a cell printed once and not checked (the specification, the freight) changes silently, and two different readings of one certificate cell are not flagged (the first is kept). One bundle, one attempt per attacker. Never "injection-proof". |
| C-57 | The extraction response schema is accepted by gemini-2.5-flash and gemini-3.5-flash in asia-south1. | PROVEN | `docs/measurements/20261014T113751-extraction-smoke-8docs-x3-full-schema.json`, `docs/measurements/20261014T115212-extraction-smoke-8docs-x1-replacement-model.json`; the tripwire `backend/tests/unit/test_gemini_request_schema.py::test_the_schema_stays_far_below_the_size_and_shape_gemini_refused` | "Accepted by both models on 2026-10-14; the earlier nested schema was refused." Re-check any other model or region with `scripts/preflight_gcp.py`. gemini-3.5-flash also needs `GEMINI_THINKING_BUDGET=-1` (it refuses 0): `docs/measurements/20261014T115012-extraction-smoke-8docs-x1-replacement-model-default-config.json`. |

## 8. The six fabrication vectors, walked

1. **Frozen or stale feeds.** There is no feed. The only time-dependent input is the exchange rate, a labelled placeholder. *Clear.*
2. **Cached or hardcoded outputs.** Demo mode **is** hardcoded extraction by design, and says so in the banner, the docs and C-05; its
   statuses are real engine output over those values. A clean clone reproduces every PROVEN row with the commands in C-49. The
   measurement files are raw run output, sanitized, and the page that quotes them is regenerated from them by a test. *Clear, because declared.*
3. **Non-isolated test states.** The fixtures are rendered text, not scans; one test machine; one process. Every measurement says "demo"
   or "live", the run count and the corpus. A demo-mode timing cannot be turned into a sentence by the generator. *Clear, with the limits stated.*
4. **Invented third-party descriptions.** Checked this audit: HS Note 1(f) and ASTM A106 (C-10, C-11, cited). ICEGATE and TradeNet: only
   secondary sources exist, and the pack says it is not their format (C-21). The spec's "MeitY-empanelled", "ASW" and "ATIGA" statements are
   unsourced (C-32, C-48). *Open for the spec only; none of it is in user-facing copy.*
5. **Hand-drawn or unsourced data.** The rule tables are unsourced by their own label (C-04); the spec's market statistics are unsourced
   (C-39, C-40). *Contained: labelled in the product, absent from the README and UI.*
6. **Survivor framing.** Failed runs are counted beside every latency and kept out of the timings, never silently dropped; a p95 needs 20
   runs; the "not yet measured" list is generated. A negative result (a deskew that does not help, a failed live run) is recorded the same way. *Clear.*

## 9. Rules for anyone editing a document

* A number about speed, accuracy, scale or savings goes into `docs/measurements/` (via `scripts/measured_results.py ingest`) and is
  quoted from `docs/MEASURED_RESULTS.md`, or it does not go in. `test_claims.py` fails on the phrases that usually carry such numbers.
* A fact about a law, a standard or a third-party system needs a link and a date here, or a label of ASSUMED and no appearance in
  user-facing text.
* When a STUBBED row becomes PROVEN, change the row **and** name the evidence file; the test checks it exists.
* Do not upgrade a row because it "should work". The failure this page exists to prevent is a claim that quietly moves from ASSUMED to PROVEN between drafts.
