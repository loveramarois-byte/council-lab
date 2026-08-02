import { expect, test } from "@playwright/test";


const now = "2026-08-02T00:00:00Z";
const provider = { id: "mock", preset_id: "mock", display_name: "本地演示", description: "不联网", provider_type: "mock", protocol_mode: "auto", base_url: "", has_api_key: false, credential_source: "none", supports_api_key: false, requires_api_key: false, enabled: true, is_active: true, default_model: "council-mock", reasoning_effort: "low", timeout_seconds: 30, max_retries: 0, available_models: ["council-mock"], model_source: "built_in", local_only: true, last_health_check: null, last_error: null, capabilities: {} };
const assignment = (role: string) => ({ role, provider_id: "mock", model: "council-mock", protocol: "auto", reasoning_effort: "low", max_output_tokens: 1200, temperature: 0.2, timeout_seconds: 30 });
const assignments = { schema_version: 2, seats: ["analyst", "challenger", "builder", "observer"].map(assignment), finalizer: assignment("finalizer") };
const templates = [
  { id: "open_discussion", name: "开放讨论", description: "通用", prompt_hint: "写下问题", system_guidance: "" },
  { id: "traditional_culture_review", name: "传统文化联合研判", description: "本地排盘后研判", prompt_hint: "说明希望研究的传统文化主题", system_guidance: "" },
];

async function mockHome(page: import("@playwright/test").Page) {
  await page.route("**/api/providers", (route) => route.fulfill({ json: [provider] }));
  await page.route("**/api/agent-assignments", (route) => route.fulfill({ json: assignments }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: templates }));
  await page.route("**/api/output-contracts", (route) => route.fulfill({ json: [{ id: "general_decision", name: "一般决策", description: "通用", input_checks: [], prompt_hint: "通用", system_guidance: "" }] }));
  await page.route("**/api/memory", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/memory/preview", (route) => route.fulfill({ json: { workspace_id: "default", selected_memory_ids: [], included: [], excluded_memory_ids: [], rendered_context: "" } }));
}

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

test("creates a traditional-culture Run only after local profile consent", async ({ page }) => {
  await mockHome(page);
  let payload: Record<string, any> = {};
  let readinessRequests = 0;
  await page.route("**/api/readiness", (route) => { readinessRequests += 1; return route.fulfill({ json: {} }); });
  await page.route("**/api/runs", (route) => { payload = route.request().postDataJSON(); return route.fulfill({ json: { id: "traditional-created" } }); });

  await page.goto("/");
  await page.getByRole("button", { name: "仅体验本地演示" }).click();
  await page.getByRole("button", { name: "传统文化" }).click();
  await expect(page.getByLabel("本地排盘资料")).toBeVisible();
  await expect(page.getByText("高风险决策支持", { exact: true })).toHaveCount(0);
  await expect(page.getByText("自动总结", { exact: true })).toHaveCount(0);

  const create = page.getByRole("button", { name: "排盘并进入研判" });
  await expect(create).toBeDisabled();
  await page.getByLabel("出生日期").fill("2000-08-16");
  await page.getByLabel("出生时间").fill("03:30");
  await page.getByRole("textbox", { name: "你的问题" }).fill("比较性情结构，并指出不可验证之处");
  await page.getByText("性情结构", { exact: true }).click();
  await page.getByText("我同意将排盘字段和必要出生参数发送给本次已配置的五个模型席位").click();
  await expect(create).toBeEnabled();
  await create.click();
  await page.waitForURL("**/runs/traditional-created");

  expect(readinessRequests).toBe(0);
  expect(payload).toMatchObject({ council_mode: "traditional_culture", workflow_strategy: "independent", template_id: "traditional_culture_review", traditional_culture_consent: true });
  expect(payload).not.toHaveProperty("high_risk");
  expect(payload).not.toHaveProperty("auto_summarize");
  expect(payload).not.toHaveProperty("selected_memory_ids");
  expect(payload.traditional_culture_snapshot.calendar_facts.eight_char).toBe("庚辰 甲申 丙午 庚寅");
  expect(payload.traditional_culture_snapshot.engines.map((engine: any) => `${engine.id}@${engine.version}`)).toEqual(["lunar-javascript@1.7.7", "iztro@2.5.8"]);
  expect(payload.traditional_culture_snapshot.snapshot_sha256).toMatch(/^[a-f0-9]{64}$/);
});

test("renders provenance and boundaries on a mobile result without decision assets", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const cultureSnapshot = snapshot();
  const run = { id: "traditional-result", question: "比较性情结构", mode: "standard", council_mode: "traditional_culture", workflow_strategy: "independent", provider_id: "mock", model: "council-mock", reasoning_effort: "high", workflow_engine: "langgraph", checkpoint_count: 5, status: "completed", created_at: now, updated_at: now, analysis: { expected_model_calls: 5 }, readiness: null, candidates: [], critiques: [], verifications: [], revisions: [], scores: [], final_decision: { final_answer: "## 计算快照\n四柱已冻结。\n## 反证与限制\n传统解释不可验证。", key_reasons: [], verified_claims: [], partially_verified_claims: [], contradicted_claims: [], unverified_claims: ["传统解释未验证"], disagreements: [], risks_and_limitations: ["不得用于高风险决策"], confidence: { level: "traditional_interpretation", explanation: "不提供正确率" }, sources: [], provider_summary: { provider: "Mock", protocol: "mock", model: "council-mock", used_ccswitch: false, degraded: false }, usage: { model_calls: 5, tool_calls: 0, input_tokens: 100, output_tokens: 50, duration_ms: 1000 } }, usage: { model_calls: 5, tool_calls: 0, input_tokens: 100, output_tokens: 50, duration_ms: 1000 }, degraded: false, protocol: "mock", context_snapshot: { strategy: "deterministic_context_clipping", token_budget: 4000, estimated_tokens: 10, included_turns: 0, total_turns: 0, compacted: false, summary: "" }, limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 }, discussion_turns: [], participant_roles: ["校历", "辨典", "参派", "证伪"].map((name, index) => ({ id: ["analyst", "challenger", "builder", "observer"][index], name, role: "专席", brief: "" })), seat_assignments: [], finalizer_assignment: null, current_speaker_index: 4, discussion_round: 1, awaiting_user: false, auto_summarize: false, high_risk_control: false, recoverable: false, template_name: "传统文化联合研判", traditional_culture_snapshot: cultureSnapshot, traditional_culture_consent: true };
  const assetRequests: string[] = [];
  page.on("request", (request) => { if (/decision-brief|claims|memory-proposals/.test(request.url())) assetRequests.push(request.url()); });
  await page.route("**/api/runs/traditional-result", (route) => route.fulfill({ json: run }));
  await page.goto("/runs/traditional-result");

  const card = page.getByLabel("传统文化本地计算快照");
  await expect(card).toContainText("庚辰 甲申 丙午 庚寅");
  await expect(card).toContainText("木三局");
  await expect(page.getByText("传统解释不属于科学验证")).toBeVisible();
  await expect(page.getByRole("button", { name: "结果回访" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "沉淀记忆" })).toHaveCount(0);
  await card.locator("summary").click();
  await expect(card.locator(".traditional-palaces section")).toHaveCount(12);
  await expect(card.getByRole("link", { name: /lunar-javascript@1.7.7/ })).toBeVisible();
  await expect.poll(() => assetRequests).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
