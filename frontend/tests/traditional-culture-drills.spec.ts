import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { buildTraditionalCultureSnapshot } from "../lib/traditional-culture";


const backendUrl = process.env.COUNCIL_TEST_BACKEND_URL || "http://127.0.0.1:8001";
const internalApiHeaders = { "X-Council-Internal-Token": process.env.COUNCIL_INTERNAL_API_TOKEN || "" };
const now = "2026-08-02T00:00:00Z";
const provider = { id: "mock", preset_id: "mock", display_name: "本地演示", description: "不联网", provider_type: "mock", protocol_mode: "auto", base_url: "", has_api_key: false, credential_source: "none", supports_api_key: false, requires_api_key: false, enabled: true, is_active: true, default_model: "council-mock", reasoning_effort: "low", timeout_seconds: 30, max_retries: 0, available_models: ["council-mock"], model_source: "built_in", local_only: true, last_health_check: null, last_error: null, capabilities: {} };
const assignment = (role: string) => ({ role, provider_id: "mock", model: "council-mock", protocol: "auto", reasoning_effort: "low", max_output_tokens: 1200, temperature: 0.2, timeout_seconds: 30 });
const assignments = { schema_version: 2, seats: ["analyst", "challenger", "builder", "observer"].map(assignment), finalizer: assignment("finalizer") };
const templates = [
  { id: "open_discussion", name: "开放讨论", description: "通用", prompt_hint: "写下问题", system_guidance: "" },
  { id: "traditional_culture_review", name: "传统文化联合研判", description: "本地排盘后研判", prompt_hint: "说明希望研究的传统文化主题", system_guidance: "" },
];

function snapshot() {
  return {
    schema_version: 1,
    calculation_source: "local_browser",
    calculated_at: now,
    profile: { calendar_type: "solar", birth_date: "2000-08-16", birth_time: "03:30", time_precision: "exact", gender: "male", birth_place: "", timezone: "Asia/Shanghai", true_solar_time_applied: false, focus_topics: ["temperament"] },
    engines: [
      { id: "lunar-javascript", version: "1.7.7", source_url: "https://github.com/6tail/lunar-javascript", license: "MIT" },
      { id: "iztro", version: "2.5.8", source_url: "https://github.com/SylarLong/iztro", license: "MIT" },
    ],
    calendar_facts: { solar_datetime: "2000-08-16 03:30:00", lunar_date: "二〇〇〇年七月十七", zodiac: "龙", constellation: "狮子", eight_char: "庚辰 甲申 丙午 庚寅", pillars: ["庚辰", "甲申", "丙午", "庚寅"], pillar_wuxing: ["金土", "木金", "火火", "金木"], heavenly_stem_ten_gods: ["偏财", "偏印", "日主", "偏财"] },
    ziwei_chart: { solar_date: "2000-8-16", lunar_date: "二〇〇〇年七月十七", chinese_date: "庚辰 甲申 丙午 庚寅", time_label: "寅时", time_range: "03:00~05:00", five_elements_class: "木三局", soul_star: "破军", body_star: "文昌", soul_palace_branch: "午", body_palace_branch: "戌", palaces: Array.from({ length: 12 }, (_, index) => ({ index, name: `宫${index}`, heavenly_stem: "甲", earthly_branch: "子", is_body_palace: index === 8, is_original_palace: index === 2, major_stars: index === 4 ? ["紫微（庙）"] : [], minor_stars: [], changsheng12: "长生", decadal_range: [1, 10] })) },
    notices: ["本地计算", "传统解释未验证"],
    snapshot_sha256: "0c281caafaafe14a94824ab728821e27e20c6d874c74b7038ff6441677f55d83",
  };
}

async function mockHome(page: Page, memories: unknown[] = []) {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [provider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.route("**/api/output-contracts", (route) => route.fulfill({ json: [{ id: "general_decision", name: "一般决策", description: "通用", input_checks: [], prompt_hint: "通用", system_guidance: "" }] }));
  await page.route("**/api/memory", (route) => route.fulfill({ json: memories }));
  await page.route("**/api/memory/preview", (route) => route.fulfill({ json: { workspace_id: "default", selected_memory_ids: [], included: [], excluded_memory_ids: [], rendered_context: "" } }));
}

async function openTraditional(page: Page, memories: unknown[] = []) {
  await mockHome(page, memories);
  await page.goto("/");
  await page.getByRole("button", { name: "仅体验本地演示" }).click();
  await page.getByRole("button", { name: "传统文化" }).click();
}

async function fillRequiredProfile(page: Page) {
  await page.getByLabel("出生日期").fill("2000-08-16");
  await page.getByLabel("出生时间").fill("03:30");
  await page.getByRole("textbox", { name: "你的问题" }).fill("比较传统解释并指出不可验证之处");
  await page.getByText("我同意将排盘字段和必要出生参数发送给本次已配置的五个模型席位").click();
}

const creationSamples = [
  { date: "1900-01-01", time: "00:00", gender: "male", precision: "exact" },
  { date: "1912-01-01", time: "01:59", gender: "female", precision: "approximate" },
  { date: "1949-10-01", time: "02:00", gender: "male", precision: "exact" },
  { date: "1966-05-16", time: "03:30", gender: "female", precision: "approximate" },
  { date: "1978-12-18", time: "05:59", gender: "male", precision: "exact" },
  { date: "1984-02-29", time: "07:00", gender: "female", precision: "exact" },
  { date: "1990-01-01", time: "09:01", gender: "male", precision: "approximate" },
  { date: "2000-08-16", time: "11:30", gender: "female", precision: "exact" },
  { date: "2008-08-08", time: "13:59", gender: "male", precision: "exact" },
  { date: "2012-02-29", time: "17:00", gender: "female", precision: "approximate" },
  { date: "2020-01-25", time: "21:30", gender: "male", precision: "exact" },
  { date: "2026-08-02", time: "23:59", gender: "female", precision: "exact" },
] as const;

for (const [index, sample] of creationSamples.entries()) {
  test(`演练 ${index + 1}/48：本地排盘边界 ${sample.date} ${sample.time}`, async ({ page }) => {
    await openTraditional(page);
    let payload: Record<string, any> = {};
    await page.route("**/api/runs", (route) => {
      payload = route.request().postDataJSON();
      return route.fulfill({ json: { id: `culture-drill-${index}` } });
    });
    await page.getByLabel("出生日期").fill(sample.date);
    await page.getByLabel("出生时间").fill(sample.time);
    if (sample.gender === "female") await page.getByLabel("女").check();
    await page.getByLabel("时间精度").selectOption(sample.precision);
    await page.getByRole("textbox", { name: "你的问题" }).fill("比较传统解释，并明确标出不可验证之处");
    await page.getByText("性情结构", { exact: true }).click();
    await page.getByText("我同意将排盘字段和必要出生参数发送给本次已配置的五个模型席位").click();
    await page.getByRole("button", { name: "排盘并进入研判" }).click();
    await page.waitForURL(`**/runs/culture-drill-${index}`);
    expect(payload.traditional_culture_snapshot.profile).toMatchObject({ birth_date: sample.date, birth_time: sample.time, gender: sample.gender, time_precision: sample.precision });
    expect(payload.traditional_culture_snapshot.ziwei_chart.palaces).toHaveLength(12);
    expect(payload.traditional_culture_snapshot.snapshot_sha256).toMatch(/^[a-f0-9]{64}$/);
  });
}

const prohibitedQuestions = [
  "请根据命盘决定是否停药",
  "根据命盘帮我开降压药处方",
  "根据命盘判断要不要起诉对方",
  "根据命盘决定是否签这份合同",
  "看命盘告诉我今天是否抄底比特币",
  "用命盘给我的期货仓位建议",
  "根据命盘决定能不能通过这次监管申报",
  "根据命盘判断该不该报税",
  "看命盘决定今晚是否上线核心服务",
  "依据命盘判断故障后是否立即回滚",
  "Use the chart to tell me whether to stop medication",
  "Use my chart to decide whether to deploy to production tonight",
] as const;

async function rejectProhibitedQuestion(request: APIRequestContext, question: string, index: number) {
  const cultureSnapshot = await buildTraditionalCultureSnapshot({
    calendar_type: "solar",
    birth_date: "2000-08-16",
    birth_time: "03:30",
    time_precision: "exact",
    gender: "male",
    birth_place: "",
    timezone: "Asia/Shanghai",
    true_solar_time_applied: false,
    focus_topics: ["temperament"],
  });
  const response = await request.post(`${backendUrl}/api/runs`, {
    headers: { ...internalApiHeaders, "Idempotency-Key": `culture-drill-risk-${index}` },
    data: {
      question,
      provider_id: "mock",
      council_mode: "traditional_culture",
      workflow_strategy: "independent",
      template_id: "traditional_culture_review",
      traditional_culture_snapshot: cultureSnapshot,
      traditional_culture_consent: true,
    },
  });
  if (response.ok()) {
    const created = await response.json() as { id: string };
    await request.delete(`${backendUrl}/api/runs/${created.id}`, { headers: internalApiHeaders });
  }
  expect(response.status(), question).toBe(400);
  await expect(response.json()).resolves.toMatchObject({ detail: expect.stringContaining("不能用于") });
}

for (const [index, question] of prohibitedQuestions.entries()) {
  test(`演练 ${index + 13}/48：危险意图必须失败关闭`, async ({ page, request }) => {
    if (index === 0) {
      await openTraditional(page);
      await page.getByLabel("出生日期").fill("2000-08-16");
      await page.getByLabel("出生时间").fill("03:30");
      await page.getByRole("textbox", { name: "你的问题" }).fill(question);
      await page.getByText("我同意将排盘字段和必要出生参数发送给本次已配置的五个模型席位").click();
      await page.getByRole("button", { name: "排盘并进入研判" }).click();
      await expect(page.locator(".form-error")).toContainText("不能用于医疗、法律、投资、合规或生产事故决策");
      await page.screenshot({ path: "../.gstack/qa-reports/screenshots/issue-001-after.png", fullPage: true });
      await expect(page).toHaveURL(/\/$/);
      return;
    }
    await rejectProhibitedQuestion(request, question, index);
  });
}

const formGateCases = [
  { name: "全部为空", fill: async (_page: Page) => {} },
  { name: "缺出生时间", fill: async (page: Page) => { await page.getByLabel("出生日期").fill("2000-08-16"); await page.getByRole("textbox", { name: "你的问题" }).fill("比较传统解释"); await page.getByText("我同意将排盘字段和必要出生参数发送给本次已配置的五个模型席位").click(); } },
  { name: "缺出生日期", fill: async (page: Page) => { await page.getByLabel("出生时间").fill("03:30"); await page.getByRole("textbox", { name: "你的问题" }).fill("比较传统解释"); await page.getByText("我同意将排盘字段和必要出生参数发送给本次已配置的五个模型席位").click(); } },
  { name: "问题不足三字", fill: async (page: Page) => { await page.getByLabel("出生日期").fill("2000-08-16"); await page.getByLabel("出生时间").fill("03:30"); await page.getByRole("textbox", { name: "你的问题" }).fill("解释"); await page.getByText("我同意将排盘字段和必要出生参数发送给本次已配置的五个模型席位").click(); } },
  { name: "没有发送同意", fill: async (page: Page) => { await page.getByLabel("出生日期").fill("2000-08-16"); await page.getByLabel("出生时间").fill("03:30"); await page.getByRole("textbox", { name: "你的问题" }).fill("比较传统解释"); } },
  { name: "取消发送同意", fill: async (page: Page) => { await fillRequiredProfile(page); await page.getByText("我同意将排盘字段和必要出生参数发送给本次已配置的五个模型席位").click(); } },
  { name: "键盘快捷键不能绕过", fill: async (page: Page) => { await page.getByRole("textbox", { name: "你的问题" }).fill("比较传统解释"); await page.getByRole("textbox", { name: "你的问题" }).press(process.platform === "darwin" ? "Meta+Enter" : "Control+Enter"); } },
  { name: "出生地限制 120 字", fill: async (page: Page) => { await page.getByRole("textbox", { name: "出生地" }).fill("地".repeat(121)); } },
] as const;

for (const [index, gate] of formGateCases.entries()) {
  test(`演练 ${index + 25}/48：表单门禁 ${gate.name}`, async ({ page }) => {
    await openTraditional(page);
    let createRequests = 0;
    await page.route("**/api/runs", (route) => { createRequests += 1; return route.fulfill({ json: { id: "should-not-create" } }); });
    await gate.fill(page);
    if (gate.name === "出生地限制 120 字") {
      await expect(page.getByRole("textbox", { name: "出生地" })).toHaveValue("地".repeat(120));
    } else {
      await expect(page.getByRole("button", { name: "排盘并进入研判" })).toBeDisabled();
      expect(createRequests).toBe(0);
    }
  });
}

const modeChecks = [
  ["隐藏审议模板", "审议模板"],
  ["隐藏发言策略", "发言策略"],
  ["隐藏输出契约", "输出契约"],
  ["隐藏高风险开关", "高风险决策支持"],
  ["隐藏自动总结", "自动总结"],
] as const;

for (const [index, [name, label]] of modeChecks.entries()) {
  test(`演练 ${index + 33}/48：传统模式${name}`, async ({ page }) => {
    await openTraditional(page, [{ memory: { id: "memory-1", type: "constraint", content: "旧决策", created_at: now }, source: null }]);
    const byLabel = page.getByLabel(label, { exact: true });
    const byText = page.getByText(label, { exact: true });
    await expect(byLabel.or(byText)).toHaveCount(0);
  });
}

test("演练 38/48：切回通用圆桌恢复通用控制", async ({ page }) => {
  await openTraditional(page);
  await page.getByRole("button", { name: "通用圆桌" }).click();
  await expect(page.getByLabel("审议模板")).toBeVisible();
  await expect(page.getByText("高风险决策支持", { exact: true })).toBeVisible();
});

test("演练 39/48：切回通用圆桌清除出生资料发送同意", async ({ page }) => {
  await openTraditional(page);
  await fillRequiredProfile(page);
  await page.getByRole("button", { name: "通用圆桌" }).click();
  await page.getByRole("button", { name: "传统文化" }).click();
  await expect(page.getByRole("button", { name: "排盘并进入研判" })).toBeDisabled();
});

test("演练 40/48：传统模式不调用普通准备度接口", async ({ page }) => {
  await openTraditional(page);
  let readinessRequests = 0;
  await page.route("**/api/readiness", (route) => { readinessRequests += 1; return route.fulfill({ json: {} }); });
  await page.route("**/api/runs", (route) => route.fulfill({ json: { id: "no-readiness" } }));
  await fillRequiredProfile(page);
  await page.getByRole("button", { name: "排盘并进入研判" }).click();
  await page.waitForURL("**/runs/no-readiness");
  expect(readinessRequests).toBe(0);
});

function completedTraditionalRun(id: string) {
  return {
    id,
    question: "比较传统解释并指出不可验证之处",
    mode: "standard",
    council_mode: "traditional_culture",
    workflow_strategy: "independent",
    provider_id: "mock",
    model: "council-mock",
    reasoning_effort: "high",
    workflow_engine: "langgraph",
    checkpoint_count: 5,
    status: "completed",
    created_at: now,
    updated_at: now,
    analysis: { expected_model_calls: 5 },
    readiness: null,
    candidates: [], critiques: [], verifications: [], revisions: [], scores: [],
    final_decision: { final_answer: "## 计算快照\n四柱已冻结。\n## 反证与限制\n传统解释不可验证。", key_reasons: [], verified_claims: [], partially_verified_claims: [], contradicted_claims: [], unverified_claims: ["传统解释未验证"], disagreements: [], risks_and_limitations: ["不得用于高风险决策"], confidence: { level: "traditional_interpretation", explanation: "不提供正确率" }, sources: [], provider_summary: { provider: "Mock", protocol: "mock", model: "council-mock", used_ccswitch: false, degraded: false }, usage: { model_calls: 5, tool_calls: 0, input_tokens: 100, output_tokens: 50, duration_ms: 1000 } },
    usage: { model_calls: 5, tool_calls: 0, input_tokens: 100, output_tokens: 50, duration_ms: 1000 },
    degraded: false,
    protocol: "mock",
    context_snapshot: { strategy: "deterministic_context_clipping", token_budget: 4000, estimated_tokens: 10, included_turns: 0, total_turns: 0, compacted: false, summary: "" },
    limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 },
    discussion_turns: [],
    participant_roles: ["校历", "辨典", "参派", "证伪"].map((name, index) => ({ id: ["analyst", "challenger", "builder", "observer"][index], name, role: "专席", brief: "" })),
    seat_assignments: [],
    finalizer_assignment: null,
    current_speaker_index: 4,
    discussion_round: 1,
    awaiting_user: false,
    auto_summarize: false,
    high_risk_control: false,
    recoverable: false,
    template_name: "传统文化联合研判",
    traditional_culture_snapshot: snapshot(),
    traditional_culture_consent: true,
  };
}

const resultWidths = [320, 344, 360, 375, 390, 414, 430, 768] as const;

for (const [index, width] of resultWidths.entries()) {
  test(`演练 ${index + 41}/48：结果页 ${width}px 无横向溢出`, async ({ page }) => {
    await page.setViewportSize({ width, height: 812 });
    const id = `culture-result-${width}`;
    await page.route(`**/api/runs/${id}`, (route) => route.fulfill({ json: completedTraditionalRun(id) }));
    await page.goto(`/runs/${id}`);
    const card = page.getByLabel("传统文化本地计算快照");
    await expect(card).toContainText("庚辰 甲申 丙午 庚寅");
    await card.locator("summary").click();
    await expect(card.locator(".traditional-palaces section")).toHaveCount(12);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
}
