import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testIgnore: /.*\.unit\.spec\.ts$/, // pure unit specs run with playwright.unit.config.ts
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "html",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      // The journeys run in parallel from one address and each starts real analyses: the API's abuse limits (per-minute
      // writes and runs, concurrent runs) would turn a busy test minute into 429s. They are switched off for THIS backend only.
      command:
        "cd ../backend && APP_MODE=demo RATE_LIMIT_WRITES_PER_MINUTE=0 RATE_LIMIT_RUNS_PER_MINUTE=0 MAX_CONCURRENT_RUNS=0 .venv/bin/uvicorn app.main:app --port 8080",
      url: "http://localhost:8080/healthz",
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npm run dev",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
