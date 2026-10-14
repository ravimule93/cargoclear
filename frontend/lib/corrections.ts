/**
 * Corrections by the authorised agent: how an evidence row names the value it shows (its address), and how to read that
 * value back from an extraction.
 *
 * MIRRORS backend/app/domain/corrections.py (the field tables and the path grammar). The backend is the authority and
 * refuses anything outside its tables; a contract test (backend/tests/unit/test_corrections_contract.py) fails if these
 * lists drift from the Python ones.
 */
import type { EvidenceRef } from "./types";

/** Header fields of a document that can be corrected. */
export const HEADER_FIELDS = [
  "document_number",
  "consignee",
  "consignor",
  "vessel_or_flight",
  "port_of_loading",
  "port_of_discharge",
  "shipment_date",
  "invoice_value",
  "invoice_currency",
  "total_net_weight_kg",
  "total_gross_weight_kg",
  "tare_weight_kg",
  "package_count",
  "hs_code_header",
  "incoterm",
  "country_of_origin",
  "freight_amount",
  "freight_currency",
  "insurance_amount",
  "insurance_currency",
  "specification",
] as const;

/** Fields of one line item that can be corrected. */
export const LINE_FIELDS = [
  "description",
  "quantity",
  "net_weight_kg",
  "gross_weight_kg",
  "hs_code_declared",
  "unit_price",
  "total_value",
  "currency",
  "unit_price_basis",
] as const;

/** Lists on a document whose entries can be corrected one by one. */
export const ROW_LISTS = ["heat_numbers", "test_results"] as const;

/** Weights carry a printed unit (a lab value does too; see `hasUnit`). */
const WEIGHT_FIELDS = new Set(["total_net_weight_kg", "total_gross_weight_kg", "tare_weight_kg", "net_weight_kg", "gross_weight_kg"]);

/** An extracted document as the API returns it: loosely typed on purpose (the backend schema is large and this only reads it). */
export type ExtractedDoc = Record<string, unknown>;

const header = new Set<string>(HEADER_FIELDS);
const line = new Set<string>(LINE_FIELDS);
const rows = new Set<string>(ROW_LISTS);

/**
 * The address of the value an evidence entry shows, or null when the entry does not point at exactly one correctable value
 * (for example an HS code stated on several lines, or a derived figure).
 */
export function evidencePath(ev: EvidenceRef): string | null {
  const isIndex = (n: unknown): n is number => typeof n === "number" && Number.isInteger(n) && n >= 0;
  if (rows.has(ev.field)) return isIndex(ev.row) ? `${ev.field}[${ev.row}]` : null;
  if (isIndex(ev.line_item)) return line.has(ev.field) ? `line_items[${ev.line_item}].${ev.field}` : null;
  return header.has(ev.field) ? ev.field : null;
}

/** Does the value at this address carry a printed unit (a weight or a certificate cell)? */
export function hasUnit(path: string): boolean {
  if (path.startsWith("test_results[")) return true;
  const field = path.includes(".") ? path.slice(path.lastIndexOf(".") + 1) : path;
  return WEIGHT_FIELDS.has(field);
}

/** Rows cannot be cleared (a person corrects a certificate cell, they do not delete it). */
export function canClear(path: string): boolean {
  return !/^[a-z_]+\[\d+\]$/.test(path);
}

export interface CellValue {
  value: string | null;
  unit: string | null;
  corrected: boolean;
  originalValue: string | null;
  originalUnit: string | null;
}

function asText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(value);
  return String(value);
}

function asRef(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** The value (and unit) an extraction has at an address; null when the document or the address does not exist. */
export function readCell(docs: ExtractedDoc[], documentId: string, path: string): CellValue | null {
  const doc = docs.find((d) => d.document_id === documentId);
  if (!doc) return null;

  let ref: Record<string, unknown> | null;
  const lineMatch = /^line_items\[(\d+)\]\.([a-z_]+)$/.exec(path);
  const rowMatch = /^([a-z_]+)\[(\d+)\]$/.exec(path);
  if (lineMatch) {
    const items = Array.isArray(doc.line_items) ? (doc.line_items as unknown[]) : [];
    const item = asRef(items[Number(lineMatch[1])]);
    if (!item) return null;
    ref = asRef(item[lineMatch[2]]);
  } else if (rowMatch) {
    const list = Array.isArray(doc[rowMatch[1]]) ? (doc[rowMatch[1]] as unknown[]) : [];
    ref = asRef(list[Number(rowMatch[2])]);
    if (!ref) return null;
  } else {
    ref = asRef(doc[path]);
  }

  if (!ref) return { value: null, unit: null, corrected: false, originalValue: null, originalUnit: null };
  return {
    value: asText(ref.value),
    unit: asText(ref.unit),
    corrected: ref.corrected === true,
    originalValue: asText(ref.original_value),
    originalUnit: asText(ref.original_unit),
  };
}

/** A short human label for an address: "Consignee", "Line 2 · HS code declared", "Certificate cell 7". */
export function pathLabel(path: string): string {
  const words = (name: string) => name.replace(/_kg$/, "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const lineMatch = /^line_items\[(\d+)\]\.([a-z_]+)$/.exec(path);
  if (lineMatch) return `Line ${Number(lineMatch[1]) + 1} · ${words(lineMatch[2])}`;
  const rowMatch = /^([a-z_]+)\[(\d+)\]$/.exec(path);
  if (rowMatch) return `${rowMatch[1] === "heat_numbers" ? "Heat number" : "Certificate cell"} ${Number(rowMatch[2]) + 1}`;
  return words(path);
}
