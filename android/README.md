# CargoClear for Android

Native Android client for the CargoClear-JAPAC workbench. The plan, decisions and phases are in [`docs/ANDROID_APP_PLAN.md`](../docs/ANDROID_APP_PLAN.md).
Decision support only: the backend decides every status, check and duty figure; this app renders what the API returns.

**Status: Phase 6 (hardening and release preparation; all phases of the plan are built).** You can create a bundle (Singapore or India, plus the Case C and Case D demo starters in demo mode), open one by id or by
a pasted web link, and read it: status, checks with the documents and values they compared, the indicative duty estimate with its assumptions, what is
missing, and the documents with their Conflict / Gap / Clean chips. **Run analysis** (then **Reassess**) starts a run and shows its stage and percentage as the
server reports them; a run started elsewhere (the web UI, `curl`) shows its progress and its result live as well. **Add document** opens the system file picker;
the files go up in the background, one after another (so a large scan survives the app being backgrounded or killed, and waits for a connection if there is none),
and once an assessment exists the batch ends with one reassessment, as in the web UI. In demo mode **Use sample MTC (demo)** adds the sample mill test certificate:
the Case C journey (`MISSING_EVIDENCE`, add the certificate, `COMPLIANT_FOR_SUBMISSION`) works end to end.

**The viewer.** Tapping a document, or an evidence row of a check, opens the PDF page by page (Android's `PdfRenderer`, no third-party PDF library). Pinch, drag, double tap
or the zoom buttons move the page; zoomed in, a sharp window onto the part in view is rendered over the whole page, so the page is drawn at the zoom it is shown at without ever holding a huge bitmap.
The evidence the latest assessment cites on the page is drawn as boxes, carried back through the transform the backend recorded for the page (turned and straightened
scans included) onto the original; a material finding is a solid line, a warning dashed, a passed check dotted (colour is never the only cue). A tapped evidence row opens
the page it cites with that box chosen and brought into view; **Evidence (N)** lists the page's evidence (the way to reach a box without seeing the canvas); **What the model
saw** shows the page image exactly as the extraction was shown it, with the boxes as cited. Documents you open are kept on this phone (private cache, evicted oldest first), so they
open again without a connection. **Settings** (the gear on the start screen) holds the viewer's screenshot block (Android's `FLAG_SECURE`, on by default, because customs
documents can be commercially sensitive) and a button that clears the downloaded documents.

**Corrections.** An evidence row that shows one extracted value has an **Edit** control under it (a derived figure, or a value stated on several lines, has none). It opens a bottom sheet:
the value as printed, its unit where it has one (a weight, a certificate cell), a reason that is kept in the audit trail, and "The document does not state this value" (not for
a certificate cell or a heat number: those can be corrected, never deleted). Saving the value as it already is records a **confirmation**; anything else is a **correction**; either
changes nothing until it is recomputed. The **Corrections** card lists what is in force, what each replaced, whether the assessment on screen includes it ("In this assessment",
"Pending recompute", or "Not used" with the reason), **Undo** for each, and **Recompute with corrections** (re-runs every check on the stored extraction: no document is read again and no model
is called). Editing is switched off while a run goes and on a saved copy. Case D's journey works end to end: correct Cr 0.35 to 0.28 on the certificate, recompute (Specialist Review Required),
undo, recompute (Material Contradiction).

**History.** The third tab holds the **Reasoning Delta** (what changed between assessments, one card per change instead of the web's table) and the **Audit Chain Timeline**: whether the chain
verifies, what its signature says (the backend's own words, including "demo key, not KMS"), **Sign now** when events came after the signed head, and every event with the person's corrections described in a line.
The chain is read when the segment is opened, and again when an assessment, a run, a document or a correction changes it. **Declaration pre-fill** (on the Assessment tab) prepares the pack (JSON or the PDF summary) on the phone and hands
it to the system share sheet; the file lives in the private cache and the share sheet gets a one-file read grant, so no storage permission is asked.

**Optional extras (each can be removed without touching the rest):**

* **Share to CargoClear.** A PDF shared from mail, Drive or a messaging app is copied into the private cache and the app asks which bundle it belongs to (a new one, or a recent one);
  the files then go up through the same background queue and each copy is deleted when its batch ends.
* **Scan a document.** With Google Play services present, **Add document** offers *Scan a document* (Google's on-device scanner, which returns a PDF without a camera permission for this app);
  without them the picker opens as before. *Not verified here:* the emulator's Play services could not download the scanner module, so what the scanner hands back has only been exercised by the
  unit tests of the code after it (the copy and the upload), not on a device.
* **Tell me when an analysis finishes.** Off until the person turns it on (in Settings, or from the offer shown while a run goes), because it needs the notification permission. If the app is
  in the background while a run is going, a short expedited job holds the live stream and posts one notification when that run ends; the lock screen shows only that an analysis finished, not which bundle.
  Tapping it opens the bundle. It does nothing while the app is in front, and stops when the app comes back.
* **Two panes** on a window at least 840 dp wide and 480 dp tall (tablet, unfolded foldable): the assessment beside the document list and viewer, History folded under them.
* **Share link** appears in the top bar's menu only when the app reaches the UI through its own HTTPS proxy (the `hosted` flavor); the link is `/workbench/{id}`, and a dialog says first that anyone
  holding it can open the bundle, because the backend has no sign-in. Opening such links inside the app needs App Links on the UI's domain and is not done.

Failures are shown in the server's own words with the request id. Bundles this phone has opened are listed on the home screen (the backend has no list endpoint and no
accounts), and a bundle can still be read from a saved copy when the server cannot be reached (read-only: nothing can be sent from it).

**Hardening (Phase 6).** *About CargoClear* (Settings) says what the app is and is not, in the claim register's own words, how it treats the data it holds, and lists its open-source
components with the licence each one's POM names (`tools/list_licenses.py` writes the list from the release build). What happens when the system ends the process: the bundle screen is
restored, a half-typed correction comes back with its text, a queued upload still runs (in a fresh process, once there is a connection), and a run in progress is picked up again from the
server. What happens under memory pressure: a bitmap is never bigger than the phone's heap can afford, a render that still runs out of memory is retried at half the size, the page bitmaps are
let go while the screen is not showing, and a trim signal drops the sharp window onto a zoomed page (it is drawn again on the next move). A connection that comes back after the radio was
off reopens the live stream at once instead of after its read timeout, and its replay brings the screen up to date.

**Not done:** a person has not walked the app with TalkBack (see *Manual checklist* below), the camera scan has not run end to end, nothing has run on a physical phone, and the hosted
flavor has not met a deployed UI. `docs/CLAIMS.md` section 8 labels each of these.

**Where this app differs from the web UI on purpose:** Run and Add document are disabled while files are going up (the web only disables Add), so a run never reads half a batch;
a failed action or upload can be dismissed; the file picker replaces drag and drop; the sample certificate is uploaded straight from the screen, not through the background
queue (it is 11 KB); when how a page was prepared cannot be fetched, the viewer draws **no** boxes and says so (the web draws them where the model put them, which is wrong for a
turned page); an evidence row opens the exact page and box (the web only selects the document); the pre-fill pack is shared rather than downloaded; the audit chain is read when
its segment is opened (the web's drawer reads it whenever it is mounted); the Reasoning Delta is a list of cards; Recompute is disabled while files are going up as well as while a run goes (undo and edit only while a run goes).

## Layout

```
android/
  app/          UI (Compose + Material 3), navigation, Hilt wiring, build flavors
  core/model/   pure Kotlin (no Android types): DTOs, the logic ported from frontend/lib (corrections addresses, bbox mapping, finding
                document, health chips, money) and the bundle screen's state machine; tests run on the plain JVM
  core/data/    Retrofit/OkHttp access to the backend, the Server-Sent Events client, repositories, Room (recent bundles + saved copies) and the
                WorkManager upload queue
  fixtures/     real JSON recorded from the demo backend (Case C, Case D, the event stream): what the tests decode
  tools/        record_fixtures.py (writes fixtures/ from a local demo backend, including `--only corrections` for the Case D correction journey) and make_alignment_fixtures.py (scanned pages, rotated, tilted or with
                /Rotate, and the transform metadata the backend's real preprocessing recorded for them: fixtures/viewer/)
```

## Prerequisites

* JDK 17 (Temurin 17 is installed on the development machine; set `JAVA_HOME` to it).
* Android SDK with platform 37 and build tools 36 or newer (`sdk.dir` in `android/local.properties`, which is git-ignored).
* The wrapper pins Gradle 9.5.1 (AGP 9.3 needs Gradle 9.5 or newer; AGP 9.4 needs 9.6 or newer). The first run downloads it if it is not cached.

## Build flavors

| Flavor | Talks to | Notes |
|---|---|---|
| `local` | `http://10.0.2.2:8080/api/v1/` (the backend on your computer, as the emulator sees it) | Cleartext HTTP is allowed for `10.0.2.2`/`localhost` only. Debug only: the release variant is disabled. App id `com.cargoclear.japac.local`. |
| `hosted` | `cargoclear.hostedApiBase` (the deployed UI's `/api/proxy/`) | HTTPS only. Empty until the UI is deployed: the app then says "Not configured" instead of calling a host nobody chose. |

Override an address with `-Pcargoclear.localApiBase=...` or `-Pcargoclear.hostedApiBase=...` (or in `~/.gradle/gradle.properties`). To go through the Next.js dev
server instead of the backend directly, use `http://10.0.2.2:3000/api/proxy/`.

## Release build

```bash
cd android
./gradlew :app:assembleHostedRelease        # unsigned APK: app/build/outputs/apk/hosted/release/
./gradlew :app:bundleHostedRelease          # unsigned AAB, for a store
```

**Signing material stays out of the repository.** Give the release build a keystore and its passwords in `~/.gradle/gradle.properties` (never in this repository), or in the environment, and the same
commands produce a signed build; without them they produce an unsigned one, which is what a CI check wants. A keystore inside the repository is refused by the build.

```properties
# ~/.gradle/gradle.properties
cargoclear.release.storeFile=/absolute/path/outside/the/repo/cargoclear-release.jks
cargoclear.release.storePassword=...
cargoclear.release.keyAlias=cargoclear
cargoclear.release.keyPassword=...          # optional: the store password is used when it is absent
# or CARGOCLEAR_RELEASE_STORE_FILE, CARGOCLEAR_RELEASE_STORE_PASSWORD, CARGOCLEAR_RELEASE_KEY_ALIAS, CARGOCLEAR_RELEASE_KEY_PASSWORD
```

Make a key once, and keep it (and its backup) somewhere that is not this repository and not a cloud folder: `keytool -genkeypair -keystore <path outside the repo> -alias cargoclear -keyalg RSA -keysize 4096 -validity 9125`.
The same signature is needed for every later update, so losing the key means a new app identity.

The hosted flavor's address is empty until the UI is deployed (`cargoclear.hostedApiBase`, the UI's `/api/proxy/`; see *Build flavors*). When it is, build with it, install, and walk the journeys of
`docs/HOW_TO_RUN_AND_DEMO.md` section 4g against the hosted stack: that run has not happened.

**The minified build is exercised against real payloads** through `./gradlew :app:assembleLocalR8check`: the release code (R8 shrinking and obfuscation) on the local flavor, signed with the debug key and
installable next to the debug build (`com.cargoclear.japac.local.r8`). The release variant of the local flavor is disabled on purpose (cleartext), and the `r8check` build type exists only for it, so a
debug-signed minified build of the hosted flavor cannot be produced. On 2026-10-15 this build ran Case C (run, sample certificate, reassess) and Case D (viewer, correction, recompute, history and audit
chain, a file upload through the system picker, the run-finished notification) with no serialization or class-loading error.

## Run it against the local demo backend

```bash
# terminal 1: the backend, as in the repository README (no Google Cloud needed)
cd backend
APP_MODE=demo .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

```bash
# terminal 2: build, install and start the app on a running emulator or a connected phone
cd android
./gradlew :app:installLocalDebug
adb shell am start -n com.cargoclear.japac.local/com.cargoclear.japac.MainActivity
```

The emulator reaches the backend on your computer's loopback through `10.0.2.2`, so the backend does not need to listen on the network.

## Checks

```bash
cd android
./gradlew test                                  # JVM unit tests of all modules
./gradlew :app:connectedLocalDebugAndroidTest :core:data:connectedDebugAndroidTest
                                                # Compose screen tests and the Room tests, on a running emulator or device
                                                # (Android uninstalls the app afterwards; run :app:installLocalDebug again)
./gradlew :app:assembleHostedRelease            # release build (unsigned; signing material stays outside the repository)

cd ../backend
.venv/bin/python -m pytest tests/unit/test_android_contract.py -o addopts='' -q
                                                # the Kotlin DTOs and correction tables against the Python models
```

The tests decode **recorded backend payloads** (`android/fixtures`) strictly: a field the backend sends that the DTOs do not name fails a test. When the API
changes, re-record them from a local demo backend and read the diff:

```bash
python3 android/tools/record_fixtures.py        # needs the demo backend from "Run it against the local demo backend"; refuses a live one
python3 android/tools/record_fixtures.py --only corrections   # just the Case D correction journey (corrections, audit, recompute, pre-fill)

cd backend && .venv/bin/python ../android/tools/make_alignment_fixtures.py
                                                # the rotated / tilted scans of fixtures/viewer, from the backend's own preprocessing; it refuses to
                                                # write a case whose own metadata does not carry the marker back onto the page
```

**Box alignment is tested on a device, with real renderings** (`PdfPagesTest`): Android's `PdfRenderer` draws each alignment page, the largest ink block is found in the bitmap,
and the box the backend cited on the processed page, carried back by the app's own mapping and layout, must outline it (IoU of at least 0.85) at fit and zoomed, for a clean page,
two tilts, two sideways scans, an upside-down page and a PDF whose page says `/Rotate 90`. The sample PDFs of Case C and Case D are drawn at their evidence boxes, so every
evidence box of both must hold printed ink. `backend/tests/unit/test_android_contract.py` keeps the same matrices and the same cases honest on the Python side.

## Accessibility

* **Automated, on a device** (`AccessibilityAuditTest`): on every key screen (start, assessment, documents, history in both segments, the correction sheet, the add-document sheet, settings, about, the
  share intake, the viewer and its evidence list) every control a person can tap, toggle or select must have a name, a role, a drawn size of at least 24 dp across (WCAG 2.2 criterion 2.5.8) and a touch area of at least 48 dp.
  Compose gives every clickable a 48 dp hit area by itself, so that last check is a tripwire; the drawn size and the names and roles are what can fail, and the test is shown to fail when a role is removed or a row is made too small.
* **Contrast** (`ContrastTest`): every text and background pair of both themes, against WCAG's ratios (4.5:1 for text, 3:1 for outlines). It found that buttons in the dark theme's focus colour had white text (too thin);
  they now use a dark `onFocus` colour.
* **Large text:** checked by eye at 200% system font on the start screen, the assessment, history and settings. It showed a title broken mid-word, a confidence line wrapped letter by letter, chips in the app bar
  broken mid-word and bottom-bar labels split ("Assessme/nt"); all four are fixed (the bar is as tall as its text needs, rows wrap, labels shrink to one line).
* **Not done, and why:** a walk with TalkBack. It is installed on the emulator image, but the touches `adb` injects bypass its gestures, so its focus order cannot be driven from a script. The names,
  roles and sizes are covered above; **reading order is not.** The first thing to look at by hand: the floating Run button and the bottom bar, whose position in the swipe order is decided by where they sit on screen.

## Manual checklist

Run before a release, on a phone if there is one. What has and has not been done is dated 2026-10-15 on an emulator (API 36) against the local demo backend.

| Check | Status |
|---|---|
| TalkBack: swipe through the start screen, the assessment (including the correction sheet), the viewer's evidence list and settings; every control is named, in a sensible order, and its state is spoken | **not done** |
| 200% font on the main screens | done on the screens listed above; the viewer and the correction sheet were not looked at |
| Dark theme | done (assessment, viewer); contrast of every pair is tested |
| Airplane mode during a run | done: the screen caught up about 8 s after the network returned (it had taken about 45 s before the stream reconnected on a network signal) |
| Process death during a run | done: relaunched on the finished assessment, Run enabled |
| Process death with a half-typed correction | done: the sheet came back with its text |
| Upload queued offline, process killed, network restored | done: the upload ran in a fresh process and the bundle was reassessed |
| Low memory (`adb shell am send-trim-memory <pkg> RUNNING_CRITICAL`, then `BACKGROUND` and `COMPLETE`) | done: no crash, the page stayed up, the sharp window was drawn again on return |
| A low-memory phone (small heap) | **not done**: the pixel budget is computed from the heap limit and unit-tested, never run on a device with a small one |
| Camera scan | **not done** (the emulator could not download Google's scanner module) |
| A physical phone | **not done** |

## Things the emulator does that you will meet when testing

* **WorkManager waits for a *validated* connection.** Uploads and the run watcher are queued with a "connected" constraint, which Android only meets once the network has passed its own connectivity
  check. An emulator that cannot reach Google's check never validates, and every queued upload sits at "Waiting to upload" forever. Fix it on the emulator with
  `adb shell settings put global captive_portal_mode 0`, then turn mobile data off and on (`adb shell svc data disable; adb shell svc data enable`).
* **After recording new fixtures, run the instrumented tests once with `--rerun-tasks`** (or `./gradlew :app:mergeLocalDebugAndroidTestAssets --rerun`): the asset merge can keep serving the old file list.
* **Typing into a field with `adb shell input text` is unreliable** while Gboard's stylus panel is open; select the field, press End and Delete, then type.

## Things the backend does that you will meet when testing

* **Rate limits per client:** 10 run requests a minute and 60 writes a minute (`RATE_LIMIT_RUNS_PER_MINUTE`, `RATE_LIMIT_WRITES_PER_MINUTE`). Starting runs in quick
  succession answers 429 "Too many requests. Try again in N seconds."; the app shows that message and the request id. `tools/record_fixtures.py` waits such a limit out.
* **One run per bundle at a time:** a second analyze/reassess/recompute while one is going answers 409 ("already in progress"); the app words it as the web does.
* **Uploads are content-addressed:** the same bytes sent again are the same document, so a retried upload is safe. A file is sent with a declared length, which lets the
  server refuse an oversized one before reading it; a document provider that announces a wrong size gets the file re-sent without a declared length.
* **`transform-metadata` answers 404 until a document has been analysed**, and the demo backend does not straighten pages unless it is started with `PREPROCESS_DESKEW=true`
  (the viewer then shows a "straightened" note and maps the boxes back). To see a tilted scan: `python scripts/make_degraded_scans.py` writes tilted and sideways copies of
  the sample PDFs under the same file names (so the demo extraction still keys on them); upload those to a bundle on a backend started with that flag.
* **A document's id names its content**, so a downloaded PDF never goes stale and is cached by id.
* **Cloud Run's request-size limit** (32 MiB on HTTP/1) is lower than the server's 50 MB upload cap. Not verified against a real deployment; see the plan, section 13.

## Rules this app keeps

* No credentials, tokens or API keys in the app. A bundle id is the only access control the backend has, so ids are never logged in release builds
  and nothing of this app goes into a cloud backup (`android:allowBackup="false"` plus explicit exclusion rules).
* Wording that states what the product is or is not ("indicative", "demo-curated", "decision support") is copied from the web UI, not paraphrased.
  The claim register is `docs/CLAIMS.md`; the app adds no performance or accuracy figures.
* The design tokens in `ui/theme/Color.kt` are the values of `frontend/app/globals.css`.
