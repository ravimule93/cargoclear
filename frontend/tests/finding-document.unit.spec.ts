import { expect, test } from "@playwright/test";
import { findingDocumentId } from "../lib/finding-document";
import type { CheckResult } from "../lib/types";

const check = (over: Partial<CheckResult>): CheckResult => ({ check_id: "X", severity: "PASS", message: "m", ...over });
const docs = ["inv-1", "mtc-1", "bl-1"];

test.describe("The document opened first", () => {
  test("a finding that names its document is believed: the certificate, not the invoice cited first", () => {
    const material = check({
      severity: "MATERIAL",
      focus_document: "mtc-1",
      evidence: [
        { doc: "inv-1", field: "hs_code_declared" },
        { doc: "mtc-1", field: "test_results" },
      ],
    });
    expect(findingDocumentId([material], docs)).toBe("mtc-1");
    expect(findingDocumentId([{ ...material, evidence: [...material.evidence!].reverse() }], docs)).toBe("mtc-1");
  });

  test("an older assessment carries no focus: the first document its evidence cites", () => {
    const material = check({ severity: "MATERIAL", evidence: [{ doc: "bl-1", field: "x" }, { doc: "mtc-1", field: "y" }] });
    expect(findingDocumentId([material], docs)).toBe("bl-1");
  });

  test("only documents of the bundle on screen count", () => {
    const material = check({ severity: "MATERIAL", focus_document: "gone", evidence: [{ doc: "gone-too", field: "x" }, { doc: "bl-1", field: "y" }] });
    expect(findingDocumentId([material], docs)).toBe("bl-1");
    expect(findingDocumentId([check({ severity: "MATERIAL", focus_document: "gone" })], docs)).toBeNull();
  });

  test("no material finding, no checks, or nothing cited: no opinion", () => {
    expect(findingDocumentId([check({ severity: "WARN", focus_document: "mtc-1" }), check({})], docs)).toBeNull();
    expect(findingDocumentId(undefined, docs)).toBeNull();
    expect(findingDocumentId([check({ severity: "MATERIAL" })], docs)).toBeNull();
  });

  test("the first MATERIAL finding wins", () => {
    const first = check({ check_id: "A", severity: "MATERIAL", focus_document: "mtc-1" });
    const second = check({ check_id: "B", severity: "MATERIAL", focus_document: "inv-1" });
    expect(findingDocumentId([check({ severity: "WARN", focus_document: "bl-1" }), first, second], docs)).toBe("mtc-1");
  });
});
