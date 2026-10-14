import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { CASE_D_FILES, caseDPath } from "./support/fixtures";

/**
 * The route a LIVE deployment offers: no demo buttons, so a person creates an empty bundle, chooses where the goods are going,
 * uploads the documents and runs the analysis. (In demo mode the extraction is keyed on the file names, so the same upload
 * reaches the same verdict as the Case D button: that is what lets this run without Google Cloud.)
 */
test.describe("Choosing the destination and uploading", () => {
  test("the home page offers Singapore and India, defaults to Singapore, and is accessible", async ({ page }) => {
    await page.goto("/");
    const select = page.getByTestId("destination-select");
    await expect(select).toHaveValue("SG");
    await expect(select.locator("option")).toHaveText(["Singapore (SG)", "India (IN)"]);

    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations.filter((v) => v.impact === "critical" || v.impact === "serious")).toEqual([]);

    await Promise.all([page.waitForURL(/\/workbench\/bnd-[A-Za-z0-9_-]+$/), page.getByRole("button", { name: "New empty bundle" }).click()]);
    await expect(page.getByTestId("bundle-destination")).toHaveText("To SG");
  });

  test("an India-import bundle created empty, filled by upload, reaches the Case D verdict", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("destination-select").selectOption("IN");
    await Promise.all([page.waitForURL(/\/workbench\/bnd-[A-Za-z0-9_-]+$/), page.getByRole("button", { name: "New empty bundle" }).click()]);
    await expect(page.getByTestId("bundle-destination")).toHaveText("To IN");
    await expect(page.getByTestId("status-pill")).toContainText("Not assessed yet");

    await page.getByTestId("upload-input").first().setInputFiles(CASE_D_FILES.map(caseDPath));
    await expect(page.getByLabel("Documents in this bundle").getByRole("button")).toHaveCount(4, { timeout: 30_000 });

    // a click that lands before hydration does nothing: click again unless a run began
    const pill = page.getByTestId("status-pill");
    for (let attempt = 0; attempt < 4; attempt++) {
      await page.getByTestId("run-button").click({ timeout: 2_000 }).catch(() => undefined);
      try {
        await expect(pill).not.toContainText("Not assessed yet", { timeout: 8_000 });
        break;
      } catch {
        // nothing started yet
      }
    }
    await expect(pill).toContainText("Material Contradiction", { timeout: 30_000 });
    const panel = page.getByLabel("Compliance assessment and actions");
    await expect(panel).toContainText("TH-77121");
    await expect(page.getByTestId("valuation-card")).toContainText("IN");
  });
});
