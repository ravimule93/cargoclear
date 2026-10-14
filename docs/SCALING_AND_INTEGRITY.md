# Scaling, audit signing and preprocessing (Phase 3)

How the API runs on more than one instance without two of them analysing one bundle, how the audit trail is made tamper-evident
beyond the database, and how pages are prepared for the model. Everything here was written and tested **without Google Cloud
access**: the transaction code runs on a fake client with Firestore-like optimistic transactions, and the live parts are listed in
[GCP_VERIFICATION.md](GCP_VERIFICATION.md) sections 9 to 11.

## 1. Who may run an assessment: a lease per bundle

`bundles/{id}/control/lease` (`backend/app/repo/leases.py`) exists exactly while a run is queued or running.

| Field | Meaning |
|---|---|
| `run_id`, `mode`, `iteration` | the run that holds it, how it runs, and the assessment number it will write |
| `state` | `QUEUED` (waiting for a worker) or `RUNNING` |
| `owner` | the instance executing it (empty while queued) |
| `fence` | counts the executions of this run: every acquisition, and every take-over of a dead executor, adds one |
| `expires_at` | the lease is dead once this passes; a live executor extends it every `RUN_HEARTBEAT_SECONDS` |

Every change is one atomic read-modify-write (a Firestore transaction; a plain dict update in demo mode). The decision of each
operation is a small pure function (`decide_claim`, `decide_acquire`, `decide_heartbeat`, `decide_release`, `decide_reap`) shared by
both stores, so the rules are tested once and the transaction plumbing is thin.

* **Claim** (`POST /analyze|reassess|recompute`): succeeds only if there is no lease or the lease has expired. Twelve instances
  claiming at once yield one winner and eleven 409s. An expired lease is replaced and handed back, so its dead run is marked failed
  (and audited) by exactly the caller that replaced it.
* **Fencing.** A run proves it still owns the bundle with `(run_id, fence)`. The two writes that must never be stale, the
  assessment iteration (plus the bundle's status) and the terminal state of the run (plus the release of the lease), are
  **transactions that read the lease first**. An executor that was paused past its lease and then wakes up fails its check
  (`LeaseLost`) and writes nothing. Its **failure handling is fenced too**: a take-over keeps the run id, so a stale executor that
  recorded "failed" under it would mark the new owner's healthy run failed and put a failure into the shared audit trail. It checks
  its lease first and, if it lost it, records nothing and releases nothing; only an executor that still holds its lease records its own failure.
  Between stages a cheap read of the lease stops a stale run early.
* **Reaping.** A lease that expired is deleted and returned to exactly one caller (any instance, from `start_run` or an SSE poll).
  A RUNNING run record untouched for `RUN_STALE_AFTER_SECONDS` is reaped too (a heartbeat touches both, so they agree; the record
  check also covers runs started before leases existed).

## 2. Dispatch: local or Cloud Tasks

`RUN_DISPATCH=local` (default; demo, tests, one always-on instance): the API runs the pipeline as a background task right after the
202, as before. `RUN_DISPATCH=cloudtasks` (needed for more than one instance):

1. `start_run` claims a **QUEUED** lease, writes the run record (`QUEUED`), enqueues one Cloud Task named after the run (a duplicate
   enqueue is the same task), and answers 202. If the queue refuses the task nothing stays claimed.
2. Cloud Tasks calls `POST /internal/v1/runs/{bundle}/{run}/execute` with an OIDC token of the tasks service account.
3. The worker (`orchestrator.execute_queued`) acquires the lease (QUEUED → RUNNING, fence + 1) and runs the pipeline **inside that
   request**, answering when the run has ended. A run therefore lives in an HTTP request that Cloud Run keeps alive and
   CPU-allocated: scale-in cannot kill it mid-run, and any instance can pick it up.
4. Cloud Tasks delivers at least once. The lease makes that safe:

| Delivery | Answer |
|---|---|
| the run is being executed by a live worker | `409 busy` (Cloud Tasks retries later) |
| the executor died: its lease has expired | the new worker **takes the run over** (fence + 1, the pipeline restarts; the audit shows `ANALYSIS_STARTED` again with `attempt` 2) |
| the worker failed before any stage ran (a store hiccup right after it took the lease) | it answers an error and **expires its own lease at once**, so the next delivery takes the run over instead of being told "busy" until the lease runs out; nothing is recorded as a failed run |
| the run already ended, or was reaped | `200 obsolete` (nothing to do) |
| the run failed deterministically | `200 done` (the failure is on the run; retrying it helps nobody) |

A run nobody picks up within `RUN_QUEUE_WAIT_SECONDS` is failed as interrupted. On shutdown a dispatched run is **stopped, not
failed**: its lease expires and Cloud Tasks hands it to the next worker.

The worker endpoint is outside `/api/v1` (all the UI's proxy forwards), absent unless `RUN_DISPATCH=cloudtasks`, and accepts only
a token that is **verified here** (signature, audience = this service's URL, verified email) and whose email is the tasks service
account. Cloud Run's IAM check alone is not enough: the UI's account holds `roles/run.invoker` too.

**Caps.** `MAX_CONCURRENT_RUNS` counts the runs of one process (local dispatch). With Cloud Tasks the service-wide cap is the
queue's `max-concurrent-dispatches` (`infra/tasks/setup_queue.sh`), and a run beyond it waits as QUEUED instead of being refused.

**Rate limits** (`RATE_LIMIT_BACKEND=firestore`): fixed-window counters per class and client, one document per minute in
`ratelimits`, counted in a transaction, the client stored as a hash, `expires_at` for a Firestore TTL policy. If Firestore is
slow or down a request is counted by the process's own limiter: degraded, never off.

**Still process-local, by design.** The SSE wake-up (`run_events`) only wakes streams on the same instance; the others poll Firestore
every second while a run is active, so a stream on another instance is at most a second behind. The per-bundle upload count
(`MAX_DOCUMENTS_PER_BUNDLE`) is checked under an in-process lock, so simultaneous uploads through two instances could exceed it by
a few; nothing breaks, and it is a limit, not an invariant.

## 3. Signing the head of the audit chain

The audit chain is hash-linked, so editing an event breaks every hash after it. Whoever can write the whole collection can also
rewrite the whole chain consistently. A **signature over the chain head with a key the database does not hold** closes that gap.

After each completed assessment `services/signing.py` signs `{purpose, bundle_id, seq, hash}` of the newest event (ECDSA P-256 /
SHA-256) and appends the signature to the chain as an `AUDIT_HEAD_SIGNED` event, so it is ordered, hashed and verified like every
other event. Events after the last signature (a correction, for instance) are an **unsigned tail**, which the summary reports, until
the next assessment (or `POST /bundles/{id}/audit/sign`) signs the head again.

* **Key:** `SIGNING_KEY_VERSION` = a Cloud KMS `EC_SIGN_P256_SHA256` key version (`infra/kms/setup_signing_key.sh`); the private
  key never leaves KMS, and the API's identity may only sign with it and read its public half. Requests and answers are
  CRC32C-checked, as Google requires.
* **Verification:** every signature is checked against the key's **public half fetched from KMS** (cached; a version is immutable);
  a key carried in an event is never trusted. The check also requires that the signed head really is in the chain: a history
  rewritten consistently, with every hash recomputed, still fails (`the signed head is not in the chain`).
* **Demo mode** signs with a throwaway in-process key, labelled `local-demo`. A demo signature is checked only against the key
  **this process holds**, never against the public key written into the event (that is data an attacker can write); one made by another
  process (a restart) is `UNVERIFIED`, and a `local-demo` signature is **refused (`INVALID`) in live mode or when a KMS key is
  configured**, so forging one cannot make a KMS deployment look signed. A demo signature therefore shows only that the chain was
  not edited after it was signed, in this session, and says so in `meaning`. **Live mode without a key does not sign** and says `NOT_CONFIGURED`.
* **A signing failure never fails an assessment.** It is recorded as `AUDIT_SIGNING_FAILED` (the error type only) so the gap is
  visible in the trail, and the summary counts it.
* **Status** (`GET /bundles/{id}/audit` → `signature`): `SIGNED`, `PARTIAL` (signed earlier; N later events unsigned), `UNSIGNED`,
  `INVALID`, `UNVERIFIED` (the public key could not be retrieved), `NOT_CONFIGURED`. The UI shows it beside "Chain verified".

**Wording, everywhere:** *tamper-evident under the operator's key.* It is **not legal non-repudiation**: there is no user
authentication, so the signer is the service, not a person.

## 4. Preprocessing: what the model is shown

* **Image mode** (`PAGE_IMAGE_MODE`): `bw` (1-bit, the original input) or `gray` (8-bit). Same geometry either way. The A/B on the
  real model is `scripts/live_smoke_extraction.py --page-mode`, on the degraded set from `scripts/make_degraded_scans.py`, compared
  with `scripts/compare_smoke_reports.py`.
* **Deskew** (`PREPROCESS_DESKEW`, off by default): the skew is measured on the upright page by a projection profile (to the nearest 0.1°: at most
  0.05° off on the synthetic test pages, not measured on real scans; blank, black, noisy or line-less pages measure 0), and a skew between `DESKEW_MIN_DEGREES` (0.3) and
  `DESKEW_MAX_DEGREES` (10) is corrected on a canvas of the same size. The correction is **reversible**: the page records
  `processed_to_source_affine`, a 3x3 in normalized 0-1000 coordinates, **aspect-aware** (conjugated with the page's width and height,
  so a rectangular page does not turn into a shear) and composed with the orientation rotation. The viewer maps every evidence box
  through it, so boxes land on the original page. A skew outside the range is not corrected and the page says why
  (`deskew_skipped`).
* **Orientation:** axis first (which rotation pair makes the text rows most uneven, judged at every small tilt so a crooked scan
  is not mistaken for a sideways one), then polarity (a weak top-heavy bias). A sideways page is turned; an upside-down page is
  turned only when it is clearly bottom-heavy: without OCR the two are hard to tell apart.
* **Persisted pages** (`PERSIST_PROCESSED_PAGES`, on): the page image the model was shown is stored privately **per assessment**
  (`bundles/{id}/pages/it0001/{doc}/page-001.png`; the extraction record carries `pages_iteration`, and a recompute carries the one of
  the assessment it copied) and served by `GET /bundles/{id}/documents/{doc}/pages/{n}?iteration=N` (the latest when omitted); the viewer
  links to the page of the assessment on screen ("What the model saw") and says when a page was straightened. A later run with another
  image mode therefore does not replace the answer for an earlier assessment. Pages kept before this layout (no `pages_iteration`) are still served.
* **Tests:** a deterministic corpus (`backend/tests/support/scans.py`): seeded pages with noise, blur, fading, JPEG artifacts, uneven
  light, tilt either way, and sideways feeds, each with a marker block whose position is known. The tests check the skew estimate,
  the straightening, and that a marker found on the processed page maps back onto the original within 0.4 % of the page, on a
  non-square page, through real PDFs, sideways and tilted. The same matrices and vectors are pinned in
  `frontend/tests/transform-bbox.unit.spec.ts`.

## 5. What is and is not proven

| | Proven locally | Needs Google Cloud |
|---|---|---|
| lease decisions, fencing, take-over, reaping | all of it, on the in-memory store and on Firestore-like optimistic transactions | the real `async_transactional` and contention (an emulator test file is ready: `backend/tests/emulator/`) |
| Cloud Tasks dispatch | the task's shape, the worker's authentication and answers, duplicate / dead-executor / obsolete deliveries | that Cloud Tasks delivers it, the OIDC audience, retry timing against the lease TTL |
| shared rate limits | counting across two instances, fallback on failure | latency and contention on real Firestore, the TTL policy |
| signing | the statement, verification, every rewrite attack, the KMS request shape with a fake KMS | a real KMS signature verifying under the real public key |
| preprocessing | geometry, round trip, orientation, modes, persistence | whether grayscale or deskew actually improves extraction (the A/B) |
