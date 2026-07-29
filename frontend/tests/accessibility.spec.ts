import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";


const mockProvider = {
  id: "mock",
  preset_id: "mock",
  display_name: "本地演示",
  description: "不联网",
  provider_type: "mock",
  protocol_mode: "auto",
  base_url: "",
  has_api_key: false,
  credential_source: "none",
  supports_api_key: false,
  requires_api_key: false,
  enabled: true,
  is_active: true,
  default_model: "council-mock",
  reasoning_effort: "low",
  timeout_seconds: 30,
  available_models: ["council-mock"],
  model_source: "built_in",
  local_only: true,
  last_health_check: null,
  last_error: null,
  capabilities: {},
};

const assignment = (role: string) => ({
  role,
  provider_id: "mock",
  model: "council-mock",
  protocol: "auto",
  reasoning_effort: "low",
  max_output_tokens: 1200,
  temperature: 0.2,
  timeout_seconds: 30,
});

async function mockConfiguration(page: import("@playwright/test").Page) {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({
    json: {
      seats: [assignment("analyst"), assignment("challenger"), assignment("builder"), assignment("observer")],
      finalizer: assignment("finalizer"),
    },
  }));
  await page.route("**/api/templates", (route) => route.fulfill({
    json: [{ id: "open_discussion", name: "开放讨论", description: "依次讨论", prompt_hint: "写下问题", system_guidance: "" }],
  }));
}

for (const target of [
  { name: "首页首次配置", path: "/" },
  { name: "席位设置", path: "/settings/agents" },
]) {
  test(`${target.name}没有 serious 或 critical 无障碍问题`, async ({ page }) => {
    await mockConfiguration(page);
    await page.goto(target.path);
    await expect(page.locator("body")).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    const blocking = results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact || ""));
    expect(blocking).toEqual([]);
  });
}
