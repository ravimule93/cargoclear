# CargoClear-JAPAC product summary

CargoClear is a pre-submission customs-document assessment aid for JAPAC trade bundles. It helps an authorised Custom House Agent inspect evidence, deterministic checks, and reasoning changes before the agent makes the final decision.

It is not a government-submission tool, duty/payment system, legal decision-maker, supplier-risk scorer, or authentication/SSO product. Authentication and SSO remain out of scope for this MVP.

## User experience

The workbench is an investigator interface, not a chatbot: document rail, original-PDF viewer with evidence overlays, assessment panel, and Reasoning Delta/Audit Chain drawer.

The API returns one of four statuses:

- `COMPLIANT_FOR_SUBMISSION`
- `MISSING_EVIDENCE`
- `MATERIAL_CONTRADICTION`
- `SPECIALIST_REVIEW_REQUIRED`

The status is advisory. It does not assert that goods are legal or ready for a government submission.

## Case C demo

The supported browser journey starts at `/`; it does not use a hardcoded bundle URL.

1. Select **Start Case C demo**. This creates a new bundle containing the Invoice, Bill of Lading, and Packing List.
2. Run analysis. The bundle reaches `MISSING_EVIDENCE`, including the Mill Test Certificate requirement for the Case C HS classification.
3. Select **Use sample MTC (demo)**. The document is added and the bundle reassesses to `COMPLIANT_FOR_SUBMISSION`.
4. Inspect the Reasoning Delta and the hash-verified Audit Chain.

In demo mode, extraction is synthetic and keyed by document filename. The UI states this explicitly; the sample PDFs are illustrative, not proof that live document reading occurred.

## Evidence provenance

The backend records preprocessing metadata per evidence document. It renders processed extraction pages at 200 DPI in 1-bit B&W, conservatively applies confident 0/90/180/270-degree orientation fixes, and records source-page/artifact provenance. Large inputs are materialized as sequential artifacts when the configured page or size threshold applies.

The viewer displays the original PDF and maps processed evidence boxes back using the persisted transform metadata endpoint:

`GET /api/v1/bundles/{bundle_id}/documents/{document_id}/transform-metadata`

The endpoint returns `{ "document_id": "…", "transform_meta": [ … ] }` through the existing scoped API/proxy flow. Storage URIs and credentials are not exposed to the browser.

Deskew detection is diagnostic today: `deskew_applied` remains false because a reversible deskew mapping is not yet persisted. Rotation and identity transforms are supported; absent/unknown metadata safely preserves the existing coordinates.

## Demo and live modes

- `APP_MODE=demo` uses local/in-memory fallbacks and exposes the Case C endpoints. No GCP credentials are required for the intended local journey.
- `APP_MODE=live` disables demo endpoints and requires real GCS, Firestore, BigQuery, and Gemini access through a credential source or Cloud Run service identity. Live mode never falls back to synthetic extraction fixtures.
