import { defineConfig } from "@playwright/test";

/**
 * Pure unit specs (*.unit.spec.ts): no browser, no backend, no dev server.
 *   npm run test:unit
 * The end-to-end suite (playwright.config.ts) ignores them.
 */
export default defineConfig({
  testDir: "./tests",
  testMatch: /.*\.unit\.spec\.ts$/,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: "list",
});
