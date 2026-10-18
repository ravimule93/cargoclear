import { expect, test, type Locator, type Page } from "@playwright/test";
import type { AssessmentIteration, Bundle, DocumentRecord, StatusEvent, UserIdentity } from "../lib/types";

const BUNDLE_ID = "bnd-feedback-fixture";
const PATH = `/workbench/${BUNDLE_ID}`;
const RUN_ID = "run-feedback-fixture";
const user: UserIdentity = {
  user_id: "usr-feedback-fixture", email: "review@example.com", name: "Review Agent",
  tenant_id: "example.com", role: "LICENSED_CHA", issuer: "test-fixture-only",
};

interface FeedbackWindow extends Window {
  __feedbackEmit: (name: string, payload: unknown) => number;
  __feedbackOpenStreams: () => number;
}

/** A controllable browser transport, not a recording or a claim about real model output. */
async function installFixtureStream(page: Page) {
  await page.addInitScript(() => {
    const streams: FixtureEventSource[] = [];
    class FixtureEventSource extends EventTarget {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSED = 2;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
      readyState = FixtureEventSource.CONNECTING;
      url: string;
      withCredentials = false;
      constructor(url: string | URL) {
        super();
        this.url = String(url);
        streams.push(this);
        queueMicrotask(() => {
          if (this.readyState === FixtureEventSource.CLOSED) return;
          this.readyState = FixtureEventSource.OPEN;
          this.dispatchEvent(new Event("open"));
        });
      }
      close() { this.readyState = FixtureEventSource.CLOSED; }
    }
    Object.defineProperty(window, "EventSource", { configurable: true, value: FixtureEventSource });
    Object.defineProperty(window, "__feedbackOpenStreams", {
      value: () => streams.filter((stream) => stream.readyState === FixtureEventSource.OPEN).length,
    });
    Object.defineProperty(window, "__feedbackEmit", {
      value: (name: string, payload: unknown) => {
        const active = streams.filter((stream) => stream.readyState === FixtureEventSource.OPEN);
        for (const stream of active) stream.dispatchEvent(new MessageEvent(name, { data: JSON.stringify(payload) }));
        return active.length;
      },
    });
  });
}

/** Every backend/account endpoint is intercepted; no run, upload, account mutation or logout reaches a real service. */
async function mockFeedback(page: Page, options: { waitForMeta?: Promise<void>; signedIn?: boolean } = {}) {
  await installFixtureStream(page);
  const documents: DocumentRecord[] = ["invoice", "bill_of_lading", "packing_list"].map((name, index) => ({
    document_id: `doc-feedback-${index}`, bundle_id: BUNDLE_ID, filename: `${name}.pdf`,
    doc_type: ["COMMERCIAL_INVOICE", "BILL_OF_LADING", "PACKING_LIST"][index],
    gcs_uri: "test-fixture-only", sha256: "test-fixture-only", bytes: 100, uploaded_at: "2026-10-18T00:00:00Z",
  }));
  const initialAssessment: AssessmentIteration = {
    bundle_id: BUNDLE_ID, iteration: 1, status: "MATERIAL_CONTRADICTION", data_source: "fixture",
    documents: documents.map((document) => document.document_id), grounding: [], missing_evidence: [],
    checks: Array.from({ length: 24 }, (_, index) => ({
      check_id: `FIXTURE-${String(index + 1).padStart(2, "0")}`,
      severity: index === 0 ? "MATERIAL" : "WARN",
      message: `Synthetic review finding ${index + 1}. This deliberately long assessment exercises independent panel scrolling; it is not an observed customs finding.`,
    })),
    confidence: { min_field_confidence: 0.99, action: "INTERACTIVE_REVIEW" },
    reasoning_delta: { kind: "INITIAL", narrative: "Synthetic feedback interaction fixture only." },
  };
  let assessment = initialAssessment;
  const bundle: Bundle = {
    id: BUNDLE_ID, reference: "Synthetic feedback test", destination_country: "SG",
    status: assessment.status, current_iteration: 1, documents, created_at: "2026-10-18T00:00:00Z",
  };
  let signedIn = options.signedIn ?? true;
  let releaseRun!: () => void;
  const runResponseReady = new Promise<void>((resolve) => { releaseRun = resolve; });
  const calls = { meta: 0, reassess: 0, create: 0, logout: 0 };
  const writes: string[] = [];
  const unhandled: string[] = [];
  let currentStatus: StatusEvent = {
    kind: "status", bundle_id: BUNDLE_ID, run_id: "preceding-completed-run", state: "COMPLETE", stage: "finalize", progress: 1,
  };

  await page.route("**/api/auth/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/auth/logout") {
      calls.logout += 1;
      signedIn = false;
      return route.fulfill({ status: 302, headers: { location: "/" }, body: "" });
    }
    unhandled.push(`${request.method()} ${url.pathname}`);
    return route.fulfill({ status: 404, json: { message: "Unused feedback account fixture route" } });
  });
  await page.route("**/api/proxy/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.slice("/api/proxy".length);
    if (request.method() !== "GET") writes.push(`${request.method()} ${path}`);
    if (path === "/meta") {
      calls.meta += 1;
      await options.waitForMeta;
      return route.fulfill({ json: {
        app_mode: "demo", data_source_policy: "test-fixture-only", pipeline_engine: "native",
        auth: { enabled: true, allowed_email_domains: ["*"] }, user: signedIn ? user : null,
      } });
    }
    if (path === "/mode") return route.fulfill({ json: {
      active_mode: "demo", configured_mode: "demo", supported_modes: ["demo", "live"],
      live_available: false, credential_source: null, provider: "test-fixture-only", model: "test-fixture-only",
    } });
    if (path === "/bundles" && request.method() === "GET") return route.fulfill({ json: [] });
    if (path === "/bundles" && request.method() === "POST") {
      calls.create += 1;
      return route.fulfill({ status: 201, json: bundle });
    }
    if (path === `/bundles/${BUNDLE_ID}`) return route.fulfill({ json: bundle });
    if (path === `/bundles/${BUNDLE_ID}/assessment`) return route.fulfill({ json: assessment });
    if (path === `/bundles/${BUNDLE_ID}/iterations`) return route.fulfill({ json: assessment.iteration === 1 ? [assessment] : [initialAssessment, assessment] });
    if (path === `/bundles/${BUNDLE_ID}/extractions`) return route.fulfill({ json: [] });
    if (path === `/bundles/${BUNDLE_ID}/corrections`) return route.fulfill({ json: { corrections: [], effective: [], pending: 0 } });
    if (path === `/bundles/${BUNDLE_ID}/status`) return route.fulfill({ json: currentStatus });
    if (path === `/bundles/${BUNDLE_ID}/audit`) return route.fulfill({ json: {
      bundle_id: BUNDLE_ID, events: [], verified: true, error: null,
      signature: { configured: false, status: "NOT_CONFIGURED" },
    } });
    if (path === `/bundles/${BUNDLE_ID}/reassess` && request.method() === "POST") {
      calls.reassess += 1;
      await runResponseReady;
      return route.fulfill({ status: 202, json: { bundle_id: BUNDLE_ID, run_id: RUN_ID, state: "QUEUED" } });
    }
    unhandled.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 404, json: { code: "NOT_FOUND", message: "Unused feedback fixture route" } });
  });
  const emit = async (name: string, payload: unknown) => {
    const delivered = await page.evaluate(({ name, payload }) => (window as FeedbackWindow).__feedbackEmit(name, payload), { name, payload });
    expect(delivered).toBeGreaterThan(0);
  };
  const emitStatus = async (status: Partial<StatusEvent> & Pick<StatusEvent, "state" | "progress">) => {
    currentStatus = { kind: "status", bundle_id: BUNDLE_ID, run_id: RUN_ID, ...status };
    await emit("status", currentStatus);
  };
  return {
    calls, writes, unhandled, releaseRun, emitStatus,
    async open() {
      await page.goto(PATH);
      await expect(page.getByTestId("decision-status-pill")).toHaveText("Material Contradiction");
      await expect.poll(() => page.evaluate(() => (window as FeedbackWindow).__feedbackOpenStreams())).toBeGreaterThan(0);
    },
    async complete() {
      assessment = { ...initialAssessment, iteration: 2, status: "COMPLIANT_FOR_SUBMISSION", checks: [], reasoning_delta: { kind: "REASSESSMENT", narrative: "Synthetic completed interaction fixture." } };
      bundle.current_iteration = 2;
      bundle.status = assessment.status;
      await emit("iteration", assessment);
      await emitStatus({ state: "COMPLETE", stage: "finalize", progress: 1 });
    },
  };
}

async function expectHeaderProgress(page: Page, value?: number) {
  const progress = page.getByRole("banner").getByTestId("run-progress");
  await expect(page.getByTestId("run-progress")).toHaveCount(1);
  await expect(progress).toBeVisible();
  await expect(progress).toBeInViewport();
  const bounds = (await progress.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.y).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(viewport.width);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(viewport.height);
  const bar = progress.getByRole("progressbar", { name: "Assessment progress", exact: true });
  await expect(bar).toBeInViewport();
  await expect(bar).toHaveAttribute("aria-valuemin", "0");
  await expect(bar).toHaveAttribute("aria-valuemax", "100");
  if (value === undefined) await expect(bar).not.toHaveAttribute("aria-valuenow");
  else await expect(bar).toHaveAttribute("aria-valuenow", String(value));
  return progress;
}

for (const width of [1440, 390]) {
  test(`reassessment at ${width}px keeps progress above a scrolled review without losing decision, focus or position`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const fixture = await mockFeedback(page);
    try {
      await fixture.open();
      // A completed stream replay must not leak its old 100% into the next request's pending state.
      await fixture.emitStatus({ run_id: "preceding-completed-run", state: "COMPLETE", stage: "finalize", progress: 1 });
      const scroller = page.locator(".cc-assessment-content");
      await expect.poll(() => scroller.evaluate((element) => element.scrollHeight - element.clientHeight)).toBeGreaterThan(1000);
      await scroller.evaluate((element) => { element.scrollTop = element.scrollHeight; });
      const beforeRun = await scroller.evaluate((element) => element.scrollTop);
      await page.getByTestId("run-button").click();
      await expect.poll(() => fixture.calls.reassess).toBe(1);
      const preparing = await expectHeaderProgress(page);
      await expect(preparing).toContainText("Preparing assessment");
      await expect(preparing).not.toContainText("100%");
      await fixture.emitStatus({ state: "RUNNING", stage: "extract", progress: 0.45 });
      fixture.releaseRun();
      const progress = await expectHeaderProgress(page, 45);
      await expect(progress).toContainText("Multimodal Gemini Extraction");
      await expect(page.getByTestId("run-button")).toBeDisabled();
      await expect(page.getByTestId("decision-status-pill")).toHaveText("Material Contradiction");
      expect(await scroller.evaluate((element) => element.scrollTop)).toBeGreaterThan(beforeRun - 150);
      const stableFocus = page.getByRole("link", { name: /All Bundles|← All$/ }).first();
      await stableFocus.focus();
      const beforeStage = await scroller.evaluate((element) => element.scrollTop);
      if (width === 1440) {
        const screenshot = testInfo.outputPath("reassess-bottom-progress.png");
        await page.screenshot({ path: screenshot });
        await testInfo.attach("Synthetic scrolled review: 45% extraction", { path: screenshot, contentType: "image/png" });
      }
      await fixture.emitStatus({ state: "RUNNING", stage: "ground", progress: 0.75 });
      await expectHeaderProgress(page, 75);
      await expect(progress).toContainText("Evidence Grounding & Bounding Boxes");
      await expect(stableFocus).toBeFocused();
      expect(Math.abs(await scroller.evaluate((element) => element.scrollTop) - beforeStage)).toBeLessThanOrEqual(48);
      await expect(page.getByTestId("decision-status-pill")).toHaveText("Material Contradiction");
      await fixture.complete();
      await expect(page.getByTestId("run-progress")).toHaveCount(0);
      await expect(page.getByTestId("decision-status-pill")).toHaveText("Compliant For Submission");
      await expect(page.getByTestId("run-button")).toBeEnabled();
      expect(fixture.writes).toEqual([`POST /bundles/${BUNDLE_ID}/reassess`]);
      expect(fixture.unhandled).toEqual([]);
    } finally { fixture.releaseRun(); }
  });
}

test("accepted reassessment stays pending through an old-assessment fallback poll before the first new stream status", async ({ page }) => {
  const fixture = await mockFeedback(page);
  try {
    await fixture.open();
    await fixture.emitStatus({ run_id: "preceding-completed-run", state: "COMPLETE", stage: "finalize", progress: 1 });
    const acceptedResponse = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === `/api/proxy/bundles/${BUNDLE_ID}/reassess`
    );
    await page.getByTestId("run-button").click();
    await expect.poll(() => fixture.calls.reassess).toBe(1);
    await expectHeaderProgress(page);
    const oldAssessmentPoll = page.waitForResponse((response) =>
      response.request().method() === "GET" && new URL(response.url()).pathname === `/api/proxy/bundles/${BUNDLE_ID}/assessment`
    );
    // The HTTP request has finished, but the new run has not sent QUEUED/RUNNING yet.
    fixture.releaseRun();
    const accepted = await acceptedResponse;
    expect(accepted.status()).toBe(202);
    await accepted.finished();
    let progress = await expectHeaderProgress(page);
    await expect(progress).toContainText("Preparing assessment");
    await expect(progress).not.toContainText("100%");
    await expect(page.getByTestId("run-button")).toBeDisabled();
    // Exercise the real 2-second fallback interval: its unchanged iteration must not clear the pending new run.
    await page.waitForTimeout(2200);
    const oldPollResponse = await oldAssessmentPoll;
    await oldPollResponse.finished();
    expect((await oldPollResponse.json()).iteration).toBe(1);
    progress = await expectHeaderProgress(page);
    await expect(progress).toContainText("Preparing assessment");
    await expect(progress).not.toContainText("100%");
    await expect(page.getByTestId("run-button")).toBeDisabled();
    await expect(page.getByTestId("decision-status-pill")).toHaveText("Material Contradiction");
    await fixture.emitStatus({ state: "RUNNING", stage: "extract", progress: 0.45 });
    await expectHeaderProgress(page, 45);
    await fixture.complete();
    await expect(page.getByTestId("run-progress")).toHaveCount(0);
    await expect(page.getByTestId("run-button")).toBeEnabled();
    await expect(page.getByTestId("decision-status-pill")).toHaveText("Compliant For Submission");
    expect(fixture.writes).toEqual([`POST /bundles/${BUNDLE_ID}/reassess`]);
    expect(fixture.unhandled).toEqual([]);
  } finally { fixture.releaseRun(); }
});

test("a failed reassessment removes progress and retains the last decision with a retryable error", async ({ page }) => {
  const fixture = await mockFeedback(page);
  try {
    await fixture.open();
    await page.getByTestId("run-button").click();
    await expect.poll(() => fixture.calls.reassess).toBe(1);
    await fixture.emitStatus({ state: "RUNNING", stage: "extract", progress: 0.45 });
    fixture.releaseRun();
    await expectHeaderProgress(page, 45);
    const focus = page.getByRole("link", { name: /All Bundles|← All$/ }).first();
    await focus.focus();
    await fixture.emitStatus({ state: "ERROR", stage: "extract", progress: 0.45, message: "Synthetic processor unavailable; retry this assessment." });
    await expect(page.getByTestId("run-progress")).toHaveCount(0);
    await expect(page.getByRole("alert").filter({ hasText: "Synthetic processor unavailable" })).toBeVisible();
    await expect(page.getByTestId("decision-status-pill")).toHaveText("Material Contradiction");
    await expect(page.getByTestId("run-button")).toBeEnabled();
    await expect(focus).toBeFocused();
    expect(fixture.unhandled).toEqual([]);
  } finally { fixture.releaseRun(); }
});

test("compact Files and Audit tabs keep one header progressbar with live bounded progress", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  const fixture = await mockFeedback(page);
  try {
    await fixture.open();
    await page.locator("#tab-btn-rail").click();
    await page.getByTestId("run-button").click();
    await expect.poll(() => fixture.calls.reassess).toBe(1);
    await fixture.emitStatus({ state: "QUEUED", stage: "initializing", progress: -0.5 });
    fixture.releaseRun();
    await expectHeaderProgress(page, 0);
    await expect(page.locator("#tab-btn-rail")).toHaveAttribute("aria-selected", "true");
    await page.locator("#tab-btn-drawer").click();
    await fixture.emitStatus({ state: "RUNNING", stage: "synthesize", progress: 1.5 });
    const progress = await expectHeaderProgress(page, 100);
    await expect(progress).toContainText("Tariff & Regulatory Synthesis");
    await expect(page.locator("#tab-btn-drawer")).toHaveAttribute("aria-selected", "true");
    await fixture.emitStatus({ state: "RUNNING", stage: "finalize", progress: 0.9 });
    await expectHeaderProgress(page, 90);
    await expect(page.locator("#tab-btn-drawer")).toHaveAttribute("aria-selected", "true");
    await fixture.complete();
    await expect(page.getByTestId("run-progress")).toHaveCount(0);
    await expect(page.locator("#tab-btn-drawer")).toHaveAttribute("aria-selected", "true");
    expect(fixture.unhandled).toEqual([]);
  } finally { fixture.releaseRun(); }
});

async function tokenColors(locator: Locator) {
  return locator.evaluate((element) => {
    const probe = document.createElement("span");
    element.append(probe);
    const resolve = (token: string) => {
      probe.style.color = `var(${token})`;
      return getComputedStyle(probe).color;
    };
    const colors = {
      text: resolve("--cc-err"), border: resolve("--cc-err-bd"), surface: resolve("--cc-surface"),
      hover: resolve("--cc-err-bg"), active: resolve("--cc-danger-action"), activeText: resolve("--cc-action-text"),
    };
    probe.remove();
    return colors;
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`${theme} Sign out is red in normal, hover, keyboard-focus and active states while preserving safe logout`, async ({ page, baseURL }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript((value) => localStorage.setItem("cargoclear-theme", value), theme);
    await page.context().addCookies(["__session", "cargoclear_session_token", "cargoclear_google_id_token"].map((name) => ({ name, value: "synthetic-test-session", url: baseURL! })));
    const fixture = await mockFeedback(page);
    await fixture.open();
    const menu = page.getByLabel(`Account menu for ${user.email}`, { exact: true });
    const signOut = page.getByRole("button", { name: "Sign out", exact: true });
    await menu.focus();
    await page.keyboard.press("Enter");
    await expect(signOut).toBeVisible();
    const colors = await tokenColors(signOut);
    await expect(signOut).toHaveCSS("color", colors.text);
    await expect(signOut).toHaveCSS("border-top-color", colors.border);
    await expect(signOut).toHaveCSS("background-color", colors.surface);
    await signOut.hover();
    await expect(signOut).toHaveCSS("background-color", colors.hover);
    await menu.focus();
    await page.keyboard.press("Tab");
    await expect(signOut).toBeFocused();
    await expect(signOut).toHaveCSS("outline-color", colors.text);
    await expect(signOut).toHaveCSS("outline-style", "solid");
    await expect(signOut).toHaveCSS("outline-width", "2px");
    await page.keyboard.press("Escape");
    await expect(signOut).toBeHidden();
    await expect(menu).toBeFocused();
    await page.keyboard.press("Enter");
    await signOut.hover();
    await page.mouse.down();
    try {
      await expect(signOut).toHaveCSS("background-color", colors.active);
      await expect(signOut).toHaveCSS("color", colors.activeText);
      if (theme === "light") {
        const screenshot = testInfo.outputPath("sign-out-red.png");
        await page.screenshot({ path: screenshot });
        await testInfo.attach("Synthetic account menu: red active Sign out", { path: screenshot, contentType: "image/png" });
      }
      const logout = page.waitForRequest((request) => new URL(request.url()).pathname === "/api/auth/logout");
      await page.mouse.up();
      const request = await logout;
      expect(request.method()).toBe("GET");
      expect(new URL(request.url()).searchParams.get("returnTo")).toBe("/");
      await expect(page).toHaveURL(/\/$/);
      await expect(page.getByRole("button", { name: "New empty bundle", exact: true })).toBeVisible();
      await expect(page.getByTestId("destination-select")).toBeDisabled();
      const remaining = await page.context().cookies();
      expect(remaining.filter((cookie) => ["__session", "cargoclear_session_token", "cargoclear_google_id_token"].includes(cookie.name))).toEqual([]);
      expect(fixture.calls.logout).toBe(1);
      expect(fixture.writes).toEqual([]);
      expect(fixture.unhandled).toEqual([]);
    } finally { await page.mouse.up(); }
  });
}

test("header home and list links remain distinct from New, which focuses setup without creating a bundle", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await mockFeedback(page);
  await fixture.open();
  const header = page.getByRole("banner");
  await expect(header.getByRole("link", { name: "CargoClear-JAPAC", exact: true })).toHaveAttribute("href", "/");
  await expect(header.getByRole("link", { name: "← All Bundles", exact: true })).toHaveAttribute("href", "/");
  const newBundle = header.getByRole("link", { name: "+ New", exact: true });
  await expect(newBundle).toHaveAttribute("href", "/#new-bundle");
  await newBundle.click();
  await expect(page).toHaveURL(/\/#new-bundle$/);
  const setup = page.locator("#new-bundle");
  await expect(setup).toBeInViewport();
  await expect(setup).toBeFocused();
  await expect(setup.getByRole("button", { name: "New empty bundle", exact: true })).toBeVisible();
  await expect(setup.getByTestId("destination-select")).toHaveValue("SG");
  expect(fixture.calls.create).toBe(0);
  expect(fixture.writes).toEqual([]);
  expect(fixture.unhandled).toEqual([]);
});

for (const width of [1440, 390]) {
  test(`new-bundle hash at ${width}px waits for metadata before focusing destination setup`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let releaseMeta!: () => void;
    const waitForMeta = new Promise<void>((resolve) => { releaseMeta = resolve; });
    const fixture = await mockFeedback(page, { waitForMeta });
    try {
      await page.goto("/#new-bundle");
      await expect.poll(() => fixture.calls.meta).toBeGreaterThanOrEqual(1);
      await expect(page.locator("#new-bundle")).toHaveCount(0);
      expect(fixture.writes).toEqual([]);
      releaseMeta();
      const setup = page.locator("#new-bundle");
      await expect(setup).toBeVisible();
      await expect(setup).toBeInViewport();
      await expect(setup).toBeFocused();
      await expect(setup.getByTestId("destination-select")).toBeEnabled();
      await expect(setup.getByTestId("destination-select")).toHaveValue("SG");
      await expect(setup.getByRole("button", { name: "New empty bundle", exact: true })).toBeVisible();
      expect(fixture.calls.create).toBe(0);
      expect(fixture.writes).toEqual([]);
      expect(fixture.unhandled).toEqual([]);
    } finally { releaseMeta(); }
  });
}
