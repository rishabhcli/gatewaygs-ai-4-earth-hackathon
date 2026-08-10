import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: true,
  globalSetup: "./tests/global-setup.ts",
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4171",
    trace: "on-first-retry",
  },
  webServer: {
    command: "make dev:up",
    cwd: "../..",
    url: "http://127.0.0.1:4171/readyz.json",
    reuseExistingServer: true,
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
