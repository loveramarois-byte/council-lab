import { expect, test } from "@playwright/test";

const now = new Date().toISOString();
const usage = { model_calls: 5, tool_calls: 0, input_tokens: 100, output_tokens: 30, estimated_cost: null, duration_ms: 100 };
const participants = [{ id: "analyst", name: "析理", role: "拆解者", brief: "拆解" }];
const run = {
  id: "memory-source", question: "是否先灰度发布？", mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "high",
  status: "completed", created_at: now, updated_at: now, analysis: null, candidates: [], critiques: [], verifications: [], revisions: [], scores: [],
  final_decision: { final_answer: "先灰度两周。", key_reasons: [], verified_claims: [], partially_verified_claims: [], contradicted_claims: [], unverified_claims: [], disagreements: [], risks_and_limitations: [], confidence: { level: "unverified", explanation: "未外部核验" }, sources: [], provider_summary: { provider: "Mock", protocol: "mock", model: "council-mock", used_ccswitch: false, degraded: false }, usage },
  usage, degraded: false, protocol: "mock", workflow_engine: "langgraph", checkpoint_count: 2,
  context_snapshot: { strategy: "deterministic_context_clipping", token_budget: 4000, estimated_tokens: 200, included_turns: 1, total_turns: 1, compacted: false, summary: "" },
  limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, discussion_turns: [], participant_roles: participants, seat_assignments: [], finalizer_assignment: null, current_speaker_index: 1, discussion_round: 1, awaiting_user: false, auto_summarize: false, high_risk_control: false, recoverable: false, memory_snapshot: [],
};
const brief = { id: "brief-memory", run_id: run.id, version: 1, schema_version: 1, generated_at: now, generation_reason: "run_completed", status: "conditional", recommendation: "先灰度两周。", support: "majority", decisive_reasons: [], rejected_alternatives: [], unresolved: [], assumptions: [], actions: [], reopen_triggers: [], minority_report: null, limitations: ["未经过外部事实核验。"] };
const proposal = { id: "proposal-memory", workspace_id: "local-default", source_run_id: run.id, type: "decision", content: "先灰度两周。", rationale: "结构化简报中的当前建议", related_entity_ids: [], created_at: now };
const memory = { id: "memory-approved", workspace_id: "local-default", source_run_id: run.id, proposal_id: proposal.id, type: "decision", content: "必须支持五分钟回滚才灰度。", verification_status: "unverified", valid_from: now, valid_until: null, supersedes_memory_id: null, created_at: now };
const memoryView = { memory, active: true, deleted: false, last_action: "approved", last_action_at: now };
const mockProvider = { id: "mock", preset_id: "mock", display_name: "本地演示", description: "不联网", provider_type: "mock", protocol_mode: "auto", base_url: "", has_api_key: false, credential_source: "none", supports_api_key: false, requires_api_key: false, enabled: true, is_active: true, default_model: "council-mock", reasoning_effort: "low", timeout_seconds: 30, available_models: ["council-mock"], model_source: "built_in", local_only: true, last_health_check: null, last_error: null, capabilities: {} };
const assignment = (role: string) => ({ role, provider_id: "mock", model: "council-mock", protocol: "auto", reasoning_effort: "low", max_output_tokens: 1200, temperature: 0.2, timeout_seconds: 30 });

test("用户批准记忆后可在新 Run 前预览并明确选择注入", async ({ page }) => {
  let approved = false;
  let createPayload: Record<string, unknown> | null = null;
  await page.route("**/api/runs/memory-source", (route) => route.fulfill({ json: run }));
  await page.route("**/api/runs/memory-source/decision-brief", (route) => route.fulfill({ json: brief }));
  await page.route("**/api/runs/memory-source/lineage", (route) => route.fulfill({ json: { parent: null, children: [] } }));
  await page.route("**/api/runs/memory-source/memory-proposals", (route) => route.fulfill({ json: approved ? [{ proposal, status: "approved", memory_id: memory.id, reviewed_at: now }] : route.request().method() === "POST" ? [{ proposal, status: "pending" }] : [] }));
  await page.route("**/api/memory/proposals/proposal-memory/approve", (route) => {
    expect(route.request().postDataJSON()).toEqual({ content: "必须支持五分钟回滚才灰度。" });
    approved = true;
    return route.fulfill({ json: memoryView });
  });
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: { schema_version: 2, seats: ["analyst", "challenger", "builder", "observer"].map(assignment), finalizer: assignment("finalizer") } }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: [{ id: "open_discussion", name: "开放讨论", description: "依次讨论", prompt_hint: "写下需要四席共同审议的问题", system_guidance: "" }] }));
  await page.route("**/api/readiness", (route) => route.fulfill({
    json: {
      ready: true,
      task_labels: ["decision"],
      checks: [],
      clarification_questions: [],
      recommended_mode: "full_council",
    },
  }));
  await page.route("**/api/memory", (route) => route.fulfill({ json: approved ? [memoryView] : [] }));
  await page.route("**/api/memory/preview", (route) => {
    const ids = route.request().postDataJSON().selected_memory_ids as string[];
    return route.fulfill({ json: { workspace_id: "local-default", selected_memory_ids: ids, included: ids.length ? [{ memory_id: memory.id, source_run_id: run.id, type: memory.type, content: memory.content, verification_status: "unverified" }] : [], excluded_memory_ids: [], rendered_context: ids.length ? `[已批准的历史决策]\n- ${memory.content}` : "" } });
  });
  await page.route("**/api/runs", (route) => { createPayload = route.request().postDataJSON(); return route.fulfill({ json: { id: "memory-child" } }); });

  await page.goto("/runs/memory-source");
  await page.getByRole("button", { name: "沉淀记忆" }).click();
  const dialog = page.getByRole("dialog", { name: "沉淀长期记忆" });
  await dialog.getByLabel("记忆候选 decision").fill("必须支持五分钟回滚才灰度。");
  await dialog.getByRole("button", { name: "批准此条" }).click();
  await expect(dialog.getByText("已批准")).toBeVisible();
  await dialog.getByRole("button", { name: "关闭长期记忆" }).click();

  await page.goto("/");
  await page.getByRole("button", { name: "仅体验本地演示" }).click();
  const picker = page.getByRole("region", { name: "本次使用的已批准记忆" });
  await expect(picker).toContainText("默认不注入");
  await picker.getByRole("checkbox").check();
  await picker.getByText("查看实际注入快照").click();
  await expect(picker).toContainText("五分钟回滚");
  await page.getByPlaceholder("写下需要四席共同审议的问题").fill("这次是否开始灰度？");
  await page.getByRole("button", { name: /进入圆桌/ }).click();
  await page.waitForURL("**/runs/memory-child");
  expect(createPayload).toMatchObject({ selected_memory_ids: [memory.id] });
});
