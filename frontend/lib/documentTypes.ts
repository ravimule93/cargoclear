/**
 * The types a person may say a file is when uploading it (`declared_type` of POST /bundles/{id}/documents). The same six the
 * extraction reads (`DECLARABLE_TYPES` in backend/app/services/document_identity.py; backend/tests/unit/test_document_identity.py
 * checks the two lists agree). When the model reads another type, the assessment warns (T-001).
 */
export const DECLARABLE_DOCUMENT_TYPES = [
  { value: "COMMERCIAL_INVOICE", label: "Commercial Invoice" },
  { value: "BILL_OF_LADING", label: "Bill of Lading" },
  { value: "PACKING_LIST", label: "Packing List" },
  { value: "CERTIFICATE_OF_ORIGIN", label: "Certificate of Origin" },
  { value: "PHYTOSANITARY", label: "Phytosanitary Certificate" },
  { value: "MILL_TEST_CERTIFICATE", label: "Mill Test Certificate" },
] as const;

export type DeclarableDocumentType = (typeof DECLARABLE_DOCUMENT_TYPES)[number]["value"];

/** What the picker offers when the person says nothing: the file is sent without a declared type and the model decides. */
export const NO_DECLARED_TYPE = "";

/**
 * Smart document type heuristic based on filename patterns.
 * Returns suggested DeclarableDocumentType, or NO_DECLARED_TYPE if unknown.
 */
export function suggestDocumentType(filename: string): DeclarableDocumentType | "" {
  const lower = filename.toLowerCase();
  if (lower.includes("invoice") || lower.includes("inv")) return "COMMERCIAL_INVOICE";
  if (
    lower.includes("lading") ||
    lower.includes("bol") ||
    lower.includes("awb") ||
    lower.includes("bill_of_lading") ||
    lower.startsWith("bl") ||
    lower.includes("b_l")
  ) {
    return "BILL_OF_LADING";
  }
  if (
    lower.includes("packing") ||
    lower.includes("pkg") ||
    lower.includes("packing_list") ||
    lower.startsWith("pl")
  ) {
    return "PACKING_LIST";
  }
  if (
    lower.includes("mtc") ||
    lower.includes("mill") ||
    lower.includes("test_cert") ||
    lower.includes("cert_of_test")
  ) {
    return "MILL_TEST_CERTIFICATE";
  }
  if (
    lower.includes("coo") ||
    lower.includes("origin") ||
    lower.includes("certificate_of_origin")
  ) {
    return "CERTIFICATE_OF_ORIGIN";
  }
  if (lower.includes("phyto") || lower.includes("plant") || lower.includes("fumigation")) {
    return "PHYTOSANITARY";
  }
  return NO_DECLARED_TYPE;
}

/** Format uppercase token into human-friendly label (e.g. COMMERCIAL_INVOICE -> Commercial Invoice) */
export function formatDocType(type: string): string {
  const match = DECLARABLE_DOCUMENT_TYPES.find((d) => d.value === type);
  if (match) return match.label;
  return type.replace(/_/g, " ");
}
