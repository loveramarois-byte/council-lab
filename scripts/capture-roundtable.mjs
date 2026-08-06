import { chromium } from "../frontend/node_modules/@playwright/test/index.mjs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = process.argv[2] || path.join(repoRoot, "docs/images/roundtable-v2.png");
const baseURL = process.env.COUNCIL_SHOWCASE_URL || "http://127.0.0.1:3000";
const now = "2026-07-28T10:30:00Z";

const participants = [
  { id: "analyst", name: "析理", role: "问题架构师", brief: "定义目标、终点与可证伪条件" },
  { id: "challenger", name: "诘问", role: "制度审查者", brief: "寻找反例、成本转移与激励漏洞" },
  { id: "builder", name: "构策", role: "政策设计师", brief: "把分歧转成可执行转型方案" },
  { id: "observer", name: "观澜", role: "风险与公平观察者", brief: "检查分配、公平与失败退出机制" },
];

const assignments = [
  ["analyst", "CC Switch", "gpt-5.6-sol"],
  ["challenger", "CC Switch", "claude-opus-5"],
  ["builder", "CC Switch", "claude-fable-5"],
  ["observer", "CC Switch", "gemini-3.1-pro-preview"],
].map(([role, provider_name, model]) => ({
  role,
  provider_id: provider_name === "CC Switch" ? "ccswitch" : provider_name.toLowerCase().replace(/\s+/g, "-"),
  provider_name,
  model,
  protocol: "auto",
  reasoning_effort: "high",
  max_output_tokens: 2800,
  temperature: 0.2,
  timeout_seconds: 120,
}));

const turns = [
  {
    id: "turn-1", speaker_type: "agent", speaker_id: "analyst", speaker_name: "析理", role_label: "问题架构师",
    content: "**先拆掉“AI 等于岗位消失”的前提。** 任务会先重组，真正要守住的是中位数实际收入、每周工时、再就业周期和代际流动。技术只提高 GDP 而不改善这四项，就不算成功。",
    provider_id: "ccswitch", provider_name: "CC Switch", model: "gpt-5.6-sol", round: 1, created_at: now,
  },
  {
    id: "turn-2", speaker_type: "agent", speaker_id: "challenger", speaker_name: "诘问", role_label: "制度审查者",
    content: "**反驳把全民基本收入当万能解。** 如果住房、医疗和教育供给不变，现金可能被价格吸收，还会默认人退出劳动市场。更稳的是工资保险、可携带福利与基本公共服务打底。",
    provider_id: "ccswitch", provider_name: "CC Switch", model: "claude-opus-5", round: 1, created_at: now,
  },
  {
    id: "turn-user", speaker_type: "user", speaker_id: "user", speaker_name: "你", role_label: "主持人",
    content: "别只谈制度。最终答案必须说明**普通人未来三年该学什么、老板为什么愿意缩短工时，以及改革失败时怎么止损**。",
    round: 1, created_at: now,
  },
  {
    id: "turn-3", speaker_type: "agent", speaker_id: "builder", speaker_name: "构策", role_label: "政策设计师",
    content: "**采纳质疑，改用双轨方案。** 企业只有分享 AI 增益才获税收抵扣，推动 32 小时工作周；个人能力按 20% AI 协作、35% 领域判断、25% 沟通担责、20% 可复用资产配置。",
    provider_id: "ccswitch", provider_name: "CC Switch", model: "claude-fable-5", round: 1, created_at: now,
  },
  {
    id: "turn-4", speaker_type: "agent", speaker_id: "observer", speaker_name: "观澜", role_label: "风险与公平观察者",
    content: "**部分认同，但反对按“机器人数量”征税。** 那会惩罚采用技术的小企业；应税的是超额利润和垄断租。试点须按地区、年龄和收入分层，两年未改善实际收入或再就业即退出。",
    provider_id: "ccswitch", provider_name: "CC Switch", model: "gemini-3.1-pro-preview", round: 1, created_at: now,
  },
];

const question = "当 AI 能完成大多数知识工作后，普通人靠什么获得收入、尊严和上升通道？社会应该先缩短工时、改革教育，还是重写分配规则？";
const run = {
  id: "showcase", question, mode: "rigorous", provider_id: "ccswitch", model: "gpt-5.6-sol", reasoning_effort: "high",
  workflow_engine: "langgraph", checkpoint_count: 9,
  context_snapshot: { strategy: "deterministic", token_budget: 12000, estimated_tokens: 6840, included_turns: 5, total_turns: 5, compacted: false, summary: "" },
  status: "completed", created_at: now, updated_at: now, analysis: null,
  candidates: [], critiques: [], verifications: [], revisions: [], scores: [],
  final_decision: {
    final_answer: "**最终裁决：不在缩短工时、改革教育和重新分配之间三选一，而是签订“AI 红利契约”。** 近期用工资保险、可携带福利和公共服务稳住转型；企业只有把生产率提升转成工资、32 小时工时或新增培训，才享受税收优惠。个人未来三年优先建立 AI 协作、领域判断、沟通担责和可复用数字资产。资金来自超额利润与垄断租，而非按机器人征税。每 24 个月用实际收入、工时、再就业周期和代际流动复评；两项连续恶化即暂停扩张并重配预算。",
    key_reasons: ["结果而非 GDP 优先", "企业分享效率红利", "个人能力组合", "失败可退出"],
    verified_claims: [], partially_verified_claims: [], contradicted_claims: [], unverified_claims: [],
    disagreements: ["全民基本收入是否应成为首要工具", "是否应按自动化设备征税"], risks_and_limitations: ["政策效果会因地区产业和公共服务供给而异"],
    confidence: { level: "medium", score: 0.76, explanation: "方向可检验，但具体税率和福利强度需要通过地区试点校准。" },
    sources: [],
    provider_summary: { provider: "Mixed providers", protocol: "openai-compatible", model: "gpt-4.1", used_ccswitch: false, degraded: false },
    usage: { model_calls: 5, tool_calls: 0, input_tokens: 18320, output_tokens: 3710, duration_ms: 78240 },
  },
  usage: { model_calls: 5, tool_calls: 0, input_tokens: 18320, output_tokens: 3710, duration_ms: 78240 },
  degraded: false, error: null, protocol: "responses", discussion_turns: turns, participant_roles: participants,
  current_speaker_index: 4, discussion_round: 1, awaiting_user: false,
  high_risk_control: false,
  limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 },
  seat_assignments: assignments, template_name: "演示会话 · 示例模型配置",
  finalizer_assignment: { ...assignments[0], role: "finalizer" },
  auto_summarize: false, recoverable: false, limit_reason: null,
};

const provider = {
  id: "ccswitch", preset_id: "ccswitch", display_name: "CC Switch", description: "本机路由",
  provider_type: "ccswitch", protocol_mode: "auto", base_url: "http://127.0.0.1:15721/v1",
  has_api_key: false, credential_source: "none", supports_api_key: false, requires_api_key: false,
  enabled: true, is_active: true, default_model: "gpt-5.6-sol", reasoning_effort: "high",
  available_models: assignments.map((item) => item.model), model_source: "provider", local_only: true, last_health_check: now, last_error: null,
};

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
  await page.route("**/api/providers", (route) => route.fulfill({ json: [provider] }));
  await page.route("**/api/runs/showcase", (route) => route.fulfill({ json: run }));
  await page.route("**/api/runs/showcase/decision-brief", (route) => route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "showcase fixture has no brief" }) }));
  await page.goto(`${baseURL}/runs/showcase`, { waitUntil: "networkidle" });
  await page.locator(".council-stage").waitFor();
  await page.addStyleTag({ content: `
    .council-stage { width: min(1320px, 100%); padding-top: 14px; }
    .council-question { grid-template-columns: 72px minmax(0, 1fr); }
    .council-question h1 { font-size: 18px; }
    .council-question p { display: none; }
    .council-seat { height: 74px; }
    .dialogue-scroll { padding: 10px 18px 8px; }
    .opening-question { max-width: 92%; margin-bottom: 9px; padding: 7px 11px; }
    .opening-question p { font-size: 12px; line-height: 1.42; }
    .discussion-turn { max-width: 96%; margin-bottom: 8px; padding: 8px 11px 9px; }
    .discussion-turn.user { max-width: 88%; }
    .discussion-turn .rich-text { margin-top: 6px; font-size: 12.5px; line-height: 1.48; }
    .roundtable-summary { margin-top: 10px; padding: 10px 13px 12px; }
    .roundtable-summary > .rich-text { margin-top: 7px; font-size: 12.5px; line-height: 1.5; }
    .decision-reading, .transcript-separator { display: none; }
    .completed-actions { display: none; }
  ` });
  await page.evaluate(() => document.fonts.ready);
  const layout = await page.evaluate(() => {
    const transcript = document.querySelector(".dialogue-scroll");
    const required = [...document.querySelectorAll(".discussion-turn")];
    return {
      overflow: transcript ? transcript.scrollHeight - transcript.clientHeight : 1,
      visibleBlocks: required.filter((node) => {
        const box = node.getBoundingClientRect();
        return box.top >= 0 && box.bottom <= window.innerHeight;
      }).length,
      requiredBlocks: required.length,
    };
  });
  if (layout.overflow > 1 || layout.visibleBlocks !== layout.requiredBlocks) {
    throw new Error(`Showcase content is clipped: ${JSON.stringify(layout)}`);
  }
  await page.screenshot({ path: output, fullPage: false });
  console.log(output);
} finally {
  await browser.close();
}
