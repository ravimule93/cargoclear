import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { openCaseDDemoWorkbench } from "./support/case-d";

test.describe("Case D: an India import whose certificate contradicts the declared HS code", () => {
  test("a contradiction, an anti-dumping warning and an indicative estimate that states its assumptions", async ({ page }) => {
    await openCaseDDemoWorkbench(page);

    const rail = page.getByLabel("Documents in this bundle");
    for (const name of [
      "case_d_commercial_invoice.pdf",
      "case_d_bill_of_lading.pdf",
      "case_d_packing_list.pdf",
      "case_d_mtc_test_cert.pdf",
    ]) {
      await expect(rail).toContainText(name);
    }

    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Material Contradiction", { timeout: 30_000 });

    // Source is optional. Opening it preserves the automatic finding-document selection: the certificate, not the first in the rail.
    await expect(page.getByTitle("case_d_mtc_test_cert.pdf").first()).toBeVisible();
    await expect(page.getByLabel(/^Page 1 of \d+: case_d_mtc_test_cert\.pdf$/)).not.toBeVisible();
    await page.getByRole("button", { name: "View PDF", exact: true }).click();
    await expect(page.getByLabel(/^Page 1 of \d+: case_d_mtc_test_cert\.pdf$/)).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Close source PDF" }).click();
    await expect(page.getByTestId("status-pill")).toContainText("Material Contradiction");

    const panel = page.getByLabel("Compliance assessment and actions");
    // the contradiction, in words a specialist can act on
    await expect(panel).toContainText("Alloy Status vs Declared HS Code");
    await expect(panel).toContainText("heat TH-77121 reports Cr 0.35%");
    await expect(panel).toContainText("7304.51");
    // the anti-dumping warning
    await expect(panel).toContainText("Anti-Dumping Exposure");
    await expect(panel).toContainText("Anti-dumping duty may apply");
    // everything else holds: the contradiction is the only MATERIAL item (the passed rules are collapsed)
    await expect(panel).toContainText("Verified Rules (");
    // nothing is missing: this is a contradiction, not a gap
    await expect(panel).not.toContainText("Mandatory Trade Documents Required");

    // the estimate: present, labelled indicative, with its assumptions one click away
    const card = page.getByTestId("valuation-card");
    await expect(card).toBeVisible();
    await expect(card).toContainText("Indicative duty exposure (IN, HS 7304.31.00)");
    await expect(card).toContainText("Not a customs determination");
    await expect(card.getByTestId("valuation-status")).toHaveText("Estimate");
    await expect(card.getByTestId("valuation-total")).toContainText("INR");
    await expect(card).toContainText("ADD");
    await expect(card.getByTestId("valuation-implied")).toContainText("7304.51");
    await expect(card.getByTestId("valuation-implied")).toContainText("unchanged");  // the reference data gives both subheadings one set of rates
    await card.getByText(/What this estimate assumed/).click();
    await expect(card.getByTestId("valuation-assumptions")).toContainText("ILLUSTRATIVE");
    await expect(card.getByTestId("valuation-assumptions")).toContainText("insurance is not stated");
    await expect(card).toContainText("demo-curated");

    // the audit chain is intact
    await page.locator("#tab-audit").click();
    await expect(page.getByTestId("audit-verified-badge")).toHaveText("Chain verified");
  });

  test("the result page has no critical or serious accessibility violations", async ({ page }) => {
    await openCaseDDemoWorkbench(page);
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Material Contradiction", { timeout: 30_000 });
    await expect(page.getByTestId("valuation-card")).toBeVisible();
    // the run button fades out of its disabled state: scan the settled page, not a frame of a transition
    await page.addStyleTag({ content: "*, *::before, *::after { transition: none !important; animation: none !important; }" });
    await expect(page.getByTestId("run-button")).toBeEnabled();

    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");

    expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  });

  test("Case C still ends compliant, with the new checks passing and an estimate beside the verdict", async ({ page }) => {
    await page.goto("/");
    await Promise.all([
      page.waitForURL(/\/workbench\/bnd-[A-Za-z0-9_-]+$/),
      page.getByRole("button", { name: "Start Case C demo" }).click(),
    ]);
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Missing Evidence", { timeout: 30_000 });
    await page.getByTestId("sample-mtc-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Compliant For Submission", { timeout: 30_000 });

    const panel = page.getByLabel("Compliance assessment and actions");
    await panel.getByRole("button", { name: /Verified Rules/ }).click();
    for (const title of ["Alloy Status vs Declared HS Code", "Carbon Equivalent vs Specification", "Chemistry & Strength vs Specification", "Heat-Number Traceability", "Invoice Line Arithmetic"]) {
      await expect(panel).toContainText(title);
    }
    await expect(page.getByTestId("valuation-card")).toContainText("Indicative duty exposure (SG, HS 7304.19.00)");
    await expect(page.getByTestId("valuation-total")).toContainText("SGD");
  });
});
