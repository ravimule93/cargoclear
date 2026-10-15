# Red-team pass (Phase 4)

An adversarial read of CargoClear as a skeptical judge would take it, following the `submission-redteam` phases: deliverables, clean
clone, live walk, claim audit, pitch defense, judge's-eye score. Date: 2026-10-14. Rubric: the one in the specification (Technical Merit
and Gen AI implementation 40 %, Problem Alignment and Impact 25 %, Innovation and Creativity 25 %, User Experience and Solution Design 10 %).

```
SUBMISSION RED-TEAM — CargoClear-JAPAC — no deadline set
Inventory gaps: 5 | Live-walk defects: 10 found, 10 fixed, 1 design choice kept | Claim-audit verdict: FIX-THEN-SHIP (docs/CLAIMS.md)
Pitch-defense open: a model comparison ("why Gemini"), a stronger guard-aware injection attack (one was tried and got through on gemini-2.5-flash: C-56), anything that needs the live stack
Judge score estimate: see section 5 (an estimate by the author of this audit, not a prediction)
Highest-severity risk: the hosted end-to-end runs have not been done and the UI is not deployed (Gemini reading the synthetic fixtures is measured live since 2026-10-14: C-09, C-57)
Verdict: FIX-LIST-THEN-SUBMIT
```

## 1. Deliverables inventory

The submission card was not available to this audit: "Required?" is therefore a question for the person who has it, not a finding.

| Deliverable | Required? | Exists? | Owner | Verified live? |
|---|---|---|---|---|
| Source repository with README and setup | confirm | yes: README, `docs/HOW_TO_RUN_AND_DEMO.md`; Apache-2.0 `LICENSE` | user | clean-clone run: section 2 |
| Working app at a URL | confirm | **no**: the API was deployed privately on 2026-10-13, the UI was not (it needs a dedicated UI service account); the deployed revision predates Phases 2 and 3 | user + teammate | no |
| Demo video | confirm | **partly**: `scripts/record_demo.sh` records a captioned walkthrough; the stills and manifest were recorded in demo mode; the `.webm` needs Playwright's ffmpeg (a download not made without asking) and a live recording needs the deployed stack | user | demo mode: yes; live: no |
| Slide deck | confirm | **no** | user | n/a |
| Cover image / thumbnail | confirm | **no** (the stills in `demo-recordings/` can supply one) | user | n/a |
| Written project description | confirm | **no** as a single page; README, `Product.md` and `docs/CLAIMS.md` hold the content (the `submission-packager` skill can draft it from the register) | user | n/a |
| Architecture diagram | confirm | **no** in the README; the 4.0 specification has one (historical) | user | n/a |
| Measured numbers | for any quantitative claim | demo-mode only; live pending: `docs/MEASURED_RESULTS.md` | teammate | no |
| Fallback demo | recommended | yes: ladder and script in `docs/DEMO_SCRIPT.md` | user | demo mode: yes |
| Pitch Q&A | recommended | yes: section 4 | user | n/a |
| Automated pre-screen exposure (hard-coded results) | likely | demo mode **is** hard-coded extraction, by design and disclosed (banner, README, C-05); live mode never falls back to it (`backend/tests/unit/test_live_mode_integrity.py`) | user | yes, by test |

## 2. Clean-clone gate

Only the files git would ship (tracked plus untracked-and-not-ignored, `git ls-files --cached --others --exclude-standard`, read-only) were
copied into an empty directory, a fresh Python 3.12 environment was built from `requirements-dev.txt`, and `npm ci --legacy-peer-deps`
was run from `package-lock.json`. Nothing from the working directory's ignored files (virtual environments, `node_modules`, `.next`,
generated reports, recordings) was carried over.

| Step | Result |
|---|---|
| install backend dependencies from the lock | passed |
| `pytest tests/unit tests/integration` | 2,409 passed (2 min 26 s) |
| `npm ci --legacy-peer-deps` | passed (344 files copied in all) |
| `npm run typecheck`, `npm run lint`, `npm run test:unit`, `npm run build` | passed |

Not run in the clean copy: the Playwright suite (it needs a browser, which would have to be downloaded; it was run from a scratch
copy with the machine's own Chromium: 18 of 18 passed, three runs in a row) and anything that needs Google Cloud. Cloud Build runs the same backend and
frontend steps in a clean container (`cloudbuild.yaml`); it has not been re-run since Phases 2 and 3 (C-50).

## 3. Live walk

Walked as three roles on the local demo-mode stack (the hosted stack was not available): the **authorised agent** (the primary user:
Case C, Case D, correct, recompute, pre-fill, audit), a **first-time visitor** (the home page, the demo banner, the words on screen)
and the **operator** (runbook, recorder, measurement tool). Test states isolate the variable: Case D and Case C run on fresh bundles,
and each defect below was reproduced before it was fixed and re-verified after.

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | In live mode the UI could only create a Singapore bundle (the demo buttons are demo-only), so the India-import journey, the strongest demonstration, could not be run from the browser against a live stack. | high | **Fixed**: a destination selector on the home page, the destination shown in the top bar, a browser test that creates an India bundle, uploads the four PDFs and reaches the Case D verdict (`frontend/tests/destination_journey.spec.ts`). |
| 2 | The Reasoning Delta narrated a correction as "to test_results[20] in doc-f74c9c3e83f32ccc" (machine address and id). | medium (developer jargon on a user surface) | **Fixed**: "certificate cell 21 of case_d_mtc_test_cert.pdf" (`backend/tests/unit/test_reasoning.py`). |
| 3 | The same narrative printed raw status names (`MATERIAL_CONTRADICTION`) and doubled a full stop ("Zr..."). | low | **Fixed**, tested. |
| 4 | "Extraction Confidence: 96 %" read like an accuracy. It is the lowest confidence the model reported. | medium (a number that invites the wrong question) | **Fixed**: "Lowest reported confidence", with an explanation on hover (C-51). |
| 5 | The measurement tool overwrote the first recompute's time and status with those of the recompute after the undo. | high for the measurement, none for the product | **Fixed**: two named measurements (`recompute`, `recompute_after_undo`), tested against the real app. |
| 6 | A runbook said a recompute "takes about a second". Measured in demo mode: milliseconds; unmeasured live. | medium (an unearned number) | **Fixed**: the sentence points at the measurements instead. |
| 7 | Five documents still said deskew is not applied and the API must stay single-instance, true before Phase 3. | medium (the docs contradicted the code) | **Fixed**, and guarded: `backend/tests/unit/test_claims.py` fails if those sentences return. |
| 8 | The skew estimator was documented as "about 0.1 degree" while the tests only asserted 0.3. | low | **Fixed**: measured (at most 0.05 on the synthetic pages), pinned by a test, worded with its corpus (C-34). |
| 9 | The UI title and the API description called the product an "adjudicator". It does not adjudicate. | medium (contradicts the decision-support boundary) | **Fixed** (C-45). |
| 10 | On a finished Case D bundle the viewer showed the first document in the rail (the invoice) while the finding is about the certificate. | medium (a judge sees the wrong page first) | **Fixed**: with nothing chosen, the viewer opens the document the first material finding cites last (the engines cite the declared value first, then the value that contradicts it). |
| 11 | Raw check ids (`M-001`), rule-set names and audit event types are visible. | low | **Kept, by design**: the specialist user cites them, and they are what the audit trail records. Not a defect; "confirm intent" if a reviewer disagrees. |

Not walked, because it needs the hosted stack (Gemini reading the synthetic fixtures has been run since: C-09): Gemini reading a real scan, latency end to end, the UI behind the proxy
with an ID token, KMS signing, Cloud Tasks. Each is a STUBBED row in the register.

Permission holes: there is no authentication, so there are no roles to leak between. Anyone with the UI address can create bundles; anyone
with a bundle's address can read it (C-52). That is the stated scope (`Product.md`), and the rate limits bound abuse; it is a finding, not a bug.

## 4. Pitch defense

One-breath answers, each consistent with [CLAIMS.md](CLAIMS.md). A question marked **work item** has no complete answer yet.

**Why not RAG, or a system prompt, or an off-the-shelf document API?**
Because the product is not "answer questions about documents". Extraction is the only part a model does; the verdict, the alloy test, the
limits and the duty are deterministic code over curated tables, so each result can be cited, tested and audited. A prompt cannot give a
hash-chained trail or a reproducible "0.35 % is at or above 0.30 %". (Grounding of the HS code does use embedding search over a tariff
table in BigQuery: that is the retrieval, and its result is a candidate the rules compare, not a verdict.)

**Why Gemini, and what breaks on a cheaper model?**
**Work item.** Gemini is the Google Cloud model and `GEMINI_LIVE_MODEL` is a setting, not code. Two models were run on the synthetic
fixtures (gemini-2.5-flash, which is being retired, and gemini-3.5-flash, which needs `GEMINI_THINKING_BUDGET=-1`; C-09, C-57), and no
cheaper or smaller model was, so "what breaks on a cheaper one" has no measured answer. One thing did break on both: the original nested
extraction schema was refused ("too many states"), and the answer was reshaped into lists of entries (C-57).

**What is your weakest number?**
There are no unsourced numbers left in the README, Product.md or the UI, and a test fails if one returns. The weakest *result* is that no
latency or accuracy is measured on the live stack yet: `docs/MEASURED_RESULTS.md` says so, and lists what is missing.

**What breaks first at 10x usage?**
By default one API instance with a cap on concurrent runs, so extra runs queue or are refused with a clear message, and Gemini quota and
latency come before CPU. The scale-out path (Firestore lease, Cloud Tasks, shared limits) is built and tested on a faithful fake, not on
Google Cloud, and no load test exists (C-26 to C-29). **Work item** for the teammate: the emulator tests and one live multi-instance run.

**What did you not build, and why is that a choice?**
Government filing and payment (decision support is the boundary: the agent is liable, not the tool); authentication and SSO (out of scope
for the MVP, and stated); a government declaration format (no official public schema was found: C-21); OCR (the model reads the page);
a batch API for large containers; verification of the rule tables (the reviewer's job, labelled `demo-curated` everywhere they appear).

**Is it just a wrapper around Gemini?**
No: remove the model and the deterministic engine, the corrections, the audit chain, the signatures and the pre-fill still run (demo mode
is exactly that). Remove the engine and what is left is a transcription. The product is the join of the two with evidence.

**How do you know the model read the table correctly?**
Live, we do not yet: the smoke test that grades every chemistry cell is built and not run (C-09). What protects the verdict meanwhile:
every cited value has a page and a box, confidence routing sends low-confidence readings to review, the agent can correct a cell and
recompute without a model call, and the audit trail records both the reading and the correction.

**What if your rule tables are wrong?**
They are labelled `demo-curated` and partly placeholders in the UI, the API and the docs; each check names the rule set it used; each
assessment stores a fingerprint of the tables. A reviewer verifies them (`backend/app/reference/README.md`); the product never promotes them on its own.

**What if a document contains instructions for the model?**
It can change what the model reads, and the verdict then follows the reading, so we tested it (`docs/INJECTION_TEST.md`, exploratory,
live, synthetic documents, the shipped schema, eleven cells on the certificate, the invoice and the bill of lading). With only the
original one-sentence guard, gemini-2.5-flash read the injected value instead of the printed one, at reported confidence 1.00, in 41 of
132 runs (the same total twice), mostly on the certificate's table cells; gemini-3.5-flash did not once. Most of those readings would
have been caught loudly by the engines (a limit breach, a contradicting document), but two kinds are not: a cell printed once and
checked against nothing (the specification) changes silently, and so does the freight, which moves the indicative duty estimate with
no check moving. Text hidden in the PDF never reaches the model: pages are rendered to images first. The prompt now carries a stronger
guard (C-55); with it the printed value was read in every run on both models against attacks written without knowing it (C-56). We
also wrote five attacks after reading the guard, and one of them got through: a forged second cell next to the printed one, with text in
the guard's own voice saying that cell wins. The guard let it change the reading in 4 of 165 runs on gemini-2.5-flash (the bill of
lading's freight, silently, and its gross weight) and 0 of 165 on gemini-3.5-flash; the one-sentence prompt, 17 of 165 on
gemini-2.5-flash. So it is not "immune": one bundle, one attempt per attacker, three near-duplicate runs per document. Say what was
tested, never "injection-proof". The engine now flags two different readings of one certificate cell (M-005, a warning; C-58), which closes the case where a forged
copy sits beside the printed cell and the model lists both. It does not help when the model reads only the forged value, which is
what the poisoned runs did. **Work items:** a guard rule for an amended cell next to a printed one (needs the live test again); a
consistent injection across two documents; the packing list and other document types (C-53 is DELETED; its old text
said there was no guard and that confidence routing would expose an injected value, and neither held).

**Who can see my documents?**
In this MVP anyone who has a bundle's address: there is no authentication (C-52). The demo uses synthetic documents only.

**Is the duty estimate right?**
It is an estimate with its assumptions listed, over placeholder rates and an illustrative exchange rate, and it never changes the verdict or
claims to be payable (C-13, C-14).

**Why hash-chain and sign the audit trail?**
Because whoever can write the whole collection can rewrite a hash chain consistently. A signature over the head, with a key the database
does not hold, makes that detectable. It is tamper-evident under the operator's key, and it is not legal non-repudiation: there is no user
authentication, so the signer is the service. In demo mode the key is a labelled throwaway; the real KMS path is unit-tested against a fake KMS (C-24).

**How fast is it?**
Say what is measured: in demo mode a Case C analysis takes about a second because no model is called (`MEASURED_RESULTS.md`, labelled not
quotable). The live figure is not measured yet. Do not say "under 45 seconds": that is a target from the specification (C-42).

**Does it work on real, skewed, stamped scans?**
Unknown. Everything was tested on synthetic rendered documents and synthetic degraded copies; deskew and grayscale are off by default until
the live A/B decides (C-37).

## 5. Judge's-eye score (an estimate by this audit, with its reasons)

| Criterion | Estimate | Why |
|---|---|---|
| Technical merit and Gen AI implementation (40 %) | **strong design, capped by the absence of a live run** | Deterministic engine with explicit conventions, corrections as audited events, hash chain plus signing, lease/fencing design, 2,409 passing backend tests in the clean copy, a claim register enforced by tests. Against it: nothing verified on Google Cloud since Phases 1 to 3, the model is judged only by fakes, and the scale-out is untested where it matters. A judge who asks to see Gemini reading a certificate needs rung 1 of the ladder. |
| Problem alignment and impact (25 %) | **good on domain depth, weak on quantified impact** | The contradiction (a certificate inside its own standard that still defeats the declared code) is a real, specific failure. The market and time-saving statistics from the original pitch were removed because they were unsourced, and nothing measured replaces them yet. A judge who wants a number gets "not measured", honestly. |
| Innovation and creativity (25 %) | **good** | Cross-document material check against the declared HS code, edit-in-place corrections that re-run without a model call, the declaration pre-fill with per-value provenance, a signed audit trail. The individual pieces are known techniques; the combination for this user is the point. |
| User experience and solution design (10 %) | **good, accessible, a little technical** | Evidence boxes on the original page, a plain-words Reasoning Delta, an automated accessibility scan that passes, a visible mode banner. Check ids, rule-set names and event types stay visible by design. |

## 6. Fix list, in the order that matters

1. **Run the live stack** (owner: teammate, `docs/GCP_VERIFICATION.md` sections 0 to 12) and ingest the measurements; the register's STUBBED
   rows (C-08, C-09, C-16, C-19, C-24, C-26 to C-30) move only with that evidence.
2. **Deploy the UI** (needs the dedicated UI service account), re-deploy the API from the current code, then record the live walkthrough
   (`scripts/record_demo.sh --live <url>`).
3. **Missing deliverables** (owner: user): slide deck, cover image, written description, an architecture diagram; confirm which the submission card requires.
4. **Run the Firestore emulator tests** (`backend/tests/emulator/`, never run) and Cloud Build once more (C-50).
5. **Review the rule tables** (`backend/app/reference/`), so the rates and limits can stop being labelled placeholders.
6. Open design questions: authentication (C-52); the injection test with a consistent change across two documents and on the
   packing list and other document types (C-56, `docs/INJECTION_TEST.md`); a comparison with a smaller model ("why Gemini").
7. **Flag a conflicting second reading of one certificate cell: built (M-005, C-58).** The guard-aware injection test showed that
   when the page holds two values for one heat and parameter the model returns both and the engines kept the first and said nothing,
   so whether a forged cell counted depended on the order the model listed the rows (`docs/INJECTION_TEST.md`, C-56). A WARN now
   cites both cells; the checks still read the first. Offline evidence only; a person is asked, nothing is decided. It does not
   cover the case where the model returns only the forged value: that is the guard's job.
8. Housekeeping the audit noticed: three dead files from Phase 0 (`backend/app/repo/bigquery.py`, `backend/app/domain/events.py`,
   `frontend/lib/sse.ts`) still await deletion by the owner.
