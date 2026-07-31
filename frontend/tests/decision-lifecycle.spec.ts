import { expect, test } from "@playwright/test";

const now = new Date().toISOString();
const usage = { model_calls: 3, tool_calls: 0, input_tokens: 100, output_tokens: 30, estimated_cost: null, duration_ms: 100 };
const participants = [
  { id: "analyst", name: "析理", role: "拆解者", brief: "拆解" },
  { id: "challenger", name: "诘问", role: "挑战者", brief: "反例" },
];

function completedRun(id: string, question: string, reused = false) {
  return {
    id, question, mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "high",
    status: "completed", created_at: now, updated_at: now, analysis: null, candidates: [], critiques: [], verifications: [], revisions: [], scores: [],
    final_decision: { final_answer: id === "fork-child" ? "先做 14 天试点。" : "直接灰度发布。", key_reasons: [], verified_claims: [], partially_verified_claims: [], contradicted_claims: [], unverified_claims: ["需求未核验"], disagreements: [], risks_and_limitations: ["未外部核验"], confidence: { level: "unverified", explanation: "无百分比" }, sources: [], provider_summary: { provider: "Mock", protocol: "mock", model: "council-mock", used_ccswitch: false, degraded: false }, usage },
    usage, degraded: false, protocol: "mock", workflow_engine: "langgraph", checkpoint_count: 3,
    context_snapshot: { strategy: "deterministic_context_clipping", token_budget: 4000, estimated_tokens: 200, included_turns: 2, total_turns: 2, compacted: false, summary: "" },
    limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 },
    discussion_turns: participants.map((seat, index) => ({ id: `turn-${index + 1}`, speaker_type: "agent", speaker_id: seat.id, speaker_name: seat.name, role_label: seat.role, content: `${seat.name}意见`, round: 1, reused_from_run_id: reused && index === 0 ? "fork-parent" : null, created_at: now })),
    participant_roles: participants, seat_assignments: [], finalizer_assignment: null, current_speaker_index: 2, discussion_round: 1, awaiting_user: false, auto_summarize: false, high_risk_control: false, recoverable: false,
  };
}

function brief(runId: string, recommendation: string) {
  return { id: `brief-${runId}`, run_id: runId, version: 1, schema_version: 1, generated_at: now, generation_reason: "run_completed", status: "conditional", recommendation, support: "majority", decisive_reasons: [], rejected_alternatives: [], unresolved: [], assumptions: [], actions: [], reopen_triggers: [], minority_report: null, limitations: ["未经过外部事实核验。"] };
}

test("完成 Run 可创建不可变分叉并在子 Run 比较结果", async ({ page }) => {
  const parent = completedRun("fork-parent", "是否应该直接发布？");
  const child = completedRun("fork-child", "是否应该直接发布？\n\n新增情景约束：预算减半。", true);
  const parentBrief = brief(parent.id, "直接灰度发布。");
  const childBrief = brief(child.id, "先做 14 天试点。");
  const fork = { id: "fork-record", parent_run_id: parent.id, child_run_id: child.id, checkpoint: "after_seat_1", reason: "预算减半后重新评估", changed_inputs: {}, reused_turn_ids: ["turn-1"], regenerated_seat_ids: ["challenger"], approval_inherited: false, created_at: now };
  let forkPayload: Record<string, unknown> | null = null;
  let actor = "";

  await page.route("**/api/runs/fork-parent", (route) => route.fulfill({ json: parent }));
  await page.route("**/api/runs/fork-child", (route) => route.fulfill({ json: child }));
  await page.route("**/api/runs/fork-parent/decision-brief", (route) => route.fulfill({ json: parentBrief }));
  await page.route("**/api/runs/fork-child/decision-brief", (route) => route.fulfill({ json: childBrief }));
  await page.route("**/api/runs/fork-parent/lineage", (route) => route.fulfill({ json: { parent: null, children: [] } }));
  await page.route("**/api/runs/fork-child/lineage", (route) => route.fulfill({ json: { parent: fork, children: [] } }));
  await page.route("**/api/runs/compare?*", (route) => route.fulfill({ json: { left_run_id: parent.id, right_run_id: child.id, related: true, left: parentBrief, right: childBrief, changed_fields: ["recommendation"], status_changed: false, recommendation_changed: true, support_changed: false, unresolved_added: [], unresolved_removed: [] } }));
  await page.route("**/api/runs/fork-parent/fork", (route) => {
    forkPayload = route.request().postDataJSON();
    actor = route.request().headers()["x-council-actor"] || "";
    expect(route.request().headers()["idempotency-key"]).toBeTruthy();
    return route.fulfill({ json: child });
  });

  await page.goto("/runs/fork-parent");
  await page.getByRole("button", { name: "创建情景分叉" }).click();
  await page.getByLabel("分叉检查点").selectOption("after_seat_1");
  await page.getByLabel("分叉原因").fill("预算减半后重新评估");
  await page.getByLabel("新增情景约束").fill("预算减半。");
  await page.getByRole("button", { name: "创建新 Run" }).click();

  await page.waitForURL("**/runs/fork-child");
  expect(forkPayload).toMatchObject({ checkpoint: "after_seat_1", reason: "预算减半后重新评估", prompt_append: "预算减半。" });
  expect(actor).toBe("local-requester");
  await expect(page.getByText("复用父 Run")).toBeVisible();
  const comparison = page.getByRole("article", { name: "父子 Run 结果比较" });
  await expect(comparison).toContainText("直接灰度发布");
  await expect(comparison).toContainText("先做 14 天试点");
  await expect(page.getByRole("link", { name: "父 Run" })).toHaveAttribute("href", "/runs/fork-parent");
});
