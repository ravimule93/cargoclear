import { expect, test } from "@playwright/test";
import { attributeLabel, plainValue } from "../lib/delta-labels";

test.describe("Reasoning Delta labels", () => {
  test("a correction is named by what it corrects, not by a document id and an address", () => {
    expect(attributeLabel("correction.doc-f74c9c3e83f32ccc.test_results[20]")).toBe("Correction: Certificate cell 21");
    expect(attributeLabel("correction.doc-1.line_items[2].hs_code_declared")).toBe("Correction: Line 3 · Hs code declared");
    expect(attributeLabel("correction.doc-1.total_gross_weight_kg")).toBe("Correction: Total gross weight");
  });

  test("a requirement is a document name, a status is a word, a check id stays as cited", () => {
    expect(attributeLabel("missing_evidence.ME-MILL_TEST_CERTIFICATE")).toBe("Required document: Mill Test Certificate");
    expect(attributeLabel("missing_evidence.ME-CORE-COMMERCIAL_INVOICE")).toBe("Required document: Commercial Invoice");
    expect(attributeLabel("status")).toBe("Status");
    expect(attributeLabel("M-001")).toBe("M-001");
    expect(attributeLabel("")).toBe("");
  });

  test("statuses read as words and everything else is left alone", () => {
    expect(plainValue("MATERIAL_CONTRADICTION")).toBe("Material Contradiction");
    expect(plainValue("SPECIALIST_REVIEW_REQUIRED")).toBe("Specialist Review Required");
    expect(plainValue("PASS")).toBe("PASS");
    expect(plainValue("0.35 %")).toBe("0.35 %");
    expect(plainValue(null)).toBe("");
    expect(plainValue(undefined)).toBe("");
  });
});
