# Curated reference data (reviewer checklist)

These tables drive the deterministic engines (`services/metallurgy.py`, `services/trade_remedies.py`,
`services/valuation.py`). They are **demo-curated**: written for the prototype from general knowledge, **not verified**,
and never presented by the application as official. Every table carries `rule_set` and `regulation_ref`, which the UI
shows next to the checks that use it.

**To verify a table:** correct the values, set `"verification"` to `{"status": "verified", "reviewer": "<name>",
"date": "<YYYY-MM-DD>"}`, and change `rule_set` from `demo-curated` to a label that says what it now is (for example
`verified-2026-11`). The assessment records a fingerprint of these files (`reference_data` on every iteration), so any
verdict can be tied to the exact tables it used. A malformed table stops the service at start-up
(`app/reference/loader.py`).

Run the checks after editing: `cd backend && .venv/bin/python -m pytest tests/unit/test_reference_data.py -q`.

| File | What it encodes | What to check |
|---|---|---|
| `hs_rules.json` | HS Chapter 72 **Note 1(f)** alloy-element thresholds; the stainless test (Note 1(e)); which 4- and 6-digit codes are non-alloy / stainless / alloy / either; the alloy "twin" subheading to suggest | Every threshold against the WCO HS text you work from; each `alloy_class_by_prefix` row against your tariff (national 8-digit schedules may split further) |
| `specs.json` | Heat-analysis limits and mechanical minimums for API 5L PSL1/PSL2 Gr B, ASTM A106 Gr B, ASTM A53 Gr B | **Every number**, against the edition of each standard you apply. The standards are paywalled; these were written from memory. The API 5L carbon-equivalent limit depends on wall thickness (thickness is not extracted: the check says so as an assumption) |
| `duty_rates.json` | India: BCD, SWS (on BCD), IGST; Singapore: customs duty, GST | Rates and the stacking rule (IGST base = assessable value + BCD + SWS + anti-dumping duty) against the current tariff and notifications |
| `valuation_defaults.json` | Freight and insurance as a % of FOB when the documents do not state them | The statutory defaults (India: customs valuation rules, 2007, rule 10) |
| `exchange_rates.json` | USD to INR and SGD | **Illustrative placeholders (`"illustrative": true`).** Replace with the destination customs authority's notified rate, its effective date and reference. For India the applicable rate is the one in force when the Bill of Entry is presented, not the Bill of Lading date |
| `anti_dumping.json` | One illustrative entry (China, heading 7304, India) | **The scope, origin and rate are placeholders and `notification_ref` is empty.** Real duties are product-, producer- and date-specific. Replace with verified entries |

## declaration_inputs.json

What a customs declaration typically needs that **no trade document carries** (importer / exporter codes, the declarant's licence, the
port, the valuation method, the exemption claim, the number assigned on filing), per destination, plus a default for other
destinations. The pre-fill pack lists them under `to_be_supplied`. They are typical, not authoritative: **verify each entry against the
current declaration form** and set the `verification` block. The declaration's name (`Import declaration (Bill of Entry)`) is
this table's wording, not an official one.

## Policy decisions the engines make (change them in code if you disagree)

1. **A certificate is read "as certified".** The alloy test (Note 1(f)) uses the elements the certificate reports. Elements a
   standard certificate does not report (for example B, Co, Pb, W, Zr) are named in the message as not reported, and are not
   treated as an assumption that would downgrade the result to a warning. If you want stricter behaviour, say so.
2. **Any heat decides.** If any heat on a certificate reaches a Note 1(f) threshold, the goods are treated as alloy steel.
3. **A standard's own tolerance is not Note 1(f).** ASTM A106 Gr B allows up to 0.40 % chromium; Note 1(f) makes a steel
   alloy at 0.30 %. A certificate can be inside its standard and still contradict a non-alloy HS code. The engine reports both.
4. **Anti-dumping findings are always a warning**, because the producer-specific rate and the exact scope need a specialist.
5. **The duty estimate never changes the assessment status.** It lists every assumption it made (rate source, statutory
   freight/insurance defaults, illustrative exchange rate) and is labelled indicative.
