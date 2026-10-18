import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/proxy/meta", (route) => route.fulfill({
    json: {
      app_mode: "demo",
      data_source_policy: "demo",
      pipeline_engine: "native",
      auth: { enabled: true, allowed_email_domains: ["*"] },
    },
  }));
});

test("account tabs support keyboard selection and expose labelled forms", async ({ page }) => {
  await page.goto("/auth/signin");
  const signIn = page.getByRole("tab", { name: "Sign in", exact: true });
  const signUp = page.getByRole("tab", { name: "Create account", exact: true });
  await signIn.focus();
  await page.keyboard.press("ArrowRight");
  await expect(signUp).toBeFocused();
  await expect(signUp).toHaveAttribute("aria-selected", "true");
  const registration = page.getByRole("tabpanel", { name: "Create account" });
  await expect(registration.getByLabel("Full name")).toHaveAttribute("autocomplete", "name");
  await expect(registration.getByLabel("Password", { exact: true })).toHaveAttribute("autocomplete", "new-password");
  await page.keyboard.press("Home");
  await expect(signIn).toBeFocused();
  const login = page.getByRole("tabpanel", { name: "Sign in" });
  await expect(login.getByLabel("Work email")).toHaveAttribute("autocomplete", "username");
  await expect(login.getByLabel("Password", { exact: true })).toHaveAttribute("autocomplete", "current-password");
  await expect(registration).toBeHidden();
});

test("password mismatch focuses the correction and preserves registration input", async ({ page }) => {
  await page.goto("/auth/signin?tab=signup");
  const panel = page.getByRole("tabpanel", { name: "Create account" });
  await panel.getByLabel("Full name").fill("Review Agent");
  await panel.getByLabel("Work email").fill("review@example.com");
  await panel.getByLabel("Password", { exact: true }).fill("sample-one");
  const confirmation = panel.getByLabel("Confirm password");
  await confirmation.fill("sample-two");
  await panel.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("Passwords do not match");
  await expect(confirmation).toBeFocused();
  await expect(confirmation).toHaveAttribute("aria-invalid", "true");
  await expect(panel.getByLabel("Full name")).toHaveValue("Review Agent");
  await confirmation.fill("sample-one");
  await expect(confirmation).not.toHaveAttribute("aria-invalid", "true");
  await expect(panel.getByRole("alert")).toHaveCount(0);
});

test("existing-account recovery shows its message in the selected sign-in panel", async ({ page }) => {
  await page.route("**/api/proxy/auth/signup", (route) => route.fulfill({
    status: 409,
    json: { code: "CONFLICT", message: "Account exists" },
  }));
  await page.goto("/auth/signin?tab=signup");
  const registration = page.getByRole("tabpanel", { name: "Create account" });
  await registration.getByLabel("Full name").fill("Review Agent");
  await registration.getByLabel("Work email").fill("review@example.com");
  await registration.getByLabel("Password", { exact: true }).fill("sample-password");
  await registration.getByLabel("Confirm password").fill("sample-password");
  await registration.getByRole("button", { name: "Create account", exact: true }).click();
  const login = page.getByRole("tabpanel", { name: "Sign in" });
  await expect(login.getByRole("alert")).toContainText("An account already exists");
  await expect(login.getByLabel("Work email")).toHaveValue("review@example.com");
  await expect(page.getByRole("tab", { name: "Sign in", exact: true })).toBeFocused();
});

test("sign-in prevents duplicate requests and restores retry without clearing input", async ({ page }) => {
  let releaseResponse!: () => void;
  let requests = 0;
  const responseReady = new Promise<void>((resolve) => { releaseResponse = resolve; });
  await page.route("**/api/proxy/auth/signin", async (route) => {
    requests += 1;
    await responseReady;
    await route.fulfill({ status: 401, json: { code: "UNAUTHORIZED", message: "Invalid credentials" } });
  });
  await page.goto("/auth/signin");
  const login = page.getByRole("tabpanel", { name: "Sign in" });
  await login.getByLabel("Work email").fill("review@example.com");
  await login.getByLabel("Password", { exact: true }).fill("sample-password");
  await login.getByRole("button", { name: /^sign in$/i }).click();
  await expect(login.getByRole("button", { name: "Verifying credentials..." })).toBeDisabled();
  await expect(login.getByRole("status")).toHaveText("Signing in. Please wait.");
  await login.getByLabel("Work email").press("Enter");
  expect(requests).toBe(1);
  releaseResponse();
  await expect(login.getByRole("alert")).toContainText("Invalid email or password");
  await expect(login.getByRole("button", { name: /^sign in$/i })).toBeEnabled();
  await expect(login.getByLabel("Work email")).toHaveValue("review@example.com");
  await expect(login.getByLabel("Password", { exact: true })).toHaveValue("sample-password");
});

test("both account forms have no serious accessibility violations or narrow-screen overflow", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/auth/signin?error=authorization_cancelled");
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(1);
  for (const tab of ["Sign in", "Create account"]) {
    await page.getByRole("tab", { name: tab, exact: true }).click();
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(results.violations.filter((issue) => issue.impact === "critical" || issue.impact === "serious")).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
});
