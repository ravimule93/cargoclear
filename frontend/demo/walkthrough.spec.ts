import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import {
  CASE_C_CERTIFICATE,
  CASE_C_FILES,
  CASE_D_FILES,
  caseCPath,
  caseDPath,
} from "../tests/support/fixtures";

/**
 * The recorded walkthrough: Case C (missing evidence, then compliant), Case D (a contradiction the certificate's own chemistry
 * causes), a correction by the agent and a recompute, the declaration pre-fill and the signed audit trail.
 *
 * It drives the real UI. In demo mode it uses the demo buttons; against a LIVE stack (no demo buttons) it creates an empty bundle,
 * chooses the destination and uploads the sample PDFs, so the same script records both. Every screen carries a caption that
 * says which mode it is, so a recording cannot be mistaken for the other one.
 */

const OUT = path.resolve(process.env.DEMO_OUT_DIR ?? path.join(__dirname, "../../demo-recordings/latest"));
const DWELL = Number(process.env.DEMO_DWELL_MS ?? 2400);
const ANALYSIS = Number(process.env.DEMO_ANALYSIS_TIMEOUT_MS ?? 240_000);

type Step = { n: number; at_seconds: number; title: string; caption: string; screenshot: string };
const steps: Step[] = [];
let started = Date.now();
let modeLine = "";

async function caption(page: Page, text: string) {
  await page.evaluate((t) => {
    let el = document.getElementById("cc-demo-caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "cc-demo-caption";
      el.setAttribute("aria-hidden", "true");
      Object.assign(el.style, {
        position: "fixed", left: "0", right: "0", bottom: "0", zIndex: "2147483647", padding: "14px 28px",
        background: "rgba(17,24,39,0.94)", color: "#fff", font: "600 20px/1.35 system-ui, sans-serif",
        textAlign: "center", pointerEvents: "none",
      });
      document.body.appendChild(el);
    }
    el.textContent = t;
  }, text);
}

/** Say what is on screen, let it be read, and keep a still of it. */
async function show(page: Page, title: string, text: string) {
  await caption(page, `${modeLine} ${text}`.trim());
  await page.waitForTimeout(DWELL);
  const n = steps.length + 1;
  const file = `${String(n).padStart(2, "0")}-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.png`;
  fs.mkdirSync(path.join(OUT, "screens"), { recursive: true });
  await page.screenshot({ path: path.join(OUT, "screens", file) });
  steps.push({ n, at_seconds: Math.round((Date.now() - started) / 100) / 10, title, caption: text, screenshot: `screens/${file}` });
}

/** A click that lands before the page has hydrated does nothing: click again unless a run began. */
async function startRun(page: Page) {
  const pill = page.getByTestId("status-pill");
  const before = await pill.innerText();
  for (let attempt = 0; attempt < 4; attempt++) {
    await page.getByTestId("run-button").click({ timeout: 3_000 }).catch(() => undefined);
    try {
      await expect(pill).not.toHaveText(before, { timeout: 8_000 });
      return;
    } catch {
      // nothing started yet
    }
  }
}

async function openCase(page: Page, kind: "c" | "d", demo: boolean) {
  await page.goto("/");
  if (demo) {
    const name = kind === "c" ? "Start Case C demo" : "Start Case D demo (India import)";
    await Promise.all([page.waitForURL(/\/workbench\/bnd-[A-Za-z0-9_-]+$/), page.getByRole("button", { name }).click()]);
    return;
  }
  await page.getByTestId("destination-select").selectOption(kind === "c" ? "SG" : "IN");
  await Promise.all([page.waitForURL(/\/workbench\/bnd-[A-Za-z0-9_-]+$/), page.getByRole("button", { name: "New empty bundle" }).click()]);
  const files = kind === "c" ? CASE_C_FILES.map(caseCPath) : CASE_D_FILES.map(caseDPath);
  await page.getByTestId("upload-input").first().setInputFiles(files);
  await expect(page.getByLabel("Documents in this bundle").getByRole("button")).toHaveCount(files.length, { timeout: 60_000 });
}

test("CargoClear walkthrough: Case C, Case D, a correction, the pre-fill and the audit trail", async ({ page }) => {
  started = Date.now();
  const meta = await (await page.request.get("/api/proxy/meta")).json();
  const demo = meta.app_mode === "demo";
  modeLine = demo
    ? "DEMO MODE (synthetic extraction keyed on file names, no model call)."
    : "LIVE MODE (Gemini reads the PDFs; Google Cloud services).";
  const panel = () => page.getByLabel("Compliance assessment and actions");
  const pill = () => page.getByTestId("status-pill");

  await page.goto("/");
  await show(page, "Home", "CargoClear: pre-submission customs document assessment. Decision support only: the authorised agent decides.");

  // ---- Case C -------------------------------------------------------------------------------------------------------------
  await openCase(page, "c", demo);
  await show(page, "Case C bundle", "Case C, India to Singapore: an invoice, a bill of lading and a packing list. No assessment yet.");
  await startRun(page);
  await expect(pill()).toContainText("Missing Evidence", { timeout: ANALYSIS });
  await show(page, "Case C missing evidence", "The product names what is missing: a Mill Test Certificate, which this HS code needs.");

  if (demo) {
    await page.getByTestId("sample-mtc-button").click();
  } else {
    await page.getByTestId("upload-input").first().setInputFiles(caseCPath(CASE_C_CERTIFICATE));
    await expect(page.getByLabel("Documents in this bundle").getByRole("button")).toHaveCount(4, { timeout: 60_000 });
    await startRun(page);
  }
  await expect(pill()).toContainText("Compliant For Submission", { timeout: ANALYSIS });
  await show(page, "Case C compliant", "With the certificate added, the bundle reassesses to Compliant For Submission.");

  await page.locator("#tab-delta").click();
  await show(page, "Case C reasoning delta", "The Reasoning Delta says what changed between the two assessments, and why.");
  await page.locator("#tab-audit").click();
  await expect(page.getByTestId("audit-verified-badge")).toHaveText("Chain verified");
  await show(page, "Case C audit chain", "Every step is in a hash-chained audit trail that verifies.");

  // ---- Case D -------------------------------------------------------------------------------------------------------------
  await openCase(page, "d", demo);
  await show(page, "Case D bundle", "Case D, an import into India: four documents, declared under a non-alloy HS code.");
  await startRun(page);
  await expect(pill()).toContainText("Material Contradiction", { timeout: ANALYSIS });
  await expect(panel()).toContainText("TH-77121");
  // the viewer opens the certificate by itself (the finding is about it): the green box marks where 0.35 is printed
  await expect(page.getByLabel(/^Page 1 of \d+: case_d_mtc_test_cert\.pdf$/)).toBeVisible({ timeout: 30_000 });
  await page.mouse.move(660, 420); // scroll the page to the chemistry table, where the box marks the 0.35
  await page.mouse.wheel(0, 700);
  await page.waitForTimeout(800);
  await show(page, "Case D contradiction", "Heat TH-77121 reads 0.35 % chromium. Above 0.30 %, HS Chapter 72 Note 1(f) makes the steel alloy: the declared code contradicts the certificate.");
  await page.getByTestId("valuation-card").scrollIntoViewIfNeeded();
  await show(page, "Case D duty estimate", "An indicative duty estimate, with every assumption listed. Illustrative rates; never an amount payable and never the status.");

  // ---- a correction by the authorised agent ----------------------------------------------------------------------------------
  const edit = panel().getByRole("button", { name: /Correct Certificate cell \d+ in case_d_mtc_test_cert\.pdf/ });
  await edit.scrollIntoViewIfNeeded();
  await edit.click();
  const editor = panel().getByTestId("correction-editor");
  await editor.getByTestId("correction-value").fill("0.28");
  await editor.getByTestId("correction-reason").fill("certificate prints 0.28 in the Cr column");
  await show(page, "Correction", "The agent looked at the certificate and states what it prints. The model's reading stays on record.");
  await editor.getByTestId("correction-save").click();
  await expect(panel().getByTestId("corrections-card")).toContainText("Pending recompute");
  await show(page, "Correction pending", "Recorded in the audit trail. Nothing changes until the checks are re-run.");
  await page.getByTestId("recompute-button").click();
  await expect(pill()).toContainText("Specialist Review Required", { timeout: ANALYSIS });
  await show(page, "Recompute", "Recompute re-runs every check on the stored reading: no document is read again, no model is called. The anti-dumping warning remains.");
  await page.locator("#tab-delta").click();
  await show(page, "Correction delta", "The Reasoning Delta names the correction, the value it replaced and the reason.");

  // ---- the pre-fill pack and the signed audit trail --------------------------------------------------------------------------
  await page.getByTestId("prefill-card").scrollIntoViewIfNeeded();
  await show(page, "Pre-fill", "The declaration pre-fill: each value with its source document and page, JSON and PDF. It says NOT CLEARED first; never ready to file.");
  await page.locator("#tab-audit").click();
  await expect(page.getByTestId("audit-signature-badge")).toHaveAttribute("data-status", /SIGNED|PARTIAL/);
  await show(page, "Signed audit trail", "The head of the audit chain is signed with a key the database does not hold: tamper-evident under the operator's key, not legal non-repudiation.");

  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(
    path.join(OUT, "steps.json"),
    JSON.stringify(
      { recorded_at: new Date().toISOString(), app_mode: meta.app_mode, pipeline_engine: meta.pipeline_engine, base_url_kind: /localhost|127\.0\.0\.1/.test(page.url()) ? "local" : "hosted", dwell_ms: DWELL, steps },
      null, 2,
    ) + "\n",
  );
});
