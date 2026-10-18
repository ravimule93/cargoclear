import { expect, test, type Page, type TestInfo } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type { AssessmentIteration, Bundle, DocumentRecord } from "../lib/types";
import { openCaseCDemoWorkbench } from "./support/case-c";
import { openCaseDDemoWorkbench } from "./support/case-d";

const assessmentPanel = (page: Page) => page.getByLabel("Compliance assessment and actions", { exact: true });
const sourcePanel = (page: Page) => page.getByLabel("Document viewer and annotations", { exact: true });
const pdfFileRequest = /\/api\/proxy\/bundles\/[^/]+\/documents\/[^/]+\/file(?:\?|$)/;

async function completeCaseD(page: Page) {
  await openCaseDDemoWorkbench(page);
  await page.getByTestId("run-button").click();
  await expect(page.getByTestId("status-pill")).toContainText("Material Contradiction", { timeout: 30_000 });
  await expect(page.getByTestId("run-button")).toBeEnabled();
}

async function expectNoPageOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => ({
    horizontal: document.documentElement.scrollWidth > window.innerWidth,
    vertical: document.documentElement.scrollHeight > window.innerHeight,
  }))).toEqual({ horizontal: false, vertical: false });
}

async function attachViewport(page: Page, testInfo: TestInfo, name: string) {
  const screenshotPath = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path: screenshotPath });
  await testInfo.attach(name, { path: screenshotPath, contentType: "image/png" });
}

test.describe("Decision workspace and contextual evidence", () => {
  test("compact source returns to its file and Escape on another section does not change navigation", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    await openCaseCDemoWorkbench(page);
    await page.locator("#tab-btn-rail").click();
    const file = page.getByTestId("document-item").first();
    await file.click();
    await expect(sourcePanel(page)).toBeFocused();
    await page.getByRole("button", { name: "Close source PDF" }).click();
    await expect(page.locator("#tab-btn-rail")).toHaveAttribute("aria-selected", "true");
    await expect(file).toBeFocused();

    await file.click();
    await page.locator("#tab-btn-drawer").click();
    await page.keyboard.press("Escape");
    await expect(page.locator("#tab-btn-drawer")).toBeFocused();
    await expect(page.locator("#tab-btn-drawer")).toHaveAttribute("aria-selected", "true");
    const skip = page.getByRole("link", { name: "Skip to assessment", exact: true });
    await skip.focus();
    await page.keyboard.press("Enter");
    await expect(assessmentPanel(page)).toBeVisible();
    await expect(assessmentPanel(page)).toBeFocused();
    await expect(page.locator("#tab-btn-assess")).toHaveAttribute("aria-selected", "true");
  });

  test("required-evidence action opens classification and a background decision never steals dialog focus", async ({ page }) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await openCaseCDemoWorkbench(page);
    await page.getByTestId("run-button").click();
    await expect(page.getByTestId("status-pill")).toContainText("Missing Evidence", { timeout: 30_000 });
    await expect(page.getByTestId("run-button")).toBeEnabled();
    const nextAction = page.getByTestId("next-action");
    await expect(nextAction).toHaveText("Add required evidence");
    const panel = assessmentPanel(page);
    await expect(panel.getByRole("button", { name: /multi-file staging.*classification/i })).toHaveCount(0);
    await expect(panel.getByRole("button", { name: /upload missing certificate/i })).toHaveCount(0);
    await expect(panel.getByRole("combobox", { name: "Type of the next document (optional)", exact: true })).toHaveCount(0);
    await nextAction.click();
    const dialog = page.getByRole("dialog", { name: "Add & Classify Trade Documents" });
    const close = dialog.getByRole("button", { name: "Close dialog" });
    await expect(dialog).toBeVisible();
    await expect(close).toBeFocused();
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
    await close.focus();

    // Another client can finish a run while this agent is classifying files. Use this test's
    // isolated bundle and the real sample/upload/reassess APIs to exercise that status change.
    await page.evaluate(() => {
      const state = window as Window & { outsideDialogFocus: string[] };
      state.outsideDialogFocus = [];
      document.addEventListener("focusin", (event) => {
        const target = event.target;
        if (target instanceof HTMLElement && document.querySelector('[role="dialog"]') && !target.closest('[role="dialog"]')) {
          state.outsideDialogFocus.push(target.id || target.tagName);
        }
      });
    });
    const bundleId = new URL(page.url()).pathname.split("/").at(-1)!;
    const sample = await page.request.get("/api/proxy/demo/case-c/mtc");
    expect(sample.ok()).toBe(true);
    const upload = await page.request.post(`/api/proxy/bundles/${bundleId}/documents`, {
      multipart: { file: { name: "mtc_pipe_test_cert.pdf", mimeType: "application/pdf", buffer: await sample.body() } },
    });
    expect(upload.ok()).toBe(true);
    const reassess = await page.request.post(`/api/proxy/bundles/${bundleId}/reassess`, { data: { mode: "full" } });
    expect(reassess.ok()).toBe(true);
    await expect(page.getByTestId("status-pill")).toContainText("Compliant For Submission", { timeout: 30_000 });
    await expect(close).toBeFocused();
    expect(await page.evaluate(() => (window as Window & { outsideDialogFocus: string[] }).outsideDialogFocus)).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(nextAction).toBeFocused();
    await expect(nextAction).toHaveText("Review declaration prefill");
  });

  test("Case D loads source only on demand and closes to the cited evidence without losing review position", async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    const requestedFiles: string[] = [];
    page.on("request", (request) => { if (pdfFileRequest.test(request.url())) requestedFiles.push(request.url()); });
    await completeCaseD(page);
    await expect(sourcePanel(page)).toBeHidden();
    expect(requestedFiles).toEqual([]);
    const panel = assessmentPanel(page);
    const evidence = panel.getByRole("button", { name: /^Open case_d_mtc_test_cert\.pdf, page 1$/ }).first();
    await evidence.scrollIntoViewIfNeeded();
    await evidence.focus();
    const scroller = panel.locator(".cc-assessment-content");
    const before = await scroller.evaluate((element) => element.scrollTop);
    await evidence.click();
    await expect(sourcePanel(page)).toBeVisible();
    await expect(sourcePanel(page)).toBeFocused();
    await expect(sourcePanel(page).getByRole("img", { name: /^Page 1 of \d+: case_d_mtc_test_cert\.pdf$/ })).toBeVisible({ timeout: 15_000 });
    expect(requestedFiles.length).toBeGreaterThan(0);
    await expect(panel.getByTestId("next-action")).toBeVisible();
    await expect(evidence).toBeInViewport();
    await attachViewport(page, testInfo, "case-d-decision-and-source");
    await page.getByRole("button", { name: "Close source PDF" }).click();
    await expect(sourcePanel(page)).toBeHidden();
    await expect(evidence).toBeFocused();
    await expect.poll(async () => Math.abs(await scroller.evaluate((element) => element.scrollTop) - before)).toBeLessThanOrEqual(12);
    await evidence.click();
    await expect(sourcePanel(page)).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(sourcePanel(page)).toBeHidden();
    await expect(evidence).toBeFocused();
  });

  for (const width of [320, 390, 768, 1023]) {
    test(`compact workbench at ${width}px has roving section tabs, hidden inactive panels and no page overflow`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      await openCaseCDemoWorkbench(page);
      const sections = page.getByRole("tablist", { name: "Workbench sections" });
      const assess = page.locator("#tab-btn-assess");
      const viewer = page.locator("#tab-btn-viewer");
      const rail = page.locator("#tab-btn-rail");
      const drawer = page.locator("#tab-btn-drawer");
      await expect(sections).toBeVisible();
      await expect(assessmentPanel(page)).toHaveAttribute("role", "tabpanel");
      await assess.focus();
      await page.keyboard.press("ArrowRight");
      await expect(viewer).toBeFocused();
      await expect(viewer).toHaveAttribute("aria-selected", "true");
      await expect(sourcePanel(page)).toBeVisible();
      await expect(assessmentPanel(page)).toBeHidden();
      await expect(sourcePanel(page).getByRole("img", { name: /^Page 1 of \d+:/ })).toBeVisible({ timeout: 15_000 });
      const tabsBounds = await sections.boundingBox();
      const headingBounds = await sourcePanel(page).getByRole("heading", { name: "Source document", exact: true }).boundingBox();
      const closeBounds = await sourcePanel(page).getByRole("button", { name: "Close source PDF", exact: true }).boundingBox();
      expect(tabsBounds).not.toBeNull();
      expect(headingBounds).not.toBeNull();
      expect(closeBounds).not.toBeNull();
      expect(headingBounds!.y).toBeGreaterThanOrEqual(tabsBounds!.y + tabsBounds!.height - 1);
      expect(closeBounds!.y).toBeGreaterThanOrEqual(tabsBounds!.y + tabsBounds!.height - 1);
      expect(closeBounds!.y + closeBounds!.height).toBeLessThanOrEqual(900);
      await attachViewport(page, testInfo, `compact-${width}-source`);
      await page.keyboard.press("ArrowRight");
      await expect(rail).toBeFocused();
      await expect(page.getByRole("tabpanel", { name: "Bundle files", exact: true })).toBeVisible();
      await expect(sourcePanel(page)).toBeHidden();
      await page.keyboard.press("End");
      await expect(drawer).toBeFocused();
      await expect(page.getByRole("tabpanel", { name: "Reasoning delta and audit trail", exact: true })).toBeVisible();
      await page.keyboard.press("Home");
      await expect(assess).toBeFocused();
      await expect(assessmentPanel(page)).toBeVisible();
      await expect(sections.locator('[role="tab"][aria-selected="true"]')).toHaveCount(1);
      await expect(sections.locator('[role="tab"][tabindex="0"]')).toHaveCount(1);
      await page.keyboard.press("ArrowLeft");
      await expect(drawer).toBeFocused();
      await page.keyboard.press("ArrowRight");
      await expect(assess).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(page.getByRole("button", { name: "Assess these documents", exact: true })).toBeFocused();
      await expectNoPageOverflow(page);
      await attachViewport(page, testInfo, `compact-${width}-assessment`);
    });
  }

  for (const width of [1024, 1280, 1440]) {
    test(`desktop workbench at ${width}px retains actionable assessment beside source without page overflow`, async ({ page }) => {
      test.setTimeout(60_000);
      await page.setViewportSize({ width, height: 900 });
      await completeCaseD(page);
      await expect(page.getByRole("tablist", { name: "Workbench sections" })).toBeHidden();
      await expect(assessmentPanel(page)).toHaveAttribute("role", "region");
      await expect(page.getByRole("region", { name: "Bundle files", exact: true })).toBeVisible();
      await expectNoPageOverflow(page);
      await page.getByRole("button", { name: "View PDF", exact: true }).click();
      await expect(sourcePanel(page).getByRole("img", { name: /^Page 1 of \d+: case_d_mtc_test_cert\.pdf$/ })).toBeVisible({ timeout: 15_000 });
      const nextAction = assessmentPanel(page).getByTestId("next-action");
      await expect(nextAction).toBeVisible();
      await nextAction.focus();
      await expect(nextAction).toBeFocused();
      await nextAction.click();
      await expect(page.locator("#material-findings")).toBeFocused();
      await expect(sourcePanel(page)).toBeVisible();
      await page.getByRole("button", { name: "Close source PDF" }).focus();
      await expect(page.getByRole("button", { name: "Close source PDF" })).toBeFocused();
      await expectNoPageOverflow(page);
    });
  }

  for (const theme of ["light", "dark"] as const) {
    test(`${theme} completed contradiction and open source have no serious accessibility violations`, async ({ page }, testInfo) => {
      test.setTimeout(60_000);
      await page.addInitScript((selectedTheme) => localStorage.setItem("cargoclear-theme", selectedTheme), theme);
      await page.setViewportSize({ width: 1440, height: 900 });
      await completeCaseD(page);
      await page.addStyleTag({ content: "*, *::before, *::after { transition: none !important; animation: none !important; }" });
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      for (const openSource of [false, true]) {
        if (openSource) {
          await page.getByRole("button", { name: "View PDF", exact: true }).click();
          await expect(sourcePanel(page).getByRole("img", { name: /^Page 1 of \d+: case_d_mtc_test_cert\.pdf$/ })).toBeVisible({ timeout: 15_000 });
          await expect(assessmentPanel(page).getByTestId("next-action")).toBeVisible();
          await expect(sourcePanel(page).getByRole("button", { name: "Zoom in", exact: true })).toBeEnabled();
        }
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
        expect(results.violations.filter((issue) => issue.impact === "critical" || issue.impact === "serious").map((issue) => ({
          id: issue.id, targets: issue.nodes.map((node) => node.target),
        }))).toEqual([]);
        await attachViewport(page, testInfo, `${theme}-contradiction-${openSource ? "with-source" : "decision"}`);
      }
      await page.getByRole("button", { name: "Close source PDF" }).click();
      await page.getByTestId("remove-document").click();
      await expect(page.getByTestId("confirm-remove-document")).toBeVisible();
      const removalScan = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      expect(removalScan.violations.filter((issue) => issue.impact === "critical" || issue.impact === "serious")).toEqual([]);
    });
  }
});

/** A deliberately synthetic, local-only two-page PDF, with a real xref table for PDF.js. */
function twoPagePdf(): Buffer {
  const stream = (pageNumber: number) => `BT /F1 12 Tf 24 360 Td (Synthetic UX fixture - Page ${pageNumber}) Tj ET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ...[1, 2].map((number) => `<< /Length ${Buffer.byteLength(stream(number))} >>\nstream\n${stream(number)}\nendstream`),
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${offsets.length}\n0000000000 65535 f \n`;
  pdf += offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  pdf += `trailer\n<< /Size ${offsets.length} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(pdf);
}

test("a page-two citation opens and reselects its exact page and highlight in a real two-page PDF", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const bundleId = "bnd-ux-two-pages";
  const documentId = "doc-ux-two-pages";
  const file = twoPagePdf();
  let fileRequests = 0;
  const document: DocumentRecord = {
    document_id: documentId, bundle_id: bundleId, filename: "ux-two-pages.pdf", doc_type: "MILL_TEST_CERTIFICATE",
    gcs_uri: "test-fixture-only", sha256: "test-fixture-only", bytes: file.length, uploaded_at: "2026-10-17T00:00:00Z",
  };
  const assessment: AssessmentIteration = {
    iteration: 1, bundle_id: bundleId, status: "MATERIAL_CONTRADICTION", data_source: "fixture", documents: [documentId],
    checks: [{
      check_id: "M-001", severity: "MATERIAL", message: "Synthetic fixture: review the chromium cell on page two.", focus_document: documentId,
      evidence: [{ doc: documentId, field: "chromium", page: 2, raw_value: "0.35", unit: "%", bbox: { page: 2, ymin: 100, xmin: 100, ymax: 160, xmax: 650 } }],
    }],
    grounding: [], missing_evidence: [], confidence: { min_field_confidence: 0.9, action: "AUTO_FLAG" },
    reasoning_delta: { kind: "INITIAL", narrative: "Synthetic interaction fixture only." },
  };
  const bundle: Bundle = { id: bundleId, reference: "Synthetic UX test", destination_country: "IN", status: assessment.status, current_iteration: 1, documents: [document], created_at: "2026-10-17T00:00:00Z" };
  await page.route("**/api/proxy/meta", (route) => route.fulfill({ json: { app_mode: "demo", data_source_policy: "demo", pipeline_engine: "native", auth: { enabled: false, allowed_email_domains: ["*"] } } }));
  await page.route(`**/api/proxy/bundles/${bundleId}**`, async (route) => {
    const suffix = new URL(route.request().url()).pathname.slice(`/api/proxy/bundles/${bundleId}`.length);
    if (suffix === `/documents/${documentId}/file`) {
      fileRequests += 1;
      return route.fulfill({ contentType: "application/pdf", body: file });
    }
    // Keep SSE and polling on the same fixture so a real backend replay cannot overwrite it.
    if (suffix === "/stream") return route.fulfill({ contentType: "text/event-stream", body: `retry: 60000\nevent: iteration\ndata: ${JSON.stringify(assessment)}\n\nevent: status\ndata: ${JSON.stringify({ state: "COMPLETE", run_id: "ux-fixture", progress: 1 })}\n\n` });
    if (suffix === "/status") return route.fulfill({ json: { state: "COMPLETE", run_id: "ux-fixture", progress: 1 } });
    if (suffix === "") return route.fulfill({ json: bundle });
    if (suffix === "/assessment") return route.fulfill({ json: assessment });
    if (suffix === "/iterations") return route.fulfill({ json: [assessment] });
    if (suffix === "/extractions") return route.fulfill({ json: [] });
    if (suffix === "/corrections") return route.fulfill({ json: { corrections: [], effective: [], pending: 0 } });
    return route.fulfill({ status: 404, json: { code: "NOT_FOUND", message: "Unused synthetic test route" } });
  });
  await page.goto(`/workbench/${bundleId}`);
  await expect(page.getByTestId("decision-status-pill")).toContainText("Material Contradiction");
  await expect(sourcePanel(page)).toBeHidden();
  expect(fileRequests).toBe(0);
  const evidence = assessmentPanel(page).getByRole("button", { name: "Open ux-two-pages.pdf, page 2", exact: true }).first();
  await evidence.click();
  const source = sourcePanel(page);
  await expect(source.getByRole("img", { name: "Page 2 of 2: ux-two-pages.pdf", exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(source.locator('[data-selected-evidence="true"]')).toBeVisible();
  await source.getByRole("button", { name: "Previous page", exact: true }).click();
  await expect(source.getByRole("img", { name: "Page 1 of 2: ux-two-pages.pdf", exact: true })).toBeVisible();
  await expect(source.locator('[data-selected-evidence="true"]')).toHaveCount(0);
  await evidence.click();
  await expect(source.getByRole("img", { name: "Page 2 of 2: ux-two-pages.pdf", exact: true })).toBeVisible();
  await expect(source.locator('[data-selected-evidence="true"]')).toBeVisible();
  expect(fileRequests).toBe(1);
  await page.keyboard.press("Escape");
  await expect(source).toBeHidden();
  await expect(evidence).toBeFocused();
});
