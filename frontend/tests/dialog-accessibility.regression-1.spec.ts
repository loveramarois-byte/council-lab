import { expect, test } from "@playwright/test";

const now = new Date().toISOString();
const usage = { model_calls: 5, tool_calls: 0, input_tokens: 100, output_tokens: 30, estimated_cost: null, duration_ms: 100 };
const run = { id: "dialog-a11y", question: "是否发布？", mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "high", status: "completed", created_at: now, updated_at: now, analysis: null, readiness: null, candidates: [], critiques: [], verifications: [], revisions: [], scores: [], final_decision: { final_answer: "先灰度。", key_reasons: [], verified_claims: [], partially_verified_claims: [], contradicted_claims: [], unverified_claims: [], disagreements: [], risks_and_limitations: [], confidence: { level: "unverified", explanation: "未核验" }, sources: [], provider_summary: { provider: "Mock", protocol: "mock", model: "council-mock", used_ccswitch: false, degraded: false }, usage }, usage, degraded: false, protocol: "mock", workflow_engine: "langgraph", checkpoint_count: 2, context_snapshot: { strategy: "deterministic_context_clipping", token_budget: 4000, estimated_tokens: 10, included_turns: 0, total_turns: 0, compacted: false, summary: "" }, limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, discussion_turns: [], participant_roles: [{ id: "analyst", name: "析理", role: "拆解者", brief: "拆解" }], seat_assignments: [], finalizer_assignment: null, current_speaker_index: 1, discussion_round: 1, awaiting_user: false, auto_summarize: false, high_risk_control: false, recoverable: false };
const brief = { id: "brief-dialog", run_id: run.id, version: 1, schema_version: 1, generated_at: now, generation_reason: "run_completed", status: "conditional", recommendation: "先灰度。", support: "majority", decisive_reasons: [], rejected_alternatives: [], unresolved: [], assumptions: [], actions: [], reopen_triggers: [], minority_report: null, limitations: ["未核验"] };

test("结果回访弹窗捕获焦点、支持 Escape，并把焦点还给触发按钮", async ({ page }) => {
  await page.route("**/api/runs/dialog-a11y", (route) => route.fulfill({ json: run }));
  await page.route("**/api/runs/dialog-a11y/decision-brief", (route) => route.fulfill({ json: brief }));
  await page.route("**/api/runs/dialog-a11y/lineage", (route) => route.fulfill({ json: { parent: null, children: [] } }));
  await page.route("**/api/runs/dialog-a11y/memory-proposals", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/runs/dialog-a11y/claims", (route) => route.fulfill({ json: [] }));

  await page.goto("/runs/dialog-a11y");
  const trigger = page.getByRole("button", { name: "结果回访" });
  await trigger.click();

  const dialog = page.getByRole("dialog", { name: "结果回访" });
  const close = page.getByRole("button", { name: "关闭结果回访" });
  await expect(dialog).toBeVisible();
  await expect(close).toBeFocused();

  await page.getByLabel("最终采用的决定").fill("先灰度");
  await page.getByLabel("预期结果").fill("降低发布风险");
  await close.focus();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "保存回访" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});
