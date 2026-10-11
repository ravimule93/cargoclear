import { test, expect } from "@playwright/test";
import { openCaseCDemoWorkbench } from "./support/case-c";

test.describe("Hero Case C Demo Workflow", () => {
  test("creates, analyzes, corrects, and audits an isolated Case C demo bundle", async ({ page }) => {
    await openCaseCDemoWorkbench(page);

    // A newly created demo workbench has its three documents but no assessment yet.
    await expect(page.getByRole("banner")).toContainText("CargoClear");
    await expect(page.getByTestId("demo-banner")).toContainText(
      "extraction uses synthetic fixtures keyed on filename, not a real document reading"
    );
    await expect(page.getByLabel("Compliance assessment and actions")).toContainText("No assessment yet");

    // The Case C evidence is created by the demo endpoint, not a pre-existing hardcoded bundle.
    const rail = page.getByLabel("Documents in this bundle");
    await expect(rail).toContainText("commercial_invoice.pdf");
    await expect(rail).toContainText("bill_of_lading.pdf");
    await expect(rail).toContainText("packing_list.pdf");

    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Missing Evidence", { timeout: 30_000 });
    const assessPanel = page.getByLabel("Compliance assessment and actions");
    await expect(assessPanel).toContainText("Mandatory Trade Documents Required");
    await expect(assessPanel).toContainText("Mill Test Certificate");
    await expect(page.getByTestId("sample-mtc-button")).toBeVisible();

    await page.getByTestId("sample-mtc-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Compliant For Submission", { timeout: 30_000 });

    const deltaTab = page.locator("#tab-delta");
    await deltaTab.click();
    await expect(deltaTab).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#panel-delta")).not.toBeEmpty();

    const auditTab = page.locator("#tab-audit");
    await auditTab.click();
    await expect(auditTab).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("audit-verified-badge")).toHaveText("Chain verified");
  });
});
