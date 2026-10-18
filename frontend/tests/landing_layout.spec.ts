import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const REQUIRED = "Authentication required. Please sign in to continue.";
const primaryTask = (page: Page) => page.locator('section[aria-labelledby="start-assessment-heading"]');
const workspaceAccess = (page: Page) => page.locator('section[aria-labelledby="workspace-access-heading"]');
const demoCases = (page: Page) => page.locator('section[aria-labelledby="demo-cases-heading"]');
const caseCard = (page: Page, kind: "c" | "d") => demoCases(page).locator(`article[aria-labelledby="case-${kind}-heading"]`);
const PRESETS = ["customs.com", "dhl.com", "fedex.com"] as const;

/** Signed-out API fixture. Protected requests are recorded and intercepted, never sent to a real workspace. */
async function mockSignedOutHome(page: Page) {
  const protectedRequests: string[] = [];
  const createRequests: string[] = [];
  await page.route("**/api/proxy/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.slice("/api/proxy".length);
    if (path === "/meta") return route.fulfill({ json: {
      app_mode: "demo", data_source_policy: "test-fixture-only", pipeline_engine: "native",
      auth: { enabled: true, allowed_email_domains: ["*"] }, user: null,
    } });
    if (path === "/mode") return route.fulfill({ json: {
      active_mode: "demo", configured_mode: "demo", supported_modes: ["demo", "live"],
      live_available: false, credential_source: null, provider: "test-fixture-only", model: "test-fixture-only",
    } });
    if (path === "/bundles" || path.startsWith("/bundles/") || /^\/demo\/case-[cd](?:\/|$)/.test(path)) {
      protectedRequests.push(`${request.method()} ${path}`);
      if (request.method() === "POST") createRequests.push(path);
      if (path === "/bundles" && request.method() === "GET") return route.fulfill({ json: [] });
      return route.fulfill({ status: 401, json: { code: "UNAUTHORIZED", message: REQUIRED } });
    }
    return route.fulfill({ status: 404, json: { code: "NOT_FOUND", message: "Unused landing-layout test route" } });
  });
  return { protectedRequests, createRequests };
}

async function expectAccessOptions(page: Page) {
  const access = workspaceAccess(page);
  await expect(access.getByRole("link", { name: /sign in to account/i })).toHaveAttribute("href", "/auth/signin?tab=signin");
  await expect(access.getByRole("link", { name: /create.*account/i })).toHaveAttribute("href", "/auth/signin?tab=signup");
  await expect(access.getByRole("link", { name: "Continue with Google SSO", exact: true })).toHaveAttribute("href", "/api/auth/signin/google");
  for (const label of PRESETS) await expect(access.getByRole("button", { name: label, exact: true })).toBeEnabled();
  await expect(access.getByRole("button", { name: /^(customs\.com|dhl\.com|fedex\.com)$/ })).toHaveCount(3);
}

for (const theme of ["light", "dark"] as const) {
  for (const width of [320, 390, 639, 640, 768, 1024, 1440, 1920]) {
    test(`signed-out landing at ${width}px in ${theme} keeps the task first and workspace access responsive`, async ({ page }) => {
      await page.addInitScript((value) => localStorage.setItem("cargoclear-theme", value), theme);
      await page.setViewportSize({ width, height: 900 });
      const { protectedRequests } = await mockSignedOutHome(page);
      await page.goto("/");
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      const task = primaryTask(page);
      const access = workspaceAccess(page);
      await expect(task).toBeVisible();
      await expect(access).toBeVisible();
      const create = task.getByRole("button", { name: "New empty bundle", exact: true });
      await expect(create).toBeVisible();
      await expect(create).toBeInViewport();
      const destination = task.getByTestId("destination-select");
      await expect(destination).toBeDisabled();
      await expect(destination).toHaveValue("SG");
      await expect(destination).toHaveAttribute("aria-describedby", "destination-sign-in-hint");
      await expect(task.locator("#destination-sign-in-hint")).toHaveText("Sign in to change destination.");
      await expect(task.locator("#destination-sign-in-hint")).toBeVisible();
      await expect(caseCard(page, "c").getByRole("button", { name: "Start Case C demo", exact: true })).toBeVisible();
      await expect(caseCard(page, "d").getByRole("button", { name: "Start Case D demo (India import)", exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Recent cases", exact: true })).toHaveCount(0);
      await expectAccessOptions(page);

      expect(await task.evaluate((element) => {
        const accessSection = document.getElementById("workspace-access-heading")?.closest("section");
        return Boolean(accessSection && (element.compareDocumentPosition(accessSection) & Node.DOCUMENT_POSITION_FOLLOWING));
      })).toBe(true);

      const taskBox = (await task.boundingBox())!;
      const accessBox = (await access.boundingBox())!;
      if (width >= 1024) {
        expect(taskBox.x + taskBox.width).toBeLessThanOrEqual(accessBox.x + 1);
        expect(Math.abs(taskBox.y - accessBox.y)).toBeLessThanOrEqual(1);
        expect(Math.abs(taskBox.height - accessBox.height)).toBeLessThanOrEqual(1);
        expect(Math.abs(accessBox.width - 320)).toBeLessThanOrEqual(1);
      } else {
        expect(taskBox.y + taskBox.height).toBeLessThanOrEqual(accessBox.y + 1);
        expect(Math.abs(taskBox.x - accessBox.x)).toBeLessThanOrEqual(1);
      }

      const demoBox = (await demoCases(page).boundingBox())!;
      const caseCBox = (await caseCard(page, "c").boundingBox())!;
      const caseDBox = (await caseCard(page, "d").boundingBox())!;
      const topRowBottom = Math.max(taskBox.y + taskBox.height, accessBox.y + accessBox.height);
      const layoutRight = width >= 1024 ? accessBox.x + accessBox.width : taskBox.x + taskBox.width;
      expect(demoBox.y).toBeGreaterThanOrEqual(topRowBottom - 1);
      expect(Math.abs(demoBox.x - taskBox.x)).toBeLessThanOrEqual(1);
      expect(Math.abs(demoBox.x + demoBox.width - layoutRight)).toBeLessThanOrEqual(1);
      expect(Math.abs(caseCBox.width - caseDBox.width)).toBeLessThanOrEqual(1);
      if (width >= 640) {
        expect(caseCBox.x + caseCBox.width).toBeLessThanOrEqual(caseDBox.x + 1);
        expect(Math.abs(caseCBox.y - caseDBox.y)).toBeLessThanOrEqual(1);
        expect(Math.abs(caseCBox.height - caseDBox.height)).toBeLessThanOrEqual(1);
      } else {
        expect(caseCBox.y + caseCBox.height).toBeLessThanOrEqual(caseDBox.y + 1);
        expect(Math.abs(caseCBox.x - caseDBox.x)).toBeLessThanOrEqual(1);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      expect(protectedRequests).toEqual([]);
    });
  }
}

for (const theme of ["light", "dark"] as const) {
  for (const width of [320, 1440]) {
    test(`signed-out landing at ${width}px in ${theme} has no serious accessibility violations`, async ({ page }) => {
      await page.addInitScript((value) => localStorage.setItem("cargoclear-theme", value), theme);
      await page.setViewportSize({ width, height: 900 });
      const { protectedRequests } = await mockSignedOutHome(page);
      await page.goto("/");
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(primaryTask(page)).toBeVisible();
      await expect(workspaceAccess(page)).toBeVisible();
      await page.addStyleTag({ content: "*, *::before, *::after { transition: none !important; animation: none !important; }" });
      const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      expect(result.violations.filter((issue) => issue.impact === "critical" || issue.impact === "serious").map((issue) => ({
        id: issue.id, targets: issue.nodes.map((node) => node.target),
      }))).toEqual([]);
      expect(protectedRequests).toEqual([]);
    });
  }
}

test("all signed-out case actions focus a visible authentication error without creating or listing cases", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { protectedRequests, createRequests } = await mockSignedOutHome(page);
  await page.goto("/");
  const alert = page.getByRole("alert").filter({ hasText: REQUIRED });
  for (const action of ["New empty bundle", "Start Case C demo", "Start Case D demo (India import)"]) {
    await page.getByRole("button", { name: action, exact: true }).click();
    await expect(alert).toBeVisible();
    await expect(alert).toBeInViewport();
    await expect(alert).toBeFocused();
    await expect(alert.getByRole("link", { name: "Sign in", exact: true })).toHaveAttribute("href", /\/auth\/signin/);
    await expect(page).toHaveURL(/\/$/);
  }
  expect(createRequests).toEqual([]);
  expect(protectedRequests).toEqual([]);
});

test("demo disclosure is closed initially, keeps its disclaimer visible, and toggles with the keyboard", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { protectedRequests } = await mockSignedOutHome(page);
  await page.goto("/");
  const disclosure = page.locator("details").filter({ has: page.locator("summary", { hasText: "About demo data" }) });
  const summary = disclosure.locator("summary");
  const disclaimer = page.locator("#demo-data-disclaimer");
  await expect(summary).toHaveText("About demo data");
  await expect(disclosure).toHaveJSProperty("open", false);
  await expect(disclaimer).toHaveText("Synthetic demo data. Duty estimates are illustrative; the authorised agent makes the final decision.");
  await expect(disclaimer).toBeVisible();
  expect(await disclaimer.evaluate((element) => element.closest("details") === null)).toBe(true);
  await summary.focus();
  await expect(summary).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(disclosure).toHaveJSProperty("open", true);
  await page.keyboard.press("Space");
  await expect(disclosure).toHaveJSProperty("open", false);
  await expect(summary).toBeFocused();
  await expect(disclaimer).toBeVisible();
  expect(protectedRequests).toEqual([]);
});

for (const label of PRESETS) {
  test(`the ${label} demo preset still opens the authenticated landing workflow`, async ({ page }) => {
    const { createRequests } = await mockSignedOutHome(page);
    await page.goto("/");
    await workspaceAccess(page).getByRole("button", { name: label, exact: true }).click();
    await expect(workspaceAccess(page)).toHaveCount(0);
    await expect(primaryTask(page).getByTestId("destination-select")).toBeEnabled();
    await expect(page.getByRole("button", { name: "Start Case C demo", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Start Case D demo (India import)", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recent cases", exact: true })).toBeVisible();
    const cookies = await page.context().cookies();
    const address = label === "customs.com" ? "demo-cha@customs.com" : label === "dhl.com" ? "agent@dhl.com" : "broker@fedex.com";
    expect(cookies.find((cookie) => cookie.name === "__session")?.value).toBe(`mock-jwt-${address}-LICENSED_CHA`);
    expect(createRequests).toEqual([]);
  });
}
