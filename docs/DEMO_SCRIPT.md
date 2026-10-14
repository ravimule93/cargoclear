# Demo script and fallback ladder

How to show CargoClear, in what order, what to say, and what to do when the live stack does not cooperate. Every sentence in the
"say" column comes from [CLAIMS.md](CLAIMS.md) (the column "How to say it"); nothing here may be quoted above what that register allows.
Numbers come from [MEASURED_RESULTS.md](MEASURED_RESULTS.md) or are not said.

## 1. The ladder: decide in the first minute, announce the rung out loud

| Rung | What it shows | When to use it | Say |
|---|---|---|---|
| 1. Hosted live stack | Gemini reads the PDFs; Firestore, BigQuery and Cloud Storage | the preflight and one end-to-end run passed in the last hour | "This is the deployed stack." |
| 2. Local demo-mode stack | the whole workflow and every deterministic check; **synthetic extraction keyed on file names** | the hosted stack is down or slow | "This is demo mode: extraction is a stand-in, so what you are seeing is the workflow and the checks, not the model reading." |
| 3. Recorded walkthrough | the same screens, captioned with the mode | no network, no laptop stack | "This is a recording of the demo-mode stack." (or "of the live stack", per its `manifest.json`) |
| 4. The stills (`screens/`) | one image per step, captioned | the video will not play | the same sentence, per image |

Rules: never present rung 2 or 3 as rung 1; the demo banner and the recording's captions say which it is, and the manifest records it.
If a live run is slow, **say so** and switch to the recording while it finishes; do not talk over a spinner.

**Rehearsal numbers** (fill in after a live rehearsal; leave blank until then, and do not guess): slowest live analysis seen ______ s.
Switch rung when an analysis has run twice that long.

## 2. Ten minutes before

```bash
# the hosted stack
python3 scripts/preflight_gcp.py                      # Gemini and BigQuery accept the real request
python3 scripts/live_e2e_hosted.py --base-url "$UI_URL" --expect-mode live --case d --runs 1
# the fallback, ready on the laptop
scripts/record_demo.sh --no-video                     # proves the local stack works (stills only); or without --no-video for the video
```

Have open: the UI, `demo-recordings/<latest>/walkthrough.webm`, and [CLAIMS.md](CLAIMS.md) section 6 (what not to say).

## 3. The walkthrough (the recording follows the same 15 steps)

Case C is the "missing paper" story, Case D the "the paper contradicts the declaration" story. Case D is the stronger one: start
there if you have three minutes.

| # | On screen | Say |
|---|---|---|
| 1 | Home page | "A pre-submission assessment for the authorised agent. Decision support only: the agent decides." |
| 2 | Case C bundle: invoice, bill of lading, packing list | "India to Singapore. Three documents, no assessment yet." |
| 3 | `Missing Evidence` | "The product names what is missing: a Mill Test Certificate, which this HS code needs." |
| 4 | Certificate added: `Compliant For Submission` | "With the certificate, the bundle reassesses to compliant." |
| 5 | Reasoning Delta | "The delta says what changed between the two assessments and why: the new document is named." |
| 6 | Audit chain, `Chain verified` | "Every step is in a hash-chained audit trail." |
| 7 | Case D bundle (India import) | "An import into India, declared under a non-alloy HS code." |
| 8 | `Material Contradiction`; the certificate opens by itself, scrolled to the chemistry table, the green box on 0.35 | "Heat TH-77121 reads 0.35 % chromium. At 0.30 % or more, Chapter 72 Note 1(f) makes the steel alloy. The certificate is fine by its own standard; it contradicts the declaration." |
| 9 | Duty estimate card, "What this estimate assumed" | "Indicative, with every assumption listed. The rates are illustrative placeholders. It never changes the verdict and is never an amount payable." |
| 10 | The edit box on the chromium cell | "The agent checks the certificate and states what it prints. The model's reading stays on record." |
| 11 | `Pending recompute` | "Recorded in the audit trail. Nothing changes until the checks are re-run." |
| 12 | `Specialist Review Required` after Recompute | "No document is read again and no model is called. The anti-dumping warning remains, so it is not cleared." |
| 13 | Reasoning Delta names the correction | "The delta names the correction, the value it replaced and the reason." |
| 14 | Declaration pre-fill card | "Values for whoever keys the declaration, each with its source document and page. It says `NOT CLEARED` first. CargoClear's own format, not a government one." |
| 15 | Audit chain with `Head signed through #N` | "The head of the chain is signed with a key the database does not hold: tamper-evident under the operator's key. Not legal non-repudiation: there is no user authentication." |

## 4. What not to say (each is in CLAIMS.md as ASSUMED or DELETED)

* any speed, accuracy, saving, market-size or scale number that is not on the measured-results page; "hours to minutes"; "under 45 seconds";
* "zero hallucination", "adjudicates", "files", "clears", "approves", "legally binding", "non-repudiation";
* that the duty figure is right (the rates are placeholders), that it reads real scans, that it meets MeitY or uses CMEK;
* that it scales to N instances (it is built and tested on a fake; the default is one instance).

If asked about any of them, use the answers in [REDTEAM.md](REDTEAM.md) section 4.

## 5. Recording

```bash
scripts/record_demo.sh                                 # demo mode on this machine (needs `npx playwright install ffmpeg` once, for the video)
scripts/record_demo.sh --live https://<ui>.run.app     # the deployed stack, after the live runs have passed
scripts/record_demo.sh --no-video                      # stills and manifest only
```

Output: `demo-recordings/<mode>-<time>/` with `walkthrough.webm`, `screens/`, `steps.json` and `manifest.json` (mode, source commit, whether
the tree was uncommitted, the video's SHA-256, a caption per step). The folder is git-ignored; keep the video where the team keeps files.
Re-record after any change to the UI (the manifest records the commit it was made from). `--dwell 6000` slows the captions for a voice-over.
A recording is evidence of the interaction and the checks. Only a `--live` recording shows the model reading a document, and the
documents are synthetic samples either way.
