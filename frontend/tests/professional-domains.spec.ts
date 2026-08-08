import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const now = new Date().toISOString();
const usage = { model_calls: 5, tool_calls: 0, input_tokens: 120, output_tokens: 80, estimated_cost: null, duration_ms: 1000 };
const provider = { id: "mock", preset_id: "mock", display_name: "本地演示", description: "不联网", provider_type: "mock", protocol_mode: "auto", base_url: "", has_api_key: false, credential_source: "none", supports_api_key: false, requires_api_key: false, enabled: true, is_active: true, default_model: "council-mock", reasoning_effort: "low", timeout_seconds: 30, available_models: ["council-mock"], model_source: "built_in", local_only: true, last_health_check: null, last_error: null, capabilities: {} };
const assignment = (role: string) => ({ role, provider_id: "mock", model: "council-mock", protocol: "auto", reasoning_effort: "low", max_output_tokens: 1200, temperature: 0.2, timeout_seconds: 30 });
const assignments = { schema_version: 2, seats: ["analyst", "challenger", "builder", "observer"].map(assignment), finalizer: assignment("finalizer") };
const templates = [
  { id: "open_discussion", name: "开放讨论", description: "依次讨论", prompt_hint: "写下问题", system_guidance: "", default_output_contract: "general_decision", requires_high_risk: false },
  { id: "medical_information_review", name: "医疗信息整理", description: "整理检查与治疗信息", prompt_hint: "描述诊断和检查", system_guidance: "", default_output_contract: "medical_second_opinion", requires_high_risk: true },
  { id: "legal_risk_review", name: "法律风险梳理", description: "识别法律风险", prompt_hint: "描述司法辖区和文件", system_guidance: "", default_output_contract: "legal_risk_review", requires_high_risk: true },
  { id: "financial_decision_review", name: "财务决策分析", description: "分析财务风险", prompt_hint: "描述金额与损失", system_guidance: "", default_output_contract: "financial_decision_review", requires_high_risk: true },
];
const contracts = [
  { id: "general_decision", name: "一般决策", description: "比较方案", input_checks: ["目标"], prompt_hint: "通用", system_guidance: "", requires_high_risk: false },
  { id: "medical_second_opinion", name: "医疗信息整理", description: "整理医疗信息", input_checks: ["诊断"], prompt_hint: "医疗", system_guidance: "", required_disclaimer: "不构成诊断或治疗建议。", requires_high_risk: true },
  { id: "legal_risk_review", name: "法律风险梳理", description: "识别法律风险", input_checks: ["司法辖区"], prompt_hint: "法律", system_guidance: "", required_disclaimer: "不构成法律意见。", requires_high_risk: true },
  { id: "financial_decision_review", name: "财务决策分析", description: "分析财务风险", input_checks: ["最大损失"], prompt_hint: "财务", system_guidance: "", required_disclaimer: "不构成投资建议。", requires_high_risk: true },
];

async function mockHome(page: import("@playwright/test").Page) {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [provider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.route("**/api/output-contracts", (route) => route.fulfill({ json: contracts }));
  await page.route("**/api/memory", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/memory/preview", (route) => route.fulfill({ json: { workspace_id: "local-default", selected_memory_ids: [], included: [], excluded_memory_ids: [], rendered_context: "" } }));
}

test("专业模板自动匹配契约并强制发送高风险控制", async ({ page }) => {
  let payload: Record<string, unknown> = {};
  await mockHome(page);
  await page.route("**/api/readiness", (route) => route.fulfill({ json: { ready: false, task_labels: ["decision", "high_risk"], checks: [], clarification_questions: ["请补充诊断和检查结果。"], recommended_mode: "high_risk_council", rules_version: "decision-readiness-v1" } }));
  await page.route("**/api/runs", (route) => { payload = route.request().postDataJSON(); return route.fulfill({ json: { id: "medical-domain-run" } }); });

  await page.goto("/");
  await page.getByRole("button", { name: "开始本地演示" }).click();
  await page.getByLabel("审议模板").selectOption("medical_information_review");
  await page.getByRole("button", { name: "高级设置" }).click();
  await expect(page.getByLabel("输出契约")).toHaveValue("medical_second_opinion");
  const riskToggle = page.getByRole("checkbox", { name: /高风险决策支持/ });
  await expect(riskToggle).toBeChecked();
  await expect(riskToggle).toBeDisabled();
  await page.getByRole("textbox", { name: "你的问题" }).fill("癌症患者是否应该调整化疗剂量？");
  await page.getByRole("button", { name: "进入圆桌" }).click();
  await page.waitForURL("**/runs/medical-domain-run");

  expect(payload).toMatchObject({ template_id: "medical_information_review", output_contract: "medical_second_opinion", high_risk: true });
  expect(payload).not.toHaveProperty("readiness_override");
  expect(payload).not.toHaveProperty("auto_summarize");
});

test("专业结果先显示免责声明并区分已核验与未核验信息", async ({ page }) => {
  const run = { id: "medical-result", question: "整理肿瘤治疗信息", mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "high", output_contract: "medical_second_opinion", workflow_engine: "langgraph", checkpoint_count: 2, status: "completed", created_at: now, updated_at: now, analysis: null, readiness: null, candidates: [], critiques: [], verifications: [], revisions: [], scores: [], final_decision: { final_answer: "请向主治医师确认。", key_reasons: [], verified_claims: [], partially_verified_claims: [], contradicted_claims: [], unverified_claims: [], disagreements: [], risks_and_limitations: [], confidence: { level: "unverified", explanation: "未核验" }, sources: [], provider_summary: { provider: "Mock", protocol: "mock", model: "council-mock", used_ccswitch: false, degraded: false }, usage }, usage, degraded: false, protocol: "mock", limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, discussion_turns: [], participant_roles: [{ id: "analyst", name: "析理", role: "拆解者", brief: "拆解" }], seat_assignments: [], finalizer_assignment: null, current_speaker_index: 1, discussion_round: 1, awaiting_user: false, auto_summarize: false, high_risk_control: false, recoverable: false };
  const brief = { id: "brief-medical", run_id: run.id, version: 1, schema_version: 2, generated_at: now, generation_reason: "run_completed", status: "conditional", recommendation: "补齐检查原文后由主治医师判断。", support: "majority", output_contract: "medical_second_opinion", decisive_reasons: [], rejected_alternatives: [], unresolved: [], assumptions: [], actions: [], reopen_triggers: [], minority_report: null, limitations: ["病历不完整"], contract_extension: { contract: "medical_second_opinion", scope: run.question, verified_information: ["用户上传的病理报告日期"], unverified_information: ["当前剂量是否准确"], risk_factors: ["存在药物相互作用可能"], professional_questions: ["哪些检查结果会改变治疗路径？"], required_disclaimer: "本次审议仅用于医疗信息整理，不构成诊断或治疗建议。" } };
  await page.route("**/api/runs/medical-result", (route) => route.fulfill({ json: run }));
  await page.route("**/api/runs/medical-result/decision-brief", (route) => route.fulfill({ json: brief }));
  await page.route("**/api/runs/medical-result/claims", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/runs/medical-result/lineage", (route) => route.fulfill({ json: { parent: null, children: [] } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/runs/medical-result");

  const disclaimer = page.getByRole("note", { name: "医疗信息边界" });
  await expect(disclaimer).toContainText("不构成诊断或治疗建议");
  const extension = page.getByRole("region", { name: "医疗信息整理契约" });
  await expect(extension).toContainText("用户上传的病理报告日期");
  await expect(extension).toContainText("当前剂量是否准确");
  const layout = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth }));
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
  const serious = (await new AxeBuilder({ page }).analyze()).violations.filter((item) => item.impact === "serious" || item.impact === "critical");
  expect(serious).toEqual([]);
});
