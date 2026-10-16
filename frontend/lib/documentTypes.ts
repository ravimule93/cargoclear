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
