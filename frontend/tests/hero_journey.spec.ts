import { test, expect } from "@playwright/test";

test.describe("Hero Case C Demo Workflow", () => {
  test("loads workbench, displays initial missing evidence, and allows audit inspection", async ({ page }) => {
    await page.goto("/workbench/HERO-CASE-C-7304");

    // 1. Verify TopBar branding and bundle ID
    await expect(page.getByRole("banner")).toContainText("CargoClear");
    await expect(page.getByRole("banner")).toContainText("HERO-CASE-C-7304");

    // 2. Verify initial status pill shows Missing Evidence
    const statusPill = page.getByRole("status");
    await expect(statusPill).toContainText("Missing Evidence");

    // 3. Verify Document Rail contains the 3 initial trade files
    const rail = page.getByLabel("Documents in this bundle");
    await expect(rail).toContainText("Commercial_Invoice");
    await expect(rail).toContainText("Bill_of_Lading");
    await expect(rail).toContainText("Packing_List");

    // 4. Verify Compliance Assessment panel details
    const assessPanel = page.getByLabel("Compliance assessment and actions");
    await expect(assessPanel).toContainText("Mandatory Trade Documents Required");
    await expect(assessPanel).toContainText("Mill Test Certificate");

    // 5. Verify upload dropzone is ready for corrective certificate
    await expect(page.getByText("Upload Missing Certificate (PDF)")).toBeVisible();

    // 6. Test DeltaDrawer tab switching
    const auditTab = page.locator("#tab-audit");
    await auditTab.click();
    await expect(auditTab).toHaveAttribute("aria-selected", "true");

    const deltaTab = page.locator("#tab-delta");
    await deltaTab.click();
    await expect(deltaTab).toHaveAttribute("aria-selected", "true");
  });
});
