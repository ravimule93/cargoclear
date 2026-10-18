import { defineConfig, devices } from "@playwright/test";

// Dedicated test ports avoid silently testing an older developer API.
const apiPort = Number(process.env.CARGOCLEAR_TEST_API_PORT ?? 18080);
const uiPort = Number(process.env.CARGOCLEAR_TEST_UI_PORT ?? 3100);
if (![apiPort, uiPort].every((port) => Number.isInteger(port) && port > 1024 && port < 65536)) {
  throw new Error("CargoClear test ports must be integers between 1025 and 65535.");
}

export default defineConfig({
  testDir: "./tests",
  testIgnore: /.*\.unit\.spec\.ts$/, // pure unit specs run with playwright.unit.config.ts
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "html",
  use: {
    baseURL: `http://localhost:${uiPort}`,
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
        `cd ../backend && APP_MODE=demo AUTH_ENABLED=false RATE_LIMIT_WRITES_PER_MINUTE=0 RATE_LIMIT_RUNS_PER_MINUTE=0 MAX_CONCURRENT_RUNS=0 .venv/bin/uvicorn app.main:app --port ${apiPort}`,
      url: `http://localhost:${apiPort}/healthz`,
      reuseExistingServer: false,
    },
    {
      command: `API_BASE=http://127.0.0.1:${apiPort} npm run dev -- --port ${uiPort}`,
      url: `http://localhost:${uiPort}`,
      reuseExistingServer: false,
    },
  ],
});
