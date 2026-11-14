import { defineConfig } from "@playwright/test";

// Runs against a running app (scripts/dev.sh start, or the CI services).
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 60_000 },
  workers: 2,
  use: { baseURL: process.env.MEGAVIR_WEB_URL ?? "http://localhost:3000", trace: "retain-on-failure" },
  reporter: [["list"]],
});
