import { expect, test, type Locator, type Page } from "@playwright/test";
import type { AssessmentIteration, Bundle, DocumentRecord, UserIdentity } from "../lib/types";

const BUNDLE_ID = "bnd-document-controls";
const PATH = `/workbench/${BUNDLE_ID}`;
const user: UserIdentity = {
  user_id: "usr-document-controls", email: "review@example.com", name: "Review Agent",
  tenant_id: "example.com", role: "LICENSED_CHA", issuer: "test-fixture-only",
};
const pdf = (name: string) => ({ name, mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n% Synthetic interaction fixture\n%%EOF") });
const record = (id: string, filename: string, docType: string): DocumentRecord => ({
  document_id: id, bundle_id: BUNDLE_ID, filename, doc_type: docType,
  gcs_uri: "test-fixture-only", sha256: "test-fixture-only", bytes: 100, uploaded_at: "2026-10-18T00:00:00Z",
});

/** Fully mocked UI fixtures: uploads and reassessment never reach a real account or document processor. */
async function mockControls(page: Page, authenticated = true) {
  let signedIn = authenticated;
  const requests: string[] = [];
  const uploads: { filename: string | null; declaredType: string | null }[] = [];
  const documents = [
    record("doc-controls-invoice", "invoice.pdf", "COMMERCIAL_INVOICE"),
    record("doc-controls-lading", "bill_of_lading.pdf", "BILL_OF_LADING"),
    record("doc-controls-packing", "packing_list.pdf", "PACKING_LIST"),
  ];
  const bundle: Bundle = {
    id: BUNDLE_ID, reference: "Synthetic document controls test", destination_country: "SG",
    status: "MISSING_EVIDENCE", current_iteration: 1, documents, created_at: "2026-10-18T00:00:00Z",
  };
  const assessment: AssessmentIteration = {
    bundle_id: BUNDLE_ID, iteration: 1, status: "MISSING_EVIDENCE", data_source: "fixture",
    documents: documents.map((document) => document.document_id), checks: [], grounding: [],
    missing_evidence: [{ id: "ME-MILL_TEST_CERTIFICATE", document_label: "Mill Test Certificate", hs_code: "73041900", reason: "Synthetic interaction fixture only." }],
    confidence: { min_field_confidence: 0.99, action: "AUTO_ACCEPT" },
    reasoning_delta: { kind: "INITIAL", narrative: "Synthetic interaction fixture only." },
  };
  const status = { kind: "status", bundle_id: BUNDLE_ID, run_id: "run-controls", state: "COMPLETE", progress: 1 };

  await page.route("**/api/proxy/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.slice("/api/proxy".length);
    if (path === "/meta") return route.fulfill({ json: {
      app_mode: "demo", data_source_policy: "test-fixture-only", pipeline_engine: "native",
      auth: { enabled: true, allowed_email_domains: ["*"] }, user: signedIn ? user : null,
    } });
    if (path === "/mode") return route.fulfill({ json: {
      active_mode: "demo", configured_mode: "demo", supported_modes: ["demo", "live"],
      live_available: false, credential_source: null, provider: "test-fixture-only", model: "test-fixture-only",
    } });
    requests.push(`${request.method()} ${path}`);
    if (!signedIn) return route.fulfill({ status: 401, json: { code: "UNAUTHORIZED", message: "Authentication required. Please sign in to continue." } });
    if (path === "/bundles") return route.fulfill({ json: [] });
    if (path === `/bundles/${BUNDLE_ID}`) return route.fulfill({ json: bundle });
    if (path === `/bundles/${BUNDLE_ID}/assessment`) return route.fulfill({ json: assessment });
    if (path === `/bundles/${BUNDLE_ID}/iterations`) return route.fulfill({ json: [assessment] });
    if (path === `/bundles/${BUNDLE_ID}/extractions`) return route.fulfill({ json: [] });
    if (path === `/bundles/${BUNDLE_ID}/corrections`) return route.fulfill({ json: { corrections: [], effective: [], pending: 0 } });
    if (path === `/bundles/${BUNDLE_ID}/status`) return route.fulfill({ json: status });
    if (path === `/bundles/${BUNDLE_ID}/stream`) return route.fulfill({
      contentType: "text/event-stream",
      body: `retry: 60000\nevent: iteration\ndata: ${JSON.stringify(assessment)}\n\nevent: status\ndata: ${JSON.stringify(status)}\n\n`,
    });
    if (path === `/bundles/${BUNDLE_ID}/reassess`) return route.fulfill({ status: 202, json: status });
    if (path === `/bundles/${BUNDLE_ID}/documents` && request.method() === "POST") {
      const body = request.postDataBuffer()?.toString("utf8") ?? "";
      const filename = /name="file"; filename="([^"]+)"/.exec(body)?.[1] ?? null;
      const declaredType = /name="declared_type"\r?\n\r?\n([^\r\n]+)/.exec(body)?.[1] ?? null;
      uploads.push({ filename, declaredType });
      const uploaded = record(`doc-controls-upload-${uploads.length}`, filename ?? "unknown.pdf", "UNKNOWN");
      uploaded.declared_type = declaredType;
      documents.push(uploaded);
      return route.fulfill({ status: 201, json: uploaded });
    }
    return route.fulfill({ status: 404, json: { code: "NOT_FOUND", message: "Unused document-controls test route" } });
  });
  return { requests, uploads, setSignedIn: (value: boolean) => { signedIn = value; } };
}

async function openMissingAssessment(page: Page) {
  await page.goto(PATH);
  await expect(page.getByTestId("decision-status-pill")).toContainText("Missing Evidence");
  await expect(page.getByTestId("next-action")).toHaveText("Add required evidence");
}

async function expectCenteredNativeChevron(select: Locator) {
  const style = await select.evaluate((element) => {
    const computed = getComputedStyle(element);
    return {
      appearance: computed.appearance, image: computed.backgroundImage,
      positionY: computed.backgroundPositionY, repeat: computed.backgroundRepeat,
      paddingEnd: parseFloat(computed.paddingInlineEnd),
    };
  });
  expect(style.appearance).toBe("none");
  expect(style.image).not.toBe("none");
  expect(style.positionY.split(",").every((value) => value.trim() === "50%")).toBe(true);
  expect(style.repeat.split(",").every((value) => value.trim() === "no-repeat")).toBe(true);
  expect(style.paddingEnd).toBeGreaterThanOrEqual(32);
}

for (const opener of ["next-action", "classify-upload-button"] as const) {
  test(`${opener} opens one shared classifier and Escape restores its trigger`, async ({ page }) => {
    await mockControls(page);
    await openMissingAssessment(page);
    const panel = page.getByLabel("Compliance assessment and actions", { exact: true });
    await expect(panel.getByRole("combobox")).toHaveCount(0);
    await expect(panel.getByRole("button", { name: /multi-file staging.*classification/i })).toHaveCount(0);
    await expect(panel.getByRole("button", { name: /upload missing certificate/i })).toHaveCount(0);
    const trigger = page.getByTestId(opener);
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "Add & Classify Trade Documents" });
    await expect(dialog).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(1);
    await expect(dialog.getByRole("button", { name: "Close dialog" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });
}

test("one staged PDF keeps keyboard classification and its declared type in the upload payload", async ({ page }) => {
  const { uploads } = await mockControls(page);
  await openMissingAssessment(page);
  await page.getByTestId("next-action").click();
  const dialog = page.getByRole("dialog", { name: "Add & Classify Trade Documents" });
  await dialog.getByTestId("staging-file-input").setInputFiles(pdf("support.pdf"));
  const classification = dialog.getByRole("combobox", { name: "Document type for support.pdf", exact: true });
  await classification.focus();
  await page.keyboard.press("Space");
  await page.keyboard.press("m");
  await page.keyboard.press("Enter");
  await expect(classification).toHaveValue("MILL_TEST_CERTIFICATE");
  await dialog.getByRole("button", { name: "Upload 1 File", exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(uploads).toEqual([{ filename: "support.pdf", declaredType: "MILL_TEST_CERTIFICATE" }]);
});

test("a multi-file batch keeps separate native classification and declared types for each PDF", async ({ page }) => {
  const { uploads } = await mockControls(page);
  await openMissingAssessment(page);
  await page.getByTestId("next-action").click();
  const dialog = page.getByRole("dialog", { name: "Add & Classify Trade Documents" });
  await dialog.getByTestId("staging-file-input").setInputFiles([pdf("invoice.pdf"), pdf("packing_list.pdf")]);
  const invoice = dialog.getByRole("combobox", { name: "Document type for invoice.pdf", exact: true });
  const packing = dialog.getByRole("combobox", { name: "Document type for packing_list.pdf", exact: true });
  await invoice.focus();
  await page.keyboard.press("Space");
  await page.keyboard.press("b");
  await page.keyboard.press("Enter");
  await expect(invoice).toHaveValue("BILL_OF_LADING");
  await packing.focus();
  await page.keyboard.press("Space");
  await page.keyboard.press("m");
  await page.keyboard.press("Enter");
  await expect(packing).toHaveValue("MILL_TEST_CERTIFICATE");
  await dialog.getByRole("button", { name: "Upload 2 Files", exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(uploads).toEqual([
    { filename: "invoice.pdf", declaredType: "BILL_OF_LADING" },
    { filename: "packing_list.pdf", declaredType: "MILL_TEST_CERTIFICATE" },
  ]);
});

for (const width of [320, 390]) {
  test(`shared classification at ${width}px contains long filenames and native dropdowns without horizontal overflow`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockControls(page);
    await openMissingAssessment(page);
    const trigger = page.getByTestId("next-action");
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "Add & Classify Trade Documents" });
    const invoiceName = "very-long-commercial-invoice-reference-for-india-singapore-October-2026-shipment-INV-1234567890.pdf";
    const packingName = "very-long-packing-list-reference-for-multiple-cargo-lines-October-2026-bundle-PL-1234567890.pdf";
    await dialog.getByTestId("staging-file-input").setInputFiles([pdf(invoiceName), pdf(packingName)]);
    await expect(dialog.getByTestId("staged-file-row")).toHaveCount(2);
    await expect(dialog.getByText(invoiceName, { exact: true })).toBeVisible();
    await expect(dialog.getByText(packingName, { exact: true })).toBeVisible();
    const invoice = dialog.getByRole("combobox", { name: `Document type for ${invoiceName}`, exact: true });
    const packing = dialog.getByRole("combobox", { name: `Document type for ${packingName}`, exact: true });
    await expect(invoice).toHaveValue("COMMERCIAL_INVOICE");
    await expect(packing).toHaveValue("PACKING_LIST");
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    const dialogBox = (await dialog.boundingBox())!;
    expect(dialogBox.x).toBeGreaterThanOrEqual(0);
    expect(dialogBox.x + dialogBox.width).toBeLessThanOrEqual(width);
    for (const classification of [invoice, packing]) {
      await expectCenteredNativeChevron(classification);
      const bounds = (await classification.boundingBox())!;
      expect(bounds.x).toBeGreaterThanOrEqual(dialogBox.x);
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(Math.min(width, dialogBox.x + dialogBox.width));
    }
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`${theme} native dropdowns share centered chevrons and the signed-out destination explains its disabled state`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem("cargoclear-theme", value), theme);
    const fixture = await mockControls(page, false);
    await page.goto("/");
    const destination = page.getByTestId("destination-select");
    await expect(destination).toBeDisabled();
    await expect(destination).toHaveAttribute("aria-describedby", "destination-sign-in-hint");
    await expect(page.locator("#destination-sign-in-hint")).toHaveText("Sign in to change destination.");
    await expect(page.locator("#destination-sign-in-hint")).toBeVisible();
    await expect(destination).toHaveCSS("cursor", "not-allowed");
    expect(await destination.evaluate((element) => Number(getComputedStyle(element).opacity))).toBeLessThan(1);
    await expectCenteredNativeChevron(destination);
    expect(fixture.requests).toEqual([]);

    fixture.setSignedIn(true);
    await page.reload();
    await expect(destination).toBeEnabled();
    await expectCenteredNativeChevron(destination);
    await destination.focus();
    await page.keyboard.press("Space");
    await page.keyboard.press("i");
    await page.keyboard.press("Enter");
    await expect(destination).toHaveValue("IN");

    await openMissingAssessment(page);
    const files = page.getByRole("region", { name: "Bundle files", exact: true });
    await files.getByRole("button", { name: /reclassify type/i }).click();
    const reclassification = files.getByRole("combobox", { name: "Correct document type for invoice.pdf", exact: true });
    await expectCenteredNativeChevron(reclassification);
    await files.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.getByTestId("next-action").click();
    const dialog = page.getByRole("dialog", { name: "Add & Classify Trade Documents" });
    await dialog.getByTestId("staging-file-input").setInputFiles(pdf("support.pdf"));
    await expectCenteredNativeChevron(dialog.getByRole("combobox", { name: "Document type for support.pdf", exact: true }));
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });
}
