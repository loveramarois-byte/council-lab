import { expect, test } from "@playwright/test";

async function createMockRoundtable(request: import("@playwright/test").APIRequestContext) {
  const response = await request.post("http://127.0.0.1:8001/api/runs", {
    data: { question: "数据库迁移应该先讨论哪些风险？", mode: "standard", provider_id: "mock", model: "council-mock" },
  });
  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<{ id: string }>;
}

test("首页明确四席会连续辩论并自动形成答案", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /不是四份答案/ })).toBeVisible();
  await expect(page.getByText("四位 AI 逐个发言、互相回应，第四位结束后自动形成最终答案。")).toBeVisible();
  await expect(page.getByRole("button", { name: /进入圆桌/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /引导.*Low/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /圆桌.*High/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /深挖.*Ultra/ })).toBeVisible();
  await expect(page.locator(".app-shell")).toHaveCSS("display", "flex");
  const stylesheets = await page.locator('link[rel="stylesheet"]').evaluateAll((links) => links.map((link) => (link as HTMLLinkElement).href));
  expect(stylesheets.length).toBeGreaterThan(0);
  for (const stylesheet of stylesheets) {
    const response = await page.request.get(stylesheet);
    expect(response.ok(), `${stylesheet} 应能正常加载`).toBeTruthy();
  }
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
  await expect(page.getByLabel("模型", { exact: true })).toHaveValue("deepseek-v4-flash");
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
  await expect(page.getByRole("button", { name: "保存并测试" })).toBeVisible();
});

test("CC Switch 打开设置后自动识别模型", async ({ page }) => {
  await page.goto("/settings/providers");
  await expect(page.getByText(/已自动识别 \d+ 个可用模型/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByLabel("模型", { exact: true })).not.toHaveValue("");
  expect(await page.getByLabel("模型", { exact: true }).locator("option").count()).toBeGreaterThan(0);
});

test("四位 AI 自动依次辩论并给出最终答案", async ({ page, request }) => {
  const run = await createMockRoundtable(request);
  try {
    await page.goto(`/runs/${run.id}`);
    await expect(page.locator(".council-seat")).toHaveCount(4);
    await expect(page.getByText("4 次独立调用", { exact: true })).toBeVisible();
    await expect(page.getByText("同一模型", { exact: true })).toBeVisible();
    await expect(page.getByText("共享公开记录", { exact: true })).toBeVisible();
    await expect(page.getByText("LangGraph", { exact: true })).toBeVisible();
    await expect(page.getByText(/\d+ 个检查点/)).toBeVisible();
    await expect(page.getByText(/\d+ \/ \d+ Token/)).toBeVisible();
    await expect(page.locator(".council-session")).toContainText("council-mock · high");
    await expect(page.locator(".discussion-turn.agent")).toHaveCount(4, { timeout: 10_000 });
    await expect(page.getByText("圆桌最终答案")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".council-seat.completed")).toHaveCount(4);
    await expect(page.locator(".summary-node.completed")).toHaveCount(1);
    await expect(page.getByText("第 5 次独立调用", { exact: false })).toBeVisible();
    await expect(page.locator(".discussion-turn.agent").nth(0)).toContainText("析理");
    await expect(page.locator(".discussion-turn.agent").nth(1)).toContainText("诘问");
    await expect(page.locator(".discussion-turn.agent").nth(2)).toContainText("构策");
    await expect(page.locator(".discussion-turn.agent").nth(3)).toContainText("观澜");
  } finally {
    await request.delete(`http://127.0.0.1:8001/api/runs/${run.id}`);
  }
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
    await request.delete(`http://127.0.0.1:8001/api/runs/${run.id}`);
  }
});

test("席位失败时明确显示原因并允许从当前席位重试", async ({ page }) => {
  const failedRun = {
    id: "failed-fixture",
    question: "我想睡觉",
    mode: "standard",
    provider_id: "ccswitch",
    model: "gpt-5.6-sol",
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

test("CC Switch 长时间等待时显示故障转移状态并允许重试当前席位", async ({ page }) => {
  const waitingSince = new Date(Date.now() - 48_000).toISOString();
  const waitingRun = {
    id: "waiting-fixture",
    question: "测试上游等待状态",
    mode: "standard",
    provider_id: "ccswitch",
    model: "gpt-5.6-sol",
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
  await expect(page.getByText("CC Switch 正在切换上游")).toBeVisible();
  await expect(page.getByText(/已等待 \d+ 秒/)).toBeVisible();
  await expect(page.getByRole("button", { name: "继续等待" })).toBeVisible();
  await page.getByRole("button", { name: "重试本席" }).click();
  expect(retryRequested).toBeTruthy();
});
