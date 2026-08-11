import { expect, test } from "@playwright/test";

const now = new Date().toISOString();
const usage = { model_calls: 1, tool_calls: 0, input_tokens: 20, output_tokens: 10, estimated_cost: null, duration_ms: 100 };

test("native shell uses focus mode without WebKit element fullscreen", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.addInitScript(() => {
    (window as Window & { __COUNCIL_NATIVE__?: boolean }).__COUNCIL_NATIVE__ = true;
    Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
    Object.defineProperty(Element.prototype, "requestFullscreen", {
      configurable: true,
      value: () => {
        const state = window as Window & { __fullscreenRequests?: number };
        state.__fullscreenRequests = (state.__fullscreenRequests || 0) + 1;
        return Promise.resolve();
      },
    });
    (window as Window & { __immersiveStates?: boolean[] }).__immersiveStates = [];
    window.addEventListener("council:immersive-change", ((event: CustomEvent<{ active: boolean }>) => {
      (window as Window & { __immersiveStates?: boolean[] }).__immersiveStates?.push(event.detail.active);
    }) as EventListener);
  });

  const run = {
    id: "native-immersive",
    question: "扩大讨论区时怎样保持内容完整？",
    mode: "standard",
    provider_id: "mock",
    model: "council-mock",
    reasoning_effort: "high",
    status: "completed",
    created_at: now,
    updated_at: now,
    analysis: null,
    candidates: [],
    critiques: [],
    verifications: [],
    revisions: [],
    scores: [],
    final_decision: { final_answer: "使用原生焦点模式，不创建 WebKit 元素全屏窗口。", usage },
    usage,
    degraded: false,
    protocol: "mock",
    workflow_engine: "langgraph",
    checkpoint_count: 2,
    context_snapshot: { strategy: "deterministic_context_clipping", token_budget: 4000, estimated_tokens: 20, included_turns: 1, total_turns: 1, compacted: false, summary: "" },
    limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 },
    discussion_turns: [{ id: "turn-1", speaker_type: "agent", speaker_id: "analyst", speaker_name: "析理", role_label: "拆解者", content: "沉浸内容保持在主窗口内。", round: 1, created_at: now }],
    participant_roles: [{ id: "analyst", name: "析理", role: "拆解者", brief: "拆解" }],
    seat_assignments: [],
    finalizer_assignment: null,
    current_speaker_index: 1,
    discussion_round: 1,
    awaiting_user: false,
    auto_summarize: false,
    high_risk_control: false,
    recoverable: false,
  };

  await page.route("**/api/runs/native-immersive", (route) => route.fulfill({ json: run }));
  await page.route("**/api/runs/native-immersive/decision-brief", (route) => route.fulfill({ status: 404, json: { detail: "not found" } }));
  await page.route("**/api/runs/native-immersive/lineage", (route) => route.fulfill({ json: { parent: null, children: [] } }));
  await page.route("**/api/runs/native-immersive/claims", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/runs/native-immersive/memory-proposals", (route) => route.fulfill({ json: [] }));

  await page.goto("/runs/native-immersive");
  await page.getByRole("button", { name: "进入沉浸模式" }).click();

  await expect(page.locator(".council-page")).toHaveClass(/immersive/);
  expect(await page.evaluate(() => (window as Window & { __fullscreenRequests?: number }).__fullscreenRequests || 0)).toBe(0);
  await expect.poll(() => page.evaluate(() => (window as Window & { __immersiveStates?: boolean[] }).__immersiveStates)).toContain(true);

  await page.getByRole("button", { name: "退出沉浸模式" }).click();
  await expect(page.locator(".council-page")).not.toHaveClass(/immersive/);
  await expect.poll(() => page.evaluate(() => (window as Window & { __immersiveStates?: boolean[] }).__immersiveStates)).toContain(false);
  expect(consoleErrors.filter((message) => message.includes("hydrated") || message.includes("Hydration"))).toEqual([]);
});
