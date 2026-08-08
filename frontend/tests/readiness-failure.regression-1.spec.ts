import { expect, test } from "@playwright/test";

const mockProvider = { id: "mock", preset_id: "mock", display_name: "本地演示", description: "不联网", provider_type: "mock", protocol_mode: "auto", base_url: "", has_api_key: false, credential_source: "none", supports_api_key: false, requires_api_key: false, enabled: true, is_active: true, default_model: "council-mock", reasoning_effort: "low", timeout_seconds: 30, available_models: ["council-mock"], model_source: "built_in", local_only: true, last_health_check: null, last_error: null, capabilities: {} };
const assignment = (role: string) => ({ role, provider_id: "mock", model: "council-mock", protocol: "auto", reasoning_effort: "low", max_output_tokens: 1200, temperature: 0.2, timeout_seconds: 30 });
const assignments = { schema_version: 2, seats: ["analyst", "challenger", "builder", "observer"].map(assignment), finalizer: assignment("finalizer") };
const templates = [{ id: "open_discussion", name: "开放讨论", description: "依次讨论", prompt_hint: "写下需要四席共同审议的问题", system_guidance: "" }];

test("准备度接口失败时明确阻断，用户覆盖后才创建 Run", async ({ page }) => {
  let createPayload: Record<string, unknown> | null = null;
  let createRequests = 0;
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.route("**/api/memory", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/memory/preview", (route) => route.fulfill({ json: { workspace_id: "local-default", selected_memory_ids: [], included: [], excluded_memory_ids: [], rendered_context: "" } }));
  await page.route("**/api/readiness", (route) => route.fulfill({ status: 503, json: { detail: "temporarily unavailable" } }));
  await page.route("**/api/runs", (route) => {
    createRequests += 1;
    createPayload = route.request().postDataJSON();
    return route.fulfill({ json: { id: "readiness-failure-child" } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "开始本地演示" }).click();
  await page.getByRole("textbox", { name: "你的问题" }).fill("我们现在是否应该发布？");
  await page.getByRole("button", { name: "进入圆桌" }).click();

  const panel = page.getByRole("region", { name: "决策准备度" });
  await expect(panel).toContainText("准备度检查暂时不可用");
  await expect(panel).toContainText("目标：");
  await expect(panel).toContainText("约束：");
  await expect(panel).toContainText("选项：");
  await expect(panel).toContainText("成功标准：");
  expect(createRequests).toBe(0);

  await panel.getByRole("button", { name: "仍然继续" }).click();
  await page.waitForURL("**/runs/readiness-failure-child");
  expect(createRequests).toBe(1);
  expect(createPayload).toMatchObject({ readiness_override: true, readiness_override_reason: "用户查看准备度缺口后选择继续" });
});
