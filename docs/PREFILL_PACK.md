# Declaration pre-fill pack

The pre-fill pack is the values of one assessment, laid out for the person who keys the customs declaration: what the documents state,
where each value came from, what the *other* documents say, what needs a person's eyes, and what the declarant must still supply.

* **JSON** — `GET /api/v1/bundles/{id}/prefill` (`?iteration=N` for an older assessment, `?download=true` to receive it as a file).
* **PDF summary** — `GET /api/v1/bundles/{id}/prefill.pdf`: the same content as a printable A4, verdict first.
* **Schema** — [`docs/schemas/declaration-prefill.schema.json`](schemas/declaration-prefill.schema.json) (JSON Schema, generated from
  `backend/app/domain/prefill.py`; a test fails if the two drift). Current version: `1.0` (`schema_id: cargoclear.declaration-prefill`).

The workbench shows a **Declaration pre-fill** card with both downloads once an assessment exists.

## What it is not

* **Not a government format.** See [Government formats](#government-formats-deliberately-not-targeted) below.
* **Not a filed declaration, and never "ready to file".** A bundle that is not cleared says so in `banner`, first, and lists what blocks it.
* **Not a duty determination.** `valuation` is the assessment's indicative estimate, copied as it is, with its assumptions.

## Shape

| Block | What it holds |
|---|---|
| `banner` | `null` for a cleared bundle with every correction included. Otherwise: `NOT CLEARED` (status, contradictions, missing documents, items for review), and/or corrections made after this assessment that it does not include, and/or `SUPERSEDED` (a newer assessment exists). |
| `declaration` | What the destination calls the declaration, from the curated reference data (`declaration_inputs.json`, unverified until reviewed). |
| `assessment` | Iteration, status, run mode, data source; `blocking` (MATERIAL findings), `review` (WARN findings), `missing_documents`, `pending_corrections`. |
| `parties`, `shipment`, `commercial` | One **value** per declaration field (below). |
| `lines` | The commercial invoice's line items (else the packing list's): description, HS code, quantity, unit price and basis, line value, currency, net and gross weight. Lines are **not** joined across documents: there is no safe key. |
| `material` | The mill test certificate's specification and heat numbers (empty when the bundle has none). |
| `valuation` | The indicative duty estimate of the assessment. Never an amount payable. |
| `to_be_supplied` | What the declarant must supply and no trade document carries (for India: IEC, GSTIN, CHA code, port, valuation method, exemption claim, Bill of Entry number; for Singapore: UEN, declarant, permit type, payment, permit number). Curated, **unverified**. |
| `corrections` | The agent's corrections these values include (applied or skipped, with the value each replaced and the reason). |
| `documents` | The documents this assessment read, with file name, type, SHA-256 and size. |
| `provenance` | Number of audit events, the **head hash** of the audit chain when the pack was made, whether the chain verified, and the fingerprint of the reference tables used. |
| `integrity.content_sha256` | SHA-256 of the pack's canonical JSON with this block removed (below). |

### A value

```json
{
  "value": "25400", "unit": "KGS",
  "source": { "document_id": "doc-…", "filename": "case_d_bill_of_lading.pdf", "doc_type": "BILL_OF_LADING", "page": 1, "bbox": { … } },
  "confidence": 0.99,
  "corrected": false,
  "alternatives": [ { "document_id": "doc-…", "doc_type": "PACKING_LIST", "value": "25400", "unit": "KGS" } ],
  "conflict": false,
  "review": []
}
```

* `value` is **as printed**; `null` means no document states it (and `review` says so).
* `source` points at the document and, when the extraction located it, the page and box (0–1000, top-left origin).
* `corrected: true` means the agent corrected it (`confidence` is then 1.0).
* `alternatives` lists what the other documents state for the same field; `conflict` is true when they disagree.
* `review` is empty when nothing is flagged. Otherwise it says why a person should check the value: `documents disagree: …`,
  `read with confidence 0.80` (below the 0.95 auto-accept tier, and not corrected), `not stated on any document`, or
  `M-001 (material) cites this value` (an open finding of the assessment cites exactly this value).

### Which document a value comes from

The best source first; the others become `alternatives`. The pack never chooses silently between conflicting documents: it keeps
the preferred document's value, marks `conflict`, and says who disagrees.

| Field | Order of preference |
|---|---|
| consignee, consignor | commercial invoice, bill of lading, packing list |
| invoice / bill-of-lading / packing-list number | that document only |
| vessel, ports, shipment date | bill of lading, invoice, packing list |
| incoterm | invoice, bill of lading |
| country of origin | invoice, certificate of origin, packing list, mill test certificate |
| packages | packing list, bill of lading |
| gross weight | bill of lading, packing list |
| net weight | packing list, bill of lading |
| invoice value, invoice currency | invoice |
| freight, insurance (amount, currency) | invoice, bill of lading |

What counts as "the same": entity names compare without case and punctuation; numbers numerically; weights in kilograms within the
same tolerance as the weight check (the larger of 0.5 % and 5 kg); HS codes on their common digits; everything else without case
and extra spaces.

## Integrity

`integrity.content_sha256` is the SHA-256 of the pack's JSON **without** the `integrity` block, serialised with sorted keys and
compact separators (`json.dumps(body, sort_keys=True, separators=(",", ":"))`, UTF-8, ASCII-escaped). Anyone holding only the file can
recompute it; `scripts/live_e2e_hosted.py --case d --corrections` does exactly that against a live stack. `provenance.audit_head_hash`
ties the pack to the audit chain it was made from: if the trail has moved on since, the head differs.

Downloading a pack is a read. It writes nothing to the audit chain (a GET must not change state, and with no user authentication
"who downloaded it" would only ever be the literal `user`).

## Government formats: deliberately not targeted

The roadmap said to map onto a government format only once an official schema is confirmed to be available. As of 2026-10-14 it is **not confirmed**:

* **India (ICEGATE Bill of Entry).** Only secondary sources were found. They describe an EDI/XML-style Bill of Entry message
  (a "BE message format", versions cited as v2.x) and an "upload SB/BE XML" path on the portal. No official JSON schema or public API
  specification was located, and the official technical documents were not retrieved. Ask ICEGATE/CBIC (or an ICEGATE-certified
  software vendor or your Custom House Agent) for the current BE specification and any developer onboarding.
* **Singapore (TradeNet).** Singapore Customs' own page gives background only. Declarations are described as filed through an approved
  service provider (CrimsonLogic's TradeWeb); no public message specification was located.

So the pack uses plain, neutral names. A mapping is a small, separate step once a specification is in hand; the pack already carries
what such a mapping needs (value, unit, source, review state). Do not treat any field name here as an official one.

Sources (accessed 2026-10-14, secondary and unverified):
[ICEGATE BE message format overview](https://blog.credlix.com/complete-guide-to-icegate-be-message-format-v2-23-for-importers/) ·
[ICEGATE Bill of Entry filing guide](https://afleo.com/icegate-bill-of-entry-filing-guide/) ·
[Singapore Customs: TradeNet](https://www.customs.gov.sg/businesses/national-single-window/tradenet) ·
[TradeWeb (vendor documentation)](https://docs.fr8labs.co/s/home/doc/singapore-tradeweb-Z4NgIFR46P.md).

## The PDF summary

Verdict first (the banner, red when not cleared), then parties, shipment, commercial, lines, the certificate, the duty estimate, the
findings to resolve, the agent's corrections, what the declarant must supply, and the source documents with their SHA-256 and the
audit head. The footer carries the pack hash.

The PDF uses the standard PDF fonts, which cover Latin-1 only: other characters (a Chinese company name, the rupee sign) print as `?`
in the PDF. The JSON keeps them exactly. The footer says so. Streams are uncompressed (a few kilobytes more) so the text can be checked
without a PDF library.

## Changing the format

Edit `backend/app/domain/prefill.py`, bump `SCHEMA_VERSION` for any change a consumer could notice, regenerate the schema
(`UPDATE_PREFILL_SCHEMA=1 pytest tests/unit/test_prefill_schema.py`) and say so in `Handoff.md`.
