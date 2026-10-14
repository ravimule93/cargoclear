import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { canClear, evidencePath, hasUnit, pathLabel, readCell, type ExtractedDoc } from "../lib/corrections";

const doc: ExtractedDoc = {
  document_id: "inv-1",
  consignee: { value: "ACME PTE LTD", confidence: 0.9 },
  total_gross_weight_kg: { value: "14,280.50", unit: "KGS", confidence: 0.9, corrected: true, original_value: "14,208.50", original_unit: "KGS" },
  incoterm: null,
  line_items: [{ description: { value: "SEAMLESS PIPE", confidence: 0.9 }, total_value: { value: 1000, confidence: 0.9 } }],
  test_results: [{ value: "0.35", unit: "%", parameter: "Cr", heat_number: "H2", confidence: 0.9 }],
  heat_numbers: [{ value: "H2", confidence: 0.9 }],
};

test.describe("evidencePath", () => {
  test("a header field, a line-item field and a list row each name exactly one value", () => {
    expect(evidencePath({ doc: "d", field: "consignee" })).toBe("consignee");
    expect(evidencePath({ doc: "d", field: "total_gross_weight_kg", page: 1, bbox: null })).toBe("total_gross_weight_kg");
    expect(evidencePath({ doc: "d", field: "hs_code_declared", line_item: 2 })).toBe("line_items[2].hs_code_declared");
    expect(evidencePath({ doc: "d", field: "test_results", row: 7 })).toBe("test_results[7]");
    expect(evidencePath({ doc: "d", field: "heat_numbers", row: 0 })).toBe("heat_numbers[0]");
  });

  test("anything that does not point at one correctable value has no address", () => {
    expect(evidencePath({ doc: "d", field: "hs_code_declared" })).toBeNull(); // stated on several lines
    expect(evidencePath({ doc: "d", field: "test_results" })).toBeNull(); // a row list with no row
    expect(evidencePath({ doc: "d", field: "test_results", row: -1 })).toBeNull();
    expect(evidencePath({ doc: "d", field: "bogus" })).toBeNull();
    expect(evidencePath({ doc: "d", field: "bogus", line_item: 0 })).toBeNull();
    expect(evidencePath({ doc: "d", field: "document_id" })).toBeNull();
  });
});

test.describe("hasUnit / canClear / pathLabel", () => {
  test("weights and certificate cells carry a unit; certificate cells and heats cannot be cleared", () => {
    expect(hasUnit("total_gross_weight_kg")).toBe(true);
    expect(hasUnit("line_items[0].net_weight_kg")).toBe(true);
    expect(hasUnit("test_results[3]")).toBe(true);
    expect(hasUnit("consignee")).toBe(false);
    expect(hasUnit("heat_numbers[0]")).toBe(false);
    expect(canClear("consignee")).toBe(true);
    expect(canClear("line_items[0].total_value")).toBe(true);
    expect(canClear("test_results[3]")).toBe(false);
    expect(canClear("heat_numbers[0]")).toBe(false);
  });

  test("labels read like words", () => {
    expect(pathLabel("consignee")).toBe("Consignee");
    expect(pathLabel("total_gross_weight_kg")).toBe("Total gross weight");
    expect(pathLabel("line_items[1].hs_code_declared")).toBe("Line 2 · Hs code declared");
    expect(pathLabel("test_results[6]")).toBe("Certificate cell 7");
    expect(pathLabel("heat_numbers[0]")).toBe("Heat number 1");
  });
});

test.describe("readCell", () => {
  test("reads value, unit and the corrected markers", () => {
    expect(readCell([doc], "inv-1", "consignee")).toEqual({ value: "ACME PTE LTD", unit: null, corrected: false, originalValue: null, originalUnit: null });
    expect(readCell([doc], "inv-1", "total_gross_weight_kg")).toEqual({
      value: "14,280.50", unit: "KGS", corrected: true, originalValue: "14,208.50", originalUnit: "KGS",
    });
    expect(readCell([doc], "inv-1", "line_items[0].total_value")?.value).toBe("1000");
    expect(readCell([doc], "inv-1", "test_results[0]")).toMatchObject({ value: "0.35", unit: "%" });
    expect(readCell([doc], "inv-1", "heat_numbers[0]")?.value).toBe("H2");
  });

  test("an empty field is an address with no value; a missing document or row is nothing", () => {
    expect(readCell([doc], "inv-1", "incoterm")).toEqual({ value: null, unit: null, corrected: false, originalValue: null, originalUnit: null });
    expect(readCell([doc], "inv-1", "line_items[0].unit_price")?.value).toBeNull();
    expect(readCell([doc], "nope", "consignee")).toBeNull();
    expect(readCell([doc], "inv-1", "line_items[4].total_value")).toBeNull();
    expect(readCell([doc], "inv-1", "test_results[9]")).toBeNull();
  });
});

test.describe("pathLabel", () => {
  test("every label matches the vectors the backend's path_label is held to (docs/schemas/path-labels.json)", () => {
    const docs = process.env.CARGOCLEAR_DOCS ?? path.resolve(__dirname, "../../docs");
    const { vectors } = JSON.parse(fs.readFileSync(path.join(docs, "schemas", "path-labels.json"), "utf-8")) as {
      vectors: { path: string; label: string }[];
    };
    expect(vectors.length).toBeGreaterThanOrEqual(8);
    for (const vector of vectors) expect(pathLabel(vector.path), vector.path).toBe(vector.label);
  });
});
