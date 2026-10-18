import { expect, type Page } from "@playwright/test";

/** Create an isolated Case C bundle through the same demo-mode flow a user sees. */
export async function openCaseCDemoWorkbench(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Start Case C demo" })).toBeVisible();
  await expect(
    page.getByText(/Synthetic examples of the evidence-resolution workflow\. Extraction uses filename-keyed fixtures, not real PDF reading\./)
  ).toBeVisible();

  await Promise.all([
    page.waitForURL(/\/workbench\/bnd-[A-Za-z0-9_-]+$/),
    page.getByRole("button", { name: "Start Case C demo" }).click(),
  ]);

  await expect(page.getByTestId("status-pill")).toContainText("Not assessed yet");
  await expect(page.getByLabel("Documents in this bundle").getByTestId("document-item")).toHaveCount(3);
}
