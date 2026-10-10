# Product.md — CargoClear-JAPAC

**Pre-submission adversarial customs adjudicator** for JAPAC cross-border trade (Google Cloud AI Builder Cup 2026). Decision support only: the authorised customs house agent (CHA) decides.

## What it does
Given a bundle of trade documents (commercial invoice, bill of lading, packing list, certificates…), it extracts fields with provenance (value, confidence, bounding box), runs deterministic checks (weight parity W-001, HS-code consistency H-002, entity alignment), grounds the declared HS code against the tariff, and returns one of four statuses:
`COMPLIANT_FOR_SUBMISSION` · `MISSING_EVIDENCE` · `MATERIAL_CONTRADICTION` · `SPECIALIST_REVIEW_REQUIRED`.
Every state change is appended to a SHA-256 hash-chained audit log; each reassessment produces a Reasoning Delta explaining what changed and why.

## The workbench (investigator layout, not chat)
Top bar (bundle, status pill, Add Document, Run analysis / Reassess) · Document rail · PDF viewer with evidence boxes · Assessment panel · Drawer with Reasoning Delta and Audit Chain tabs.

## Demo journey — Case C (works in a browser with no GCP credentials)
1. `/` → **Start Case C demo** (or **New empty bundle**).
2. Workbench opens with Invoice, Bill of Lading, Packing List; panel says *No assessment yet*.
3. **Run analysis** → status *Missing Evidence*; W-001 and H-002 pass; a Mill Test Certificate is required for HS 7304.19.00. W-001 boxes sit on the printed weights on the Bill of Lading and Packing List.
4. **Use sample MTC (demo)** (or upload your own) → automatic reassessment → *Compliant For Submission*; the Reasoning Delta names `mtc_pipe_test_cert.pdf`.
5. **Audit Chain Timeline** shows the real events and *Chain verified*.

## Honesty rules
- **Demo mode extracts from synthetic fixtures keyed on the filename, not by reading the document.** A persistent banner says so: "DEMO MODE - extraction uses synthetic fixtures keyed on filename, not a real document reading." The sample PDFs are generated from the same fixture values (and say "Synthetic sample … not a real shipping document").
- The UI never invents data: missing data is shown as loading, empty, not-found or error. If the backend is down the page shows only the error and Retry.
- Live mode (`APP_MODE=live` + GCP credentials) uses Gemini 2.5 Flash, Firestore, GCS and BigQuery vector search; demo endpoints return 404 there.

## Known product limits (see Handoff.md)
Run progress is real but the demo pipeline finishes faster than the 1 s stream poll, so stages usually flash by; below 1280 px the workbench has no tab navigation yet; Playwright specs are stale.
