import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const pdf = (name: string) => ({
  name,
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4\n% Upload interaction test fixture\n%%EOF"),
});

async function openEmptyWorkbench(page: Page) {
  await page.goto("/");
  await Promise.all([
    page.waitForURL(/\/workbench\/bnd-[A-Za-z0-9_-]+$/),
    page.getByRole("button", { name: "New empty bundle" }).click(),
  ]);
}

test("upload dialog contains focus, hides background from assistive technology, and restores its trigger", async ({ page }) => {
  await openEmptyWorkbench(page);
  const trigger = page.getByTestId("classify-upload-button");
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Add & Classify Trade Documents" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Close dialog" })).toBeFocused();
  expect(await trigger.evaluate((element) => Boolean(element.closest('[aria-hidden="true"]')))).toBe(true);

  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  for (let step = 0; step < 8; step++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
    expect(await page.evaluate(() => (document.activeElement as HTMLInputElement)?.type === "file")).toBe(false);
  }

  const scan = await new AxeBuilder({ page }).include('[role="dialog"]').withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(scan.violations.filter((item) => item.impact === "serious" || item.impact === "critical")).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("partial uploads stay open, expose per-file errors, and retry only the failed file", async ({ page }) => {
  await openEmptyWorkbench(page);
  const requests: string[] = [];
  let failSecond = true;
  await page.route("**/api/proxy/bundles/*/documents", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const body = route.request().postDataBuffer()?.toString() ?? "";
    const filename = body.includes("invoice.pdf") ? "invoice.pdf" : "packing list.pdf";
    requests.push(filename);
    if (filename === "packing list.pdf" && failSecond) {
      failSecond = false;
      return route.fulfill({ status: 503, json: { code: "TEMPORARY_UNAVAILABLE", message: "Upload service temporarily unavailable" } });
    }
    return route.fulfill({ status: 200, json: { id: `doc-upload-${requests.length}`, filename, doc_type: "UNKNOWN" } });
  });

  await page.getByTestId("classify-upload-button").click();
  const dialog = page.getByRole("dialog");
  await page.getByTestId("staging-file-input").setInputFiles([pdf("invoice.pdf"), pdf("packing list.pdf")]);
  await dialog.getByRole("button", { name: "Upload 2 Files", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("1 of 2 files uploaded");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId("staged-file-row").filter({ hasText: "invoice.pdf" })).toContainText("Uploaded");
  const failedRow = dialog.getByTestId("staged-file-row").filter({ hasText: "packing list.pdf" });
  await expect(failedRow).toContainText("Upload failed: Upload service temporarily unavailable");
  const describedStatusId = await failedRow.getByRole("combobox").getAttribute("aria-describedby");
  expect(await page.evaluate((id) => document.getElementById(id!)?.textContent, describedStatusId)).toContain("Upload failed");
  await dialog.getByRole("button", { name: "Retry 1 File", exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(requests).toEqual(["invoice.pdf", "packing list.pdf", "packing list.pdf"]);
});

test("a cancelled batch resets when reopened, and the same file can be selected after removal", async ({ page }) => {
  await openEmptyWorkbench(page);
  const trigger = page.getByTestId("classify-upload-button");
  await trigger.click();
  const dialog = page.getByRole("dialog");
  const input = page.getByTestId("staging-file-input");
  await input.setInputFiles(pdf("invoice.pdf"));
  await expect(dialog.getByTestId("staged-file-row")).toHaveCount(1);
  const classification = dialog.getByRole("combobox", { name: "Document type for invoice.pdf", exact: true });
  await expect(classification).toHaveValue("COMMERCIAL_INVOICE");
  await classification.focus();
  await expect(classification).toBeFocused();
  await page.keyboard.press("Space");
  await page.keyboard.press("m");
  await page.keyboard.press("Enter");
  await expect(classification).toHaveValue("MILL_TEST_CERTIFICATE");
  await dialog.getByRole("button", { name: "Remove invoice.pdf", exact: true }).click();
  await input.setInputFiles(pdf("invoice.pdf"));
  await expect(dialog.getByTestId("staged-file-row")).toHaveCount(1);
  await expect(classification).toHaveValue("COMMERCIAL_INVOICE");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await trigger.click();
  await expect(dialog).toContainText("No documents staged yet.");
  await expect(dialog.getByTestId("staged-file-row")).toHaveCount(0);
});

test("an active upload announces its file and prevents accidental dismissal", async ({ page }) => {
  await openEmptyWorkbench(page);
  let releaseUpload = () => {};
  const uploadGate = new Promise<void>((resolve) => { releaseUpload = resolve; });
  await page.route("**/api/proxy/bundles/*/documents", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await uploadGate;
    await route.fulfill({ status: 200, json: { id: "doc-busy-test", filename: "invoice.pdf", doc_type: "UNKNOWN" } });
  });
  await page.getByTestId("classify-upload-button").click();
  const dialog = page.getByRole("dialog");
  await page.getByTestId("staging-file-input").setInputFiles(pdf("invoice.pdf"));
  try {
    await dialog.getByRole("button", { name: "Upload 1 File", exact: true }).click();
    await expect(dialog.getByRole("status")).toContainText("Uploading invoice.pdf, file 1 of 1.");
    await expect(dialog.getByTestId("staged-file-row")).toContainText("Uploading…");
    await expect(dialog.getByRole("progressbar", { name: "Files processed in this batch" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Close dialog" })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
  } finally {
    releaseUpload();
  }
  await expect(dialog).toBeHidden();
});
