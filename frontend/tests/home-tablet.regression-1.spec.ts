import { expect, test } from "@playwright/test";


const provider = {
  id: "mock",
  display_name: "本地演示",
  provider_type: "mock",
  base_url: "mock://local",
  protocol_mode: "mock",
  default_model: "council-mock",
  reasoning_effort: "high",
  timeout_seconds: 60,
  max_retries: 0,
  active: true,
  configured: true,
  credential_source: "mock",
  local_only: true,
};
const assignment = (role: string) => ({
  role,
  provider_id: "mock",
  model: "council-mock",
  protocol: "mock",
  reasoning_effort: "high",
  max_output_tokens: 1200,
  temperature: 0.2,
  timeout_seconds: 60,
});


test("tablet composer keeps labels horizontal and controls inside the workspace", async ({ page }) => {
  // Regression: ISSUE-002 - tablet flex layout collapsed labels to one character per line.
  // Found by /qa on 2026-08-06.
  // Report: .gstack/qa-reports/qa-report-council-local-2026-08-06.md
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.route("**/api/providers", (route) => route.fulfill({ json: [provider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: {
    schema_version: 2,
    seats: ["analyst", "challenger", "builder", "observer"].map(assignment),
    finalizer: assignment("finalizer"),
  } }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: [{
    id: "open_discussion",
    name: "开放讨论",
    description: "依次讨论",
    prompt_hint: "写下需要四席共同审议的问题",
    system_guidance: "",
  }] }));
  await page.route("**/api/output-contracts", (route) => route.fulfill({ json: [{
    id: "general_decision",
    name: "一般决策",
    description: "比较方案",
    input_checks: ["目标"],
    prompt_hint: "通用",
    system_guidance: "",
  }] }));
  await page.route("**/api/memory", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/memory/preview", (route) => route.fulfill({ json: {
    workspace_id: "default",
    selected_memory_ids: [],
    included: [],
    excluded_memory_ids: [],
    rendered_context: "",
  } }));

  await page.goto("/");
  await page.getByRole("button", { name: "仅体验本地演示" }).click();

  const questionLabel = page.locator(".composer-head .section-label");
  const questionBox = await questionLabel.boundingBox();
  expect(questionBox?.width).toBeGreaterThan(48);
  expect(questionBox?.height).toBeLessThanOrEqual(20);

  const controlWidths = await page.locator(".composer-head .template-select").evaluateAll((items) =>
    items.map((item) => Math.round(item.getBoundingClientRect().width)),
  );
  expect(controlWidths).toHaveLength(3);
  expect(controlWidths.every((width) => width >= 100)).toBeTruthy();

  const viewport = await page.evaluate(() => ({
    pageWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }));
  expect(viewport.pageWidth).toBeLessThanOrEqual(viewport.viewportWidth);
  await expect(page.getByRole("textbox", { name: "你的问题" })).toBeVisible();
});
