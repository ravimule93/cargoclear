# CargoClear-JAPAC product summary

CargoClear is a pre-submission customs-document assessment aid for JAPAC trade bundles. It helps an authorised Custom House Agent inspect evidence, deterministic checks, and reasoning changes before the agent makes the final decision.

It is not a government-submission tool, a duty **collection or payment** system, a legal decision-maker, a supplier-risk scorer, or an authentication/SSO product. Authentication and SSO remain out of scope for this MVP.

It does produce an **indicative duty estimate**: an assessable value (transaction value adjusted to CIF through the Incoterm, freight and insurance) and the duties on it for the destination (India: BCD, SWS, anti-dumping duty where an entry applies, IGST; Singapore: GST). The estimate is information for the authorised agent. It lists every assumption it made (statutory freight/insurance defaults, the exchange rate, unverified rates), it never changes the assessment status, and it is never an amount payable.

## What may be claimed

Every claim about the product is labelled in [docs/CLAIMS.md](docs/CLAIMS.md) (PROVEN with evidence, STUBBED, ASSUMED); every measured number is in [docs/MEASURED_RESULTS.md](docs/MEASURED_RESULTS.md), generated from recorded runs. Nothing about speed, accuracy or savings appears anywhere else.

## User experience

The workbench is an investigator interface, not a chatbot: document rail, original-PDF viewer with evidence overlays, assessment panel, and Reasoning Delta/Audit Chain drawer.

The API returns one of four statuses:

- `COMPLIANT_FOR_SUBMISSION`
- `MISSING_EVIDENCE`
- `MATERIAL_CONTRADICTION`
- `SPECIALIST_REVIEW_REQUIRED`

The status is advisory. It does not assert that goods are legal or ready for a government submission.

## Corrections and the declaration pre-fill

- **Corrections.** The authorised agent can state what a document actually says: edit a value in place on an evidence row (a header field, a line-item field, a heat number, a certificate cell, or the document type), or confirm the model's reading. Every entry is audited (who, what, the value it replaced, why) and **nothing changes until Recompute**. A recompute reuses the stored extraction (no document is read again, no model is called), lays the corrections over it and runs every check again; a reassessment after a new upload keeps them. A correction can be undone; the history is never edited. A value is refused when the engines could not read it without guessing (an ambiguous number, a weight without a unit).
- **Declaration pre-fill.** The values of an assessment for the person who keys the declaration, as documented JSON and a printable PDF: each value with its source document and page, what the other documents state, whether it was corrected, and why a person should look at it. A bundle that is not cleared says so first. It is CargoClear's own format, not a government one, and never "ready to file".

## Integrity and scale

- **A signed audit trail.** Every assessment ends by signing the head of the hash-chained audit trail with a key the database does not hold. If the whole history is rewritten consistently the signature no longer matches and the UI says so. The wording is deliberate: *tamper-evident under the operator's key*, not legal non-repudiation (there is no user authentication, so the signer is the service).
- **What the model saw.** The page image the extraction was shown is kept, and the viewer links to it; a page that was straightened says so, and evidence boxes are mapped back onto the original page.
- **Runs survive instance loss.** Behind the scenes a run belongs to a lease on its bundle: two instances cannot analyse one bundle, a run whose executor died is taken over, and a paused executor cannot overwrite a newer one's work.

## What it checks

- **Weights and codes:** packing list vs bill of lading gross (W-001), packing list consistency (W-002), HS consistency across documents (H-002, H-003-*), tariff grounding (G-001), entity alignment (E-*).
- **Invoice arithmetic:** quantity × unit price = line total (I-001), invoice total = sum of lines (I-002), one currency throughout (I-003).
- **The certificate against the declaration:** alloy status under HS Chapter 72 Note 1(f) against the declared code (M-001); carbon equivalent against the certificate's standard (M-002); chemistry and strength limits of that standard (M-003); every heat on the packing list covered by a certificate (M-004).
- **Origin and trade remedies:** the country of origin agrees across documents (E-origin); a value just under an alloy threshold on a non-alloy declaration (SEC-001); anti-dumping duty that may apply (SEC-002).

The rules behind M-*, SEC-* and the duty estimate are curated tables (`backend/app/reference/`), labelled `demo-curated` and unverified until a reviewer replaces that label. Every check that uses one names it. A result that rests on an assumption is a warning, never a pass.

## Choosing where the goods are going

A bundle has a destination (Singapore or India); the checks and the duty estimate depend on it. Demo mode creates the right one for each demo. On a live stack, choose it on the home page before creating an empty bundle and upload the documents. With no document chosen, the viewer opens the one the first material finding is about.

## Case C demo

The supported browser journey starts at `/`; it does not use a hardcoded bundle URL.

1. Select **Start Case C demo**. This creates a new bundle containing the Invoice, Bill of Lading, and Packing List.
2. Run analysis. The bundle reaches `MISSING_EVIDENCE`, including the Mill Test Certificate requirement for the Case C HS classification.
3. Select **Use sample MTC (demo)**. The document is added and the bundle reassesses to `COMPLIANT_FOR_SUBMISSION`.
4. Inspect the Reasoning Delta and the hash-verified Audit Chain.

In demo mode, extraction is synthetic and keyed by document filename. The UI states this explicitly; the sample PDFs are illustrative, not proof that live document reading occurred.

## Case D demo (an India import)

1. On `/`, select **Start Case D demo (India import)**. The new bundle holds all four documents for Chinese-origin seamless tubes declared under the non-alloy HS code 7304.31.00.
2. Run analysis. The bundle reaches `MATERIAL_CONTRADICTION`: heat `TH-77121` reports 0.35 % chromium, at or above the 0.30 % at which HS Note 1(f) makes a steel alloy, although the certificate satisfies its own standard (ASTM A106 allows 0.40 %).
3. Read the anti-dumping warning (`SEC-002`) and the **Indicative duty exposure** card: value → CIF → BCD, SWS, anti-dumping duty, IGST, with the same estimate under the subheading the chemistry points to, and the list of what was assumed.

All names, numbers and rates in the demo documents and tables are invented or illustrative.

## Evidence provenance

The backend records preprocessing metadata per evidence document. It renders extraction pages at 200 DPI (1-bit B&W by default; 8-bit grayscale with `PAGE_IMAGE_MODE=gray`), turns a sideways page by a quarter turn when the evidence is strong, optionally straightens a skewed page (`PREPROCESS_DESKEW`, off by default), and records source-page/artifact provenance. Large inputs are materialized as sequential artifacts when the configured page or size threshold applies. Whether grayscale or straightening improves extraction on the real model is **not yet measured**: the A/B is tooled and waits for a live run (`docs/GCP_VERIFICATION.md`, section 11).

The viewer displays the original PDF and maps processed evidence boxes back using the persisted transform metadata endpoint:

`GET /api/v1/bundles/{bundle_id}/documents/{document_id}/transform-metadata`

The endpoint returns `{ "document_id": "…", "transform_meta": [ … ] }` through the existing scoped API/proxy flow. Storage URIs and credentials are not exposed to the browser.

A straightened page records a reversible, aspect-aware `processed_to_source_affine` (composed with the rotation), and the viewer maps every evidence box through it onto the original page. Rotation and identity transforms are supported; absent/unknown metadata safely preserves the existing coordinates. The exact page image the model was shown is kept and linked from the viewer ("What the model saw").

## Multi-document capacity and scaling

CargoClear is not restricted to a fixed 4-document bundle. The bundle capacity is configurable via `MAX_DOCUMENTS_PER_BUNDLE` (defaulting to 20 documents). The engine dynamically checks entity alignment (`E-consignee`, `E-consignor`, `E-vessel`) across all uploaded documents, flags duplicate document types with non-blocking warnings (`D-DUP-<DOCTYPE>`), and dynamically checks all uploaded certificates (`H-003-<DOCTYPE>`).

## Investigator UI features

- **Document Attribution**: Every discrepancy or check highlights exactly which documents and values were compared, complete with page citations.
- **Visual Gaps**: Missing evidence or omitted fields are tagged with explicit gap badges.
- **Document Rail Badges**: Visual health indicators per document (`● Conflicts`, `▲ Gaps`, `✓ Clean`).
- **Bounding Box Tooltips**: Canvas overlays feature interactive tooltips displaying field name and confidence.
- **Drawer Controls**: Collapsible and expandable Reasoning Delta drawer.

## Demo and live modes

- `APP_MODE=demo` uses local/in-memory fallbacks and exposes the Case C endpoints. No GCP credentials are required for the intended local journey.
- `APP_MODE=live` disables demo endpoints and requires real GCS, Firestore, BigQuery, and Gemini access through a credential source or Cloud Run service identity. Live mode never falls back to synthetic extraction fixtures.

