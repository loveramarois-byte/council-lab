import { chromium } from "../frontend/node_modules/@playwright/test/index.mjs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = process.argv[2] || path.join(repoRoot, "docs/images/roundtable-v2.png");
const baseURL = process.env.COUNCIL_SHOWCASE_URL || "http://127.0.0.1:3000";
const apiURL = process.env.COUNCIL_SHOWCASE_API_URL || "http://127.0.0.1:8001";
const now = "2026-07-28T10:30:00Z";

const participants = [
  { id: "analyst", name: "析理", role: "问题架构师", brief: "定义目标、终点与可证伪条件" },
  { id: "challenger", name: "诘问", role: "证据审查者", brief: "寻找反例、偏差与代理终点陷阱" },
  { id: "builder", name: "构策", role: "研究组合设计师", brief: "把分歧转成可执行投资组合" },
  { id: "observer", name: "观澜", role: "风险与伦理观察者", brief: "检查公平性、退出规则与长期风险" },
];

const assignments = [
  ["analyst", "OpenAI", "gpt-5.4"],
  ["challenger", "DeepSeek", "deepseek-reasoner"],
  ["builder", "智谱 GLM", "glm-4.7"],
  ["observer", "Kimi", "kimi-k2.5"],
].map(([role, provider_name, model]) => ({
  role,
  provider_id: provider_name.toLowerCase().replace(/\s+/g, "-"),
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
    content: "**先把成功定义清楚。** 主终点必须是发病率、认知/功能进展与生活质量；生物标志物只用于分层和早停。所有路径都要预注册、跨队列复现，并公开失败数据。",
    provider_id: "openai", provider_name: "OpenAI", model: "gpt-5.4", round: 1, created_at: now,
  },
  {
    id: "turn-2", speaker_type: "agent", speaker_id: "challenger", speaker_name: "诘问", role_label: "证据审查者",
    content: "**反驳单一靶点优先。** 淀粉样蛋白下降不自动等于患者获益，高收入地区样本也不能外推全球。若没有跨机制对照和代表性门槛，只会得到更精致的代理终点竞赛。",
    provider_id: "deepseek", provider_name: "DeepSeek", model: "deepseek-reasoner", round: 1, created_at: now,
  },
  {
    id: "turn-user", speaker_type: "user", speaker_id: "user", speaker_name: "你", role_label: "主持人",
    content: "不要只给方向。最终方案必须写明**预算比例、两年里程碑和停止规则**，并允许阴性证据触发资金重配。",
    round: 1, created_at: now,
  },
  {
    id: "turn-3", speaker_type: "agent", speaker_id: "builder", speaker_name: "构策", role_label: "研究组合设计师",
    content: "**采纳质疑并组合下注：** 35% 全球纵向队列与数据标准，30% 机制分层平台试验，20% 血管/代谢/睡眠预防，15% 独立复现。每 24 个月按预设门槛重配预算。",
    provider_id: "zhipu", provider_name: "智谱 GLM", model: "glm-4.7", round: 1, created_at: now,
  },
  {
    id: "turn-4", speaker_type: "agent", speaker_id: "observer", speaker_name: "观澜", role_label: "风险与伦理观察者",
    content: "**部分认同，补上硬约束。** 连续两阶段未达最小临床重要差异即停；算法须跨族群校准，阴性结果强制公开；不可逆采样、知情同意与欠代表群体由独立伦理组审计。",
    provider_id: "kimi", provider_name: "Kimi", model: "kimi-k2.5", round: 1, created_at: now,
  },
];

const question = "未来十年，怎样设计一套可证伪的阿尔茨海默病研究组合，同时降低发病率、延缓病程，并避免重复押注失败的单一靶点？";
const run = {
  id: "showcase", question, mode: "rigorous", provider_id: "ccswitch", model: "gpt-5.6-sol", reasoning_effort: "high",
  workflow_engine: "langgraph", checkpoint_count: 9,
  context_snapshot: { strategy: "deterministic", token_budget: 12000, estimated_tokens: 6840, included_turns: 5, total_turns: 5, compacted: false, summary: "" },
  status: "completed", created_at: now, updated_at: now, analysis: null,
  candidates: [], critiques: [], verifications: [], revisions: [], scores: [],
  final_decision: {
    final_answer: "**最终裁决：采用可重配的组合投资，不押注单一病理机制。** 初始预算为 35% 全球队列与共享数据、30% 机制分层平台试验、20% 可干预预防、15% 独立复现。每 24 个月按临床进展、跨队列复现、代表性和成本效果四项门槛重配；连续两阶段未达最小临床重要差异即停止。保留淀粉样蛋白、tau、神经炎症与血管代谢路径的竞争性检验，并强制公开阴性结果。",
    key_reasons: ["临床终点优先", "跨机制竞争", "预算可重配", "阴性结果公开"],
    verified_claims: [], partially_verified_claims: [], contradicted_claims: [], unverified_claims: [],
    disagreements: ["单一靶点是否值得优先下注"], risks_and_limitations: ["需要真实试验数据持续校准"],
    confidence: { level: "medium", score: 0.76, explanation: "组合逻辑稳健，但具体比例仍需真实成本与试验数据校准。" },
    sources: [],
    provider_summary: { provider: "CC Switch", protocol: "responses", model: "gpt-5.6-sol", used_ccswitch: true, degraded: false },
    usage: { model_calls: 5, tool_calls: 0, input_tokens: 18320, output_tokens: 3710, duration_ms: 78240 },
  },
  usage: { model_calls: 5, tool_calls: 0, input_tokens: 18320, output_tokens: 3710, duration_ms: 78240 },
  degraded: false, error: null, protocol: "responses", discussion_turns: turns, participant_roles: participants,
  current_speaker_index: 4, discussion_round: 1, awaiting_user: false,
  limits: { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 },
  seat_assignments: assignments,
  finalizer_assignment: { ...assignments[0], role: "finalizer", provider_id: "ccswitch", provider_name: "CC Switch", model: "gpt-5.6-sol" },
  auto_summarize: false, recoverable: false, limit_reason: null,
};

const provider = {
  id: "ccswitch", preset_id: "ccswitch", display_name: "CC Switch", description: "本机模型路由",
  provider_type: "openai_compatible", protocol_mode: "responses", base_url: "http://127.0.0.1:15721/v1",
  has_api_key: true, credential_source: "system", supports_api_key: false, requires_api_key: false,
  enabled: true, is_active: true, default_model: "gpt-5.6-sol", reasoning_effort: "high",
  available_models: ["gpt-5.6-sol"], local_only: true, last_health_check: now, last_error: null,
};

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
  await page.route(`${apiURL}/api/providers`, (route) => route.fulfill({ json: [provider] }));
  await page.route(`${apiURL}/api/runs/showcase`, (route) => route.fulfill({ json: run }));
  await page.goto(`${baseURL}/runs/showcase`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: question }).waitFor();
  await page.addStyleTag({ content: `
    .council-stage { width: min(1320px, 100%); padding-top: 14px; }
    .council-question { grid-template-columns: 72px minmax(0, 1fr); }
    .council-question h1 { font-size: 18px; }
    .council-question p { display: none; }
    .council-seat { height: 74px; }
    .dialogue-scroll { padding: 12px 18px 14px; }
    .opening-question { max-width: 92%; margin-bottom: 9px; padding: 7px 11px; }
    .opening-question p { font-size: 12px; line-height: 1.42; }
    .discussion-turn { max-width: 96%; margin-bottom: 8px; padding: 8px 11px 9px; }
    .discussion-turn.user { max-width: 88%; }
    .discussion-turn .rich-text { margin-top: 6px; font-size: 12.5px; line-height: 1.48; }
    .roundtable-summary { margin-top: 10px; padding: 10px 13px 12px; }
    .roundtable-summary > .rich-text { margin-top: 7px; font-size: 12.5px; line-height: 1.5; }
    .completed-actions { display: none; }
  ` });
  await page.evaluate(() => document.fonts.ready);
  const layout = await page.evaluate(() => {
    const transcript = document.querySelector(".dialogue-scroll");
    const required = [...document.querySelectorAll(".discussion-turn, .roundtable-summary")];
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
