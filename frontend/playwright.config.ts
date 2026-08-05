import { defineConfig, devices } from "@playwright/test";

const requestedBrowser = process.env.COUNCIL_TEST_BROWSER || "chromium";
const browserProjects = {
  chromium: { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  firefox: { name: "firefox", use: { ...devices["Desktop Firefox"] } },
  webkit: { name: "webkit", use: { ...devices["Desktop Safari"] } },
};

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  use: { baseURL: process.env.COUNCIL_TEST_FRONTEND_URL || "http://localhost:3000", trace: "retain-on-failure" },
  projects: [browserProjects[requestedBrowser as keyof typeof browserProjects] || browserProjects.chromium],
});
