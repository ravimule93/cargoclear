"""A printable summary of the declaration pre-fill pack (domain/prefill.py), for the person who keys the declaration.

The JSON pack is the record; this is the same content laid out to be read next to the form: the verdict first (cleared or
not, and what blocks it), then the values with where they came from, then what the declarant still has to supply.

Fonts are the PDF standard fonts, which cover Latin-1 only: other characters (a Chinese company name, the rupee sign) print as
"?" here, and the JSON keeps them exactly. The PDF says so in its footer. Streams are left uncompressed so the text can be
checked (and searched) without a PDF library, which costs a few kilobytes.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.prefill import PrefillPack, PrefillValue

_INK = colors.HexColor("#1F2933")
_MUTED = colors.HexColor("#52606D")
_LINE = colors.HexColor("#CBD2D9")
_HEAD = colors.HexColor("#E4E7EB")
_BAD = colors.HexColor("#9B1C1C")
_BAD_BG = colors.HexColor("#FDE8E8")
_WARN = colors.HexColor("#8A4B08")
_OK = colors.HexColor("#0E6B3A")

_STATUS_WORDS = {
    "COMPLIANT_FOR_SUBMISSION": "Compliant for submission",
    "MISSING_EVIDENCE": "Missing evidence",
    "MATERIAL_CONTRADICTION": "Material contradiction",
    "SPECIALIST_REVIEW_REQUIRED": "Specialist review required",
}


def _t(text: object) -> str:
    """Text safe for a standard-font PDF: Latin-1 only, XML-escaped for Paragraph."""
    plain = "" if text is None else str(text)
    return escape(plain.encode("latin-1", "replace").decode("latin-1"))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "body": ParagraphStyle("body", parent=base, fontName="Helvetica", fontSize=8.5, leading=11, textColor=_INK),
        "small": ParagraphStyle("small", parent=base, fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=_MUTED),
        "mono": ParagraphStyle("mono", parent=base, fontName="Courier", fontSize=7.5, leading=9.5, textColor=_INK),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=_INK),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=_INK, spaceBefore=8, spaceAfter=3, keepWithNext=1),
        "banner": ParagraphStyle("banner", parent=base, fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=_BAD),
        "cell": ParagraphStyle("cell", parent=base, fontName="Helvetica", fontSize=8, leading=10, textColor=_INK),
        "head": ParagraphStyle("head", parent=base, fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, textColor=_INK),
    }


def _shown(value: PrefillValue) -> str:
    if value.value is None:
        return "(not stated)"
    text = value.value
    if value.unit and not text.upper().endswith(value.unit.upper()):
        text = f"{text} {value.unit}"
    return text


def _kind(doc_type: str) -> str:
    """'BILL_OF_LADING' -> 'Bill of lading'."""
    return doc_type.replace("_", " ").capitalize()


def _where(value: PrefillValue) -> str:
    if value.source is None:
        return ""
    page = f" p.{value.source.page}" if value.source.page else ""
    return f"{_kind(value.source.doc_type)}{page}"


def _notes(value: PrefillValue) -> str:
    notes: list[str] = []
    if value.corrected:
        notes.append("corrected by the agent")
    notes.extend(value.review)
    return "; ".join(notes)


def _table(rows: list[list[Any]], widths: list[float], styles: dict[str, ParagraphStyle], *, header: bool = True) -> Table:
    cooked = [
        [cell if not isinstance(cell, str) else Paragraph(_t(cell), styles["head" if header and r == 0 else "cell"]) for cell in row]
        for r, row in enumerate(rows)
    ]
    table = Table(cooked, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, _LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), _HEAD))
    table.setStyle(TableStyle(style))
    return table


def _field_rows(label_values: list[tuple[str, PrefillValue]]) -> list[list[Any]]:
    rows: list[list[Any]] = [["Field", "Value", "Read from", "Check"]]
    for label, value in label_values:
        rows.append([label, _shown(value), _where(value), _notes(value)])
    return rows


def _footer(pack: PrefillPack) -> Callable[[Any, Any], None]:
    def draw(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_MUTED)
        canvas.drawString(
            15 * mm, 9 * mm,
            f"CargoClear pre-fill · bundle {pack.bundle_id} · assessment {pack.assessment.iteration} · {pack.integrity.content_sha256[:16]} · "
            "non-Latin characters print as ? here; the JSON keeps them",
        )
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def render(pack: PrefillPack) -> bytes:
    """The pack as a PDF (A4)."""
    st = _styles()
    story: list[Any] = []
    width = A4[0] - 30 * mm

    story.append(Paragraph("Declaration pre-fill", st["h1"]))
    story.append(
        Paragraph(
            _t(
                f"{pack.declaration.declaration} · destination {pack.declaration.destination_country} · bundle {pack.bundle_id}"
                f"{(' · ' + pack.reference) if pack.reference else ''}"
            ),
            st["small"],
        )
    )
    story.append(
        Paragraph(
            _t(
                f"Assessment {pack.assessment.iteration}: {_STATUS_WORDS.get(pack.assessment.status, pack.assessment.status)} "
                f"({pack.assessment.run_mode or 'full'}, {pack.assessment.data_source or 'data source unknown'}) · generated {pack.generated_at}"
            ),
            st["small"],
        )
    )
    story.append(Spacer(1, 4))

    if pack.banner:
        box = Table([[Paragraph(_t(pack.banner), st["banner"])]], colWidths=[width])
        box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _BAD_BG), ("BOX", (0, 0), (-1, -1), 0.8, _BAD), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story.append(box)
    else:
        story.append(Paragraph(_t("The assessment is compliant for submission and includes every correction made so far."), ParagraphStyle("ok", parent=st["body"], textColor=_OK, fontName="Helvetica-Bold")))
    story.append(Spacer(1, 3))
    story.append(Paragraph(_t(pack.disclaimer), st["small"]))

    story.append(Paragraph("Parties", st["h2"]))
    story.append(_table(_field_rows([("Consignee", pack.parties.consignee), ("Consignor", pack.parties.consignor)]), [30 * mm, 62 * mm, 30 * mm, width - 122 * mm], st))

    s = pack.shipment
    story.append(Paragraph("Shipment", st["h2"]))
    story.append(
        _table(
            _field_rows([
                ("Invoice number", s.invoice_number), ("Bill of lading number", s.bill_of_lading_number),
                ("Packing list number", s.packing_list_number), ("Vessel / flight", s.vessel_or_flight),
                ("Port of loading", s.port_of_loading), ("Port of discharge", s.port_of_discharge),
                ("Shipment date", s.shipment_date), ("Incoterm", s.incoterm), ("Country of origin", s.country_of_origin),
                ("Packages", s.package_count), ("Gross weight", s.total_gross_weight), ("Net weight", s.total_net_weight),
            ]),
            [30 * mm, 62 * mm, 30 * mm, width - 122 * mm], st,
        )
    )

    c = pack.commercial
    story.append(Paragraph("Commercial", st["h2"]))
    story.append(
        _table(
            _field_rows([
                ("Invoice value", c.invoice_value), ("Invoice currency", c.invoice_currency),
                ("Freight", c.freight_amount), ("Freight currency", c.freight_currency),
                ("Insurance", c.insurance_amount), ("Insurance currency", c.insurance_currency),
            ]),
            [30 * mm, 62 * mm, 30 * mm, width - 122 * mm], st,
        )
    )

    if pack.lines:
        story.append(Paragraph("Lines", st["h2"]))
        rows: list[list[Any]] = [["#", "Description", "HS code", "Quantity", "Unit price", "Value", "Cur.", "Check"]]
        for line in pack.lines:
            checks = "; ".join(
                note for v in (line.description, line.hs_code, line.quantity, line.unit_price, line.line_value, line.currency) for note in ([_notes(v)] if _notes(v) else [])
            )
            unit_price = _shown(line.unit_price) + (f" {line.unit_price_basis.value}" if line.unit_price_basis.value else "")
            rows.append([str(line.line_no), _shown(line.description), _shown(line.hs_code), _shown(line.quantity), unit_price, _shown(line.line_value), _shown(line.currency), checks])
        story.append(_table(rows, [6 * mm, 40 * mm, 20 * mm, 18 * mm, 24 * mm, 20 * mm, 10 * mm, width - 138 * mm], st))

    if pack.material.certificate_document_id or pack.material.heat_numbers:
        story.append(Paragraph("Material certificate", st["h2"]))
        story.append(_table(_field_rows([("Specification", pack.material.specification)]), [30 * mm, 62 * mm, 30 * mm, width - 122 * mm], st))
        if pack.material.heat_numbers:
            story.append(Paragraph(_t("Heat numbers: " + ", ".join(pack.material.heat_numbers)), st["body"]))

    v = pack.valuation
    if v is not None:
        story.append(Paragraph("Indicative duty estimate (not an amount payable)", st["h2"]))
        facts = [f"Status: {v.status.title()}"]
        if v.assessable_value is not None:
            facts.append(f"assessable value {v.assessable_value:,.2f} {v.destination_currency or ''}".strip())
        if v.total_duty is not None:
            facts.append(f"total duty {v.total_duty:,.2f} {v.destination_currency or ''}".strip())
        story.append(Paragraph(_t(" · ".join(facts)), st["body"]))
        if v.duties:
            story.append(_table([["Duty", "Rate %", "Base", "Amount"], *[[d.name, "" if d.rate_pct is None else f"{d.rate_pct:g}", "" if d.base is None else f"{d.base:,.2f}", f"{d.amount:,.2f}"] for d in v.duties]], [30 * mm, 24 * mm, 40 * mm, 40 * mm], st))
        for note in v.assumptions:
            story.append(Paragraph(_t("Assumed: " + note), st["small"]))
        story.append(Paragraph(_t(v.disclaimer), st["small"]))

    a = pack.assessment
    if a.blocking or a.review or a.missing_documents:
        story.append(Paragraph("Findings to resolve", st["h2"]))
        rows = [["Finding", "Level", "What the check found"]]
        rows += [[f.check_id, "Contradiction", f.message] for f in a.blocking]
        rows += [[m, "Missing document", "Required by the assessment and not in the bundle."] for m in a.missing_documents]
        rows += [[f.check_id, "Review", f.message] for f in a.review]
        story.append(_table(rows, [24 * mm, 28 * mm, width - 52 * mm], st))

    if pack.corrections:
        story.append(Paragraph("Corrections by the agent in these values", st["h2"]))
        rows = [["Value", "Model read", "Corrected to", "Reason", "Status"]]
        for corr in pack.corrections:
            rows.append([f"{corr.path} ({corr.document_id})", corr.original_value or "(not stated)", corr.value or "(cleared)", corr.reason or "", corr.status if corr.status == "applied" else f"not used: {corr.note or ''}"])
        story.append(_table(rows, [48 * mm, 24 * mm, 24 * mm, width - 126 * mm, 30 * mm], st))

    story.append(
        KeepTogether([
            Paragraph("To be supplied by the declarant (on no trade document)", st["h2"]),
            Paragraph(_t("; ".join(i.label for i in pack.to_be_supplied) + "."), st["body"]),
            Paragraph(_t(f"{pack.declaration.rule_set}: {pack.declaration.regulation_ref}"), st["small"]),
        ])
    )

    story.append(Paragraph("Source documents and integrity", st["h2"]))
    story.append(_table([["File", "Type", "SHA-256"], *[[d.filename, _kind(d.doc_type), d.sha256[:24] + "..."] for d in pack.documents]], [70 * mm, 40 * mm, width - 110 * mm], st))
    p = pack.provenance
    story.append(
        Paragraph(
            _t(
                f"Audit chain: {p.audit_events} events, {'verified' if p.audit_chain_verified else 'NOT VERIFIED'}, head {(p.audit_head_hash or 'none')[:24]}. "
                f"Pack content SHA-256: {pack.integrity.content_sha256}"
            ),
            st["mono"],
        )
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
        title=f"Declaration pre-fill {pack.bundle_id}", author="CargoClear", pageCompression=0,
    )
    footer = _footer(pack)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
