import { defineConfig, devices } from "@playwright/test";

const port = process.env.PLAYWRIGHT_PORT ?? "4173";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: { baseURL: `http://127.0.0.1:${port}`, serviceWorkers: "allow" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], browserName: "chromium" } },
    { name: "webkit", use: { ...devices["Desktop Safari"], browserName: "webkit" } },
  ],
  webServer: { command: `npm run preview -- --port ${port}`, url: `http://127.0.0.1:${port}`, reuseExistingServer: true, timeout: 30_000 },
});
