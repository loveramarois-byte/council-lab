import { expect, test } from "@playwright/test";

const backendUrl = process.env.COUNCIL_TEST_BACKEND_URL || "http://127.0.0.1:8001";
const mockProvider = { id: "mock", preset_id: "mock", display_name: "本地演示", description: "不联网", provider_type: "mock", protocol_mode: "auto", base_url: "", has_api_key: false, credential_source: "none", supports_api_key: false, requires_api_key: false, enabled: true, is_active: true, default_model: "council-mock", reasoning_effort: "low", available_models: ["council-mock"], model_source: "built_in", local_only: true, last_health_check: null, last_error: null, capabilities: {} };
const readyProvider = { ...mockProvider, id: "deepseek", preset_id: "deepseek", display_name: "DeepSeek", provider_type: "compatible", has_api_key: true, credential_source: "system", supports_api_key: true, requires_api_key: true, default_model: "deepseek-chat", available_models: ["deepseek-chat"], model_source: "provider", local_only: false, last_health_check: "2026-07-28T00:00:00Z" };
const unreadyProvider = { ...readyProvider, has_api_key: false, credential_source: "none", last_health_check: null };
const assignment = (role: string, providerId = "mock") => ({ role, provider_id: providerId, model: providerId === "mock" ? "council-mock" : "deepseek-chat", protocol: "auto", reasoning_effort: "low", max_output_tokens: 1200, temperature: 0.2, timeout_seconds: 30 });
const assignments = (providerId = "mock") => ({ seats: [assignment("analyst", providerId), assignment("challenger", providerId), assignment("builder", providerId), assignment("observer", providerId)], finalizer: assignment("finalizer", providerId) });
const templates = [{ id: "open_discussion", name: "开放讨论", description: "依次讨论", prompt_hint: "写下需要四席共同审议的问题", system_guidance: "" }];

async function createMockRoundtable(request: import("@playwright/test").APIRequestContext) {
  const response = await request.post(`${backendUrl}/api/runs`, {
    data: { question: "数据库迁移应该先讨论哪些风险？", mode: "standard", provider_id: "mock", model: "council-mock" },
  });
  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<{ id: string }>;
}

test("首次打开明确区分本地演示并引导配置五席", async ({ page }) => {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments() }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  let createPayload: Record<string, unknown> | null = null;
  await page.route("**/api/runs", (route) => {
    createPayload = route.request().postDataJSON();
    return route.fulfill({ json: { id: "demo-fixture" } });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /四种视角/ })).toBeVisible();
  await expect(page.getByText("依次发言、公开回应，由你确认后再形成答案。")).toBeVisible();
  await expect(page.getByRole("heading", { name: "当前五席还是本地演示。" })).toBeVisible();
  await expect(page.getByText(/预设示例，不调用真实 AI/)).toBeVisible();
  await expect(page.getByRole("link", { name: /连接真实 AI/ })).toHaveAttribute("href", "/settings/providers");
  await expect(page.getByRole("link", { name: "资料空间" })).toHaveCount(0);
  await expect(page.getByText("资料空间", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /进入圆桌/ })).toHaveCount(0);
  await page.getByRole("button", { name: "仅体验本地演示" }).click();
  await expect(page.getByText("本地演示模式")).toBeVisible();
  await expect(page.getByRole("button", { name: /进入圆桌/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /引导.*1.8k/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /圆桌.*4k/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /深挖.*7k/ })).toBeVisible();
  await expect(page.getByText("联网核验")).toHaveCount(0);
  await expect(page.getByText("代码沙箱")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "附件" })).toHaveCount(0);
  await expect(page.locator(".app-shell")).toHaveCSS("display", "flex");
  const stylesheets = await page.locator('link[rel="stylesheet"]').evaluateAll((links) => links.map((link) => (link as HTMLLinkElement).href));
  expect(stylesheets.length).toBeGreaterThan(0);
  for (const stylesheet of stylesheets) {
    const response = await page.request.get(stylesheet);
    expect(response.ok(), `${stylesheet} 应能正常加载`).toBeTruthy();
  }
  const viewport = await page.evaluate(() => ({ page: document.documentElement.scrollHeight, viewport: window.innerHeight }));
  expect(viewport.page).toBeLessThanOrEqual(viewport.viewport);
  await page.getByPlaceholder("写下需要四席共同审议的问题").fill("这个演示请求不应携带资料空间字段");
  await page.getByRole("button", { name: /进入圆桌/ }).click();
  await page.waitForURL("**/runs/demo-fixture");
  expect(createPayload).toEqual({ question: "这个演示请求不应携带资料空间字段", mode: "standard", use_saved_assignments: true, template_id: "open_discussion" });
});

test("已有真实 Provider 时引导全 Mock 五席进入席位配置", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider, readyProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments() }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.goto("/");
  await expect(page.getByRole("link", { name: /配置五个席位/ })).toHaveAttribute("href", "/settings/agents");
  const viewport = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewportWidth: window.innerWidth, height: document.documentElement.scrollHeight, viewportHeight: window.innerHeight }));
  expect(viewport.width).toBeLessThanOrEqual(viewport.viewportWidth);
  expect(viewport.height).toBeLessThanOrEqual(viewport.viewportHeight);
});

test("混合席位保留本地演示披露并要求明确确认", async ({ page }) => {
  const mixedAssignments = assignments();
  mixedAssignments.seats[0] = assignment("analyst", "deepseek");
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider, readyProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: mixedAssignments }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "当前五席含 4 个本地演示席。" })).toBeVisible();
  await expect(page.getByText(/4 个席位使用预设示例/)).toBeVisible();
  await expect(page.getByRole("button", { name: /进入圆桌/ })).toHaveCount(0);
  await page.getByRole("button", { name: "接受混合配置并继续" }).click();
  await expect(page.getByText(/混合配置 · 4 个本地演示席/)).toBeVisible();
  await expect(page.getByRole("button", { name: /进入圆桌/ })).toBeVisible();
});

test("未就绪真实席位阻止提问并指向配置", async ({ page }) => {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider, unreadyProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments("deepseek") }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "五席配置还不能运行。" })).toBeVisible();
  await expect(page.getByText(/5 个真实 AI 席位的 Provider 尚未通过就绪检查/)).toBeVisible();
  await expect(page.getByRole("link", { name: /检查 Provider/ })).toHaveAttribute("href", "/settings/providers");
  await expect(page.getByRole("link", { name: "调整席位" })).toHaveAttribute("href", "/settings/agents");
  await expect(page.getByRole("button", { name: /进入圆桌/ })).toHaveCount(0);
});

test("席位配置读取失败时保持阻断并可重试", async ({ page }) => {
  let providerRequests = 0;
  await page.route("**/api/providers", (route) => {
    providerRequests += 1;
    return providerRequests === 1
      ? route.fulfill({ status: 503, json: { detail: "本地服务暂时不可用" } })
      : route.fulfill({ json: [mockProvider, readyProvider] });
  });
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments("deepseek") }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "暂时无法确认五席配置。" })).toBeVisible();
  await expect(page.getByRole("button", { name: /进入圆桌/ })).toHaveCount(0);
  await page.getByRole("button", { name: "重新读取" }).click();
  await expect(page.getByText("五席真实 AI 已就绪")).toBeVisible();
  await expect(page.getByRole("button", { name: /进入圆桌/ })).toBeVisible();
});

test("五席真实 Provider 就绪时直接开放提问", async ({ page }) => {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider, readyProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments("deepseek") }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.goto("/");

  await expect(page.getByText("五席真实 AI 已就绪")).toBeVisible();
  await expect(page.getByText(/本地演示模式|混合配置/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /进入圆桌/ })).toBeVisible();
});

test("旧资料空间地址兼容重定向到新建审议", async ({ page }) => {
  await page.goto("/projects");
  await page.waitForURL("/");
  await expect(page.getByRole("heading", { name: /四种视角/ })).toBeVisible();
});

test("软件能自动发现、校验并启动安装正式版本", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.route("**/api/update/check*", (route) => route.fulfill({ json: {
    current_version: "0.3.0",
    latest_version: "0.4.0",
    update_available: true,
    can_auto_update: true,
    installation_kind: "macos",
    reason: "可以在软件内完成更新。",
    release_url: "https://github.com/loveramarois-byte/council-lab/releases/tag/v0.4.0",
    published_at: "2026-07-28T00:00:00Z",
    notes: "Updater release",
    package_name: "Council-v0.4.0-macOS.zip",
  } }));
  await page.route("**/api/update/install", (route) => {
    expect(route.request().headers()["x-council-request"]).toBe("app");
    return route.fulfill({ json: {
      current_version: "0.3.0", phase: "checking", progress: 0, message: "正在确认最新版。", target_version: "0.4.0", error: null,
    } });
  });
  await page.route("**/api/update/status", (route) => route.fulfill({ json: {
    current_version: "0.3.0", phase: "downloading", progress: 42, message: "正在下载 Council-v0.4.0-macOS.zip。", target_version: "0.4.0", error: null,
  } }));

  await page.goto("/settings/update");
  await expect(page.getByRole("heading", { name: "Council 0.4.0 已发布。" })).toBeVisible();
  await expect(page.locator(".update-versions strong").nth(0)).toHaveText("v0.3.0");
  await expect(page.locator(".update-versions strong").nth(1)).toHaveText("v0.4.0");
  await expect(page.getByText("SHA256", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "下载并安装" }).click();
  await expect(page.getByText("正在下载 Council-v0.4.0-macOS.zip。")).toBeVisible({ timeout: 5000 });
  await expect(page.locator("progress")).toHaveAttribute("value", "42");
  const viewport = await page.evaluate(() => ({ page: document.documentElement.scrollHeight, viewport: window.innerHeight }));
  expect(viewport.page).toBeLessThanOrEqual(viewport.viewport);
});

test("更新不可自动安装时说明原因且移动端保持单屏", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/update/check", (route) => route.fulfill({ json: {
    current_version: "0.4.0",
    latest_version: "0.5.0",
    update_available: true,
    can_auto_update: false,
    installation_kind: "development",
    reason: "源码运行模式只检查版本，不自动覆盖项目文件。",
    release_url: "https://github.com/loveramarois-byte/council-lab/releases/tag/v0.5.0",
    published_at: "2026-07-28T00:00:00Z",
    notes: "Manual update only",
    package_name: null,
  } }));

  await page.goto("/settings/update");
  await expect(page.getByText("源码运行模式只检查版本，不自动覆盖项目文件。")).toBeVisible();
  await expect(page.getByRole("button", { name: "下载并安装" })).toHaveCount(0);
  const viewport = await page.evaluate(() => ({ page: document.documentElement.scrollHeight, viewport: window.innerHeight }));
  expect(viewport.page).toBeLessThanOrEqual(viewport.viewport);
});

test("更新检查和安装失败时给出可恢复错误", async ({ page }) => {
  await page.route("**/api/update/check*", (route) => {
    if (!route.request().url().includes("refresh=true")) return route.fulfill({ status: 503, json: { detail: "暂时无法读取 GitHub 最新版本。" } });
    expect(route.request().headers()["x-council-request"]).toBe("app");
    return route.fulfill({ json: {
      current_version: "0.4.0", latest_version: "0.5.0", update_available: true, can_auto_update: true,
      installation_kind: "macos", reason: "可以在软件内完成更新。", release_url: "https://github.com/loveramarois-byte/council-lab/releases/tag/v0.5.0",
      published_at: null, notes: "Retry test", package_name: "Council-v0.5.0-macOS.zip",
    } });
  });
  await page.route("**/api/update/install", (route) => route.fulfill({ status: 500, json: { detail: "无法启动更新。" } }));

  await page.goto("/settings/update");
  await expect(page.getByText("暂时无法读取 GitHub 最新版本。")).toBeVisible();
  await page.getByRole("button", { name: "重新检查" }).click();
  await expect(page.getByRole("heading", { name: "Council 0.5.0 已发布。" })).toBeVisible();
  await page.getByRole("button", { name: "下载并安装" }).click();
  await expect(page.getByText("无法启动更新。")).toBeVisible();
});

test("侧栏发现新版本后直达软件更新", async ({ page }) => {
  await page.route("**/api/update/check", (route) => route.fulfill({ json: {
    current_version: "0.4.0", latest_version: "0.5.0", update_available: true, can_auto_update: true,
    installation_kind: "macos", reason: "可以在软件内完成更新。", release_url: "https://github.com/loveramarois-byte/council-lab/releases/tag/v0.5.0",
    published_at: null, notes: "Badge test", package_name: "Council-v0.5.0-macOS.zip",
  } }));
  await page.goto("/");
  await expect(page.getByText("有更新", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /设置.*有更新/ })).toHaveAttribute("href", "/settings/update");
});

test("最新版和后台安装错误都能形成明确终态", async ({ page }) => {
  let latestVersion = "0.4.0";
  await page.route("**/api/update/check*", (route) => route.fulfill({ json: {
    current_version: "0.4.0", latest_version: latestVersion, update_available: latestVersion !== "0.4.0", can_auto_update: true,
    installation_kind: "macos", reason: "可以在软件内完成更新。", release_url: `https://github.com/loveramarois-byte/council-lab/releases/tag/v${latestVersion}`,
    published_at: null, notes: "Terminal state test", package_name: `Council-v${latestVersion}-macOS.zip`,
  } }));
  await page.route("**/api/update/install", (route) => route.fulfill({ json: {
    current_version: "0.4.0", phase: "checking", progress: 0, message: "正在确认最新版。", target_version: "0.5.0", error: null,
  } }));
  await page.route("**/api/update/status", (route) => route.fulfill({ json: {
    current_version: "0.4.0", phase: "error", progress: 88, message: "SHA256 校验失败，当前版本未被修改。", target_version: "0.5.0", error: "SHA256 校验失败，当前版本未被修改。",
  } }));

  await page.goto("/settings/update");
  await expect(page.getByText("当前版本已经与正式 Release 一致。")).toBeVisible();
  latestVersion = "0.5.0";
  await page.getByRole("button", { name: "重新检查" }).click();
  await expect(page.getByRole("heading", { name: "Council 0.5.0 已发布。" })).toBeVisible();
  await page.getByRole("button", { name: "下载并安装" }).click();
  await expect(page.getByText("SHA256 校验失败，当前版本未被修改。")).toBeVisible({ timeout: 5000 });
  await expect(page.locator(".update-message.error")).toBeVisible();
});

test("供应商设置为新手提供预设、凭据和模型获取入口", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.goto("/settings/providers");

  for (const provider of ["CC Switch", "DeepSeek", "智谱 GLM", "Kimi", "硅基流动", "OpenAI", "自定义兼容接口", "本地演示"]) {
    await expect(page.getByRole("button", { name: new RegExp(provider) })).toBeVisible();
  }

  await page.getByRole("button", { name: /DeepSeek/ }).click();
  await expect(page.locator('input[type="password"]')).toHaveAttribute("placeholder", "粘贴 API Key");
  await expect(page.getByRole("link", { name: /获取 API Key/ })).toHaveAttribute("href", "https://platform.deepseek.com/api_keys");
  await expect(page.getByLabel("模型", { exact: true })).toHaveValue("deepseek-chat");
  await expect(page.getByText("2 个离线备选，连接后更新")).toBeVisible();
  await page.getByRole("button", { name: "获取模型", exact: true }).click();
  await expect(page.getByText("先粘贴 API Key，再获取模型。")).toBeVisible();

  const desktop = await page.evaluate(() => ({
    pageHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
    consoleHeight: document.querySelector(".provider-console")?.clientHeight || 0,
  }));
  expect(desktop.pageHeight).toBeLessThanOrEqual(desktop.viewportHeight);
  expect(desktop.consoleHeight).toBeGreaterThan(400);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.getByRole("button", { name: /DeepSeek/ }).click();
  const mobile = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    height: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
  }));
  expect(mobile.width).toBeLessThanOrEqual(mobile.viewportWidth);
  expect(mobile.height).toBeLessThanOrEqual(mobile.viewportHeight);
  await expect(page.locator('input[type="password"]')).toBeVisible();
  await expect(page.getByRole("button", { name: "保存并测试" }).or(page.getByRole("link", { name: /下一步：配置五个席位/ }))).toBeVisible();
});

test("CC Switch 打开设置后自动识别模型", async ({ page }) => {
  await page.route("**/api/providers/ccswitch/detect", (route) => route.fulfill({
    json: {
      status: "connected",
      model_source: "provider",
      default_model: "gpt-test-primary",
      models: ["gpt-test-primary", "gpt-test-backup"],
    },
  }));
  await page.goto("/settings/providers");
  await expect(page.getByText("已自动识别 2 个可用模型。")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByLabel("模型", { exact: true })).toHaveValue("gpt-test-primary");
  expect(await page.getByLabel("模型", { exact: true }).locator("option").count()).toBe(2);
});

test("CC Switch 不可达时不会显示为已连接", async ({ page }) => {
  await page.route("**/api/providers/ccswitch/detect", (route) => route.fulfill({
    json: {
      status: "connection_refused",
      model_source: "none",
      default_model: "",
      models: [],
      error: "无法连接 CC Switch 本地路由。",
    },
  }));

  await page.goto("/settings/providers");
  await expect(page.getByText("无法连接服务地址，请确认程序已启动。")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".provider-state")).toContainText("不可用");
  await expect(page.locator(".provider-state")).not.toContainText("已连接");
  await expect(page.locator('select[aria-label="模型"]')).toHaveCount(0);
});

test("CC Switch 历史模型不会被标成当前可用", async ({ page }) => {
  await page.route("**/api/providers/ccswitch/detect", (route) => route.fulfill({
    json: {
      status: "connection_refused",
      model_source: "ccswitch_history",
      default_model: "recent-model",
      models: ["recent-model"],
      error: "无法连接 CC Switch 本地路由。",
    },
  }));

  await page.goto("/settings/providers");
  await expect(page.getByText(/读取到 1 个近期成功模型记录/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/这些记录不代表模型现在可用/)).toBeVisible();
  await expect(page.locator(".provider-state")).toContainText("不可用");
  await expect(page.getByText(/已自动识别 1 个可用模型/)).toHaveCount(0);
});

test("粘贴 API Key 后保存并测试会自动获取模型并启用供应商", async ({ page }) => {
  let savedKey = "";
  let modelsRequested = 0;
  let tested = 0;
  let activated = 0;

  await page.route("**/api/providers", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    return route.fulfill({ json: [{
      id: "deepseek", preset_id: "deepseek", display_name: "DeepSeek", description: "官方 API",
      key_url: "https://platform.deepseek.com/api_keys", docs_url: "https://api-docs.deepseek.com/",
      provider_type: "compatible", protocol_mode: "chat_completions", base_url: "https://api.deepseek.com",
      default_model: "deepseek-chat", reasoning_effort: "high",
      available_models: ["deepseek-chat", "deepseek-reasoner"], model_source: "recommended",
      local_only: false, has_api_key: false, credential_source: "none", supports_api_key: true,
      requires_api_key: true, is_active: false, capabilities: { supports_model_listing: true },
    }] });
  });
  await page.route("**/api/providers/deepseek", async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    const payload = route.request().postDataJSON() as { api_key?: string; default_model?: string };
    if (payload.api_key) savedKey = payload.api_key;
    return route.fulfill({ json: {
      id: "deepseek", preset_id: "deepseek", display_name: "DeepSeek", description: "官方 API",
      provider_type: "compatible", protocol_mode: "chat_completions", base_url: "https://api.deepseek.com",
      default_model: payload.default_model || "deepseek-chat", reasoning_effort: "high",
      available_models: ["deepseek-chat", "deepseek-reasoner"], model_source: "provider",
      local_only: false, has_api_key: true, credential_source: "system", supports_api_key: true,
      requires_api_key: true, is_active: false, capabilities: { supports_model_listing: true },
    } });
  });
  await page.route("**/api/providers/deepseek/models", (route) => {
    modelsRequested += 1;
    return route.fulfill({ json: { models: ["deepseek-chat", "deepseek-reasoner"], source: "provider", fetched: 2, default_model: "deepseek-chat" } });
  });
  await page.route("**/api/providers/deepseek/test", (route) => {
    tested += 1;
    return route.fulfill({ json: { status: "connected" } });
  });
  await page.route("**/api/providers/deepseek/activate", (route) => {
    activated += 1;
    return route.fulfill({ json: {} });
  });

  await page.goto("/settings/providers");
  await page.getByRole("button", { name: /DeepSeek/ }).click();
  await page.locator('input[type="password"]').fill("sk-test-for-e2e-only");
  await page.getByRole("button", { name: "保存并测试" }).click();

  await expect(page.getByText("连接成功，已设为当前供应商。")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByLabel("模型", { exact: true })).toHaveValue("deepseek-chat");
  await expect(page.getByRole("link", { name: /下一步：配置五个席位/ })).toHaveAttribute("href", "/settings/agents");
  expect(savedKey).toBe("sk-test-for-e2e-only");
  expect(modelsRequested).toBe(1);
  expect(tested).toBe(1);
  expect(activated).toBe(1);
});

test("四席依次辩论并在用户确认后给出最终答案", async ({ page, request }) => {
  const run = await createMockRoundtable(request);
  try {
    await page.goto(`/runs/${run.id}`);
    await expect(page.locator(".council-seat")).toHaveCount(4);
    await expect(page.getByText("4 席顺序调用", { exact: true })).toBeVisible();
    await expect(page.getByText("各席独立配置", { exact: true })).toBeVisible();
    await expect(page.getByText("公开讨论", { exact: true })).toBeVisible();
    await expect(page.getByText("LangGraph", { exact: true })).toBeVisible();
    await expect(page.getByText(/\d+ 个检查点/)).toBeVisible();
    await expect(page.getByText(/上下文 \d+ \/ \d+/)).toBeVisible();
    await expect(page.getByText(/上游累计 [\d,]+ \/ [\d,]+/)).toBeVisible();
    await expect(page.locator(".discussion-turn.agent")).toHaveCount(4, { timeout: 10_000 });
    await expect(page.locator(".council-session")).toContainText("等待你的确认");
    await expect(page.getByPlaceholder("最终答案生成前，我还想补充…")).toBeEnabled();
    await page.getByPlaceholder("最终答案生成前，我还想补充…").fill("最终答案还要考虑回滚窗口");
    await page.getByRole("button", { name: "加入最终补充" }).click();
    await expect(page.getByText("最终答案还要考虑回滚窗口", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "生成最终答案" }).click();
    await expect(page.getByText("圆桌最终答案")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".council-seat.completed")).toHaveCount(4);
    await expect(page.locator(".summary-node.completed")).toHaveCount(1);
    await expect(page.getByText("第 5 次调用", { exact: false }).first()).toBeVisible();
    await expect(page.locator(".discussion-turn.agent").nth(0)).toContainText("析理");
    await expect(page.locator(".discussion-turn.agent").nth(1)).toContainText("诘问");
    await expect(page.locator(".discussion-turn.agent").nth(2)).toContainText("构策");
    await expect(page.locator(".discussion-turn.agent").nth(3)).toContainText("观澜");
    await page.getByRole("button", { name: "结果回访" }).click();
    await page.getByLabel("预期结果").fill("两周内验证回滚方案");
    await page.getByLabel("结果状态").selectOption("partial");
    await page.getByLabel("实际发生了什么").fill("回滚方案通过了演练");
    await page.getByRole("button", { name: "保存回访" }).click();
    await expect(page.getByRole("button", { name: "编辑回访" })).toBeVisible();
    const saved = await (await request.get(`${backendUrl}/api/runs/${run.id}`)).json() as { decision_review?: { expected_result: string; outcome_status: string } };
    expect(saved.decision_review).toMatchObject({ expected_result: "两周内验证回滚方案", outcome_status: "partial" });
  } finally {
    await request.delete(`${backendUrl}/api/runs/${run.id}`);
  }
});

test("Token 限额与上下文分开显示，并可提额续跑", async ({ page }) => {
  const stoppedRun = {
    id: "token-limit-fixture",
    question: "为什么第三席之后停止？",
    mode: "standard",
    provider_id: "ccswitch",
    model: "test-reasoning-model",
    reasoning_effort: "high",
    status: "stopped",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    analysis: null,
    candidates: [], critiques: [], verifications: [], revisions: [], scores: [],
    final_decision: null,
    usage: { model_calls: 3, tool_calls: 0, input_tokens: 14803, output_tokens: 588, estimated_cost: null, duration_ms: 32338 },
    error: "已达到 Token 上限（12000），未继续请求下一席。",
    degraded: false,
    protocol: "responses",
    workflow_engine: "langgraph",
    checkpoint_count: 3,
    context_snapshot: { strategy: "deterministic_context_clipping", token_budget: 4000, estimated_tokens: 630, included_turns: 3, total_turns: 3, compacted: false, summary: "" },
    limits: { max_model_calls: 8, max_tokens: 12000, timeout_seconds: 120 },
    discussion_turns: [],
    participant_roles: [
      { id: "analyst", name: "析理", role: "拆解者", brief: "拆解问题" },
      { id: "challenger", name: "诘问", role: "挑战者", brief: "寻找反例" },
      { id: "builder", name: "构策", role: "方案师", brief: "提出方案" },
      { id: "observer", name: "观澜", role: "观察者", brief: "观察分歧" },
    ],
    seat_assignments: [],
    finalizer_assignment: null,
    current_speaker_index: 3,
    discussion_round: 1,
    awaiting_user: false,
    auto_summarize: false,
    recoverable: false,
    limit_reason: "max_tokens",
  };
  let resumePayload: Record<string, number> | null = null;
  await page.route("**/api/runs/token-limit-fixture", (route) => route.fulfill({ json: stoppedRun }));
  await page.route("**/api/runs/token-limit-fixture/resume", async (route) => {
    resumePayload = route.request().postDataJSON() as Record<string, number>;
    return route.fulfill({ json: { ...stoppedRun, status: "running", error: null, limit_reason: null, limits: resumePayload } });
  });

  await page.goto("/runs/token-limit-fixture");
  await expect(page.getByText("上下文 630 / 4000", { exact: true })).toBeVisible();
  await expect(page.getByText("上游累计 15,391 / 12,000", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "提高到 40,000 Token 并继续" }).click();
  expect(resumePayload).toEqual({ max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 });
});

test("五个席位配置可保存且明确 Provider 能力", async ({ page, request }) => {
  const response = await request.get(`${backendUrl}/api/agent-assignments`);
  const original = await response.json();
  try {
    await page.goto("/settings/agents");
    await expect(page.getByLabel("析理 Provider")).toBeVisible();
    await expect(page.getByLabel("总结席 模型")).toBeVisible();
    await page.getByLabel("析理 Provider").selectOption("mock");
    await page.getByRole("button", { name: "保存席位" }).click();
    await expect(page.getByText(/席位配置已保存，但仍包含本地演示席或未就绪 Provider/)).toBeVisible();
    await expect(page.getByRole("link", { name: /完成，开始提问/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "保存席位" })).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("析理 Provider")).toHaveValue("mock");
    await expect(page.getByText(/仅工作流档位/).first()).toBeVisible();
  } finally {
    await request.put(`${backendUrl}/api/agent-assignments`, { data: original });
  }
});

test("五个真实 AI 席位就绪后才显示完成入口", async ({ page }) => {
  const readyAssignments = assignments("deepseek");
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider, readyProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: readyAssignments }));
  await page.goto("/settings/agents");

  await page.getByRole("button", { name: "保存席位" }).click();
  await expect(page.getByText(/五个真实 AI 席位已保存/)).toBeVisible();
  await expect(page.getByRole("link", { name: /完成，开始提问/ })).toHaveAttribute("href", "/");
});

test("评测页没有硬编码模型调用成绩", async ({ page }) => {
  await page.goto("/evaluations");
  await expect(page.getByText("暂无真实评测数据")).toBeVisible();
  const averageCalls = page.locator(".eval-row").filter({ hasText: "平均模型调用" });
  await expect(averageCalls.locator(".muted-cell")).toHaveCount(3);
  for (const cell of await averageCalls.locator(".muted-cell").all()) await expect(cell).toHaveText("—");
});

test("移动端圆桌固定一屏，内部消息区滚动", async ({ page, request }) => {
  const run = await createMockRoundtable(request);
  try {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/runs/${run.id}`);
    await expect(page.locator(".discussion-turn.agent")).toHaveCount(4, { timeout: 10_000 });
    const metrics = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
      height: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      dialogueScrollable: document.querySelector(".dialogue-scroll")!.scrollHeight >= document.querySelector(".dialogue-scroll")!.clientHeight,
    }));
    expect(metrics.width).toBeLessThanOrEqual(metrics.viewportWidth);
    expect(metrics.height).toBeLessThanOrEqual(metrics.viewportHeight);
    expect(metrics.dialogueScrollable).toBeTruthy();
  } finally {
    await request.delete(`${backendUrl}/api/runs/${run.id}`);
  }
});

test("席位失败时明确显示原因并允许从当前席位重试", async ({ page }) => {
  const failedRun = {
    id: "failed-fixture",
    question: "我想睡觉",
    mode: "standard",
    provider_id: "ccswitch",
    model: "test-reasoning-model",
    reasoning_effort: "high",
    status: "failed",
    created_at: new Date(Date.now() - 130_000).toISOString(),
    updated_at: new Date().toISOString(),
    analysis: null,
    candidates: [], critiques: [], verifications: [], revisions: [], scores: [],
    final_decision: null,
    usage: { model_calls: 1, tool_calls: 0, input_tokens: 100, output_tokens: 50, estimated_cost: null, duration_ms: 120_000 },
    error: "当前席位等待上游超过 120 秒，CC Switch 未能在时限内返回结果。请重试当前席位。",
    degraded: true,
    protocol: "auto",
    discussion_turns: [{ id: "analyst-turn", speaker_type: "agent", speaker_id: "analyst", speaker_name: "析理", role_label: "拆解者", content: "第一席已经完成。", round: 1, created_at: new Date().toISOString() }],
    participant_roles: [
      { id: "analyst", name: "析理", role: "拆解者", brief: "拆解问题" },
      { id: "challenger", name: "诘问", role: "挑战者", brief: "寻找反例" },
      { id: "builder", name: "构策", role: "方案师", brief: "提出方案" },
      { id: "observer", name: "观澜", role: "观察者", brief: "观察分歧" },
    ],
    current_speaker_index: 1,
    discussion_round: 1,
    awaiting_user: false,
  };
  let retryRequested = false;
  await page.route("**/api/runs/failed-fixture", (route) => route.fulfill({ json: failedRun }));
  await page.route("**/api/runs/failed-fixture/retry-turn", (route) => {
    retryRequested = true;
    return route.fulfill({ json: { ...failedRun, status: "running", error: null, updated_at: new Date().toISOString() } });
  });

  await page.goto("/runs/failed-fixture");
  await expect(page.getByText("调用失败", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/等待上游超过 120 秒/)).toBeVisible();
  await expect(page.locator(".council-seat.failed")).toContainText("诘问");
  await page.getByRole("button", { name: "重试诘问" }).click();
  expect(retryRequested).toBeTruthy();
});

test("CC Switch 长时间等待时显示路由边界并允许重试当前席位", async ({ page }) => {
  const waitingSince = new Date(Date.now() - 48_000).toISOString();
  const waitingRun = {
    id: "waiting-fixture",
    question: "测试上游等待状态",
    mode: "standard",
    provider_id: "ccswitch",
    model: "test-reasoning-model",
    reasoning_effort: "high",
    status: "running",
    created_at: waitingSince,
    updated_at: waitingSince,
    analysis: null,
    candidates: [], critiques: [], verifications: [], revisions: [], scores: [],
    final_decision: null,
    usage: { model_calls: 0, tool_calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost: null, duration_ms: 0 },
    error: null,
    degraded: false,
    protocol: "auto",
    discussion_turns: [],
    participant_roles: [
      { id: "analyst", name: "析理", role: "拆解者", brief: "拆解问题" },
      { id: "challenger", name: "诘问", role: "挑战者", brief: "寻找反例" },
      { id: "builder", name: "构策", role: "方案师", brief: "提出方案" },
      { id: "observer", name: "观澜", role: "观察者", brief: "观察分歧" },
    ],
    current_speaker_index: 0,
    discussion_round: 1,
    awaiting_user: false,
  };
  let retryRequested = false;
  let interjectionRequested = false;

  await page.route("**/api/runs/waiting-fixture", (route) => route.fulfill({ json: waitingRun }));
  await page.route("**/api/runs/waiting-fixture/interject", async (route) => {
    interjectionRequested = true;
    const payload = route.request().postDataJSON() as { message: string };
    return route.fulfill({ json: { ...waitingRun, discussion_turns: [{ id: "user-turn", speaker_type: "user", speaker_id: "user", speaker_name: "你", role_label: "参与者", content: payload.message, round: 1, created_at: new Date().toISOString() }] } });
  });
  await page.route("**/api/runs/waiting-fixture/retry-turn", (route) => {
    retryRequested = true;
    return route.fulfill({ json: { ...waitingRun, updated_at: new Date().toISOString() } });
  });
  await page.goto("/runs/waiting-fixture");

  await expect(page.getByText("全程可插话", { exact: true })).toBeVisible();
  await expect(page.getByPlaceholder("我想补充 / 反驳 / 改变讨论方向…")).toBeEnabled();
  await page.getByPlaceholder("我想补充 / 反驳 / 改变讨论方向…").fill("这是我的中途观点");
  await page.getByRole("button", { name: "加入讨论" }).click();
  await expect(page.getByText("这是我的中途观点", { exact: true })).toBeVisible();
  expect(interjectionRequested).toBeTruthy();
  await expect(page.getByText("正在等待 CC Switch 返回上游响应")).toBeVisible();
  await expect(page.getByText(/若已配置故障转移，将由它处理/)).toBeVisible();
  await expect(page.getByText(/已等待 \d+ 秒/)).toBeVisible();
  await expect(page.getByRole("button", { name: "继续等待" })).toBeVisible();
  await page.getByRole("button", { name: "重试本席" }).click();
  expect(retryRequested).toBeTruthy();
});

test("手机连接页生成配对码并适配窄屏", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/mobile-access/info", (route) => route.fulfill({
    json: {
      enabled: true,
      lanAddress: "192.168.1.20",
      origin: "http://192.168.1.20:3000",
      pairUrl: "http://192.168.1.20:3000/pair#mobile:mobile-test-token",
    },
  }));

  await page.goto("/settings/mobile");
  await expect(page.getByRole("heading", { name: "把这一席带到手机上。" })).toBeVisible();
  await expect(page.getByText("192.168.1.20", { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: "Council 手机配对二维码" })).toBeVisible();
  await expect(page.getByRole("button", { name: /复制配对链接/ })).toBeEnabled();

  const metrics = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    qrWidth: document.querySelector<HTMLImageElement>(".qr-stage img")?.getBoundingClientRect().width || 0,
  }));
  expect(metrics.width).toBeLessThanOrEqual(metrics.viewportWidth);
  expect(metrics.qrWidth).toBeGreaterThanOrEqual(200);
});
