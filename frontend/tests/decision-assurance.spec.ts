import { expect, test } from "@playwright/test";

const now = new Date().toISOString();
const mockProvider = { id: "mock", preset_id: "mock", display_name: "本地演示", description: "不联网", provider_type: "mock", protocol_mode: "auto", base_url: "", has_api_key: false, credential_source: "none", supports_api_key: false, requires_api_key: false, enabled: true, is_active: true, default_model: "council-mock", reasoning_effort: "low", timeout_seconds: 30, available_models: ["council-mock"], model_source: "built_in", local_only: true, last_health_check: null, last_error: null, capabilities: {} };
const assignment = (role: string) => ({ role, provider_id: "mock", model: "council-mock", protocol: "auto", reasoning_effort: "low", max_output_tokens: 1200, temperature: 0.2, timeout_seconds: 30 });
const assignments = { schema_version: 2, seats: ["analyst", "challenger", "builder", "observer"].map(assignment), finalizer: assignment("finalizer") };
const templates = [{ id: "open_discussion", name: "开放讨论", description: "依次讨论", prompt_hint: "写下需要四席共同审议的问题", system_guidance: "" }];

test("准备度不足时先显示缺口，用户明确覆盖后才创建 Run", async ({ page }) => {
  let createPayload: Record<string, unknown> | null = null;
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.route("**/api/memory", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/memory/preview", (route) => route.fulfill({ json: { workspace_id: "local-default", selected_memory_ids: [], included: [], excluded_memory_ids: [], rendered_context: "" } }));
  await page.route("**/api/readiness", (route) => route.fulfill({ json: { ready: false, task_labels: ["decision", "high_risk"], checks: [{ id: "critical_facts_available", status: "fail", message: "高风险问题仍需在控制面逐项确认关键事实。" }], clarification_questions: ["高风险问题仍需在控制面逐项确认关键事实。"], recommended_mode: "high_risk_council", rules_version: "decision-readiness-v1" } }));
  await page.route("**/api/runs", (route) => { createPayload = route.request().postDataJSON(); return route.fulfill({ json: { id: "readiness-child" } }); });
  await page.goto("/");
  await page.getByRole("button", { name: "仅体验本地演示" }).click();
  await page.getByPlaceholder("写下需要四席共同审议的问题").fill("是否投资？");
  await page.getByRole("button", { name: /进入圆桌/ }).click();
  const panel = page.getByRole("region", { name: "决策准备度" });
  await expect(panel).toContainText("开始前还有信息缺口");
  expect(createPayload).toBeNull();
  await panel.getByRole("button", { name: "仍然继续" }).click();
  await page.waitForURL("**/runs/readiness-child");
  expect(createPayload).toMatchObject({ readiness_override: true, readiness_override_reason: "用户查看准备度缺口后选择继续" });
});

test("关键主张显示来源标签，回访后只通过追加结果改变当前状态", async ({ page }) => {
  const usage = { model_calls: 5, tool_calls: 0, input_tokens: 100, output_tokens: 30, estimated_cost: null, duration_ms: 100 };
  const run = { id: "claim-ui", question: "是否发布？", mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "high", status: "completed", created_at: now, updated_at: now, analysis: null, readiness: null, candidates: [], critiques: [], verifications: [], revisions: [], scores: [], final_decision: { final_answer: "先灰度。", key_reasons: [], verified_claims: [], partially_verified_claims: [], contradicted_claims: [], unverified_claims: [], disagreements: [], risks_and_limitations: [], confidence: { level: "unverified", explanation: "未核验" }, sources: [], provider_summary: { provider: "Mock", protocol: "mock", model: "council-mock", used_ccswitch: false, degraded: false }, usage }, usage, degraded: false, protocol: "mock", workflow_engine: "langgraph", checkpoint_count: 2, context_snapshot: { strategy: "deterministic_context_clipping", token_budget: 4000, estimated_tokens: 10, included_turns: 0, total_turns: 0, compacted: false, summary: "" }, limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, discussion_turns: [], participant_roles: [{ id: "analyst", name: "析理", role: "拆解者", brief: "拆解" }], seat_assignments: [], finalizer_assignment: null, current_speaker_index: 1, discussion_round: 1, awaiting_user: false, auto_summarize: false, high_risk_control: false, recoverable: false };
  const brief = { id: "brief-claim", run_id: run.id, version: 1, schema_version: 1, generated_at: now, generation_reason: "run_completed", status: "conditional", recommendation: "先灰度。", support: "majority", decisive_reasons: [], rejected_alternatives: [], unresolved: [], assumptions: [], actions: [], reopen_triggers: [], minority_report: null, limitations: ["未核验"] };
  const claim = { id: "claim-1", run_id: run.id, text: "灰度会降低一次性风险", basis: "model_inference", source_seat_ids: ["analyst"], related_entity_ids: [], citation: null, dispute_summary: null, created_at: now };
  let reviewed = false;
  await page.route("**/api/runs/claim-ui", (route) => route.fulfill({ json: { ...run, ...(reviewed ? { decision_review: { selected_decision: "灰度", expected_result: "降低风险", actual_result: "结果反驳", outcome_status: "unsuccessful", seat_outcomes: [], updated_at: now } } : {}) } }));
  await page.route("**/api/runs/claim-ui/decision-brief", (route) => route.fulfill({ json: brief }));
  await page.route("**/api/runs/claim-ui/lineage", (route) => route.fulfill({ json: { parent: null, children: [] } }));
  await page.route("**/api/runs/claim-ui/memory-proposals", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/runs/claim-ui/claims", (route) => route.fulfill({ json: [{ claim, current_basis: reviewed ? "outcome_contradicted" : "model_inference", latest_outcome: reviewed ? { result: "contradicted", note: "结果反驳" } : null }] }));
  await page.route("**/api/runs/claim-ui/decision-review", (route) => { reviewed = true; return route.fulfill({ json: { ...run, decision_review: { ...route.request().postDataJSON(), updated_at: now } } }); });
  await page.goto("/runs/claim-ui");
  const claims = page.getByRole("article", { name: "关键主张与依据" });
  await expect(claims).toContainText("模型推断", { timeout: 10_000 });
  await page.getByRole("button", { name: "结果回访" }).click();
  await page.getByLabel("最终采用的决定").fill("灰度");
  await page.getByLabel("预期结果").fill("降低风险");
  await page.getByLabel("结果状态").selectOption("unsuccessful");
  await page.getByLabel("实际发生了什么").fill("结果反驳");
  await page.getByRole("button", { name: "保存回访" }).click();
  await expect(claims).toContainText("后续结果反驳", { timeout: 10_000 });
});
