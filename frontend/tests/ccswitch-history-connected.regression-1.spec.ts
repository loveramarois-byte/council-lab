import { expect, test } from "@playwright/test";

const ccswitchProvider = {
  id: "ccswitch",
  preset_id: "ccswitch",
  display_name: "CC Switch",
  description: "本机路由",
  provider_type: "ccswitch_local",
  protocol_mode: "responses",
  base_url: "http://127.0.0.1:15721/v1",
  supports_api_key: false,
  requires_api_key: false,
  default_model: "gpt-5.6-sol",
  reasoning_effort: "ultra",
  timeout_seconds: 120,
  available_models: ["gpt-5.6-sol"],
  model_source: "ccswitch_history",
  local_only: true,
  has_api_key: false,
  credential_source: "none",
  is_active: true,
  capabilities: {},
};

test("CC Switch 路由在线时不会把历史模型记录误报为当前不可用", async ({ page }) => {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [ccswitchProvider] }));
  await page.route("**/api/providers/ccswitch/detect", (route) => route.fulfill({
    json: {
      status: "connected",
      available: true,
      model_source: "ccswitch_history",
      default_model: "gpt-5.6-sol",
      models: ["gpt-5.6-sol"],
    },
  }));

  await page.goto("/settings/providers");

  await expect(page.locator(".provider-state")).toContainText("已连接");
  await expect(page.getByText(/路由已连接；已载入 1 个近期成功模型记录/)).toBeVisible();
  await expect(page.getByText(/当前 CC Switch 路由不可用/)).toHaveCount(0);
});
