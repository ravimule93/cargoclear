import path from "node:path";

/** The synthetic sample PDFs at the repository root (override with CARGOCLEAR_FIXTURES when the frontend is checked out alone). */
export const FIXTURES_DIR = process.env.CARGOCLEAR_FIXTURES ?? path.resolve(__dirname, "../../../fixtures");

export const CASE_C_FILES = ["commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf"];
export const CASE_C_CERTIFICATE = "mtc_pipe_test_cert.pdf";
export const CASE_D_FILES = [
  "case_d_commercial_invoice.pdf",
  "case_d_bill_of_lading.pdf",
  "case_d_packing_list.pdf",
  "case_d_mtc_test_cert.pdf",
];

export const caseCPath = (name: string) => path.join(FIXTURES_DIR, "case_c", name);
export const caseDPath = (name: string) => path.join(FIXTURES_DIR, "case_d", name);
