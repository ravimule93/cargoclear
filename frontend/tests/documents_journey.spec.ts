import { test, expect } from "@playwright/test";
import { openCaseCDemoWorkbench } from "./support/case-c";
import { CASE_C_FILES, caseCPath } from "./support/fixtures";

/**
 * Fix items 10 and 11 of the input-gating audit, in the browser: taking a document out of a bundle, and saying what a file is when it
 * is uploaded (declared_type), which the assessment then compares with what the model read (T-001).
 */
test.describe("Documents: remove one, and say what a file is", () => {
  test("a document is removed after a confirmation, and the bundle is reassessed without it", async ({ page }) => {
    await openCaseCDemoWorkbench(page);
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Missing Evidence", { timeout: 30_000 });
    const rail = page.getByLabel("Documents in this bundle");

    // the control belongs to the shown document; asking is a first click, removing is a second
    await rail.getByTestId("document-item").filter({ hasText: "packing_list.pdf" }).click();
    await rail.getByTestId("remove-document").click();
    const confirm = rail.getByRole("group", { name: "Confirm removing packing_list.pdf" });
    await expect(confirm).toContainText("The audit trail keeps a record");

    // Cancel keeps the file
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(rail.getByTestId("document-item")).toHaveCount(3);

    await rail.getByTestId("remove-document").click();
    const [removed] = await Promise.all([
      page.waitForResponse((response) => response.request().method() === "DELETE" && /\/api\/proxy\/bundles\/[^/]+\/documents\/[^/]+$/.test(new URL(response.url()).pathname)),
      rail.getByTestId("confirm-remove-document").click(),
    ]);
    expect(removed.status()).toBe(200);
    expect(await removed.json()).toMatchObject({ filename: "packing_list.pdf", in_latest_assessment: true });
    await expect(rail.getByTestId("document-item")).toHaveCount(2, { timeout: 15_000 });
    await expect(rail).not.toContainText("packing_list.pdf");

    // it was in the newest assessment, so the bundle was assessed again without it
    await expect(page.getByLabel("Compliance assessment and actions")).toContainText("Iteration 2", { timeout: 30_000 });
    await page.locator("#tab-audit").click();
    await expect(page.getByTestId("audit-verified-badge")).toHaveText("Chain verified");
    await expect(page.locator("#panel-audit")).toContainText("DOCUMENT_DELETED");
  });

  test("a confirmation waits for its own document and is withdrawn when another one is shown", async ({ page }) => {
    await openCaseCDemoWorkbench(page);
    const rail = page.getByLabel("Documents in this bundle");

    await rail.getByTestId("document-item").filter({ hasText: "packing_list.pdf" }).click();
    await rail.getByTestId("remove-document").click();
    await expect(rail.getByRole("group", { name: "Confirm removing packing_list.pdf" })).toBeVisible();

    await rail.getByTestId("document-item").filter({ hasText: "bill_of_lading.pdf" }).click();
    await expect(rail.getByRole("group")).toHaveCount(0);

    // coming back, the question is not found already open
    await rail.getByTestId("document-item").filter({ hasText: "packing_list.pdf" }).click();
    await expect(rail.getByRole("group")).toHaveCount(0);
    await expect(rail.getByTestId("remove-document")).toBeVisible();
    await expect(rail.getByTestId("document-item")).toHaveCount(3);
  });

  test("a declared type labels one file; the assessment warns when the model reads another type", async ({ page }) => {
    await page.goto("/");
    await Promise.all([page.waitForURL(/\/workbench\/bnd-[A-Za-z0-9_-]+$/), page.getByRole("button", { name: "New empty bundle" }).click()]);

    // Open multi-file staging and document type classification modal
    await page.getByTestId("classify-upload-button").click();
    await expect(page.getByRole("dialog")).toBeVisible();

    // Stage the files
    const stagingInput = page.getByTestId("staging-file-input");
    await stagingInput.setInputFiles([caseCPath(CASE_C_FILES[0]), caseCPath(CASE_C_FILES[1])]);

    // The fixture CASE_C_FILES[0] is read as an invoice, so explicitly declaring it a packing list must be flagged
    const typeSelect = page.getByLabel(`Document type for ${CASE_C_FILES[0]}`);
    await expect(typeSelect).toBeVisible();
    await typeSelect.selectOption("PACKING_LIST");

    // Upload the staged documents
    const [uploadedInvoice] = await Promise.all([
      page.waitForResponse((response) => response.request().method() === "POST" && /\/api\/proxy\/bundles\/[^/]+\/documents$/.test(new URL(response.url()).pathname)),
      page.getByRole("button", { name: /Upload \d+ Files/i }).click(),
    ]);
    expect(uploadedInvoice.status()).toBe(201);
    expect(await uploadedInvoice.request().headerValue("content-type")).toMatch(/^multipart\/form-data; boundary=/);
    expect(await uploadedInvoice.json()).toMatchObject({ filename: CASE_C_FILES[0], declared_type: "PACKING_LIST" });

    // Modal closes and rail shows 2 documents
    const rail = page.getByLabel("Documents in this bundle");
    await expect(rail.getByTestId("document-item")).toHaveCount(2, { timeout: 30_000 });

    for (let attempt = 0; attempt < 4; attempt++) {
      await page.getByTestId("run-button").click({ timeout: 2_000 }).catch(() => undefined);
      try {
        await expect(page.getByTestId("status-pill")).not.toContainText("Not assessed yet", { timeout: 8_000 });
        break;
      } catch {
        // nothing started yet
      }
    }
    const panel = page.getByLabel("Compliance assessment and actions");
    await expect(panel).toContainText("Document Type Differs From the Upload", { timeout: 30_000 });
    await expect(panel).toContainText("uploaded as a Packing List");
    await expect(panel).toContainText("read it as a Commercial Invoice");
    // only the file that was labelled is flagged
    await expect(panel.getByText("Document Type Differs From the Upload")).toHaveCount(1);
  });
});
