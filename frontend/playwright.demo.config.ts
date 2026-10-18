import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

/**
 * Records the product walkthrough (demo/walkthrough.spec.ts) as a video plus a screenshot per step.
 * Run it through scripts/record_demo.sh, which also writes the manifest. Not part of `npm test`.
 *
 *   DEMO_BASE_URL unset   starts the demo-mode backend and a production build of the UI locally (needs backend/.venv and `npm ci`)
 *   DEMO_BASE_URL=<url>   records that stack as it is (a deployed UI, live mode): nothing is started
 */
const baseURL = process.env.DEMO_BASE_URL ?? "http://localhost:3000";
const hosted = Boolean(process.env.DEMO_BASE_URL);
const out = path.resolve(process.env.DEMO_OUT_DIR ?? path.join(__dirname, "../demo-recordings/latest"));
const size = { width: 1440, height: 900 };

export default defineConfig({
  testDir: "./demo",
  outputDir: path.join(out, "raw"),
  timeout: 1_800_000,
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL,
    viewport: size,
    video: process.env.DEMO_VIDEO === "off" ? "off" : { mode: "on", size }, // video needs `npx playwright install ffmpeg`
    screenshot: "off",
    trace: "off",
    launchOptions: { slowMo: 120 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: size } }],
  webServer: hosted
    ? undefined
    : [
        {
          command:
            "cd ../backend && APP_MODE=demo AUTH_ENABLED=false RATE_LIMIT_WRITES_PER_MINUTE=0 RATE_LIMIT_RUNS_PER_MINUTE=0 MAX_CONCURRENT_RUNS=0 .venv/bin/uvicorn app.main:app --port 8080",
          url: "http://localhost:8080/healthz",
          reuseExistingServer: true,
        },
        {
          // a production build: no development overlay in the video
          command: process.env.DEMO_USE_DEV ? "npm run dev" : "npm run build && npm run start",
          url: "http://localhost:3000",
          reuseExistingServer: true,
          timeout: 300_000,
        },
      ],
});
