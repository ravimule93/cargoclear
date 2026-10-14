import { pathLabel } from "./corrections";

const title = (text: string) => text.replace(/_/g, " ").toLowerCase().replace(/(^|\s)\S/g, (c) => c.toUpperCase());

/** What a person reads in the Attribute column; the machine key stays in the cell's tooltip. Check ids (M-001) are cited as they are. */
export function attributeLabel(field: string): string {
  const correction = /^correction\.[^.]+\.(.+)$/.exec(field);
  if (correction) return `Correction: ${pathLabel(correction[1])}`;
  const requirement = /^missing_evidence\.(?:ME-)?(?:CORE-)?(.+)$/.exec(field);
  if (requirement) return `Required document: ${title(requirement[1])}`;
  if (field === "status") return "Status";
  return field;
}

/** A status or severity as words (MATERIAL_CONTRADICTION -> Material Contradiction); anything else is shown as it is. */
export function plainValue(value: unknown): string {
  const text = String(value ?? "");
  return /^[A-Z]+(_[A-Z]+)+$/.test(text) ? title(text) : text;
}
