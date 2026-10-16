#!/usr/bin/env python3
"""Live smoke test for the Gemini extraction path. Run by a PERSON with Google Cloud credentials, never by CI.

    cd backend
    APP_MODE=live .venv/bin/python ../scripts/live_smoke_extraction.py [options]

It sends the four Case C sample PDFs (fixtures/case_c) through the REAL pipeline stages
(``preprocess.run`` then ``run_extraction_agent``: real Vertex AI, real money, a few cents) and compares what
Gemini read with what the PDFs actually print. The expected values are not duplicated here: the PDFs are drawn
from ``extraction._generate_fixture_for_file``, so that is the single source of truth for values AND boxes.

    synthetic Case C documents only: do not run it on real customer documents

Credentials: any ONE of GOOGLE_APPLICATION_CREDENTIALS (service-account key file), the file written by
``gcloud auth application-default login``, or a Cloud Run service identity. The script refuses to run (exit 2)
unless APP_MODE=live and credentials are present. It never prints credential content.

Options:
  --docs PDF [PDF ...]   PDFs to send (default: every PDF in fixtures/case_c). Only files inside fixtures/case_c or
                         fixtures/case_d have expectations; any other file is extracted and reported but cannot pass or fail.
  --runs N               repeat N times and report field-level agreement across runs (default 1)
  --page-mode bw|gray    the A/B of the model's INPUT: 1-bit (the original) against 8-bit grayscale. Run both on the same files
                         (the degraded ones from scripts/make_degraded_scans.py are the interesting set) and compare the two
                         reports with scripts/compare_smoke_reports.py.
  --deskew               straighten skewed pages first (PREPROCESS_DESKEW); compare with and without
  --as-fixtures          grade degraded copies by FILE NAME against the fixtures (their printed values are the same)
  --overlay              save each page with the extracted (red) and expected (green) boxes drawn on it, to
                         <out>/overlays/<doc>.page<N>.png (needs PNG pages, i.e. poppler installed)
  --dry-run              build the exact request and print it; ZERO network calls, credentials are not read
  --out DIR              where report-<UTC timestamp>.json (and overlays) go (default backend/data/live_smoke)

Exit code: 0 only if every doc_type is right and every HS-code and weight expectation is met on every run.
Bounding-box quality and confidence are reported but do not gate. 2 = refused to run (not live / no credentials).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
CASE_C_DIR = REPO_ROOT / "fixtures" / "case_c"
CASE_D_DIR = REPO_ROOT / "fixtures" / "case_d"
FIXTURE_DIRS = (CASE_C_DIR, CASE_D_DIR)
DEFAULT_OUT_DIR = BACKEND_DIR / "data" / "live_smoke"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents import extraction  # noqa: E402
from app.core import mode  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.domain.countries import country_code  # noqa: E402
from app.domain.hs import hs_match_level  # noqa: E402
from app.domain.measures import canonical_parameter, normalize_heat, parse_measure, to_mpa  # noqa: E402
from app.domain.schemas import BBox, ExtractedDocument, FieldRef, LabResult, LineItem  # noqa: E402
from app.domain.units import parse_number, to_kg, trailing_unit  # noqa: E402
from app.gateway.errors import CargoClearError  # noqa: E402
from app.services import calculation, preprocess  # noqa: E402

WEIGHT_TOLERANCE = 0.005  # 0.5 %
BANNER = "synthetic Case C documents only: do not run it on real customer documents"
POPPLER_HINT = "install poppler (macOS: brew install poppler; Debian/Ubuntu: apt-get install poppler-utils)"

# (field, kind, gates the exit code). Only fields the fixture actually carries become expectations.
HEADER_FIELDS = (
    ("document_number", "text", False),
    ("consignee", "entity", False),
    ("consignor", "entity", False),
    ("hs_code_header", "hs", True),
    ("total_net_weight_kg", "weight", True),
    ("total_gross_weight_kg", "weight", True),
    ("tare_weight_kg", "weight", True),
    # material evidence and terms of sale: the certificate's standard, the origin (it decides anti-dumping), the Incoterm
    ("specification", "text", True),
    ("country_of_origin", "country", True),
    ("incoterm", "text", False),
)
LINE_FIELDS = (
    ("hs_code_declared", "hs", True),
    ("net_weight_kg", "weight", True),
    ("gross_weight_kg", "weight", True),
)


# ---------------------------------------------------------------------------
# expectations and comparison (pure)
# ---------------------------------------------------------------------------


@dataclass
class Expectation:
    name: str                    # "doc_type", "consignee", "line_items[0].hs_code_declared", ...
    kind: str                    # doc_type | text | entity | hs | weight | heat | country | lab
    gating: bool
    expected: Any                # a FieldRef, or the doc_type string
    path: tuple[str | int, ...]  # where to find it in an ExtractedDocument


def build_expectations(expected: ExtractedDocument) -> list[Expectation]:
    out = [Expectation("doc_type", "doc_type", True, expected.doc_type, ("doc_type",))]
    for name, kind, gating in HEADER_FIELDS:
        ref = getattr(expected, name, None)
        if isinstance(ref, FieldRef) and ref.value is not None:
            out.append(Expectation(name, kind, gating, ref, (name,)))
    for index, ref in enumerate(expected.heat_numbers):
        if ref.value is not None:
            out.append(Expectation(f"heat_numbers[{index}]", "heat", True, ref, ("heat_numbers", ("heat", normalize_heat(ref.value)))))
    for row in expected.test_results:
        # matched by (heat, parameter), not by position: the model may list the rows in another order
        key = ("lab", normalize_heat(row.heat_number), canonical_parameter(row.parameter))
        out.append(Expectation(f"test_results[{row.heat_number}.{row.parameter}]", "lab", True, row, ("test_results", key)))
    for index, item in enumerate(expected.line_items):
        for name, kind, gating in LINE_FIELDS:
            ref = getattr(item, name, None)
            if isinstance(ref, FieldRef) and ref.value is not None:
                out.append(Expectation(f"line_items[{index}].{name}", kind, gating, ref, ("line_items", index, name)))
    return out


def locate(doc: ExtractedDocument, path: tuple[str | int, ...]) -> Any:
    """The value at ``path`` in an extracted document, or None if it is not there."""
    node: Any = doc
    for step in path:
        if isinstance(step, tuple):  # ("heat", normalized) or ("lab", normalized heat, canonical parameter): find a list entry by key
            rows = node if isinstance(node, list) else []
            if step[0] == "heat":
                node = next((r for r in rows if normalize_heat(r.value) == step[1]), None)
            else:
                node = next((r for r in rows if normalize_heat(r.heat_number) == step[1] and canonical_parameter(r.parameter) == step[2]), None)
        elif isinstance(step, int):
            node = node[step] if isinstance(node, list) and step < len(node) else None
        else:
            node = getattr(node, step, None)
        if node is None:
            return None
    return node


def show(ref: Any) -> str:
    if ref is None:
        return "-"
    if isinstance(ref, str):
        return ref
    unit = getattr(ref, "unit", None)
    return "-" if ref.value is None else f"{ref.value} {unit}".strip() if unit else str(ref.value)



def weight_kg(ref: FieldRef) -> tuple[float | None, str]:
    """Kilograms for a weight reference (unit as extracted, else printed inside the value), and any note."""
    parsed = parse_number(ref.value)
    if parsed is None:
        return None, f"unreadable weight {ref.value!r}"
    quantity = to_kg(parsed.value, getattr(ref, "unit", None) or trailing_unit(ref.value))
    if quantity.error:
        return None, quantity.error
    return quantity.kg, "; ".join([*parsed.assumptions, *quantity.assumptions])


def _squash(text: Any) -> str:
    return re.sub(r"\s+", "", str(text)).casefold()


def compare(expectation: Expectation, actual: Any) -> tuple[str, str]:
    """(status, note) with status OK / MISMATCH / MISSING."""
    if expectation.kind == "doc_type":
        return ("OK", "") if actual == expectation.expected else ("MISMATCH", "")
    if actual is None or actual.value is None or not str(actual.value).strip():
        return "MISSING", ""
    expected = expectation.expected
    if expectation.kind == "hs":
        return ("OK", "") if hs_match_level(actual.value, str(expected.value)) == "exact8" else ("MISMATCH", "")
    if expectation.kind == "weight":
        want, _ = weight_kg(expected)
        got, note = weight_kg(actual)
        if want is None or got is None:
            return "MISMATCH", note
        return ("OK", note) if abs(got - want) <= WEIGHT_TOLERANCE * abs(want) else ("MISMATCH", note or f"{got:g} kg")
    if expectation.kind == "heat":
        return ("OK", "") if normalize_heat(actual.value) == normalize_heat(expected.value) else ("MISMATCH", "")
    if expectation.kind == "country":
        want, got = country_code(expected.value), country_code(actual.value)
        return ("OK", "") if want is not None and want == got else ("MISMATCH", "")
    if expectation.kind == "lab":
        return _compare_lab(expected, actual)
    if expectation.kind == "entity":
        same = calculation.normalize_entity_name(str(actual.value)) == calculation.normalize_entity_name(str(expected.value))
        return ("OK", "") if same else ("MISMATCH", "")
    return ("OK", "") if _squash(actual.value) == _squash(expected.value) else ("MISMATCH", "")


def _lab_value(row: LabResult) -> tuple[float | None, str, str]:
    """(number, bound, problem) of a certificate value: chemistry in weight %, strengths in MPa."""
    if canonical_parameter(row.parameter) in ("YS", "UTS"):
        parsed = parse_number(row.value)
        if parsed is None:
            return None, "exact", f"unreadable {row.value!r}"
        measure = to_mpa(parsed.value, row.unit)
    else:
        measure = parse_measure(row.value, row.unit)
    return measure.value, measure.bound, measure.error or ""


def _compare_lab(expected: LabResult, actual: LabResult) -> tuple[str, str]:
    """A certificate value matches when it reads the same number (after unit conversion) with the same bound."""
    want, want_bound, _ = _lab_value(expected)
    got, got_bound, problem = _lab_value(actual)
    if got is None or want is None:
        return "MISMATCH", problem or "unreadable"
    # chemistry is printed and compared as-is (exact); a strength may come back in another unit, so it matches within the
    # rounding of that conversion (0.1 %)
    tolerance = 1e-3 * abs(want) if canonical_parameter(expected.parameter) in ("YS", "UTS") else 1e-9 * max(1.0, abs(want))
    if want_bound != got_bound or abs(got - want) > tolerance:
        return "MISMATCH", f"read {actual.value} {actual.unit or ''}".strip()
    return "OK", ""


def iou(a: BBox, b: BBox) -> float:
    """Intersection over union of two 0-1000 boxes; 0 if they are on different pages."""
    if a.page != b.page:
        return 0.0
    width = max(0.0, min(a.xmax, b.xmax) - max(a.xmin, b.xmin))
    height = max(0.0, min(a.ymax, b.ymax) - max(a.ymin, b.ymin))
    inter = width * height
    union = (a.xmax - a.xmin) * (a.ymax - a.ymin) + (b.xmax - b.xmin) * (b.ymax - b.ymin) - inter
    return inter / union if union > 0 else 0.0


def all_refs(doc: ExtractedDocument) -> list[FieldRef]:
    refs: list[FieldRef] = [getattr(doc, n) for n in ExtractedDocument.model_fields if isinstance(getattr(doc, n), FieldRef)]
    refs += list(doc.heat_numbers) + list(doc.test_results)
    for item in doc.line_items:
        refs += [getattr(item, n) for n in LineItem.model_fields if isinstance(getattr(item, n), FieldRef)]
    return refs


def bbox_stats(doc: ExtractedDocument) -> dict[str, Any]:
    """How many populated fields carry a box, and whether the coordinates look like the 0-1000 convention."""
    populated = [r for r in all_refs(doc) if r.value is not None]
    boxed = [r.bbox for r in populated if r.bbox is not None]
    coords = [c for b in boxed for c in (b.ymin, b.xmin, b.ymax, b.xmax)]
    return {
        "populated_fields": len(populated),
        "with_bbox": len(boxed),
        "bbox_pct": round(100 * len(boxed) / len(populated), 1) if populated else 0.0,
        "coord_min": min(coords) if coords else None,
        "coord_max": max(coords) if coords else None,
        "scale_suspect": bool(coords) and max(coords) <= 1.0,  # 0-1 floats instead of 0-1000
    }


def check_document(
    expectations: list[Expectation], actual: ExtractedDocument
) -> dict[str, Any]:
    """Compare one extraction with its expectations; returns rows plus the document-level figures."""
    rows: list[dict[str, Any]] = []
    for e in expectations:
        found = locate(actual, e.path)
        status, note = compare(e, found)
        overlap = None
        if isinstance(e.expected, FieldRef) and e.expected.bbox is not None and found is not None and found.bbox is not None:
            overlap = round(iou(found.bbox, e.expected.bbox), 3)
        rows.append({
            "name": e.name,
            "kind": e.kind,
            "gating": e.gating,
            "expected": show(e.expected),
            "extracted": show(found) if not isinstance(found, str) else found,
            "confidence": getattr(found, "confidence", None) if not isinstance(found, str) else actual.doc_type_confidence,
            "status": status,
            "note": note,
            "iou": overlap,
            "page_ok": (
                None if overlap is None or not isinstance(e.expected, FieldRef)
                else found.bbox.page == e.expected.bbox.page
            ),
        })
    overlaps = [r["iou"] for r in rows if r["iou"] is not None]
    confidences = [r["confidence"] for r in rows if r["confidence"] is not None and r["status"] != "MISSING"]
    return {
        "rows": rows,
        "failed": [r["name"] for r in rows if r["gating"] and r["status"] != "OK"],
        "doc_type_confidence": actual.doc_type_confidence,
        "line_items": len(actual.line_items),
        "bbox": bbox_stats(actual),
        "iou_mean": round(sum(overlaps) / len(overlaps), 3) if overlaps else None,
        "lowest_expected_confidence": min(confidences) if confidences else None,
    }


# ---------------------------------------------------------------------------
# running
# ---------------------------------------------------------------------------


@dataclass
class SmokeDoc:
    path: Path
    document_id: str
    raw: bytes
    expected: ExtractedDocument | None

    @property
    def filename(self) -> str:
        return self.path.name


def load_documents(paths: list[Path], *, as_fixtures: bool = False) -> list[SmokeDoc]:
    """The documents to send. A file has expectations when it sits in fixtures/case_c or fixtures/case_d, or (``as_fixtures``,
    for degraded copies of them made by scripts/make_degraded_scans.py) when its NAME is a fixture's: the values printed on a
    degraded scan are the same, only its quality is worse."""
    docs = []
    for path in paths:
        document_id = f"smoke-{path.stem}"
        known = path.resolve().parent in {d.resolve() for d in FIXTURE_DIRS} or (
            as_fixtures and any((d / path.name).is_file() for d in FIXTURE_DIRS)
        )
        expected = extraction._generate_fixture_for_file(document_id, path.name) if known else None
        docs.append(SmokeDoc(path=path, document_id=document_id, raw=path.read_bytes(), expected=expected))
    return docs


def refusal_reason() -> str | None:
    """Why the script must not run, or None. Never reads any credential."""
    if settings.app_mode != "live":
        return "APP_MODE is not 'live'. This script calls the real Gemini endpoint: run it as  APP_MODE=live ..."
    if not mode.use_live_gcp():
        return mode.no_credentials_message()  # also names a GOOGLE_APPLICATION_CREDENTIALS path that does not exist
    return None


def thinking_description() -> str:
    """What the extraction request sends for thinking with the configured model (the budget or the level, or that nothing is sent)."""
    from google.genai import types

    return extraction.describe_thinking(types, settings.gemini_live_model)


def sdk_version() -> str:
    try:
        from google import genai

        return str(getattr(genai, "__version__", "unknown"))
    except Exception as exc:  # noqa: BLE001
        return f"unavailable ({type(exc).__name__})"


def environment(page_source: str | None) -> dict[str, Any]:
    return {
        "project": settings.project_id,
        "location": settings.gemini_live_location,
        "model": settings.gemini_live_model,
        "sdk_version": sdk_version(),
        "credential_source": mode.credential_source(),
        "pages": page_source,
        "timeout_seconds": settings.gemini_timeout_seconds,
        "max_attempts": settings.gemini_max_attempts,
        "thinking_budget": settings.gemini_thinking_budget,
        "thinking": thinking_description(),
        "page_image_mode": settings.page_image_mode,
        "preprocess_deskew": settings.preprocess_deskew,
        "max_output_tokens": settings.gemini_max_output_tokens,
    }


def page_source_of(pages: list[dict[str, Any]]) -> str:
    return "png" if pages and all(p.get("mime") == "image/png" for p in pages) else "passthrough"


async def extract_once(doc: SmokeDoc) -> dict[str, Any]:
    """preprocess.run then run_extraction_agent for one PDF. No bundle_id: nothing touches Firestore or GCS."""
    prepared = await preprocess.run({"raw_bytes": doc.raw, "bundle_id": "", "document_id": doc.document_id})
    pages = prepared.get("processed_pages", [])
    result: dict[str, Any] = {"page_source": page_source_of(pages), "pages": len(pages), "_pages": pages}
    ctx = {
        "bundle_id": "",
        "documents": [{"document_id": doc.document_id, "filename": doc.filename}],
        "processed_pages": pages,
    }
    try:
        ctx = await extraction.run_extraction_agent(ctx)
    except CargoClearError as exc:
        result["error"] = {"type": type(exc).__name__, "message": exc.message, "detail": exc.detail}
        return result

    [extracted] = ctx["extracted"]
    stats = (ctx.get("extraction_stats") or [{}])[0]
    result.update(
        _extracted=extracted,
        stats={k: stats.get(k) for k in ("attempts", "latency_ms", "prompt_tokens", "output_tokens")},
        warnings=ctx.get("extraction_warnings", []),
    )
    if doc.expected is not None:
        result["check"] = check_document(build_expectations(doc.expected), extracted)
    else:
        result["check"] = None
        result["bbox"] = bbox_stats(extracted)
    return result


def agreement(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Field-level agreement across runs: the share of fields whose extracted value is identical every time."""
    names: dict[str, set[str]] = {}
    for run in runs:
        for row in (run.get("check") or {}).get("rows", []):
            names.setdefault(row["name"], set()).add(f"{row['extracted']}")
    disagreeing = sorted(n for n, seen in names.items() if len(seen) > 1)
    total = len(names)
    return {
        "fields": total,
        "identical_every_run": total - len(disagreeing),
        "pct": round(100 * (total - len(disagreeing)) / total, 1) if total else None,
        "disagreeing": {n: sorted(names[n]) for n in disagreeing},
    }


def draw_overlay(png: bytes, extracted: list[tuple[str, BBox]], expected: list[tuple[str, BBox]], page: int, out: Path) -> None:
    from PIL import Image, ImageDraw

    image = Image.open(io.BytesIO(png)).convert("RGB")
    width, height = image.size
    draw = ImageDraw.Draw(image)
    for boxes, colour, labelled in ((expected, (0, 160, 0), False), (extracted, (220, 0, 0), True)):
        for label, box in boxes:
            if box.page != page:
                continue
            rect = [box.xmin / 1000 * width, box.ymin / 1000 * height, box.xmax / 1000 * width, box.ymax / 1000 * height]
            draw.rectangle(rect, outline=colour, width=2)
            if labelled:
                draw.text((rect[0] + 2, max(0.0, rect[1] - 11)), label, fill=colour)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def save_overlays(doc: SmokeDoc, run: dict[str, Any], out_dir: Path) -> list[Path]:
    extracted: ExtractedDocument = run["_extracted"]
    shown = [(n, r.bbox) for n, r in _named_refs(extracted) if r.bbox is not None and r.value is not None]
    wanted = (
        [(e.name, e.expected.bbox) for e in build_expectations(doc.expected)
         if isinstance(e.expected, FieldRef) and e.expected.bbox is not None]
        if doc.expected is not None else []
    )
    written = []
    for number, page in enumerate(run["_pages"], start=1):
        target = out_dir / "overlays" / f"{doc.path.stem}.page{number}.png"
        draw_overlay(page["payload"], shown, wanted, number, target)
        written.append(target)
    return written


def _named_refs(doc: ExtractedDocument) -> list[tuple[str, FieldRef]]:
    named = [(n, getattr(doc, n)) for n in ExtractedDocument.model_fields if isinstance(getattr(doc, n), FieldRef)]
    for index, item in enumerate(doc.line_items):
        named += [(f"line_items[{index}].{n}", getattr(item, n)) for n in LineItem.model_fields
                  if isinstance(getattr(item, n), FieldRef)]
    return named


# ---------------------------------------------------------------------------
# printing
# ---------------------------------------------------------------------------


def print_environment(env: dict[str, Any]) -> None:
    print(BANNER)
    print(f"project:           {env['project']}")
    print(f"location:          {env['location']}")
    print(f"model:             {env['model']}")
    print(f"google-genai SDK:  {env['sdk_version']}")
    print(f"credentials:       {env['credential_source']}  (detected by presence only; content is never read or printed)")
    print(f"call settings:     timeout={env['timeout_seconds']:g}s attempts={env['max_attempts']} "
          f"{env['thinking']} max_output_tokens={env['max_output_tokens']}")


def print_page_source(source: str) -> None:
    if source == "png":
        print("pages:             rendered to PNG by pdf2image/poppler (bbox.page comes from the 'Page N of M' labels)")
    else:
        print("pages:             RAW PDF PASSTHROUGH (pdf2image/poppler unavailable)")
        print(f"  WARNING: with a raw PDF there are no page labels, so bbox.page is unreliable and --overlay is "
              f"impossible; {POPPLER_HINT}")


def print_run(doc: SmokeDoc, run: dict[str, Any], index: int, runs: int) -> None:
    title = f"{doc.filename}  (run {index}/{runs})" if runs > 1 else doc.filename
    print(f"\n=== {title} ===")
    if "error" in run:
        error = run["error"]
        print(f"EXTRACTION FAILED: {error['message']}")
        return
    stats = run["stats"]
    print(f"attempts={stats['attempts']}  latency={stats['latency_ms']} ms  prompt_tokens={stats['prompt_tokens']}  "
          f"output_tokens={stats['output_tokens']}  pages={run['pages']} ({run['page_source']})")
    check = run["check"]
    if check is None:
        bbox = run["bbox"]
        print(f"no expectations for this file (not in fixtures/case_c); doc_type={run['_extracted'].doc_type}, "
              f"{bbox['with_bbox']}/{bbox['populated_fields']} fields have a box")
        return
    print(f"{'FIELD':<36}{'EXPECTED':<24}{'EXTRACTED':<26}{'CONF':>5}  {'IoU':>5}  STATUS")
    for row in check["rows"]:
        conf = "-" if row["confidence"] is None else f"{row['confidence']:.2f}"
        overlap = "-" if row["iou"] is None else f"{row['iou']:.2f}"
        flag = "" if row["gating"] else "  (not gating)" if row["status"] != "OK" else ""
        note = f"  [{row['note']}]" if row["note"] else ""
        print(f"{row['name']:<36}{row['expected'][:23]:<24}{row['extracted'][:25]:<26}{conf:>5}  {overlap:>5}  "
              f"{row['status']}{flag}{note}")
    bbox = check["bbox"]
    iou_text = "-" if check["iou_mean"] is None else f"{check['iou_mean']:.2f}"
    lowest = "-" if check["lowest_expected_confidence"] is None else f"{check['lowest_expected_confidence']:.2f}"
    print(f"doc_type_confidence={check['doc_type_confidence']:.2f}  line_items={check['line_items']}  "
          f"fields with a valid box={bbox['bbox_pct']}% ({bbox['with_bbox']}/{bbox['populated_fields']})  "
          f"mean IoU vs the printed boxes={iou_text}  lowest confidence among expected fields={lowest}")
    print(f"box coordinates: min={bbox['coord_min']} max={bbox['coord_max']}"
          + ("  WARNING: all <= 1.0, the model may be using a 0-1 scale instead of 0-1000" if bbox["scale_suspect"] else ""))
    warnings = run["warnings"]
    print(f"sanitiser warnings: {len(warnings)}" + "".join(f"\n  - {w['path']}: {w['reason']}" for w in warnings))


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def _public(run: dict[str, Any]) -> dict[str, Any]:
    """The run without in-memory objects (no document bytes ever reach the report)."""
    return {k: v for k, v in run.items() if not k.startswith("_")}


async def run_smoke(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    docs = load_documents(args.docs, as_fixtures=args.as_fixtures)
    out_dir = Path(args.out)
    report: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(), "runs": args.runs, "documents": []}
    failures: list[str] = []
    page_source: str | None = None

    for doc in docs:
        entry: dict[str, Any] = {"file": doc.filename, "document_id": doc.document_id, "has_expectations": doc.expected is not None,
                                 "runs": []}
        runs: list[dict[str, Any]] = []
        for index in range(1, args.runs + 1):
            run = await extract_once(doc)
            if page_source is None:
                page_source = run["page_source"]
                print_environment(environment(page_source))
                print_page_source(page_source)
                report["environment"] = environment(page_source)
            print_run(doc, run, index, args.runs)
            if "error" in run:
                failures.append(f"{doc.filename}: extraction failed ({run['error']['message']})")
            elif run["check"] is not None:
                failures += [f"{doc.filename}: {name}" for name in run["check"]["failed"]]
            if args.overlay and index == 1 and "error" not in run:
                if run["page_source"] == "png":
                    for written in save_overlays(doc, run, out_dir):
                        print(f"overlay: {written}")
                else:
                    print(f"overlay skipped: pages were not rendered to PNG; {POPPLER_HINT}")
            runs.append(run)
            entry["runs"].append(_public(run))
        if args.runs > 1:
            entry["agreement"] = agreement(runs)
            summary = entry["agreement"]
            print(f"\nagreement across {args.runs} runs for {doc.filename}: {summary['identical_every_run']}/{summary['fields']} "
                  f"fields identical every time ({summary['pct']}%)")
            for name, seen in summary["disagreeing"].items():
                print(f"  - {name}: {seen}")
        report["documents"].append(entry)

    checked = [d for d in report["documents"] if d["has_expectations"]]
    if not checked:
        failures.append("no document had expectations (only the files in fixtures/case_c can be verified)")
    report["failures"] = failures
    report["passed"] = not failures
    if "environment" not in report:
        report["environment"] = environment(page_source)

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"report-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    target.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"\nreport: {target}")
    if failures:
        print("RESULT: FAIL")
        for line in failures:
            print(f"  - {line}")
        return report, 1
    print("RESULT: PASS (every doc_type, HS code and weight expectation was met)")
    return report, 0


# ---------------------------------------------------------------------------
# --dry-run: the exact request, built by the real SDK against a mock transport (zero network calls)
# ---------------------------------------------------------------------------


async def dry_run(args: argparse.Namespace) -> int:
    import httpx
    from google import genai
    from google.auth.credentials import Credentials
    from google.genai import types

    class OfflineCredentials(Credentials):
        """Looks valid, so the SDK never refreshes it. The real credentials are not read."""

        def __init__(self) -> None:
            super().__init__()
            self.token = "dry-run-token"

        def refresh(self, request: Any) -> None:  # pragma: no cover
            raise RuntimeError("dry run must not refresh credentials")

    captured: list[bytes] = []

    def endpoint(request: httpx.Request) -> httpx.Response:
        captured.append(request.read())
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": "{}"}]}}]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(endpoint))
    client = genai.Client(
        vertexai=True, project=settings.project_id, location=settings.gemini_live_location,
        credentials=OfflineCredentials(), http_options=types.HttpOptions(httpx_async_client=http),
    )
    docs = load_documents(args.docs)
    print(BANNER)
    print("DRY RUN: the request is built by the real SDK against a mock transport. No network call is made and "
          "no credential is read.")
    print(f"project={settings.project_id}  location={settings.gemini_live_location}  model={settings.gemini_live_model}  "
          f"google-genai={sdk_version()}  credentials detected: {mode.credential_source()}")
    print(f"config: temperature=0.0  max_output_tokens={settings.gemini_max_output_tokens}  {thinking_description()}"
          f"  response_mime_type=application/json  timeout={settings.gemini_timeout_seconds:g}s  "
            f"attempts={settings.gemini_max_attempts}  concurrency={settings.gemini_max_concurrency}")

    try:
        for doc in docs:
            prepared = await preprocess.run({"raw_bytes": doc.raw, "bundle_id": "", "document_id": doc.document_id})
            pages = prepared.get("processed_pages", [])
            source = page_source_of(pages)
            pages_by_doc = {doc.document_id: pages}
            try:
                extraction._check_limits(pages_by_doc, [doc.document_id])
                verdict = "within the page and size limits"
            except CargoClearError as exc:
                verdict = f"WOULD BE REFUSED before any call: {exc.message}"
            parts, _page_count = extraction._build_parts(types, pages)
            await client.aio.models.generate_content(
                model=settings.gemini_live_model, contents=parts, config=extraction._request_config(types)
            )
            body = json.loads(captured[-1])
            schema = body["generationConfig"]["responseSchema"]
            texts = [p["text"] for p in body["contents"][0]["parts"] if "text" in p]
            print(f"\n{doc.filename}: pages={len(pages)} ({source})  parts={len(parts)}  "
                  f"labels={[t for t in texts if t.startswith('Page ')] or 'none'}  "
                  f"request={len(captured[-1]):,} bytes  {verdict}")
            print(f"  response schema: {len(json.dumps(schema)):,} bytes of JSON, {len(schema.get('properties', {}))} "
                  f"top-level properties; system instruction: {len(body['systemInstruction']['parts'][0]['text'])} chars")
            if source != "png":
                print(f"  note: raw PDF passthrough (page count unknown, no labels); {POPPLER_HINT}")
    finally:
        await http.aclose()
    return 0


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="live_smoke_extraction.py",
        description="Live smoke test of Gemini extraction on the Case C sample PDFs (" + BANNER + ").",
        epilog="Run from backend/ with APP_MODE=live and Google Cloud credentials. See the module docstring.",
    )
    parser.add_argument("--docs", nargs="+", type=Path, default=sorted(CASE_C_DIR.glob("*.pdf")),
                        help="PDFs to send (default: every PDF in fixtures/case_c)")
    parser.add_argument("--runs", type=int, default=1, help="repeat N times and report agreement across runs (default 1)")
    parser.add_argument("--page-mode", choices=["bw", "gray"], default=None,
                        help="what the model is shown: bw (1-bit, the default input) or gray (8-bit grayscale): the A/B (PAGE_IMAGE_MODE)")
    parser.add_argument("--deskew", action="store_true", help="straighten skewed pages before extraction (PREPROCESS_DESKEW)")
    parser.add_argument("--as-fixtures", action="store_true",
                        help="grade files by NAME against the fixtures (degraded copies from scripts/make_degraded_scans.py)")
    parser.add_argument("--overlay", action="store_true", help="save pages with the extracted/expected boxes drawn on them")
    parser.add_argument("--dry-run", action="store_true", help="print the exact request; make no network call")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output directory (default backend/data/live_smoke)")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    missing = [p for p in args.docs if not p.is_file()]
    if missing:
        parser.error(f"not a file: {', '.join(str(p) for p in missing)}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.page_mode:
        settings.page_image_mode = args.page_mode
    if args.deskew:
        settings.preprocess_deskew = True
    reason = refusal_reason()
    if reason is not None:
        print(f"REFUSING TO RUN: {reason}", file=sys.stderr)
        return 2
    if args.dry_run:
        return asyncio.run(dry_run(args))
    _, code = asyncio.run(run_smoke(args))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
