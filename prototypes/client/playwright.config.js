import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests/browser",
  workers: 1,
  forbidOnly: true,
  retries: 0,
  reporter: "list",
  timeout: 15000,
  use: {
    baseURL: "http://127.0.0.1:43979",
    viewport: { width: 1280, height: 960 },
    locale: "en-US",
    timezoneId: "UTC",
    colorScheme: "dark",
    trace: "retain-on-failure",
    launchOptions: { chromiumSandbox: true },
  },
  expect: {
    toHaveScreenshot: { animations: "disabled", maxDiffPixelRatio: 0.001 },
  },
  webServer: {
    command: "python tests/server.py",
    url: "http://127.0.0.1:43979/health",
    reuseExistingServer: false,
    timeout: 15000,
  },
});
