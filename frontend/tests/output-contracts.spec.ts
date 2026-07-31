import { expect, test } from "@playwright/test";

const now = new Date().toISOString();
const usage = { model_calls: 5, tool_calls: 0, input_tokens: 100, output_tokens: 50, estimated_cost: null, duration_ms: 1000 };
const providers = [{ id: "mock", display_name: "Mock", provider_type: "mock", base_url: "mock://local", protocol_mode: "mock", default_model: "council-mock", reasoning_effort: "high", timeout_seconds: 60, max_retries: 0, active: true, configured: true, credential_source: "mock", local_only: true }];
const assignments = { schema_version: 1, seats: ["analyst", "challenger", "builder", "observer"].map((role) => ({ role, provider_id: "mock", model: "council-mock", protocol: "mock", reasoning_effort: "high", max_output_tokens: 1200, temperature: 0.2, timeout_seconds: 60 })), finalizer: { role: "finalizer", provider_id: "mock", model: "council-mock", protocol: "mock", reasoning_effort: "high", max_output_tokens: 1600, temperature: 0.2, timeout_seconds: 60 } };
const templates = [{ id: "open_discussion", name: "开放讨论", description: "依次讨论", prompt_hint: "写下问题", system_guidance: "" }];
const contracts = [
  { id: "general_decision", name: "一般决策", description: "比较方案", input_checks: ["目标"], prompt_hint: "通用", system_guidance: "" },
  { id: "product_review", name: "产品评审", description: "用户与验证", input_checks: ["目标用户"], prompt_hint: "产品", system_guidance: "" },
  { id: "technical_architecture", name: "技术架构评审", description: "约束与回滚", input_checks: ["需求"], prompt_hint: "架构", system_guidance: "" },
];

test("selects a product contract and sends it with the new Run", async ({ page }) => {
  let payload: Record<string, unknown> = {};
  await page.route("**/api/providers", (route) => route.fulfill({ json: providers }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.route("**/api/output-contracts", (route) => route.fulfill({ json: contracts }));
  await page.route("**/api/memory", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/memory/preview", (route) => route.fulfill({ json: { workspace_id: "default", selected_memory_ids: [], included: [], excluded_memory_ids: [], rendered_context: "" } }));
  await page.route("**/api/readiness", (route) => route.fulfill({ json: { ready: true, task_labels: ["decision"], checks: [], clarification_questions: [], recommended_mode: "full_council", rules_version: "decision-readiness-v1" } }));
  await page.route("**/api/runs", (route) => { payload = route.request().postDataJSON(); return route.fulfill({ json: { id: "product-contract-run" } }); });
  await page.goto("/");
  await page.getByRole("button", { name: "仅体验本地演示" }).click();
  await page.getByLabel("输出契约").selectOption("product_review");
  await page.getByRole("textbox", { name: "你的问题" }).fill("是否发布这个产品？");
  await page.getByRole("button", { name: "进入圆桌" }).click();
  await page.waitForURL("**/runs/product-contract-run");
  expect(payload.output_contract).toBe("product_review");
});

test("renders the typed product extension on a completed result", async ({ page }) => {
  const run = { id: "contract-result", question: "是否发布产品？", mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "high", output_contract: "product_review", workflow_engine: "langgraph", checkpoint_count: 2, status: "completed", created_at: now, updated_at: now, analysis: null, readiness: null, candidates: [], critiques: [], verifications: [], revisions: [], scores: [], final_decision: { final_answer: "先灰度。", key_reasons: [], verified_claims: [], partially_verified_claims: [], contradicted_claims: [], unverified_claims: [], disagreements: [], risks_and_limitations: [], confidence: { level: "unverified", explanation: "未核验" }, sources: [], provider_summary: { provider: "Mock", protocol: "mock", model: "council-mock", used_ccswitch: false, degraded: false }, usage }, usage, degraded: false, protocol: "mock", context_snapshot: { strategy: "deterministic_context_clipping", token_budget: 4000, estimated_tokens: 10, included_turns: 0, total_turns: 0, compacted: false, summary: "" }, limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, discussion_turns: [], participant_roles: [{ id: "analyst", name: "析理", role: "拆解者", brief: "拆解" }], seat_assignments: [], finalizer_assignment: null, current_speaker_index: 1, discussion_round: 1, awaiting_user: false, auto_summarize: false, high_risk_control: false, recoverable: false };
  const brief = { id: "brief-contract", run_id: run.id, version: 1, schema_version: 2, generated_at: now, generation_reason: "run_completed", status: "conditional", recommendation: "先灰度。", support: "majority", output_contract: "product_review", decisive_reasons: [], rejected_alternatives: [], unresolved: [], assumptions: [], actions: [], reopen_triggers: [], minority_report: null, limitations: ["未核验"], contract_extension: { contract: "product_review", target_users: ["个人开发者"], user_problem: "发布风险", value_proposition: "更安全地发布", failure_conditions: ["留存未改善"], validation_experiments: [{ hypothesis: "灰度可降低风险", method: "10% 用户灰度", success_threshold: "错误率不升高" }], stop_conditions: ["错误率上升"] } };
  await page.route("**/api/runs/contract-result", (route) => route.fulfill({ json: run }));
  await page.route("**/api/runs/contract-result/decision-brief", (route) => route.fulfill({ json: brief }));
  await page.route("**/api/runs/contract-result/claims", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/runs/contract-result/lineage", (route) => route.fulfill({ json: { parent: null, children: [] } }));
  await page.goto("/runs/contract-result");
  const extension = page.getByRole("region", { name: "产品评审契约" });
  await expect(extension).toContainText("个人开发者");
  await expect(extension).toContainText("10% 用户灰度");
  await expect(extension).toContainText("错误率上升");
});
