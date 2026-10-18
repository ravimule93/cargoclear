import { expect, test, type Page } from "@playwright/test";
import type { Bundle, Meta, UserIdentity } from "../lib/types";
import { demoToken } from "../lib/session";

const REQUIRED = "Authentication required. Please sign in to continue.";
const BUNDLE_ID = "bnd-auth-required-test";
const BUNDLE_PATH = `/workbench/${BUNDLE_ID}`;
const user: UserIdentity = {
  user_id: "usr-auth-required-test", email: "review@example.com", name: "Review Agent",
  tenant_id: "example.com", role: "LICENSED_CHA", issuer: "test-fixture-only",
};
const emptyBundle: Bundle = {
  id: BUNDLE_ID, reference: "Authentication interaction fixture", destination_country: "SG",
  status: "MISSING_EVIDENCE", current_iteration: 0, documents: [], created_at: "2026-10-18T00:00:00Z",
};
type MockMetadata = Omit<Meta, "user"> & { user: UserIdentity | null };

function metadata(authEnabled: boolean, currentUser: UserIdentity | null = null, appMode: Meta["app_mode"] = "demo"): MockMetadata {
  return {
    app_mode: appMode, data_source_policy: "test-fixture-only", pipeline_engine: "native",
    auth: { enabled: authEnabled, allowed_email_domains: ["*"] }, user: currentUser,
  };
}

interface Scenario {
  meta: MockMetadata;
  waitForMeta?: Promise<void>;
  bundleUnauthorized?: () => boolean;
  analyzeUnauthorized?: boolean;
  pollingUnauthorized?: boolean;
}

/** Isolated browser fixtures: no protected call in these tests reaches a real account or backend. */
async function mockApp(page: Page, scenario: Scenario) {
  const calls = { meta: 0, list: 0, create: 0, bundle: 0, analyze: 0, status: 0, stream: 0 };
  const protectedRequests: string[] = [];
  await page.route("**/api/proxy/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.slice("/api/proxy".length);
    if (path === "/meta") {
      calls.meta += 1;
      await scenario.waitForMeta;
      return route.fulfill({ json: scenario.meta });
    }
    if (path === "/mode") return route.fulfill({ json: {
      active_mode: scenario.meta.app_mode, configured_mode: scenario.meta.app_mode,
      supported_modes: ["demo", "live"], live_available: false, credential_source: null,
      provider: "test-fixture-only", model: "test-fixture-only",
    } });
    if (path === "/bundles" || path.startsWith("/bundles/")) protectedRequests.push(`${request.method()} ${path}`);
    if (/^\/demo\/case-[cd](?:\/|$)/.test(path)) {
      protectedRequests.push(`${request.method()} ${path}`);
      if (request.method() === "POST") calls.create += 1;
      return route.fulfill({ status: 401, json: { code: "UNAUTHORIZED", message: REQUIRED } });
    }
    if (path === "/bundles" && request.method() === "GET") {
      calls.list += 1;
      return route.fulfill({ json: [] });
    }
    if (path === "/bundles" && request.method() === "POST") {
      calls.create += 1;
      return route.fulfill({ status: 201, json: emptyBundle });
    }
    if (path === `/bundles/${BUNDLE_ID}`) {
      calls.bundle += 1;
      if (scenario.bundleUnauthorized?.()) return route.fulfill({ status: 401, json: { code: "UNAUTHORIZED", message: "JWT expired" } });
      return route.fulfill({ json: emptyBundle });
    }
    if (path === `/bundles/${BUNDLE_ID}/stream`) {
      calls.stream += 1;
      if (scenario.pollingUnauthorized) return route.fulfill({ status: 401, json: { code: "UNAUTHORIZED", message: "JWT expired" } });
      return route.fulfill({ contentType: "text/event-stream", body: "retry: 60000\n\n" });
    }
    if (path === `/bundles/${BUNDLE_ID}/status`) {
      calls.status += 1;
      if (scenario.pollingUnauthorized) return route.fulfill({ status: 401, json: { code: "UNAUTHORIZED", message: "JWT expired" } });
      return route.fulfill({ json: { kind: "status", bundle_id: BUNDLE_ID, run_id: "auth-test", state: "COMPLETE", progress: 1 } });
    }
    if (path === `/bundles/${BUNDLE_ID}/analyze`) {
      calls.analyze += 1;
      if (scenario.analyzeUnauthorized) return route.fulfill({ status: 401, json: { code: "UNAUTHORIZED", message: "JWT expired" } });
      return route.fulfill({ status: 202, json: { bundle_id: BUNDLE_ID, run_id: "auth-test", state: "QUEUED" } });
    }
    if (path.endsWith("/corrections")) return route.fulfill({ json: { corrections: [], effective: [], pending: 0 } });
    if (path.endsWith("/iterations") || path.endsWith("/extractions")) return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { code: "NOT_FOUND", message: "Unused authentication test route" } });
  });
  return { calls, protectedRequests };
}

for (const width of [390, 1440]) {
test(`signed-out home at ${width}px explains authentication at New empty bundle without creating or listing cases`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const { calls, protectedRequests } = await mockApp(page, { meta: metadata(true) });
  await page.goto("/");
  const create = page.getByRole("button", { name: "New empty bundle", exact: true });
  await expect(create).toBeVisible();
  const destination = page.getByTestId("destination-select");
  await expect(destination).toBeDisabled();
  await expect(destination).toHaveValue("SG");
  await expect(destination).toHaveAttribute("aria-describedby", "destination-sign-in-hint");
  await expect(page.locator("#destination-sign-in-hint")).toHaveText("Sign in to change destination.");
  await expect(page.locator("#destination-sign-in-hint")).toBeVisible();
  await expect(destination).toHaveCSS("cursor", "not-allowed");
  expect(await destination.evaluate((element) => {
    (element as HTMLSelectElement).focus();
    return document.activeElement === element;
  })).toBe(false);
  await expect(page.getByRole("button", { name: "Start Case C demo", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start Case D demo (India import)", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Recent cases", exact: true })).toHaveCount(0);
  const alert = page.getByRole("alert").filter({ hasText: REQUIRED });
  for (const action of [create, page.getByRole("button", { name: "Start Case C demo", exact: true }), page.getByRole("button", { name: "Start Case D demo (India import)", exact: true })]) {
    await action.click();
    await expect(alert).toBeVisible();
    await expect(alert).toBeInViewport();
    await expect(alert).toBeFocused();
    await expect(alert.getByRole("link", { name: /sign in/i })).toHaveAttribute("href", /\/auth\/signin/);
    await expect(page).toHaveURL(/\/$/);
  }
  expect(calls.create).toBe(0);
  expect(calls.list).toBe(0);
  expect(protectedRequests).toEqual([]);
});
}

test("workbench waits for authentication and never requests a bundle or stream for a signed-out user", async ({ page }) => {
  let releaseMeta!: () => void;
  const metadataReady = new Promise<void>((resolve) => { releaseMeta = resolve; });
  const { calls, protectedRequests } = await mockApp(page, { meta: metadata(true), waitForMeta: metadataReady });
  try {
    await page.goto(BUNDLE_PATH);
    await expect.poll(() => calls.meta).toBe(1);
    await expect(page.getByRole("status")).toBeVisible();
    expect(protectedRequests).toEqual([]);
    releaseMeta();
    await expect(page.getByRole("heading", { name: /authentication required/i })).toBeVisible();
    await expect(page.getByRole("main")).toContainText(REQUIRED);
    const signIn = page.getByRole("link", { name: /sign in/i }).first();
    await expect(signIn).toBeVisible();
    const href = await signIn.getAttribute("href");
    expect(new URL(href!, page.url()).searchParams.get("returnTo")).toBe(BUNDLE_PATH);
    expect(calls.bundle).toBe(0);
    expect(calls.stream).toBe(0);
    expect(calls.status).toBe(0);
    expect(protectedRequests).toEqual([]);
  } finally {
    releaseMeta();
  }
});

for (const state of ["auth disabled", "authenticated account", "approved demo preset"] as const) {
  test(`${state} can still create and open a trade bundle`, async ({ page, baseURL }) => {
    const currentMeta = state === "auth disabled" ? metadata(false) : state === "authenticated account" ? metadata(true, user, "live") : metadata(true);
    if (state === "approved demo preset") {
      await page.context().addCookies([{ name: "__session", value: demoToken("demo-cha@customs.com"), url: baseURL! }]);
    }
    const { calls } = await mockApp(page, { meta: currentMeta });
    await page.goto("/");
    await expect(page.getByTestId("destination-select")).toBeEnabled();
    if (currentMeta.app_mode === "demo") await expect(page.getByRole("button", { name: "Start Case C demo", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "New empty bundle", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${BUNDLE_PATH}$`));
    await expect(page.getByRole("heading", { name: "Add the trade documents to begin", exact: true })).toBeVisible();
    expect(calls.create).toBe(1);
    expect(calls.bundle).toBeGreaterThanOrEqual(1);
  });
}

test("an expired protected bundle request uses the shared message and Retry can recover", async ({ page }) => {
  let expired = true;
  const { calls } = await mockApp(page, { meta: metadata(true, user), bundleUnauthorized: () => expired });
  await page.goto(BUNDLE_PATH);
  const alert = page.getByRole("alert").filter({ hasText: REQUIRED });
  await expect(alert).toBeVisible();
  await expect(alert).not.toContainText("JWT expired");
  const requestsBeforeRetry = calls.bundle;
  expect(requestsBeforeRetry).toBeGreaterThanOrEqual(1);
  expired = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Add the trade documents to begin", exact: true })).toBeVisible();
  expect(calls.bundle).toBeGreaterThan(requestsBeforeRetry);
  await expect(page.getByRole("alert").filter({ hasText: REQUIRED })).toHaveCount(0);
});

test("an expired analysis action is explained consistently and leaves a retryable control", async ({ page }) => {
  const { calls } = await mockApp(page, { meta: metadata(true, user), analyzeUnauthorized: true });
  await page.goto(BUNDLE_PATH);
  const run = page.getByTestId("run-button");
  await expect(run).toBeEnabled();
  await run.click();
  const alert = page.getByRole("alert").filter({ hasText: REQUIRED });
  await expect(alert).toBeVisible();
  await expect(alert).not.toContainText("JWT expired");
  await expect(run).toBeEnabled();
  await run.click();
  await expect.poll(() => calls.analyze).toBe(2);
  await expect(alert).toBeVisible();
});

test("an expired polling status response uses the shared authentication message", async ({ page }) => {
  test.setTimeout(25_000);
  const { calls } = await mockApp(page, { meta: metadata(true, user), pollingUnauthorized: true });
  await page.goto(BUNDLE_PATH);
  await expect(page.getByRole("heading", { name: "Add the trade documents to begin", exact: true })).toBeVisible();
  await expect.poll(() => calls.status, { timeout: 15_000 }).toBeGreaterThan(0);
  const alert = page.getByRole("alert").filter({ hasText: REQUIRED });
  await expect(alert).toBeVisible();
  await expect(alert).not.toContainText("JWT expired");
});
