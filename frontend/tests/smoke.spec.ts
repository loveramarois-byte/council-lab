import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const backendUrl = process.env.COUNCIL_TEST_BACKEND_URL || "http://127.0.0.1:8001";
const internalApiToken = process.env.COUNCIL_INTERNAL_API_TOKEN || "";
const internalApiHeaders = { "X-Council-Internal-Token": internalApiToken };
const mockProvider = { id: "mock", preset_id: "mock", display_name: "本地演示", description: "不联网", provider_type: "mock", protocol_mode: "auto", base_url: "", has_api_key: false, credential_source: "none", supports_api_key: false, requires_api_key: false, enabled: true, is_active: true, default_model: "council-mock", reasoning_effort: "low", timeout_seconds: 30, available_models: ["council-mock"], model_source: "built_in", local_only: true, last_health_check: null, last_error: null, capabilities: {} };
const readyProvider = { ...mockProvider, id: "deepseek", preset_id: "deepseek", display_name: "DeepSeek", provider_type: "compatible", has_api_key: true, credential_source: "system", supports_api_key: true, requires_api_key: true, default_model: "deepseek-chat", available_models: ["deepseek-chat"], model_source: "provider", local_only: false, last_health_check: "2026-07-28T00:00:00Z" };
const ccswitchProvider = { ...mockProvider, id: "ccswitch", preset_id: "ccswitch", display_name: "CC Switch", provider_type: "ccswitch_local", protocol_mode: "responses", default_model: "gpt-5.6-sol", reasoning_effort: "ultra", timeout_seconds: 120, available_models: ["gpt-5.6-sol"], model_source: "ccswitch_history", last_health_check: "2026-07-28T00:00:00Z", capabilities: { supports_reasoning_effort: true } };
const unreadyProvider = { ...readyProvider, has_api_key: false, credential_source: "none", last_health_check: null };
const assignment = (role: string, providerId = "mock") => ({ role, provider_id: providerId, model: providerId === "mock" ? "council-mock" : "deepseek-chat", protocol: "auto", reasoning_effort: "low", max_output_tokens: 1200, temperature: 0.2, timeout_seconds: 30 });
const assignments = (providerId = "mock") => ({ schema_version: 2, seats: [assignment("analyst", providerId), assignment("challenger", providerId), assignment("builder", providerId), assignment("observer", providerId)], finalizer: assignment("finalizer", providerId) });
const templates = [
  { id: "open_discussion", name: "开放讨论", description: "依次讨论", prompt_hint: "写下需要四席共同审议的问题", system_guidance: "" },
  { id: "decision_review", name: "决策评审", description: "比较方案", prompt_hint: "说明目标、约束和选项", system_guidance: "" },
  { id: "premortem", name: "事前验尸", description: "倒推失败", prompt_hint: "描述计划和约束", system_guidance: "" },
];
const readyReadiness = { ready: true, task_labels: ["decision"], checks: [], clarification_questions: [], recommended_mode: "full_council", rules_version: "decision-readiness-v1" };

async function createMockRoundtable(request: import("@playwright/test").APIRequestContext) {
  const response = await request.post(`${backendUrl}/api/runs`, {
    headers: internalApiHeaders,
    data: { question: "数据库迁移应该先讨论哪些风险？", mode: "standard", provider_id: "mock", model: "council-mock" },
  });
  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<{ id: string }>;
}

test("首次打开明确区分本地演示并引导配置五席", async ({ page }) => {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments() }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.route("**/api/readiness", (route) => route.fulfill({ json: readyReadiness }));
  let createPayload: Record<string, unknown> | null = null;
  await page.route("**/api/runs", (route) => {
    expect(route.request().headers()["idempotency-key"]).toBeTruthy();
    createPayload = route.request().postDataJSON();
    return route.fulfill({ json: { id: "demo-fixture" } });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /四种视角/ })).toBeVisible();
  await expect(page.getByText("依次发言、公开回应；短定义与确定性计算会自动精简调用。")).toBeVisible();
  await expect(page.getByRole("heading", { name: "无需 API Key，先完成一次决策。" })).toBeVisible();
  await expect(page.getByText(/不联网、不产生模型费用/)).toBeVisible();
  await expect(page.getByRole("link", { name: /连接真实 AI/ })).toHaveAttribute("href", "/settings/providers");
  await expect(page.getByRole("link", { name: "资料空间" })).toHaveCount(0);
  await expect(page.getByText("资料空间", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /进入圆桌/ })).toHaveCount(0);
  await page.getByRole("button", { name: "开始本地演示" }).click();
  await expect(page.getByText("本地演示模式")).toBeVisible();
  await expect(page.locator(".top-meta")).toContainText("本地演示已就绪");
  await expect(page.getByRole("button", { name: /进入圆桌/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /快速审视.*1.8k/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /标准评审.*4k/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /深度审议.*7k/ })).toBeVisible();
  await expect(page.getByText(/通常 5 次调用，短任务自动精简为 2 次/)).toBeVisible();
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

test("示例决策只填充可编辑问题，高级设置仍可访问", async ({ page }) => {
  let createRequests = 0;
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments() }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.route("**/api/runs", (route) => { createRequests += 1; return route.fulfill({ json: { id: "unexpected" } }); });

  await page.goto("/");
  await page.getByRole("button", { name: "开始本地演示" }).click();
  await page.getByRole("button", { name: /现在发布，还是延期/ }).click();

  const question = page.getByRole("textbox", { name: "你的问题" });
  await expect(question).toHaveValue(/核心功能已经完成/);
  await expect(page.getByLabel("审议模板")).toHaveValue("decision_review");
  expect(createRequests).toBe(0);
  await question.fill("我们是否应该把发布日期延后一周？");
  await expect(question).toHaveValue("我们是否应该把发布日期延后一周？");

  await expect(page.getByLabel("发言策略")).toHaveCount(0);
  await page.getByRole("button", { name: "高级设置" }).click();
  await expect(page.getByLabel("发言策略")).toBeVisible();
  await expect(page.getByLabel("输出契约")).toBeVisible();
});

test("自动总结必须由用户明确开启并进入同一个创建请求", async ({ page }) => {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments() }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.route("**/api/readiness", (route) => route.fulfill({ json: readyReadiness }));
  let createPayload: Record<string, unknown> | null = null;
  await page.route("**/api/runs", (route) => {
    createPayload = route.request().postDataJSON();
    return route.fulfill({ json: { id: "auto-summary-fixture" } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "开始本地演示" }).click();
  await page.getByText("自动总结", { exact: true }).click();
  await expect(page.getByText("讨论席结束后直接生成答案")).toBeVisible();
  await page.getByPlaceholder("写下需要四席共同审议的问题").fill("请评估是否应该上线付费订阅");
  await page.getByRole("button", { name: /进入圆桌/ }).click();
  await page.waitForURL("**/runs/auto-summary-fixture");

  expect(createPayload).toMatchObject({ auto_summarize: true });
});

test("创建请求断线后使用同一幂等键重试", async ({ page }) => {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments() }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.route("**/api/readiness", (route) => route.fulfill({ json: readyReadiness }));
  const keys: string[] = [];
  let attempts = 0;
  await page.route(/\/api\/runs$/, async (route) => {
    attempts += 1;
    keys.push(route.request().headers()["idempotency-key"] || "");
    if (attempts === 1) return route.abort("connectionreset");
    return route.fulfill({ json: { id: "idempotent-retry-fixture" } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "开始本地演示" }).click();
  await page.getByPlaceholder("写下需要四席共同审议的问题").fill("网络断开后不能重复创建任务");
  await page.getByRole("button", { name: /进入圆桌/ }).click();

  await page.waitForURL("**/runs/idempotent-retry-fixture");
  expect(attempts).toBe(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[1]).toBe(keys[0]);
});

test("高风险开关由同一个创建请求原子启用服务端控制", async ({ page }) => {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments() }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  let createPayload: Record<string, unknown> | null = null;
  let actorHeader = "";
  await page.route("**/api/runs", (route) => {
    createPayload = route.request().postDataJSON();
    actorHeader = route.request().headers()["x-council-actor"] || "";
    return route.fulfill({ json: { id: "high-risk-create-fixture" } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "开始本地演示" }).click();
  await page.getByText("高风险决策支持", { exact: true }).click();
  await expect(page.getByRole("checkbox", { name: /高风险决策支持/ })).toBeChecked();
  await page.getByPlaceholder("写下需要四席共同审议的问题").fill("这项医疗决定缺少哪些关键事实？");
  await page.getByRole("button", { name: /进入圆桌/ }).click();
  await page.waitForURL("**/runs/high-risk-create-fixture");

  expect(createPayload).toMatchObject({ high_risk: true });
  expect(createPayload).not.toHaveProperty("auto_summarize");
  expect(actorHeader).toBe("local-requester");
});

test("高风险控制面在手机端显示关键事实门禁", async ({ page }) => {
  const now = new Date().toISOString();
  const run = {
    id: "high-risk-fixture", question: "医疗决策需要复核", mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "high",
    status: "awaiting_final_input", created_at: now, updated_at: now, analysis: null, candidates: [], critiques: [], verifications: [], revisions: [], scores: [], final_decision: null,
    usage: { model_calls: 4, tool_calls: 0, input_tokens: 100, output_tokens: 200, estimated_cost: null, duration_ms: 1000 }, degraded: false, protocol: "mock", workflow_engine: "langgraph", checkpoint_count: 4,
    context_snapshot: { strategy: "deterministic_context_clipping", token_budget: 4000, estimated_tokens: 300, included_turns: 4, total_turns: 4, compacted: false, summary: "" },
    limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, discussion_turns: [], participant_roles: [
      { id: "analyst", name: "析理", role: "拆解者", brief: "拆解" }, { id: "challenger", name: "诘问", role: "挑战者", brief: "反例" },
      { id: "builder", name: "构策", role: "方案师", brief: "方案" }, { id: "observer", name: "观澜", role: "观察者", brief: "分歧" },
    ], seat_assignments: [], finalizer_assignment: null, current_speaker_index: 4, discussion_round: 1, awaiting_user: true, auto_summarize: false, recoverable: false, limit_reason: null,
  };
  const fact = { fact_id: "medical_context", name: "医疗背景", description: "年龄、症状时间线、病史、用药和过敏。", required: true, value: null, source: "unknown", verified: false, verification_status: "unverified", materiality: "critical" };
  const highRisk = { run_id: run.id, status: "MORE_INFORMATION_REQUIRED", version: 1, risk_assessment: { run_id: run.id, risk_tier: "high", original_risk_tier: "high", detected_domains: ["medical"], reasons: ["检测到高风险领域：medical"], classifier_version: "high-risk-rules-v2", confidence: 0.75, requires_user_confirmation: true, assessed_at: now, manually_overridden: false }, required_facts: [fact], evidence_records: [], professional_reviews: [], assurance: { evidence_complete: false, evidence_current: false, evidence_conflict: false, professional_review_complete: false, medical_red_flag: false, blocking_reasons: ["关键事实未填写：医疗背景", "缺少证据：医疗背景"] }, decision: null, requested_by: "local-requester", created_at: now, updated_at: now };
  const audit = [{ event_id: "audit-1", sequence: 1, run_id: run.id, event_type: "risk_assessed", occurred_at: now, actor_type: "system", previous_status: "RISK_ASSESSMENT_REQUIRED", new_status: "MORE_INFORMATION_REQUIRED" }];
  let savedFacts: Array<Record<string, unknown>> = [];
  let auditRequests = 0;
  await page.route("**/api/runs/high-risk-fixture", (route) => route.fulfill({ json: run }));
  await page.route("**/api/high-risk/runs/high-risk-fixture/approval", (route) => route.fulfill({ status: 404, json: { error: { code: "APPROVAL_NOT_FOUND", message: "不存在" } } }));
  await page.route("**/api/high-risk/runs/high-risk-fixture/audit", (route) => {
    auditRequests += 1;
    return auditRequests === 1
      ? route.fulfill({ json: audit })
      : route.fulfill({ status: 503, json: { error: { code: "AUDIT_TEMPORARILY_UNAVAILABLE", message: "暂时不可用" } } });
  });
  await page.route("**/api/high-risk/runs/high-risk-fixture/facts", (route) => {
    savedFacts = route.request().postDataJSON().facts;
    return route.fulfill({ json: { ...highRisk, status: "EVIDENCE_REQUIRED", version: 2, required_facts: savedFacts } });
  });
  await page.route("**/api/high-risk/runs/high-risk-fixture", (route) => route.fulfill({ json: highRisk }));

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/runs/high-risk-fixture");
  await expect(page.getByText("需要补充关键信息").first()).toBeVisible();
  await page.getByRole("button", { name: "打开控制面" }).click();
  await expect(page.getByRole("heading", { name: "高风险决策支持" })).toBeVisible();
  const auditTimeline = page.getByRole("region", { name: "高风险审计时间线" });
  await expect(auditTimeline).toContainText("完成风险评估");
  await page.locator(".required-facts-form label").filter({ hasText: "医疗背景" }).locator("textarea").fill("成年人；症状持续两天；无已知过敏。 ");
  await page.getByRole("button", { name: "保存事实", exact: true }).click();
  expect(savedFacts[0].value).toBe("成年人；症状持续两天；无已知过敏。");
  await expect(page.getByText("等待报告与证据复核").first()).toBeVisible();
  await expect(page.locator(".high-risk-error")).toHaveCount(0);
  const viewport = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewportWidth: window.innerWidth }));
  expect(viewport.width).toBeLessThanOrEqual(viewport.viewportWidth);
});

test("高风险证据必须追加后由独立专业角色核验", async ({ page }) => {
  const now = new Date().toISOString();
  const run = {
    id: "high-risk-assurance-fixture", question: "投资适当性复核", mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "high", high_risk_control: true,
    status: "awaiting_final_input", created_at: now, updated_at: now, analysis: null, candidates: [], critiques: [], verifications: [], revisions: [], scores: [], final_decision: null,
    usage: { model_calls: 4, tool_calls: 0, input_tokens: 100, output_tokens: 200, estimated_cost: null, duration_ms: 1000 }, degraded: false, protocol: "mock", workflow_engine: "langgraph", checkpoint_count: 4,
    context_snapshot: { strategy: "deterministic_context_clipping", token_budget: 4000, estimated_tokens: 300, included_turns: 4, total_turns: 4, compacted: false, summary: "" },
    limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, discussion_turns: [], participant_roles: [
      { id: "analyst", name: "析理", role: "拆解者", brief: "拆解" }, { id: "challenger", name: "诘问", role: "挑战者", brief: "反例" },
      { id: "builder", name: "构策", role: "方案师", brief: "方案" }, { id: "observer", name: "观澜", role: "观察者", brief: "分歧" },
    ], seat_assignments: [], finalizer_assignment: null, current_speaker_index: 4, discussion_round: 1, awaiting_user: true, auto_summarize: false, recoverable: false, limit_reason: null,
  };
  const fact = { fact_id: "investment_constraints", name: "投资约束", description: "期限、流动性和损失承受力。", required: true, value: "期限五年；最大可承受损失 10%", source: "user", verified: false, verification_status: "unverified", materiality: "critical", source_title: null as string | null, source_timestamp: null as string | null };
  const baseAssessment = { run_id: run.id, risk_tier: "high", original_risk_tier: "high", detected_domains: ["investment"], reasons: ["检测到高风险领域：investment"], classifier_version: "high-risk-rules-v2", confidence: 0.75, requires_user_confirmation: true, assessed_at: now, manually_overridden: false };
  let current = { run_id: run.id, status: "EVIDENCE_REQUIRED", version: 2, risk_assessment: baseAssessment, required_facts: [fact], evidence_records: [] as Array<Record<string, unknown>>, professional_reviews: [], assurance: { evidence_complete: false, evidence_current: false, evidence_conflict: false, professional_review_complete: false, medical_red_flag: false, blocking_reasons: ["缺少证据：投资约束"] }, decision: null, requested_by: "local-requester", created_at: now, updated_at: now };
  let evidencePayload: Record<string, unknown> = {};
  let verificationPayload: Record<string, unknown> = {};
  await page.route("**/api/runs/high-risk-assurance-fixture", (route) => route.fulfill({ json: run }));
  await page.route("**/api/high-risk/runs/high-risk-assurance-fixture/approval", (route) => route.fulfill({ status: 404, json: { error: { code: "APPROVAL_NOT_FOUND", message: "不存在" } } }));
  await page.route("**/api/high-risk/runs/high-risk-assurance-fixture/audit", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/high-risk/runs/high-risk-assurance-fixture/evidence", async (route) => {
    evidencePayload = route.request().postDataJSON();
    const evidence = { evidence_id: "evidence-1", run_id: run.id, fact_id: fact.fact_id, fact_value_hash: "a".repeat(64), domain: "investment", source_type: "manual", source_title: String(evidencePayload.source_title), source_ref: String(evidencePayload.source_ref), source_timestamp: String(evidencePayload.source_timestamp), submitted_by: "local-requester", submitted_at: now, verification_status: "pending" };
    current = { ...current, version: 3, evidence_records: [evidence], required_facts: [{ ...fact, verification_status: "pending", source_title: evidence.source_title, source_timestamp: evidence.source_timestamp }], assurance: { ...current.assurance, blocking_reasons: ["证据未有效核验：投资约束（pending）"] } };
    return route.fulfill({ json: evidence });
  });
  await page.route("**/api/high-risk/runs/high-risk-assurance-fixture/evidence/evidence-1/verification", async (route) => {
    verificationPayload = route.request().postDataJSON();
    current = { ...current, version: 4, evidence_records: [{ ...current.evidence_records[0], verification_status: "verified", verified_by: "reviewer-b", verified_at: now }], required_facts: [{ ...fact, verified: true, verification_status: "verified", source_title: "Investment policy", source_timestamp: now }], assurance: { ...current.assurance, evidence_complete: true, evidence_current: true, blocking_reasons: [] } };
    return route.fulfill({ json: { verification_id: "verification-1", evidence_id: "evidence-1", run_id: run.id, status: "verified", method: "independent_source_review", reviewer_id: "reviewer-b", reviewer_role: "licensed_adviser", domain: "investment", note: "ok", verified_at: now } });
  });
  await page.route("**/api/high-risk/runs/high-risk-assurance-fixture", (route) => route.fulfill({ json: current }));

  await page.goto("/runs/high-risk-assurance-fixture");
  await page.getByRole("button", { name: "打开控制面" }).click();
  await page.getByLabel("投资约束来源标题").fill("Investment policy");
  await page.getByLabel("投资约束来源引用").fill("manual://policy-v3");
  await page.getByRole("button", { name: "追加证据" }).click();
  expect(evidencePayload).toMatchObject({ fact_id: "investment_constraints", source_type: "manual", source_title: "Investment policy" });
  await page.getByText("等待独立核验").waitFor();
  await page.locator(".professional-identity-form input").nth(0).fill("reviewer-b");
  await page.locator(".professional-identity-form input").nth(1).fill("reviewer-secret-b");
  await page.locator(".professional-identity-form input").nth(2).fill("licensed_adviser");
  await page.getByRole("button", { name: "核验此证据" }).click();
  expect(verificationPayload).toMatchObject({ status: "verified", reviewer_role: "licensed_adviser", domain: "investment" });
  await expect(page.getByText("已核验").first()).toBeVisible();
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

  await expect(page.getByRole("heading", { name: "当前配置包含 4 个本地演示席。" })).toBeVisible();
  await expect(page.getByText(/4 个席位使用预设示例/)).toBeVisible();
  await expect(page.getByRole("button", { name: /进入圆桌/ })).toHaveCount(0);
  await page.getByRole("button", { name: "确认混合配置并继续" }).click();
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

test("软件发现新版本后提供安全的自动更新入口", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.route("**/api/update/check*", (route) => route.fulfill({ json: {
    current_version: "0.3.0",
    latest_version: "0.4.0",
    update_available: true,
    can_auto_update: true,
    installation_kind: "macos",
    reason: "可以在软件内安全下载、校验并重启更新。",
    release_url: "https://github.com/loveramarois-byte/council-lab/releases/tag/v0.4.0",
    published_at: "2026-07-28T00:00:00Z",
    notes: "Updater release",
    package_name: "Council-v0.4.0-macOS.zip",
  } }));
  await page.goto("/settings/update");
  await expect(page.getByRole("heading", { name: "Council 0.4.0 已发布。" })).toBeVisible();
  await expect(page.locator(".update-versions strong").nth(0)).toHaveText("v0.3.0");
  await expect(page.locator(".update-versions strong").nth(1)).toHaveText("v0.4.0");
  await expect(page.getByText("可以在软件内安全下载", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载并安装" })).toBeVisible();
  await expect(page.getByRole("link", { name: "发布说明" })).toHaveAttribute("href", "https://github.com/loveramarois-byte/council-lab/releases/tag/v0.4.0");
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

test("App Store 版本只展示由商店管理的更新通道", async ({ page }) => {
  await page.route("**/api/update/check", (route) => route.fulfill({ json: {
    current_version: "0.16.0",
    latest_version: "0.16.0",
    update_available: false,
    current_is_newer: false,
    can_auto_update: false,
    installation_kind: "app_store",
    reason: "更新由 Mac App Store 安全提供。",
    release_url: "",
    published_at: null,
    notes: "",
    package_name: null,
  } }));

  await page.goto("/settings/update");
  await expect(page.getByRole("heading", { name: "更新由 Mac App Store 管理。" })).toBeVisible();
  await expect(page.getByText("无需在 Council 内下载或替换应用文件。")).toBeVisible();
  await expect(page.getByText("App Store", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新检查" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "下载并安装" })).toBeVisible();
});

test("更新检查失败后可重试并显示自动更新入口", async ({ page }) => {
  await page.route("**/api/update/check*", (route) => {
    if (!route.request().url().includes("refresh=true")) return route.fulfill({ status: 503, json: { detail: "暂时无法读取 GitHub 最新版本。" } });
    expect(route.request().headers()["x-council-request"]).toBe("app");
    return route.fulfill({ json: {
      current_version: "0.4.0", latest_version: "0.5.0", update_available: true, can_auto_update: true,
      installation_kind: "macos", reason: "可以在软件内安全下载、校验并重启更新。", release_url: "https://github.com/loveramarois-byte/council-lab/releases/tag/v0.5.0",
      published_at: null, notes: "Retry test", package_name: "Council-v0.5.0-macOS.zip",
    } });
  });
  await page.goto("/settings/update");
  await expect(page.getByText("暂时无法读取 GitHub 最新版本。")).toBeVisible();
  await page.getByRole("button", { name: "重新检查" }).click();
  await expect(page.getByRole("heading", { name: "Council 0.5.0 已发布。" })).toBeVisible();
  await expect(page.getByText("可以在软件内安全下载", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载并安装" })).toBeVisible();
  await expect(page.getByRole("link", { name: "发布说明" })).toHaveAttribute("href", "https://github.com/loveramarois-byte/council-lab/releases/tag/v0.5.0");
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

test("最新版和自动更新入口都能形成明确终态", async ({ page }) => {
  let latestVersion = "0.4.0";
  await page.route("**/api/update/check*", (route) => route.fulfill({ json: {
    current_version: "0.4.0", latest_version: latestVersion, update_available: latestVersion !== "0.4.0", can_auto_update: true,
    installation_kind: "macos", reason: "可以在软件内安全下载、校验并重启更新。", release_url: `https://github.com/loveramarois-byte/council-lab/releases/tag/v${latestVersion}`,
    published_at: null, notes: "Terminal state test", package_name: `Council-v${latestVersion}-macOS.zip`,
  } }));
  await page.goto("/settings/update");
  await expect(page.getByText("当前版本已经与正式 Release 一致。")).toBeVisible();
  latestVersion = "0.5.0";
  await page.getByRole("button", { name: "重新检查" }).click();
  await expect(page.getByRole("heading", { name: "Council 0.5.0 已发布。" })).toBeVisible();
  await expect(page.getByText("可以在软件内安全下载", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载并安装" })).toBeVisible();
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
  await page.getByLabel("选择模型供应商").selectOption("deepseek");
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
      available: true,
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
      available: false,
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
      available: false,
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
  let savedAssignments: ReturnType<typeof assignments> | null = null;

  await page.route("**/api/providers", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    return route.fulfill({ json: [{
      id: "deepseek", preset_id: "deepseek", display_name: "DeepSeek", description: "官方 API",
      key_url: "https://platform.deepseek.com/api_keys", docs_url: "https://api-docs.deepseek.com/",
      provider_type: "compatible", protocol_mode: "chat_completions", base_url: "https://api.deepseek.com",
      default_model: "deepseek-chat", reasoning_effort: "high", timeout_seconds: 90,
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
      default_model: payload.default_model || "deepseek-chat", reasoning_effort: "high", timeout_seconds: 90,
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
  await page.route("**/api/agent-assignments", (route) => {
    if (route.request().method() === "PUT") {
      savedAssignments = route.request().postDataJSON() as ReturnType<typeof assignments>;
      return route.fulfill({ json: savedAssignments });
    }
    return route.fulfill({ json: assignments() });
  });

  await page.goto("/settings/providers");
  await page.getByRole("button", { name: /DeepSeek/ }).click();
  await page.locator('input[type="password"]').fill("sk-test-for-e2e-only");
  await page.getByRole("button", { name: "保存并测试" }).click();

  await expect(page.getByText("连接成功，已设为当前供应商。")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByLabel("模型", { exact: true })).toHaveValue("deepseek-chat");
  await expect(page.getByRole("link", { name: "分别配置" })).toHaveAttribute("href", "/settings/agents");
  await page.getByRole("button", { name: "五席直接使用 deepseek-chat" }).click();
  await page.waitForURL("**/");
  await expect(page.locator(".setup-complete-notice")).toContainText("五席已配置完成");
  await expect(page.locator(".setup-complete-notice")).toContainText("现在可以直接输入问题开始审议");
  await page.getByRole("button", { name: "关闭配置完成提示" }).click();
  await expect(page.locator(".setup-complete-notice")).toHaveCount(0);
  expect(savedAssignments).not.toBeNull();
  expect([...savedAssignments!.seats, savedAssignments!.finalizer]).toHaveLength(5);
  expect([...savedAssignments!.seats, savedAssignments!.finalizer].every((item) => item.provider_id === "deepseek" && item.model === "deepseek-chat" && item.protocol === "chat_completions" && item.reasoning_effort === "high" && item.timeout_seconds === 90)).toBe(true);
  expect(savedAssignments!.seats[0]).toMatchObject({ max_output_tokens: 1200, temperature: 0.2 });
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
    const brief = page.getByRole("article", { name: "结构化决策简报" });
    await expect(brief).toBeVisible({ timeout: 10_000 });
    await expect(brief).toContainText("Council 未执行独立联网核验");
    await expect(page.getByText("查看原始综合文本")).toBeVisible();
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
    const saved = await (await request.get(`${backendUrl}/api/runs/${run.id}`, { headers: internalApiHeaders })).json() as { decision_review?: { expected_result: string; outcome_status: string } };
    expect(saved.decision_review).toMatchObject({ expected_result: "两周内验证回滚方案", outcome_status: "partial" });
  } finally {
    await request.delete(`${backendUrl}/api/runs/${run.id}`, { headers: internalApiHeaders });
  }
});

test("快速短定义只显示一席和第二次总结调用", async ({ page, request }) => {
  const response = await request.post(`${backendUrl}/api/runs`, {
    headers: internalApiHeaders,
    data: { question: "请用一句话解释什么是向量数据库", mode: "quick", provider_id: "mock", model: "council-mock", auto_summarize: true },
  });
  expect(response.ok()).toBeTruthy();
  const run = await response.json() as { id: string };
  try {
    await page.goto(`/runs/${run.id}`);
    await expect(page.locator(".council-seat")).toHaveCount(1);
    await expect(page.getByText("1 席顺序调用", { exact: true })).toBeVisible();
    await expect(page.getByText("短任务精简路线", { exact: true })).toBeVisible();
    await expect(page.getByText("第 2 次调用", { exact: false }).first()).toBeVisible();
    const brief = page.getByRole("article", { name: "结构化决策简报" });
    await expect(brief).toBeVisible({ timeout: 10_000 });
    await expect(brief).toContainText("Council 未执行独立联网核验");
    await expect(page.getByText("查看原始综合文本")).toBeVisible();
    const saved = await (await request.get(`${backendUrl}/api/runs/${run.id}`, { headers: internalApiHeaders })).json() as { status: string; usage: { model_calls: number }; participant_roles: unknown[] };
    expect(saved.status).toBe("completed");
    expect(saved.usage.model_calls).toBe(2);
    expect(saved.participant_roles).toHaveLength(1);
  } finally {
    await request.delete(`${backendUrl}/api/runs/${run.id}`, { headers: internalApiHeaders });
  }
});

test("沉浸模式同步原生全屏、失败回退和手机端退出", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
    Object.defineProperty(document, "fullscreenElement", {
      configurable: true,
      get: () => (window as Window & { __fullscreenElement?: Element | null }).__fullscreenElement || null,
    });
    Object.defineProperty(Element.prototype, "requestFullscreen", {
      configurable: true,
      value: function () {
        const state = window as Window & { __fullscreenDelay?: number; __fullscreenElement?: Element | null; __fullscreenRequests?: number; __fullscreenShouldReject?: boolean };
        state.__fullscreenRequests = (state.__fullscreenRequests || 0) + 1;
        if (state.__fullscreenShouldReject) return Promise.reject(new Error("Fullscreen denied by test browser"));
        const target = this as Element;
        return new Promise<void>((resolve) => window.setTimeout(() => {
          state.__fullscreenElement = target;
          document.dispatchEvent(new Event("fullscreenchange"));
          resolve();
        }, state.__fullscreenDelay || 0));
      },
    });
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: () => {
        const state = window as Window & { __fullscreenElement?: Element | null; __fullscreenExits?: number };
        state.__fullscreenExits = (state.__fullscreenExits || 0) + 1;
        state.__fullscreenElement = null;
        document.dispatchEvent(new Event("fullscreenchange"));
        return Promise.resolve();
      },
    });
  });
  const participantRoles = [
    { id: "analyst", name: "析理", role: "拆解者", brief: "拆解问题" },
    { id: "challenger", name: "诘问", role: "挑战者", brief: "寻找反例" },
    { id: "builder", name: "构策", role: "方案师", brief: "提出方案" },
    { id: "observer", name: "观澜", role: "观察者", brief: "观察分歧" },
  ];
  const runFixture = {
    id: "immersive-fixture",
    question: "沉浸阅读时怎样保留必要上下文？",
    mode: "standard",
    provider_id: "mock",
    model: "council-mock",
    reasoning_effort: "low",
    workflow_engine: "langgraph",
    checkpoint_count: 6,
    context_snapshot: { estimated_tokens: 620, token_budget: 7000, token_estimator_exact: false },
    status: "completed",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    analysis: null,
    candidates: [{
      candidate_id: "candidate-legacy",
      answer: "第 1 席关于沉浸阅读的意见。",
      structure_source: "legacy_default",
      key_reasons: ["旧版通用理由，不是模型明确表达"],
      assumptions: [], claims_to_verify: [], uncertainties: [], risks: [], proposed_sources: [],
      model: "council-mock", provider: "本地演示", status: "completed",
      usage: { model_calls: 1, tool_calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost: null, duration_ms: 0 },
    }], critiques: [], verifications: [], revisions: [], scores: [],
    final_decision: { final_answer: "保留议题、讨论正文和明确的退出入口，隐藏席位配置及导出等次要操作。" },
    usage: { model_calls: 5, tool_calls: 0, input_tokens: 900, output_tokens: 350, estimated_cost: null, duration_ms: 2000 },
    error: null,
    degraded: false,
    protocol: "auto",
    discussion_turns: participantRoles.map((participant, index) => ({
      id: `immersive-${participant.id}`,
      speaker_type: "agent",
      speaker_id: participant.id,
      speaker_name: participant.name,
      role_label: participant.role,
      content: `第 ${index + 1} 席关于沉浸阅读的意见。`,
      provider_name: "本地演示",
      model: "council-mock",
      round: 1,
      created_at: new Date().toISOString(),
    })),
    participant_roles: participantRoles,
    current_speaker_index: 4,
    discussion_round: 1,
    awaiting_user: false,
    limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 },
    seat_assignments: participantRoles.map((participant) => ({ ...assignment(participant.id), provider_name: "本地演示" })),
    finalizer_assignment: { ...assignment("finalizer"), provider_name: "本地演示" },
    template_name: "开放讨论",
    source_snapshots: [],
  };
  await page.route("**/api/runs/immersive-fixture", (route) => route.fulfill({ json: runFixture }));

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/runs/immersive-fixture");
  await expect(page.getByText("第 1 席关于沉浸阅读的意见。", { exact: true })).toBeVisible();
  await expect(page.getByText("旧版通用理由，不是模型明确表达", { exact: true })).toHaveCount(0);
  const enter = page.getByRole("button", { name: "进入沉浸模式" });
  await expect(enter).toHaveAttribute("title", "进入沉浸模式");
  await expect(enter).toHaveAttribute("aria-pressed", "false");
  await enter.click();

  await expect(page.locator(".council-page")).toHaveClass(/immersive/);
  await expect(page.getByRole("button", { name: "退出沉浸模式" })).toBeVisible();
  await expect(page.getByRole("button", { name: "退出沉浸模式" })).toBeFocused();
  await expect(page.locator(".council-callboard")).toBeHidden();
  await expect(page.locator(".sidebar")).toBeHidden();
  await expect(page.locator(".council-dialogue")).toBeVisible();
  expect(await page.evaluate(() => (window as Window & { __fullscreenRequests?: number }).__fullscreenRequests)).toBe(1);
  await page.getByRole("button", { name: "退出沉浸模式" }).click();
  await expect(page.locator(".council-page")).not.toHaveClass(/immersive/);
  expect(await page.evaluate(() => (window as Window & { __fullscreenExits?: number }).__fullscreenExits)).toBe(1);
  await expect(page.getByRole("button", { name: "进入沉浸模式" })).toBeFocused();

  await page.getByRole("button", { name: "进入沉浸模式" }).click();
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(true);
  await page.evaluate(() => document.exitFullscreen());
  await expect(page.locator(".council-page")).not.toHaveClass(/immersive/);
  await expect(page.getByRole("button", { name: "进入沉浸模式" })).toBeFocused();

  await page.evaluate(() => { (window as Window & { __fullscreenShouldReject?: boolean }).__fullscreenShouldReject = true; });
  await page.getByRole("button", { name: "进入沉浸模式" }).click();
  await expect(page.locator(".council-page")).toHaveClass(/immersive/);
  await expect(page.getByRole("button", { name: "退出沉浸模式" })).toBeFocused();
  const accessibility = await new AxeBuilder({ page }).include(".council-page").analyze();
  expect(accessibility.violations.filter((violation) => ["serious", "critical"].includes(violation.impact || ""))).toEqual([]);

  await page.keyboard.press("Escape");
  await expect(page.locator(".council-page")).not.toHaveClass(/immersive/);
  await expect(page.getByRole("button", { name: "进入沉浸模式" })).toBeFocused();

  await page.evaluate(() => {
    const state = window as Window & { __fullscreenDelay?: number; __fullscreenShouldReject?: boolean };
    state.__fullscreenShouldReject = false;
    state.__fullscreenDelay = 120;
  });
  await page.getByRole("button", { name: "进入沉浸模式" }).click();
  await page.keyboard.press("Escape");
  await page.waitForTimeout(180);
  await expect(page.locator(".council-page")).not.toHaveClass(/immersive/);
  await expect(page.getByRole("button", { name: "进入沉浸模式" })).toBeFocused();
  expect(await page.evaluate(() => document.fullscreenElement)).toBeNull();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "进入沉浸模式" }).click();
  await expect(page.getByRole("button", { name: "退出沉浸模式" })).toBeVisible();
  expect(await page.evaluate(() => (window as Window & { __fullscreenRequests?: number }).__fullscreenRequests)).toBe(4);
  const mobileViewport = await page.evaluate(() => ({
    pageWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    pageHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
  }));
  expect(mobileViewport.pageWidth).toBeLessThanOrEqual(mobileViewport.viewportWidth);
  expect(mobileViewport.pageHeight).toBeLessThanOrEqual(mobileViewport.viewportHeight);

  await page.getByRole("button", { name: "退出沉浸模式" }).click();
  await expect(page.locator(".council-page")).not.toHaveClass(/immersive/);
  await expect(page.getByRole("button", { name: "进入沉浸模式" })).toBeFocused();
});

test("最终综合失败后可重试且不会重复四席讨论", async ({ page }) => {
  const participantRoles = [
    { id: "analyst", name: "析理", role: "拆解者", brief: "拆解问题" },
    { id: "challenger", name: "诘问", role: "挑战者", brief: "寻找反例" },
    { id: "builder", name: "构策", role: "方案师", brief: "提出方案" },
    { id: "observer", name: "观澜", role: "观察者", brief: "观察分歧" },
  ];
  const discussionTurns = participantRoles.map((participant, index) => ({
    id: `turn-${participant.id}`,
    speaker_type: "agent",
    speaker_id: participant.id,
    speaker_name: participant.name,
    role_label: participant.role,
    content: `第 ${index + 1} 席发言`,
    provider_id: "ccswitch",
    provider_name: "CC Switch",
    model: "gpt-5.6-sol",
    round: 1,
    created_at: new Date().toISOString(),
  }));
  const baseRun = {
    id: "finalizer-retry-fixture",
    question: "总结席超时后能否安全重试？",
    mode: "standard",
    provider_id: "ccswitch",
    model: "gpt-5.6-sol",
    reasoning_effort: "ultra",
    workflow_engine: "langgraph",
    checkpoint_count: 5,
    context_snapshot: { estimated_tokens: 800, token_budget: 12000, token_estimator_exact: false },
    status: "awaiting_final_input" as string,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    analysis: null,
    candidates: [], critiques: [], verifications: [], revisions: [], scores: [],
    final_decision: null as { final_answer: string } | null,
    usage: { model_calls: 5, tool_calls: 0, input_tokens: 1200, output_tokens: 400, estimated_cost: null, duration_ms: 30_000 },
    error: null as string | null,
    degraded: false,
    protocol: "responses",
    discussion_turns: discussionTurns,
    participant_roles: participantRoles,
    current_speaker_index: 4,
    discussion_round: 1,
    awaiting_user: true,
    limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 },
    seat_assignments: participantRoles.map((participant) => ({ ...assignment(participant.id, "ccswitch"), provider_name: "CC Switch" })),
    finalizer_assignment: { ...assignment("finalizer", "ccswitch"), provider_name: "CC Switch" },
    template_name: "开放讨论",
    source_snapshots: [],
  };
  let currentRun = baseRun;
  let summarizeCalls = 0;
  await page.route("**/api/runs/finalizer-retry-fixture", (route) => route.fulfill({ json: currentRun }));
  await page.route("**/api/runs/finalizer-retry-fixture/summarize", (route) => {
    summarizeCalls += 1;
    currentRun = summarizeCalls === 1
      ? { ...baseRun, error: "最终综合等待上游超过 120 秒，请重试生成最终答案。" }
      : {
        ...baseRun,
        status: "completed",
        awaiting_user: false,
        error: null,
        usage: { ...baseRun.usage, model_calls: 6 },
        final_decision: { final_answer: "重试后的最终答案" },
      };
    return route.fulfill({ json: currentRun });
  });

  await page.goto("/runs/finalizer-retry-fixture");
  await expect(page.locator(".discussion-turn.agent")).toHaveCount(4);
  await page.getByRole("button", { name: "生成最终答案" }).click();
  await expect(page.getByText(/最终综合等待上游超过 120 秒/)).toBeVisible();
  await expect(page.locator(".discussion-turn.agent")).toHaveCount(4);
  await page.getByRole("button", { name: "生成最终答案" }).click();
  await expect(page.getByText("重试后的最终答案", { exact: true })).toBeVisible();
  await expect(page.locator(".discussion-turn.agent")).toHaveCount(4);
  expect(summarizeCalls).toBe(2);
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
  await expect(page.getByText("上下文 630 / 4000 · 估算", { exact: true })).toBeVisible();
  await expect(page.getByText("上游累计 15,391 / 12,000", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "提高到 40,000 Token 并继续" }).click();
  expect(resumePayload).toEqual({ max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 });
});

test("五个席位配置可保存且明确 Provider 能力", async ({ page, request }) => {
  const response = await request.get(`${backendUrl}/api/agent-assignments`, { headers: internalApiHeaders });
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
    await request.put(`${backendUrl}/api/agent-assignments`, { headers: internalApiHeaders, data: original });
  }
});


test("切换 Provider 时同步模型推理档和超时时限", async ({ page }) => {
  let saved: ReturnType<typeof assignments> | null = null;
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider, ccswitchProvider] }));
  await page.route("**/api/agent-assignments", (route) => {
    if (route.request().method() === "PUT") {
      saved = route.request().postDataJSON() as ReturnType<typeof assignments>;
      return route.fulfill({ json: saved });
    }
    return route.fulfill({ json: assignments() });
  });

  await page.goto("/settings/agents");
  await page.getByLabel("析理 Provider").selectOption("ccswitch");
  await page.getByRole("button", { name: "保存席位" }).click();

  expect(saved).not.toBeNull();
  expect(saved!.seats[0]).toMatchObject({
    provider_id: "ccswitch",
    model: "gpt-5.6-sol",
    protocol: "responses",
    reasoning_effort: "ultra",
    timeout_seconds: 120,
  });
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
    await request.delete(`${backendUrl}/api/runs/${run.id}`, { headers: internalApiHeaders });
  }
});

test("席位失败时明确显示原因并允许从当前席位重试", async ({ page }) => {
  const failedRun = {
    id: "failed-fixture",
    question: "首席还没有发言就超时",
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
  await page.route("**/api/runs/failed-fixture", (route) => route.fulfill({ json: failedRun }));
  await page.route("**/api/runs/failed-fixture/retry-turn", (route) => {
    retryRequested = true;
    return route.fulfill({ json: { ...failedRun, status: "running", error: null, updated_at: new Date().toISOString() } });
  });

  await page.goto("/runs/failed-fixture");
  await expect(page.getByText("调用失败", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/等待上游超过 120 秒/)).toBeVisible();
  await expect(page.getByText("0 次 AI 发言 · 0 次你的参与", { exact: true })).toBeVisible();
  await expect(page.locator(".council-seat.failed")).toContainText("析理");
  await page.getByRole("button", { name: "进入沉浸模式" }).click();
  await expect(page.getByRole("button", { name: "重试析理" })).toBeVisible();
  await page.getByRole("button", { name: "重试析理" }).click();
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
  await page.getByRole("button", { name: "进入沉浸模式" }).click();
  await expect(page.getByPlaceholder("我想补充 / 反驳 / 改变讨论方向…")).toBeEnabled();
  await expect(page.getByText("正在等待 CC Switch 返回上游响应")).toBeVisible();
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

test("诊断页只在用户操作后导出脱敏支持包", async ({ page }) => {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider] }));
  await page.route("**/api/update/check", (route) => route.fulfill({ json: { current_version: "0.7.0", latest_version: "0.7.0", update_available: false } }));
  await page.route("**/api/diagnostics/export", (route) => route.fulfill({
    body: "diagnostic-zip-fixture",
    contentType: "application/zip",
    headers: { "Content-Disposition": 'attachment; filename="council-diagnostics-test.zip"' },
  }));

  await page.goto("/settings/diagnostics");
  await expect(page.getByRole("heading", { name: "把问题说清楚，不把隐私带出去。" })).toBeVisible();
  await expect(page.getByText(/不包含问题、回答、资料正文、日志内容/)).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出诊断包" }).click();
  expect((await download).suggestedFilename()).toBe("council-diagnostics-test.zip");
  await expect(page.getByText(/诊断包已生成/)).toBeVisible();
});

test("普通审议不再探测高风险控制接口", async ({ page }) => {
  const now = new Date().toISOString();
  const run = {
    id: "standard-run-fixture", question: "普通审议不应产生高风险请求", mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "low",
    status: "completed", created_at: now, updated_at: now, analysis: null, candidates: [], critiques: [], verifications: [], revisions: [], scores: [], final_decision: null,
    usage: { model_calls: 0, tool_calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost: null, duration_ms: 0 }, degraded: false, protocol: "mock", discussion_turns: [], participant_roles: [], current_speaker_index: 0, discussion_round: 1, awaiting_user: false,
    limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, seat_assignments: [], finalizer_assignment: null, auto_summarize: false, high_risk_control: false, recoverable: false,
  };
  let highRiskRequests = 0;
  await page.route("**/api/runs/standard-run-fixture", (route) => route.fulfill({ json: run }));
  await page.route("**/api/high-risk/runs/standard-run-fixture", (route) => {
    highRiskRequests += 1;
    return route.fulfill({ status: 404, json: { error: { code: "HIGH_RISK_RUN_NOT_FOUND", message: "不存在" } } });
  });

  await page.goto("/runs/standard-run-fixture");
  await expect(page.getByRole("heading", { name: "普通审议不应产生高风险请求" })).toBeVisible();
  expect(highRiskRequests).toBe(0);
});

test("完成后的结构化决策简报保留阻塞项、少数意见并可导出", async ({ page }) => {
  const now = new Date().toISOString();
  const run = {
    id: "decision-brief-fixture", question: "是否应该发布这个版本？", mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "high",
    status: "completed", created_at: now, updated_at: now, analysis: null, candidates: [], critiques: [], verifications: [], revisions: [], scores: [],
    final_decision: { final_answer: "先做小范围发布，并保留回滚开关。", key_reasons: [], verified_claims: [], partially_verified_claims: [], contradicted_claims: [], unverified_claims: ["需求未核验"], disagreements: ["预算不足"], risks_and_limitations: ["模型共识不等于事实验证。"], confidence: { level: "unverified", explanation: "不提供百分比置信度" }, sources: [], provider_summary: { provider: "Mock", protocol: "mock", model: "council-mock", used_ccswitch: false, degraded: false }, usage: { model_calls: 5, tool_calls: 0, input_tokens: 100, output_tokens: 20, estimated_cost: null, duration_ms: 100 } },
    usage: { model_calls: 5, tool_calls: 0, input_tokens: 100, output_tokens: 20, estimated_cost: null, duration_ms: 100 }, provider_attempts: Array.from({ length: 5 }, (_, index) => ({ role: "analyst", provider_id: "compatible", provider_name: "Compatible", model: "test-model", endpoint: "/responses", attempt: index + 1, status_code: 200, duration_ms: 20 })), degraded: false, protocol: "mock", workflow_engine: "langgraph", checkpoint_count: 4,
    context_snapshot: { strategy: "deterministic_context_clipping", token_budget: 4000, estimated_tokens: 300, included_turns: 4, total_turns: 4, compacted: false, summary: "" },
    limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, discussion_turns: [], participant_roles: [{ id: "analyst", name: "析理", role: "拆解者", brief: "拆解" }, { id: "challenger", name: "诘问", role: "挑战者", brief: "反例" }],
    seat_assignments: [], finalizer_assignment: null, current_speaker_index: 2, discussion_round: 1, awaiting_user: false, auto_summarize: false, high_risk_control: false, recoverable: false, limit_reason: null,
  };
  const brief = {
    id: "brief-fixture", run_id: run.id, version: 1, schema_version: 1, generated_at: now, generation_reason: "run_completed", status: "conditional", recommendation: "先做小范围发布，并保留回滚开关。", support: "contested",
    decisive_reasons: [], rejected_alternatives: [],
    unresolved: [{ id: "issue-1", issue: "预算上限尚未确认", blocking: true, positions: [{ seat_id: "challenger", position: "预算不足时不应上线" }], resolution_method: "确认预算门槛后重新审议。" }],
    assumptions: [{ id: "assumption-1", claim: "当前需求强度足以支持灰度", basis: "model_inference", validation_method: "核对真实用户数据", owner: "用户", due_at: null }],
    actions: [{ id: "action-1", action: "先确认预算上限", owner: "用户", due_at: null, success_criteria: "预算获得确认", status: "pending" }],
    reopen_triggers: [{ id: "trigger-1", condition: "预算或需求发生实质变化", check_method: "重新核对", severity: "blocking" }],
    minority_report: { summary: "预算不足时不应上线。", seat_ids: ["challenger"], conditions_under_which_it_may_be_correct: ["预算低于门槛"] },
    limitations: ["席位支持度不代表事实正确概率。", "未经过外部事实核验。"],
  };
  await page.route(/\/api\/runs\/decision-brief-fixture$/, (route) => route.fulfill({ json: run }));
  await page.route("**/api/runs/decision-brief-fixture/decision-brief", (route) => route.fulfill({ json: brief }));

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/runs/${run.id}`);
  const card = page.getByRole("article", { name: "结构化决策简报" });
  await expect(card).toContainText("满足条件后推进");
  await expect(card).toContainText("存在明确反对");
  await expect(card).toContainText("预算上限尚未确认");
  await expect(card).toContainText("少数意见");
  await expect(card).toContainText("不代表事实正确概率");
  await expect(page.getByText("API 5 / 5 成功", { exact: true })).toBeVisible();
  await expect(page.getByText("查看原始综合文本")).toBeVisible();
  await page.getByRole("button", { name: "导出" }).click();
  await expect(page.locator(".completed-actions").getByRole("link", { name: /Markdown/ })).toHaveAttribute("href", `/api/runs/${run.id}/export?format=markdown`);
  await page.getByRole("button", { name: "导出" }).click();
  await page.getByRole("button", { name: "更多" }).click();
  const moreMenu = page.getByLabel("更多操作");
  await expect(moreMenu).toBeVisible();
  const moreMenuBounds = await moreMenu.boundingBox();
  expect(moreMenuBounds).not.toBeNull();
  expect(moreMenuBounds!.x).toBeGreaterThanOrEqual(0);
  expect(moreMenuBounds!.x + moreMenuBounds!.width).toBeLessThanOrEqual(390);
  await expect(page.getByRole("button", { name: "结果回访" })).toBeVisible();
  await expect(page.getByRole("link", { name: /讨论新问题/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "结束讨论" })).toHaveCount(0);
  const viewport = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewportWidth: window.innerWidth }));
  expect(viewport.width).toBeLessThanOrEqual(viewport.viewportWidth);
});

test("旧普通审议的兼容探测在轮询期间只发送一次", async ({ page }) => {
  const now = new Date().toISOString();
  const legacyRun = {
    id: "legacy-standard-fixture", question: "旧普通审议兼容读取", mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "low",
    status: "running", created_at: now, updated_at: now, analysis: null, candidates: [], critiques: [], verifications: [], revisions: [], scores: [], final_decision: null,
    usage: { model_calls: 0, tool_calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost: null, duration_ms: 0 }, degraded: false, protocol: "mock", discussion_turns: [], participant_roles: [], current_speaker_index: 0, discussion_round: 1, awaiting_user: false,
    limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, seat_assignments: [], finalizer_assignment: null, auto_summarize: false, recoverable: false,
  };
  let highRiskRequests = 0;
  let finishProbe: (() => void) | undefined;
  const probeGate = new Promise<void>((resolve) => { finishProbe = resolve; });
  await page.route("**/api/runs/legacy-standard-fixture", (route) => route.fulfill({ json: legacyRun }));
  await page.route("**/api/high-risk/runs/legacy-standard-fixture", async (route) => {
    highRiskRequests += 1;
    await probeGate;
    return route.fulfill({ status: 404, json: { error: { code: "HIGH_RISK_RUN_NOT_FOUND", message: "不存在" } } });
  });

  await page.goto("/runs/legacy-standard-fixture");
  await expect.poll(() => highRiskRequests).toBe(1);
  await page.waitForTimeout(2_700);
  expect(highRiskRequests).toBe(1);
  finishProbe?.();
});

test("Service Worker 脚本存在且不造成注册错误", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  const response = await page.request.get("/sw.js");
  expect(response.ok()).toBeTruthy();
  expect(response.headers()["content-type"]).toContain("javascript");
  const serviceWorker = await response.text();
  expect(serviceWorker).not.toContain("/api/");
  expect(serviceWorker).not.toContain("/runs/");

  await page.route("**/api/providers", (route) => route.fulfill({ json: [mockProvider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments() }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /四种视角/ })).toBeVisible();
  const activeScript = await page.evaluate(async () => (await navigator.serviceWorker.ready).active?.scriptURL || "");
  expect(activeScript).toMatch(/\/sw\.js$/);
  const cachedPaths = await page.evaluate(async () => {
    const requests = (await Promise.all((await caches.keys()).map((key) => caches.open(key).then((cache) => cache.keys())))).flat();
    return requests.map((request) => new URL(request.url).pathname);
  });
  expect(cachedPaths.length).toBeGreaterThan(0);
  expect(cachedPaths.every((path) => path === "/manifest.webmanifest" || path.startsWith("/icons/"))).toBeTruthy();
  expect(consoleErrors.filter((message) => message.includes("bad HTTP response") || message.includes("sw.js"))).toEqual([]);
});

test("大量历史记录分批显示且加载期间不闪烁空状态", async ({ page }) => {
  const now = new Date().toISOString();
  const runs = Array.from({ length: 105 }, (_, index) => ({
    id: `history-${index}`, question: `历史测试 ${index + 1}`, mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "low",
    status: "completed", created_at: now, updated_at: now, candidates: [], critiques: [], verifications: [], revisions: [], scores: [], final_decision: null,
    usage: { model_calls: 5, tool_calls: 0, input_tokens: 100, output_tokens: 20, estimated_cost: null, duration_ms: 10 }, degraded: false, protocol: "mock", discussion_turns: [], participant_roles: [], current_speaker_index: 4, discussion_round: 1, awaiting_user: false,
    limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, seat_assignments: [], auto_summarize: false, high_risk_control: false, recoverable: false,
  }));
  let releaseResponse: (() => void) | undefined;
  const responseGate = new Promise<void>((resolve) => { releaseResponse = resolve; });
  await page.route(/\/api\/runs\?summary=true&limit=\d+&offset=\d+$/, async (route) => {
    await responseGate;
    const url = new URL(route.request().url());
    const limit = Number(url.searchParams.get("limit"));
    const offset = Number(url.searchParams.get("offset"));
    return route.fulfill({ json: { items: runs.slice(offset, offset + limit), total: runs.length, limit, offset } });
  });

  await page.goto("/runs");
  await expect(page.getByText("正在读取历史记录")).toBeVisible();
  await expect(page.getByText("还没有审议记录")).toHaveCount(0);
  releaseResponse?.();
  await expect(page.locator(".run-row")).toHaveCount(50);
  await page.getByPlaceholder("搜索问题").fill("历史测试 105");
  await expect(page.locator(".run-row")).toHaveCount(0);
  await page.getByRole("button", { name: "继续加载更多记录" }).click();
  await page.getByRole("button", { name: "继续加载更多记录" }).click();
  await expect(page.locator(".run-row")).toHaveCount(1);
  await expect(page.getByText("历史测试 105", { exact: true })).toBeVisible();
  await page.getByPlaceholder("搜索问题").fill("");
  await expect(page.locator(".run-row")).toHaveCount(50);
  await page.getByRole("button", { name: /加载更多/ }).click();
  await expect(page.locator(".run-row")).toHaveCount(100);
  await page.getByRole("button", { name: /加载更多/ }).click();
  await expect(page.locator(".run-row")).toHaveCount(105);
});

test("历史页明确区分空记录、无匹配和读取失败", async ({ page }) => {
  const now = new Date().toISOString();
  const oneRun = [{
    id: "history-state-fixture", question: "唯一历史记录", mode: "standard", provider_id: "mock", model: "council-mock", reasoning_effort: "low",
    status: "completed", created_at: now, updated_at: now, candidates: [], critiques: [], verifications: [], revisions: [], scores: [], final_decision: null,
    usage: { model_calls: 5, tool_calls: 0, input_tokens: 100, output_tokens: 20, estimated_cost: null, duration_ms: 10 }, degraded: false, protocol: "mock", discussion_turns: [], participant_roles: [], current_speaker_index: 4, discussion_round: 1, awaiting_user: false,
    limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, seat_assignments: [], auto_summarize: false, high_risk_control: false, recoverable: false,
  }];
  let responseMode: "empty" | "one" | "error" = "empty";
  await page.route(/\/api\/runs\?summary=true&limit=\d+&offset=\d+$/, (route) => responseMode === "error"
    ? route.fulfill({ status: 503, json: { error: { message: "本地数据库暂时忙" } } })
    : route.fulfill({ json: { items: responseMode === "one" ? oneRun : [], total: responseMode === "one" ? 1 : 0, limit: 50, offset: 0 } }));

  await page.goto("/runs");
  await expect(page.getByText("还没有审议记录")).toBeVisible();

  responseMode = "one";
  await page.reload();
  await page.getByPlaceholder("搜索问题").fill("不存在的记录");
  await expect(page.getByText("没有匹配的审议记录")).toBeVisible();
  await expect(page.getByText("还没有审议记录")).toHaveCount(0);

  responseMode = "error";
  await page.reload();
  await expect(page.getByText("历史记录暂时无法读取")).toBeVisible();
  await expect(page.getByRole("button", { name: "重新读取" })).toBeVisible();
});
