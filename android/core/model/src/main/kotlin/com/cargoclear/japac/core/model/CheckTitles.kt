package com.cargoclear.japac.core.model

private val CHECK_TITLES = mapOf(
    "W-001" to "Weight Balance (BoL Gross vs Packing List Net+Tare)",
    "W-002" to "Packing List Internal Weight Parity",
    "H-002" to "Cross-Document HS Code Alignment",
    "E-consignee" to "Consignee Entity Alignment",
    "E-consignor" to "Consignor Entity Alignment",
    "E-vessel" to "Vessel / Voyage Identification",
    "G-001" to "Tariff Classification Grounding (AHTN)",
    "E-origin" to "Country of Origin Consistency",
    "I-001" to "Invoice Line Arithmetic (Quantity × Unit Price)",
    "I-002" to "Invoice Total vs Line Totals",
    "I-003" to "Invoice Currency Consistency",
    "M-001" to "Alloy Status vs Declared HS Code (HS Note 1)",
    "M-002" to "Carbon Equivalent vs Specification",
    "M-003" to "Chemistry & Strength vs Specification",
    "M-004" to "Heat-Number Traceability (Packing List ↔ Certificate)",
    "SEC-001" to "Alloy-Threshold Proximity (Circumvention Heuristic)",
    "SEC-002" to "Anti-Dumping Exposure",
)

/** The plain-words title of a check id; an id this table does not know is shown as it is. Port of `CHECK_TITLES` in CheckList.tsx. */
fun checkTitle(checkId: String): String =
    CHECK_TITLES[checkId]
        ?: when {
            checkId.startsWith("H-003") -> "Certificate HS Verification (${checkId.replaceFirst("H-003-", "").replace('_', ' ')})"
            // these end in the document id (one per document), like H-003 ends in the certificate type
            checkId.startsWith("P-001-") -> "Pages Not Read"
            checkId.startsWith("P-002-") -> "Pages Skipped (Terms and Conditions)"
            checkId.startsWith("T-001-") -> "Document Type Differs From the Upload"
            checkId.startsWith("L-001-") -> "Values Not in Latin Script"
            else -> checkId
        }
