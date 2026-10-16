# CargoClear for Android: implementation plan

**Status (2026-10-15): approved with the defaults of section 3. Phases 0 (foundations), 1 (read path), 2 (run and upload), 3 (document viewer), 4 (corrections, history, pre-fill) 5 (native extras) and 6 (hardening and release preparation) are done; see [`android/README.md`](../android/README.md) for what the app does today and how to run it.** Deviations so far: AGP 9.3.3 on Gradle 9.5.1 (not 9.4: slow Gradle downloads on the development network); Run and Add document are disabled while files are going up (the web disables only Add); a minimal Settings screen (screenshot block, clear downloaded documents) arrived with the viewer, which needed both; the viewer draws no boxes when how a page was prepared cannot be fetched (the web draws them unmapped); the run button is a plain button, not Material's extended FAB, because that component leaves its label out of the accessibility tree. Phase 4: the pre-fill pack is shared through the system share sheet instead of downloaded; the audit chain is read when the History segment opens; the Reasoning Delta is one card per change. Phase 5: the two-pane layout starts at 840 dp wide and 480 dp tall (not at "medium" width, which is too narrow to split); the run-finished notification is off until the person turns it on, and is a short expedited job rather than a service the app starts itself; the camera scan could not be exercised end to end on the available emulator (Play services could not download the scanner module); Share link appears only where the app reaches the UI through its HTTPS proxy. Phase 6: the hosted build against the deployed UI, a TalkBack pass, a physical phone and the camera scan are not done (see `android/README.md`, *Manual checklist*, and section 8 of `docs/CLAIMS.md`); the optional OpenAPI export and the `/meta` limits of section 14 were not done (the contract test covers the shapes without them); the editable debug backend address was not built; the minified build is checked through an `r8check` build type of the local flavor, which the plan did not list.

## 1. Goal and ground rules

Build a native Android app that does everything the web workbench does, shaped for a phone (and tablets/foldables) instead of a four-pane desktop screen.

* **Same functionality.** Create a bundle (choose Singapore or India), upload PDFs, run analysis, watch live progress, read the status, checks, missing evidence and indicative duty estimate, view the original PDF with evidence boxes, correct a value and recompute, read the Reasoning Delta and the signed audit chain, download the declaration pre-fill pack. Demo mode keeps its Case C / Case D starters and the sample certificate.
* **Same product boundaries.** Decision support only. No submission to a government portal, no legal determination, no payment, no authentication/SSO (still out of scope for the MVP). The wording that keeps the claims honest ("indicative", "demo-curated", "tamper-evident under the operator's key, not legal non-repudiation", "self-reported confidence", "never ready to file") is ported verbatim, not paraphrased.
* **No business logic on the device.** The model reads documents; the backend's deterministic rules decide. The app never computes a status, a check or a duty figure. It renders what the API returns. That is what makes "same functionality" cheap to keep true.
* **No secrets in the app.** No API key, no token, no service-account material. This matches the repo's boundary and keeps the app out of the credential business.

**Non-goals:** on-device OCR or ML extraction, new rules or checks, a login system, iOS (see the module layout in section 4 for how to leave that door open), changing assessment behaviour.

## 2. What the codebase tells us (and what it means for Android)

| Finding in the repo | Consequence |
|---|---|
| The **API is a private Cloud Run service**; the browser never calls it. The public **UI's server-side proxy** (`frontend/app/api/proxy/[...path]`) attaches a Google ID token. | An app cannot hold that identity. The v1 app talks to the **UI's `/api/proxy/*`** (zero backend change). Locally it talks to the backend directly at `/api/v1`. The base URL is configuration, so a different front door can be swapped in later. |
| Only the UI is public, and **the UI is not deployed yet** (the UI service account is the open item). | Everything through Phase 5 runs against the local demo backend, exactly like the web demo. A hosted run needs the UI deployed first. I will not run `gcloud`; you ask when you want that. |
| There is **no "list bundles" endpoint and no user identity**. A bundle id is the only access control. | "Recent bundles" must be stored on the device (Room), plus "open by id / pasted link". Bundle ids are treated as secrets: not logged in release builds, excluded from cloud backup. |
| Progress and new assessments arrive over **SSE** (`status`, `iteration`, `error` events; 15 s ping; the stream replays current status and latest iteration on connect). | An SSE client with reconnect. **Cloud Run's 300 s request timeout ends every stream**, so reconnecting is normal, not an error; the replay is the resync mechanism. Read timeout must exceed the 15 s ping. |
| Evidence boxes are **0-1000 normalised, top-left origin** on the *processed* page, mapped back to the original via `transform-metadata` (rotation 90/180/270 or a recorded deskew affine). | Port `transform-bbox.ts` and `bbox.ts` exactly, and test with the **same vectors** the backend and web already pin. This is the riskiest rendering detail (section 12). |
| The web client has real state-machine subtleties in `useWorkbench.ts`: stale-iteration drop, "still running until the stream reports a terminal state for *our* run id", auto-reassess only after the first iteration, newest-request-wins for corrections, document selection that sticks. | Ported as a pure reducer/state holder with unit tests that replay those scenarios, not re-invented. |
| Types are a **hand-maintained mirror** of the Pydantic schemas, kept honest by contract tests (`test_corrections_contract.py`). Some fields are loosely typed (`FieldRef.value` is string, number or null; `ReasoningDeltaChange` and audit `payload` are free-form; extractions are loose records). | Kotlin DTOs need `JsonElement`/`JsonObject` for those fields. A third mirror needs the same kind of guard (section 11). |
| Limits live on the server (50 MB upload, 20 documents per bundle, 30 pages, 60 writes and 10 runs per minute per IP) and `/meta` does not expose them. | Do not hard-code them in the app; show the server's error message. Optionally expose them on `/meta` (section 14). Rate limits are per client IP, so phones behind carrier NAT can share a bucket. |
| Uploads are **content-addressed**: identical bytes are the same document. | Retrying an upload is idempotent, so a resumable background uploader (WorkManager) is safe. **Corrections are not idempotent** (each appends an audit entry): never auto-retry them. |
| Demo endpoints exist only when `APP_MODE=demo`; the sample certificate must be uploaded under the exact filename `mtc_pipe_test_cert.pdf` (filename-keyed fixtures). | Gate demo UI on `GET /meta`; reproduce the filename exactly. |
| The repo enforces **claims discipline** (`docs/CLAIMS.md`, `test_claims.py`): no number without the measurement tool. | The app adds no performance or accuracy claims. Android rows enter CLAIMS.md as STUBBED until verified on a device, and the claims scan is extended to the app's strings (section 14). |
| This machine already has JDK 17, Gradle, Android Studio, SDK platforms 36 and 37 with build-tools, `adb`, and one API 36 `google_apis` arm64 AVD (from another project). | Toolchain looks sufficient; Phase 0 confirms it with a real build rather than assuming. |

## 3. Decisions (recommended default first)

| # | Decision | Recommendation | Alternatives and why not |
|---|---|---|---|
| D1 | Technology | **Native Kotlin + Jetpack Compose + Material 3.** | *PWA/TWA or WebView wrapper*: fastest, but the UI is a desktop four-pane layout and gives no camera scan, share-sheet intake, notifications or adaptive layout. *Flutter/React Native*: a second stack for one platform. |
| D2 | How the app reaches the backend | **Through the deployed UI's `/api/proxy`** in hosted builds; **direct `/api/v1`** against the local backend in dev. | *Direct to the private API*: needs a new auth path on the backend (out of MVP scope). *A new mobile gateway service*: more infrastructure for no v1 gain. |
| D3 | Scope | **Parity first (Phases 0-4, 6), native extras as an optional Phase 5** that can be cut. | Parity only; or extras folded in from the start. |
| D4 | Location | **`android/` in this monorepo.** | A separate repo loses the shared test vectors and the backend contract tests. |
| D5 | Identity | `applicationId` placeholder **`com.cargoclear.japac`**, **minSdk 26**, compile/target the latest stable API installed here (36+; check Play's target requirement at release). | minSdk 26 gives `java.time`, adaptive icons and no desugaring; lowering it costs complexity for little reach. **Please confirm or give your own package name.** |
| D6 | Distribution | **Debug/release APK sideload and Firebase App Distribution or Play internal testing later.** Keystore lives outside the repo, never committed. | Public Play release is a later, separate decision. |
| D7 | Sensitive screens | **`FLAG_SECURE` on the document viewer, on by default, switchable in Settings.** Customs documents are commercially sensitive. | Off by default (screenshots allowed). |
| D8 | Backend/doc changes | Only the **additive** items in section 14, each needing your approval. | None (everything works without them; the contract guards are weaker). |

## 4. Architecture

**Stack:** Kotlin, Compose + Material 3, single activity, Navigation Compose, ViewModel + `StateFlow` (unidirectional data flow), Hilt, Retrofit + OkHttp (+ `okhttp-sse`), kotlinx.serialization (`ignoreUnknownKeys`), Room (recent bundles, last-known snapshot), DataStore (settings), WorkManager (uploads), Coil (the "What the model saw" PNG), `android.graphics.pdf.PdfRenderer` (no third-party PDF dependency; boxes are drawn by us). Versions are chosen at kickoff from current stable releases.

**Modules (kept few on purpose):**

```
android/
  app/             UI (screens, navigation, theme), Hilt wiring, build flavors, manifest
  core/model/      pure Kotlin, no Android types: DTOs, enums, and ported logic
                   (corrections address grammar, bbox + transform mapping, highlights,
                   finding-document, delta labels, error mapping, workbench state machine)
  core/data/       Android library: Retrofit API, SSE client, repositories, Room, DataStore,
                   PDF download cache, WorkManager uploader
```

`core/model` runs its tests on the plain JVM (fast), consumes the shared test vectors, and is the part a future iOS or Multiplatform effort would reuse.

**Build flavors / config**

| Flavor | API prefix | Notes |
|---|---|---|
| `local` (debug) | `http://10.0.2.2:8080/api/v1` (backend direct) or `http://10.0.2.2:3000/api/proxy` (Next dev) | Cleartext allowed for `10.0.2.2`/`localhost` **only**, via a debug network-security config. |
| `hosted` (release) | `https://<ui-host>/api/proxy` | HTTPS only, system trust store only. Base URL from `BuildConfig`; editable in debug builds. |

**Data flow for a bundle screen:** `BundleRepository` merges the initial fetch (bundle, then assessment and iterations in parallel; a 404 on the assessment means "not analysed yet") with the SSE stream, and exposes one `BundleSession` state to `BundleViewModel`. The stream is opened when the screen is STARTED and closed when it is STOPPED, so it does not hold a connection in the background.

**Client-side logic to port (about 360 lines of pure helpers, plus the roughly 390-line `useWorkbench` state machine):** `corrections.ts` (field tables, `evidencePath`, `hasUnit`, `canClear`, `readCell`, `pathLabel`), `transform-bbox.ts`, `bbox.ts`, `highlights.ts`, `finding-document.ts`, `delta-labels.ts`, `errors.ts` (`runErrorMessage`), the `CHECK_TITLES` table, per-document health counts, and the `useWorkbench` state machine.

## 5. Feature parity map (web to Android)

| Web | Android |
|---|---|
| Home: destination select, New empty bundle, Case C/D demo starters (demo mode only), mode badge | **Home** screen: same actions, plus **Recent bundles** (local) and **Open by id / paste link**. Demo starters shown only when `/meta` says `demo`. Offline/Live/Demo badge. |
| TopBar: bundle id, reference, destination chip, status pill, connection state, Add Document, Run analysis / Reassess | Bundle top app bar (id, reference, destination, status pill, "Live updates: reconnecting"), overflow with Add document / Pre-fill / Share link; **extended FAB** Run analysis / Reassess. |
| DemoBanner ("DEMO MODE - extraction uses synthetic fixtures...") | Persistent banner, same text, whenever mode is demo or `data_source` is `fixture`. |
| DocumentRail with Conflict / Gap / Clean chips | **Documents** tab: list with the same health chips (icon + text, never colour alone). |
| DocumentViewer (pdf.js + BBoxLayer, page nav, "straightened" note, "What the model saw") | **Viewer** screen: `PdfRenderer` page, pinch/pan zoom, severity-coded boxes with labels, page nav, deskew note, "What the model saw" image. |
| AssessmentPanel: iteration, "recomputed" badge, lowest reported confidence (with its caveat) | **Assessment** tab header, same content and caveat text. |
| RunProgress (stage and %) | Progress card driven by SSE `status` events; announced politely to TalkBack. |
| ActionErrorBanner (e.g. token limits) | Same banner; shows the server message and the `request_id` for support. |
| CheckList: issues first, passed collapsed, evidence rows (doc, type, value, unit, page), assumptions, rule set + regulation ref | Same grouping and fields; evidence rows are tappable (open the document **at that page with that box focused**). |
| CorrectionEditor (value, unit for weights/cells, reason, "document does not state this", Confirm vs Save) | **Bottom sheet** with identical fields and rules (`hasUnit`, `canClear`); saving an unchanged value records a confirmation. |
| CorrectionsCard (pending count, status per correction, Undo, Recompute) | Same card; Recompute disabled while a run is active. |
| ValuationCard (value to CIF to duties, implied code, assumptions, disclaimer) | Same card; every assumption and the disclaimer stay one tap away. |
| PrefillCard (JSON/PDF download, caveat line) | Same card; files are fetched to app cache and opened/shared through the system share sheet (`FileProvider`, no storage permission). |
| MissingEvidenceCard, Upload missing certificate, "Use sample MTC (demo)" | Same; the upload uses the system file picker. |
| DeltaDrawer: Reasoning Delta + Audit Chain tabs | **History** tab with the same two segments. The Delta table becomes cards on a phone. |
| AuditTimeline: verified badge, signature badge, "Sign now", event list, "What a signature means" | Same, including the exact meaning text from the API. |
| Upload progress per file; one refresh and at most one run action per batch | Same semantics, run by WorkManager so a large upload survives backgrounding. |
| Accessibility (WCAG 2.2 AA tokens, live regions, reduced motion) | Tokens ported to a Material 3 colour scheme (light and dark); status colours are fixed, not dynamic colour; TalkBack live-region announcements for status changes; reduced-motion respected. |

## 6. Android-native experience

**Core (part of parity):** bottom navigation (Assessment / Documents / History) instead of four panes, gesture zoom on the document, Material 3, dark mode, edge-to-edge, predictive back, system share sheet for the pre-fill pack, recent bundles on the home screen, process-death restoration.

**Optional extras (Phase 5, each independently cuttable):**

1. **Scan with the camera**: ML Kit Document Scanner produces a PDF (uploads PDF only today), no camera permission needed. Needs Google Play services; the Scan button is hidden where it is unavailable.
2. **Share-sheet intake**: "Share to CargoClear" for PDFs from Gmail, Drive, WhatsApp.
3. **Run-finished notification**: a short-lived foreground service (data sync) holds the same SSE stream while a run is active and the app is backgrounded, posts a local notification on COMPLETE/ERROR, then stops. No backend push service is needed.
4. **Tablet/foldable two-pane**: viewer beside the assessment, matching the web workbench, driven by window size class.
5. **Jump to evidence**: tapping an evidence row opens the exact page and zooms to its box (the web only selects the document).
6. **Share bundle link** (the web `/workbench/{id}` URL) for continuing on a desktop. Opening web links inside the app needs App Links verification on the UI domain, so that part is deferred until the UI has a domain.

## 7. Screens and navigation

```
Home ──► Bundle ─┬─ Assessment tab (status, progress, corrections, checks, valuation, pre-fill, missing evidence)
  │              ├─ Documents tab ──► Viewer (page, boxes, "what the model saw")
  │              └─ History tab (Reasoning Delta | Audit chain)
  ├─ Open by id / paste link
  └─ Settings (backend URL in debug, FLAG_SECURE, clear cache, about and disclaimers)

Sheets: Add document (Files / Scan), Correction editor, Evidence detail
```

Compact width: one pane plus bottom navigation. Medium/expanded width: Documents/Viewer and Assessment side by side, History as a collapsible bottom panel (the web's drawer).

## 8. Connectivity details

* **Endpoints used** (all existing): `GET /meta`; `POST /bundles`; `GET /bundles/{id}`; `POST /bundles/{id}/documents` (multipart field `file`, optional field `declared_type`; the client sends it, no screen offers it yet); `DELETE /bundles/{id}/documents/{doc}` (the client has the call, no screen yet); `GET .../documents/{doc}/file`, `.../transform-metadata`, `.../pages/{n}?iteration=`; `POST /bundles/{id}/analyze|reassess|recompute`; `GET /bundles/{id}/assessment|iterations|extractions?iteration=`; `GET|POST /bundles/{id}/corrections`, `POST .../corrections/{cid}/revert`; `GET /bundles/{id}/audit`, `POST .../audit/sign`; `GET /bundles/{id}/prefill(.pdf)?iteration=`; `GET /bundles/{id}/stream` (SSE); demo: `POST /demo/case-c`, `POST /demo/case-d`, `GET /demo/case-c/mtc`.
* **Headers:** send only `Content-Type`, `Accept` and a UUID `X-Request-Id` (the proxy accepts `[A-Za-z0-9._-]{1,64}` and echoes it). Show it in error details.
* **Errors:** parse the `{code, message, detail, request_id}` envelope; keep the web's mapping (a 409 "already in progress", `VALIDATION_ERROR` on analyze means "upload at least one document"). Network failures become a distinct, retryable "can't reach the server" state.
* **SSE:** OkHttp read timeout above 15 s (server ping), exponential backoff on reconnect with the web's 3 s as the floor, resync from the replayed `status` + `iteration`, and a polling fallback (`GET /assessment`) after repeated stream failures.
* **Uploads:** stream from the content `Uri` (never read 50 MB into memory), `DISPLAY_NAME` as filename, `application/pdf`; sequential per batch like the web; WorkManager with network constraint; safe to retry (content-addressed).
* **Downloads:** pre-fill JSON/PDF and the PDF being viewed go to app-private cache (LRU, cleared on demand), never external storage.
* **Offline:** read-only. Recents and the last-known assessment snapshot render with a clear "last updated" stamp; every mutation (upload, run, correct, recompute) requires a connection and says so.

## 9. Security and privacy

* No credentials in the app; HTTPS only in release; no user-installed CAs trusted; cleartext limited to the emulator host in debug. No certificate pinning (Cloud Run certificates rotate).
* Bundle ids are capability tokens: private Room database, `allowBackup=false` / data-extraction rules excluding it, never logged in release, redacted in crash reports.
* `FLAG_SECURE` on the viewer (D7); app-private PDF cache only.
* Disclaimers ("decision support", "not an amount payable", rule-set provenance) are always reachable and unchanged.
* Hosted builds inherit the backend's trust model: with no authentication, anyone holding a bundle id can read it. The app does not change that and must not hide it.

## 10. Accessibility and design

Port `globals.css` tokens (surface, text, focus, ok/warn/err/info with their documented contrast ratios) into a Material 3 `ColorScheme` for light and dark; keep status colours fixed. Status is always colour plus icon plus text. 48 dp touch targets, layouts that survive 200% font scale, TalkBack `liveRegion` for status changes (assertive for a material contradiction, as on the web), and bounding boxes exposed to TalkBack as a list of findings, because a canvas overlay is invisible to it.

## 11. Testing and verification (mirrors how this repo already works)

* **Shared vectors, one more consumer.** `docs/schemas/path-labels.json` is already "tested twice"; Android becomes the third. The rotation and deskew vectors that `backend/tests/unit/test_deskew.py` and the web spec pin are reused (read from one place via a Gradle resource dir, not copied).
* **Contract guards against drift.** Extend the existing pattern: a backend test that reads the Kotlin field tables the way `test_corrections_contract.py` reads `corrections.ts`; DTO property names checked against the backend models (best done through an OpenAPI snapshot, section 14).
* **Fixtures from the real demo backend.** A script records the JSON for Case C and Case D (each stage, plus an SSE transcript with pings and a mid-stream drop) from the local demo backend into `android/.../test/resources`, so unit tests replay real payloads through MockWebServer.
* **State machine tests:** the `useWorkbench` scenarios (SSE replay, stale iteration, run id pending until terminal, auto-reassess rule, newest corrections request wins, sticky document selection).
* **UI:** Compose tests with the Accessibility Test Framework checks enabled; screenshot tests for the four statuses, light/dark and font scale 1.0/2.0.
* **End to end on the emulator against the local demo backend**, mirroring the README journeys: Case C (`MISSING_EVIDENCE`, add sample MTC, `COMPLIANT_FOR_SUBMISSION`) and Case D (`MATERIAL_CONTRADICTION`, correct Cr 0.35 to 0.28, recompute to `SPECIALIST_REVIEW_REQUIRED`, undo, recompute back). I can run these here and capture screenshots with `adb`.
* **Degraded scans:** `scripts/make_degraded_scans.py` already produces rotated and skewed pages; use them to check box alignment on the viewer.
* **Manual before release:** TalkBack pass, 200% font, low-memory device, airplane-mode mid-run, process death during a run and during an upload.

## 12. Phases and acceptance criteria

Sizes are relative (S/M/L), not calendar promises. Expect on the order of 8-12k lines of Kotlin including tests (the web client is about 4.4k lines of TypeScript); that is an estimate.

| Phase | Size | What | Done when |
|---|---|---|---|
| **0 Foundations** | S | Confirm D1-D8. `android/` skeleton (Gradle wrapper, version catalog, flavors, Hilt), theme tokens, `.gitignore` entries for Android, a build on this machine. | App builds and launches on the emulator and shows the Demo/Live badge from `GET /meta` on the local backend. |
| **1 Read path** | M | DTOs, API client, error envelope, SSE client, repositories, Room recents, ported pure logic with vectors, Home, Bundle screen (read-only): status, checks, missing evidence, valuation, document list with health chips. | Opening a Case C and a Case D demo bundle shows the same status, checks and estimate as the web, from MockWebServer tests **and** the live local backend. |
| **2 Run and upload** | M | Run/reassess/recompute controls, SSE progress, the `useWorkbench` state machine, file picker and WorkManager upload, auto-reassess, sample MTC (demo), error banners, run-id-pending logic. | The Case C journey passes end to end on the emulator. |
| **3 Document viewer** | L (riskiest) | `PdfRenderer` pipeline and cache, zoom/pan, box overlay with transform-metadata mapping, page nav, "What the model saw", tap-evidence-to-page. | Boxes line up on the Case C/D PDFs and on the degraded (rotated, skewed) scans, and the rotation/deskew vectors pass. |
| **4 Corrections, history, pre-fill** | M | Correction sheet, corrections card, undo, recompute, Reasoning Delta, audit chain with signature and Sign now, pre-fill download/share. | The Case D correction journey passes end to end, including the audit entries. |
| **5 Native extras (optional)** | M | Scan, share-sheet intake, run-finished notification, two-pane, share bundle link. | Each extra works on its own and can be removed without touching Phases 0-4. |
| **6 Hardening and release** | M | Accessibility audit, process-death and low-memory handling, R8, signing config (keystore outside the repo), hosted build against the deployed UI, docs. | Release build installs, the manual checklist passes, and the docs in section 14 are updated. A hosted run waits for the UI deployment. |

## 13. Risks and what to verify early

1. **Box alignment** (rotation, deskew, `/Rotate` in the PDF itself). Verify in Phase 3 with the shared vectors and the degraded scans before building anything on top.
2. **SSE on mobile** (Doze, radio changes, Cloud Run's 300 s cut). Reconnect plus replay plus the polling fallback; test with airplane mode mid-run.
3. **Large uploads.** The server cap is 50 MB, but Cloud Run documents a request-size limit on HTTP/1 that may be lower. This already affects the web UI; confirm against a real deployment instead of assuming. Scanned PDFs from ML Kit are small.
4. **The hosted stack is unverified** (the repo's STUBBED claims). The app cannot be more "live" than the backend; its claims follow the backend's labels.
5. **No authentication.** Bundle ids are the only access control, so the app stores and logs them accordingly.
6. **Per-IP rate limits** on carrier NAT. Low risk now; report the `request_id` and the server message when it happens.
7. **Hand-maintained type mirror drift**, the repo's known weak spot. Addressed by the guards in section 11.
8. **`PdfRenderer` limits:** one open page at a time and not thread-safe (serialise behind a mutex), and large bitmaps at high zoom (cap size, re-render the visible region).
9. **ML Kit scanner availability** depends on Google Play services (the installed AVD is `google_apis`, not Play Store). The feature is optional and hides itself when unavailable.

## 14. Changes outside `android/` (all additive, none made without your approval)

| Change | Why | Risk |
|---|---|---|
| `.gitignore`: Android entries (`.gradle/`, `build/`, `local.properties`, `*.keystore`, `*.jks`, `.idea/`, `captures/`) | Keep build output and signing material out of the repo. | None. I will not run git commands that change state; you commit. |
| `scripts/export_openapi.py` writing `docs/schemas/openapi.json`, plus a test that it is current | One checked-in contract the Kotlin DTO test can read (the API publishes `/openapi.json` in demo mode). | Small; mirrors the existing schema files. |
| Expose `max_upload_mb` and `max_documents_per_bundle` on `GET /meta` | Let the app show limits without hard-coding them. | Touches the API surface; optional. |
| Extend `test_corrections_contract.py` to check the Kotlin tables; `docs/schemas/path-labels.json` gains an Android consumer note | Keep three mirrors identical. | Backend test change only. |
| `docs/CLAIMS.md`: Android rows (STUBBED until verified on a device, no latency or accuracy figures); extend `test_claims.py` to scan `android/**/strings.xml` and the Kotlin UI files for the banned-phrase list | Claims discipline applies to the app's copy too. | Counts in the register header must be updated with the rows. |
| `README.md`, `docs/HOW_TO_RUN_AND_DEMO.md`, `docs/FAQ_ONBOARDING.md`: an Android section (run against local demo backend, flavors, limits) | Operational docs. | Outward-facing files are scanned by `test_claims.py`; wording will pass it. |
| If hosted use needs it: UI `public/.well-known/assetlinks.json` for App Links | Opening web links in the app. | Deferred until the UI has a domain. |

## 15. What I need from you

1. **Approve or change D1-D8**, especially D1 (native), D5 (package name), D3 (is Phase 5 in or out) and D7 (`FLAG_SECURE` default).
2. **Which backend should the first working build target?** My default: the local demo backend (same as the web demo) through Phase 5, hosted only after the UI is deployed.
3. **Which of the additive changes in section 14** may I make? My default: `.gitignore`, the docs and claims updates, and the contract tests; the `/meta` limits only if you want them.
4. **Real device or emulator for the manual checks?** I can drive the emulator and capture screenshots; TalkBack and low-memory behaviour are better confirmed on a phone.
