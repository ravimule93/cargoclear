import { expect, type Page } from "@playwright/test";

/** Create an isolated Case D (India import) bundle through the same demo-mode flow a user sees. */
export async function openCaseDDemoWorkbench(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Start Case D demo (India import)" })).toBeVisible();

  await Promise.all([
    page.waitForURL(/\/workbench\/bnd-[A-Za-z0-9_-]+$/),
    page.getByRole("button", { name: "Start Case D demo (India import)" }).click(),
  ]);

  await expect(page.getByTestId("status-pill")).toContainText("Not assessed yet");
  await expect(page.getByLabel("Documents in this bundle").getByTestId("document-item")).toHaveCount(4);
}
