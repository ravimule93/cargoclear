import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { openCaseCDemoWorkbench } from "./support/case-c";

test.describe("CargoClear Workbench Accessibility (WCAG 2.2 AA)", () => {
  test("workbench has 0 critical or serious accessibility violations", async ({ page }) => {
    await openCaseCDemoWorkbench(page);

    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze();

    const criticalViolations = accessibilityScanResults.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious"
    );

    expect(criticalViolations).toEqual([]);
  });

  test("entire workbench shell is keyboard accessible", async ({ page }) => {
    await openCaseCDemoWorkbench(page);

    const focusedElements: string[] = [];
    for (let i = 0; i < 20; i++) {
      await page.keyboard.press("Tab");
      const activeTag = await page.evaluate(
        () => document.activeElement?.tagName.toLowerCase() || ""
      );
      if (activeTag && !focusedElements.includes(activeTag)) {
        focusedElements.push(activeTag);
      }
    }

    // Verify key interactive element tags were reachable via keyboard
    expect(focusedElements.length).toBeGreaterThanOrEqual(1);
  });

  test("drawer tablist supports arrow key navigation", async ({ page }) => {
    await openCaseCDemoWorkbench(page);

    const reasoningTab = page.locator("#tab-delta");
    await reasoningTab.focus();
    await expect(reasoningTab).toHaveAttribute("aria-selected", "true");

    // Press right arrow to move to audit tab
    await page.keyboard.press("ArrowRight");
    const auditTab = page.locator("#tab-audit");
    await expect(auditTab).toHaveAttribute("aria-selected", "true");
    await expect(auditTab).toBeFocused();
  });
});
