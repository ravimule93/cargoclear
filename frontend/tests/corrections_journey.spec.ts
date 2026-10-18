import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { openCaseDDemoWorkbench } from "./support/case-d";

/**
 * The corrections journey, on Case D: the product says MATERIAL_CONTRADICTION because heat TH-77121 reads 0.35 % chromium.
 * The agent looks at the certificate, states that it prints 0.28 %, and recomputes. Nothing is read again; the verdict
 * follows the corrected value; the Reasoning Delta and the audit trail say who changed what.
 */

/** Start the first analysis. A click that lands before the dev server has hydrated the page does nothing: click again unless a run began. */
async function startAnalysis(page: Page) {
  const pill = page.getByTestId("status-pill");
  const button = page.getByTestId("run-button");
  for (let attempt = 0; attempt < 4; attempt++) {
    await button.click({ timeout: 2_000 }).catch(() => undefined); // disabled = a run is already going
    try {
      await expect(pill).not.toContainText("Not assessed yet", { timeout: 8_000 });
      return;
    } catch {
      // nothing started yet
    }
  }
}

async function analyseCaseD(page: Page) {
  await openCaseDDemoWorkbench(page);
  await startAnalysis(page);
  await expect(page.getByTestId("status-pill")).toContainText("Material Contradiction", { timeout: 30_000 });
  return page.getByLabel("Compliance assessment and actions");
}

test.describe("Corrections by the authorised agent", () => {
  test("correct a certificate cell, recompute, and the verdict follows with the reason on record", async ({ page }) => {
    const panel = await analyseCaseD(page);

    // Open the optional source before correcting it; recompute must preserve the document the agent is reviewing.
    await page.getByRole("button", { name: "View PDF", exact: true }).click();
    await expect(page.getByLabel(/^Page 1 of \d+: case_d_mtc_test_cert\.pdf$/)).toBeVisible({ timeout: 15_000 });

    // edit in place on the evidence row that shows the cell
    const edit = panel.getByRole("button", { name: /Correct Certificate cell \d+ in case_d_mtc_test_cert\.pdf/ });
    await expect(edit).toHaveCount(1);
    await edit.click();
    const editor = panel.getByTestId("correction-editor");
    await expect(editor).toContainText("Model read:");
    await expect(editor).toContainText("0.35");
    await editor.getByTestId("correction-value").fill("0.28");
    await editor.getByTestId("correction-reason").fill("certificate prints 0.28 in the Cr column");
    await expect(editor.getByTestId("correction-save")).toHaveText("Save correction");
    await editor.getByTestId("correction-save").click();
    await expect(editor).toHaveCount(0);

    // recorded, shown, and NOT yet in the assessment
    const card = panel.getByTestId("corrections-card");
    await expect(card).toContainText("Corrections (1)");
    await expect(card).toContainText("0.28");
    await expect(card).toContainText("Pending recompute");
    await expect(page.getByTestId("corrections-pending")).toContainText("1 not in this assessment yet");
    await expect(panel.getByTestId("correction-state")).toContainText("Correction pending: 0.28");
    await expect(page.getByTestId("status-pill")).toContainText("Material Contradiction");

    // recompute: no document is read again
    await page.getByTestId("recompute-button").click();
    await expect(page.getByTestId("status-pill")).not.toContainText("Material Contradiction", { timeout: 30_000 });
    await expect(page.getByTestId("status-pill")).toContainText("Specialist Review Required"); // SEC-002 (anti-dumping) is still a warning
    await expect(page.getByTestId("recompute-badge")).toBeVisible();
    await expect(card).toContainText("In this assessment");
    await expect(page.getByTestId("corrections-pending")).toHaveCount(0);
    await expect(page.getByTestId("recompute-button")).toHaveCount(0);
    await expect(panel).not.toContainText("heat TH-77121 reports Cr 0.35%");

    // the Reasoning Delta names the correction, the value it replaced and the reason
    const delta = page.getByLabel("Reasoning delta and audit trail");
    await page.getByRole("tab", { name: "Reasoning Delta", exact: true }).click();
    await expect(page.locator("#panel-delta")).toBeVisible();
    await expect(delta).toContainText("Correction by the authorised agent");
    await expect(delta).toContainText("certificate prints 0.28 in the Cr column");
    await expect(delta).toContainText("0.35 %");
    await expect(delta).toContainText("Correction: Certificate cell"); // the table says what was corrected, not a document id
    await expect(delta).not.toContainText("correction.doc-");
    // the viewer stays on the certificate it was showing: a recompute that clears the finding must not move the page under the reader
    await expect(page.getByLabel(/^Page 1 of \d+: case_d_mtc_test_cert\.pdf$/)).toBeVisible();

    // and the audit chain carries it, intact
    await page.locator("#tab-audit").click();
    await expect(page.getByTestId("audit-verified-badge")).toHaveText("Chain verified");
    await expect(delta).toContainText("FIELD_CORRECTED");
  });

  test("undo a correction and the model's reading is back after a recompute", async ({ page }) => {
    const panel = await analyseCaseD(page);
    await panel.getByRole("button", { name: /Correct Certificate cell \d+ in case_d_mtc_test_cert\.pdf/ }).click();
    await panel.getByTestId("correction-value").fill("0.28");
    await panel.getByTestId("correction-save").click();
    await page.getByTestId("recompute-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Specialist Review Required", { timeout: 30_000 });

    await panel.getByTestId("correction-undo").click();
    await expect(page.getByTestId("corrections-pending")).toContainText("1 not in this assessment yet");
    await page.getByTestId("recompute-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Material Contradiction", { timeout: 30_000 });
    await expect(panel).toContainText("heat TH-77121 reports Cr 0.35%");
    await expect(panel.getByTestId("corrections-card")).toHaveCount(0);
  });

  test("a value the engines could not read without guessing is refused beside the field", async ({ page }) => {
    const panel = await analyseCaseD(page);
    await panel.getByRole("button", { name: /Correct Certificate cell \d+ in case_d_mtc_test_cert\.pdf/ }).click();
    await panel.getByTestId("correction-value").fill("abc");
    await panel.getByTestId("correction-save").click();
    await expect(panel.getByTestId("correction-error")).toContainText("Use a number");
    await expect(panel.getByTestId("correction-editor")).toBeVisible(); // still open: the agent fixes it
    await panel.getByRole("button", { name: "Cancel" }).click();
    await expect(panel.getByTestId("correction-editor")).toHaveCount(0);
    await expect(panel.getByTestId("corrections-card")).toHaveCount(0);
  });

  test("confirming a value as it is read records a confirmation, not a correction", async ({ page }) => {
    const panel = await analyseCaseD(page);
    await panel.getByRole("button", { name: /Correct Certificate cell \d+ in case_d_mtc_test_cert\.pdf/ }).click();
    await expect(panel.getByTestId("correction-save")).toHaveText("Confirm value");
    await panel.getByTestId("correction-save").click();
    await expect(panel.getByTestId("corrections-card")).toContainText("Confirmed: 0.35");
    await page.locator("#tab-audit").click();
    await expect(page.getByLabel("Reasoning delta and audit trail")).toContainText("FIELD_CONFIRMED");
  });

  test("a correction leaves an unsigned tail on the audit trail, and Sign now signs it", async ({ page }) => {
    const panel = await analyseCaseD(page);
    await panel.getByRole("button", { name: /Correct Certificate cell \d+ in case_d_mtc_test_cert\.pdf/ }).click();
    await panel.getByTestId("correction-value").fill("0.28");
    await panel.getByTestId("correction-save").click();
    await expect(panel.getByTestId("corrections-card")).toBeVisible();

    await page.locator("#tab-audit").click();
    const badge = page.getByTestId("audit-signature-badge");
    await expect(badge).toHaveAttribute("data-status", "PARTIAL");
    await expect(badge).toContainText("1 later event not signed yet");
    await page.getByTestId("audit-sign-now").click();
    await expect(badge).toHaveAttribute("data-status", "SIGNED");
    await expect(page.getByTestId("audit-sign-now")).toHaveCount(0);
    await expect(page.getByTestId("audit-verified-badge")).toHaveText("Chain verified");
  });

  test("the open editor and the corrections card have no critical or serious accessibility violations", async ({ page }) => {
    const panel = await analyseCaseD(page);
    await panel.getByRole("button", { name: /Correct Certificate cell \d+ in case_d_mtc_test_cert\.pdf/ }).click();
    await panel.getByTestId("correction-value").fill("0.28");
    await panel.getByTestId("correction-save").click();
    await expect(panel.getByTestId("corrections-card")).toBeVisible();
    await panel.getByRole("button", { name: /Correct Certificate cell \d+ in case_d_mtc_test_cert\.pdf/ }).click();
    await expect(panel.getByTestId("correction-editor")).toBeVisible();

    await page.addStyleTag({ content: "*, *::before, *::after { transition: none !important; animation: none !important; }" });
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });
});
