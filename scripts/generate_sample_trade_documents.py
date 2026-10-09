#!/usr/bin/env python3
"""Generates realistic PDF trade documents for testing and judging demos."""

import os
from pathlib import Path


def generate_simple_pdf(filepath: Path, title: str, subtitle: str, fields: list[tuple[str, str]], footer: str):
    """Generates a standard valid PDF-1.4 file with formatted text and layout."""
    content_lines = []
    
    # Header Banner
    content_lines.append(f"BT /F2 16 Tf 50 780 Td ({title}) Tj ET")
    content_lines.append(f"BT /F1 10 Tf 50 760 Td ({subtitle}) Tj ET")
    
    # Horizontal line below header
    content_lines.append("0.5 w 50 745 m 545 745 l S")
    
    # Body Fields
    y = 715
    for label, val in fields:
        # Label in bold/dark
        content_lines.append(f"BT /F2 9 Tf 50 {y} Td ({label}:) Tj ET")
        # Value aligned
        clean_val = val.replace("(", "[").replace(")", "]")
        content_lines.append(f"BT /F1 9 Tf 180 {y} Td ({clean_val}) Tj ET")
        y -= 22
        if y < 100:
            break
            
    # Horizontal line above footer
    content_lines.append("0.5 w 50 80 m 545 80 l S")
    clean_footer = footer.replace("(", "[").replace(")", "]")
    content_lines.append(f"BT /F1 8 Tf 50 65 Td ({clean_footer}) Tj ET")
    
    stream_content = "\n".join(content_lines) + "\n"
    c_bytes = stream_content.encode("latin1")
    
    objects = []
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objects.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    objects.append(
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>\nendobj\n"
    )
    objects.append(
        f"4 0 obj\n<< /Length {len(c_bytes)} >>\nstream\n".encode("latin1")
        + c_bytes
        + b"\nendstream\nendobj\n"
    )
    # Regular Font (Helvetica)
    objects.append(b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")
    # Bold Font (Helvetica-Bold)
    objects.append(b"6 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n")
    
    body = b"%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(body))
        body += obj
        
    xref_offset = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin1")
    for o in offsets[1:]:
        body += f"{o:010d} 00000 n \n".encode("latin1")
        
    body += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("latin1")
    
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(body)
    print(f"Generated: {filepath.name}")


def main():
    root = Path(__file__).resolve().parent.parent
    sample_dir = root / "samples" / "case_c_hero_bundle"
    sample_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Commercial Invoice
    generate_simple_pdf(
        sample_dir / "Commercial_Invoice_INV-2024-001.pdf",
        title="COMMERCIAL INVOICE",
        subtitle="PT Nusantara Steel Pipe Ind. | International Trade Division",
        fields=[
            ("Invoice Number", "INV-2024-001"),
            ("Invoice Date", "2026-03-15"),
            ("Exporter / Consignor", "PT Nusantara Steel Pipe Ind., Kawasan Industri Cilegon, Indonesia"),
            ("Buyer / Consignee", "Singapore Gas & Marine Engineering Pte Ltd, 12 Tuas Basin, Singapore"),
            ("Port of Loading", "Tanjung Priok, Jakarta, Indonesia [IDTPP]"),
            ("Port of Discharge", "Port of Singapore, Singapore [SGSIN]"),
            ("Payment Terms", "Letter of Credit at Sight [L/C No. LC-SG-99210]"),
            ("Currency", "USD"),
            ("Commodity Description", "Seamless Carbon Steel Line Pipe, API 5L Grade B for pipeline use"),
            ("Tariff Classification", "AHTN HS Code 7304.19.00"),
            ("Quantity", "500 Meters [20 Bundles]"),
            ("Unit Price", "USD 85.00 per meter"),
            ("Total Invoice Value", "USD 42,500.00"),
            ("Total Net Weight", "14,000.00 KG"),
            ("Total Gross Weight", "14,280.00 KG"),
        ],
        footer="Original Document | Certified True Copy for Customs Clearance (CargoClear-JAPAC Hero Case C)",
    )

    # 2. Bill of Lading
    generate_simple_pdf(
        sample_dir / "Bill_of_Lading_BL-8941.pdf",
        title="OCEAN BILL OF LADING",
        subtitle="Samudera Shipping Line Ltd | Multimodal Transport Document",
        fields=[
            ("B/L Number", "BL-8941"),
            ("Issue Date", "2026-03-18"),
            ("Shipper", "PT Nusantara Steel Pipe Ind., Cilegon, Banten, Indonesia"),
            ("Consignee", "Singapore Gas & Marine Engineering Pte Ltd, Jurong, Singapore"),
            ("Vessel & Voyage", "KM SINAR PRAYA V.204N"),
            ("Port of Loading", "Tanjung Priok, Jakarta (IDTPP)"),
            ("Port of Discharge", "Port of Singapore, PSA Terminal (SGSIN)"),
            ("Marks & Numbers", "SGME/SIN/2026/01-20"),
            ("Number of Packages", "20 Bundles (Steel Strapped with Wooden Dunnage)"),
            ("Cargo Description", "Seamless Carbon Steel Line Pipe for pipelines (HS 7304.19.00)"),
            ("Total Gross Weight", "14,280.00 KG"),
            ("Measurement", "28.50 CBM"),
            ("Freight Status", "FREIGHT PREPAID"),
        ],
        footer="Clean On Board | Shipped in apparent good order and condition (CargoClear-JAPAC Hero Case C)",
    )

    # 3. Packing List
    generate_simple_pdf(
        sample_dir / "Packing_List_PL-001.pdf",
        title="EXPORT PACKING LIST",
        subtitle="PT Nusantara Steel Pipe Ind. | Dispatch & Logistics Dept.",
        fields=[
            ("Packing List Ref", "PL-001"),
            ("Associated Invoice", "INV-2024-001"),
            ("Date", "2026-03-15"),
            ("Exporter", "PT Nusantara Steel Pipe Ind., Cilegon, Indonesia"),
            ("Consignee", "Singapore Gas & Marine Engineering Pte Ltd, Singapore"),
            ("Total Bundles", "20 Bundles (25 pipes per bundle = 500 pipes total)"),
            ("Dimension per Bundle", "12,000 mm x 600 mm x 600 mm"),
            ("Total Net Weight", "14,000.00 KG"),
            ("Tare Weight", "280.00 KG (Dunnage, banding, end-caps)"),
            ("Total Gross Weight", "14,280.00 KG"),
            ("Weight Parity Equation", "Net (14,000.0 kg) + Tare (280.0 kg) = Gross (14,280.0 kg) [Delta = 0.0 kg]"),
        ],
        footer="Approved by Warehouse Superintendent | Ready for Containerization (CargoClear-JAPAC Hero Case C)",
    )

    # 4. Mill Test Certificate (The missing document for corrective upload)
    generate_simple_pdf(
        sample_dir / "mtc_pipe_test_cert.pdf",
        title="MILL TEST CERTIFICATE (MTC)",
        subtitle="Krakatau-Nusantara Quality Assurance Lab | EN 10204 3.1 Certified",
        fields=[
            ("Certificate Number", "MTC-7304-2026-QA"),
            ("Testing Standard", "EN 10204 Type 3.1 / API Specification 5L / ASTM A106 Grade B"),
            ("Manufacturer", "PT Nusantara Steel Pipe Ind., Plant II Cilegon"),
            ("Heat Number", "HT-882914-A"),
            ("Lot / Batch Number", "BATCH-2026-03"),
            ("Product Description", "Seamless Carbon Steel Line Pipe for Gas Pipelines"),
            ("Tariff Code", "AHTN HS 7304.19.00"),
            ("Yield Strength", "355 MPa (Min Required: 245 MPa - PASS)"),
            ("Tensile Strength", "490 MPa (Standard: 415-655 MPa - PASS)"),
            ("Elongation", "28% (Standard Min: 21% - PASS)"),
            ("Chemical Composition", "C: 0.16% | Mn: 0.85% | P: 0.012% | S: 0.004% | Si: 0.22%"),
            ("Hydrostatic Test", "21.5 MPa held for 10 seconds without leakage - PASS"),
            ("Non-Destructive Test", "100% Ultrasonic & Eddy Current Tested - ACCEPTED"),
            ("Regulatory Clearance", "Satisfies AHTN Chapter 73 / Singapore ASW Mandatory Certificate Rule 4.2"),
        ],
        footer="Chief Metallurgist Seal & Signature Verified | Valid for Customs Release (Hero Case C Corrective Doc)",
    )
    
    print("\nAll 4 Hero Case C test documents generated successfully in:")
    print(sample_dir)


if __name__ == "__main__":
    main()
