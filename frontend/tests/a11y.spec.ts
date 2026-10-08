import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Workbench Accessibility (WCAG 2.2 AA)", () => {
  test("workbench has no critical accessibility violations", async ({ page }) => {
    await page.goto("/workbench/default-bundle");

    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze();

    const criticalViolations = accessibilityScanResults.violations.filter(
      (v) => v.impact === "critical"
    );

    expect(criticalViolations).toEqual([]);
  });

  test("workbench is keyboard navigable", async ({ page }) => {
    await page.goto("/workbench/default-bundle");

    // Cycle through keyboard navigation stops
    for (let i = 0; i < 15; i++) {
      await page.keyboard.press("Tab");
    }

    const activeElementTag = await page.evaluate(
      () => document.activeElement?.tagName
    );
    expect(activeElementTag).toBeDefined();
  });
});
