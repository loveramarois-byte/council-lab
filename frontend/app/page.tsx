"use client";

import Link from "next/link";
import { ArrowUp, Bot, ChevronDown, ChevronRight, CircleAlert, CircleCheck, LoaderCircle, Play, RefreshCw, Settings2, ShieldCheck, SlidersHorizontal, Sparkles, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AgentAssignmentsConfig, api, DecisionReadiness, DeliberationTemplate, MemoryPreview, MemoryView, OutputContractDefinition, OutputContractId, providerIsReady, Provider } from "../lib/api";

const modes = [
  { id: "quick", label: "快速审视", detail: "方向明确的小问题", budget: "1.8k", duration: "通常 1–3 分钟", icon: Zap },
  { id: "standard", label: "标准评审", detail: "多数产品与技术决策", budget: "4k", duration: "通常 2–5 分钟", icon: ShieldCheck },
  { id: "rigorous", label: "深度审议", detail: "复杂或难以逆转的选择", budget: "7k", duration: "通常 4–8 分钟", icon: Sparkles },
];

const exampleDecisions: Array<{
  label: string;
  question: string;
  templateId: string;
  outputContract: OutputContractId;
}> = [
  {
    label: "现在发布，还是延期？",
    question: "我们是否应该现在发布产品？核心功能已经完成，但仍有 3 个中等缺陷；本周发布能赶上行业活动。团队 4 人，可以在 48 小时内回滚。请比较现在发布与延期一周，给出选择、主要风险和退出条件。",
    templateId: "decision_review",
    outputContract: "product_review",
  },
  {
    label: "两套架构如何选择？",
    question: "新服务应该采用模块化单体还是微服务？团队 6 人，预计一年内从每天 5 万请求增长到 50 万请求，当前最重要的是交付速度和故障可恢复性。请比较两种方案，并给出迁移触发条件。",
    templateId: "decision_review",
    outputContract: "technical_architecture",
  },
  {
    label: "这个计划会怎样失败？",
    question: "假设我们的新产品在六个月后失败了：预算只能支撑 8 个月，目前有 20 位试用用户，还没有稳定付费渠道。请倒推最可能的失败原因、最早预警信号和本月应采取的预防动作。",
    templateId: "premortem",
    outputContract: "product_review",
  },
];

function readinessModeLabel(mode: string): string {
  return ({
    direct: "直接回答",
    quick_council: "快速圆桌",
    full_council: "完整圆桌",
    high_risk_council: "高风险控制流程",
    manual_review: "人工确认后继续",
  } as Record<string, string>)[mode] || "按当前配置";
}

function readinessTaskLabel(label: string): string {
  return ({
    analysis: "分析任务",
    decision: "决策问题",
    high_risk: "可能涉及高风险",
    readiness_unavailable: "检查状态未知",
  } as Record<string, string>)[label] || label.replaceAll("_", " ");
}

const defaultContracts: OutputContractDefinition[] = [{
  id: "general_decision",
  name: "一般决策",
  description: "比较目标、约束、选项、取舍和退出条件。",
  input_checks: ["决策目标", "关键约束", "候选方案", "成功标准"],
  prompt_hint: "说明要做的决定、约束、候选方案和怎样算成功。",
  system_guidance: "",
}];

export default function HomePage() {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("standard");
  const [workflowStrategy, setWorkflowStrategy] = useState<"sequential" | "independent">("sequential");
  const [highRisk, setHighRisk] = useState(false);
  const [autoSummarize, setAutoSummarize] = useState(false);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [assignments, setAssignments] = useState<AgentAssignmentsConfig | null>(null);
  const [templates, setTemplates] = useState<DeliberationTemplate[]>([]);
  const [outputContracts, setOutputContracts] = useState<OutputContractDefinition[]>(defaultContracts);
  const [memories, setMemories] = useState<MemoryView[]>([]);
  const [selectedMemoryIds, setSelectedMemoryIds] = useState<string[]>([]);
  const [memoryPreview, setMemoryPreview] = useState<MemoryPreview | null>(null);
  const [templateId, setTemplateId] = useState("open_discussion");
  const [outputContract, setOutputContract] = useState<OutputContractId>("general_decision");
  const [demoAcknowledged, setDemoAcknowledged] = useState(false);
  const [configState, setConfigState] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [readiness, setReadiness] = useState<DecisionReadiness | null>(null);
  const [readinessOverride, setReadinessOverride] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [setupNotice, setSetupNotice] = useState(false);

  const loadConfiguration = useCallback(async () => {
    setConfigState("loading");
    setLoadError("");
    try {
      const [items, config, templateItems, contractItems, memoryItems] = await Promise.all([api.providers(), api.assignments(), api.templates(), api.outputContracts().catch(() => defaultContracts), api.memory().catch(() => [])]);
      setProviders(items);
      setAssignments(config);
      setTemplates(templateItems);
      setOutputContracts(contractItems.length ? contractItems : defaultContracts);
      setMemories(memoryItems.filter((item) => item.active && !item.deleted));
      setDemoAcknowledged(false);
      setConfigState("ready");
    } catch (nextError) {
      setConfigState("error");
      setLoadError(nextError instanceof Error ? nextError.message : "无法读取本地配置");
    }
  }, []);

  useEffect(() => { void loadConfiguration(); }, [loadConfiguration]);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("configured") !== "1") return;
    setSetupNotice(true);
    window.history.replaceState({}, "", "/");
  }, []);
  useEffect(() => {
    let cancelled = false;
    void api.memoryPreview(selectedMemoryIds).then((value) => { if (!cancelled) setMemoryPreview(value); }).catch(() => { if (!cancelled) setMemoryPreview(null); });
    return () => { cancelled = true; };
  }, [selectedMemoryIds]);
  useEffect(() => { setReadiness(null); setReadinessOverride(false); }, [question, highRisk]);

  const selectedMode = useMemo(() => modes.find((item) => item.id === mode)!, [mode]);
  const selectedTemplate = templates.find((item) => item.id === templateId);
  const selectedContract = outputContracts.find((item) => item.id === outputContract);
  const generalTemplates = templates.filter((item) => !item.requires_high_risk);
  const professionalTemplates = templates.filter((item) => item.requires_high_risk);
  const generalContracts = outputContracts.filter((item) => !item.requires_high_risk);
  const professionalContracts = outputContracts.filter((item) => item.requires_high_risk);
  const professionalModeRequired = Boolean(selectedTemplate?.requires_high_risk || selectedContract?.requires_high_risk || readiness?.recommended_mode === "high_risk_council");
  const allAssignments = assignments ? [...assignments.seats, assignments.finalizer] : [];
  const hasFiveAssignments = allAssignments.length === 5;
  const mockSeatCount = allAssignments.filter((item) => item.provider_id === "mock").length;
  const hasDemoSeats = mockSeatCount > 0;
  const configurationRunnable = configState === "ready" && hasFiveAssignments && allAssignments.every((assignment) => {
    if (assignment.provider_id === "mock") return true;
    const provider = providers.find((item) => item.id === assignment.provider_id);
    return Boolean(provider && providerIsReady(provider));
  });
  const configurationReady = configurationRunnable && mockSeatCount === 0;
  const unreadyRealSeatCount = allAssignments.filter((assignment) => {
    if (assignment.provider_id === "mock") return false;
    const provider = providers.find((item) => item.id === assignment.provider_id);
    return !provider || !providerIsReady(provider);
  }).length;
  const realProviderReady = providers.some(providerIsReady);
  const setupHref = realProviderReady ? "/settings/agents" : "/settings/providers";
  const setupLabel = realProviderReady ? "配置五个席位" : "连接真实 AI";
  const activeProviderNames = assignments
    ? new Set(allAssignments.map((assignment) => providers.find((item) => item.id === assignment.provider_id)?.display_name || assignment.provider_id))
    : new Set<string>();
  const demoDisclosure = mockSeatCount === 5
    ? "回复为预设示例，不调用真实 AI。"
    : `${mockSeatCount} 个席位使用预设示例，其余席位调用已配置的真实 AI。`;
  const topStatus = configState === "loading"
    ? "正在读取席位"
    : configState === "error"
      ? "席位配置读取失败"
      : configurationReady
        ? "五席真实 AI 已就绪"
        : configurationRunnable
          ? demoAcknowledged
            ? mockSeatCount === 5 ? "本地演示已就绪" : `混合配置已确认 · ${mockSeatCount} 个演示席`
            : `${mockSeatCount} 个本地演示席 · 需确认`
          : "席位配置未就绪";

  const useExample = (example: (typeof exampleDecisions)[number]) => {
    setQuestion(example.question);
    setTemplateId(example.templateId);
    setOutputContract(example.outputContract);
    setHighRisk(false);
    setAutoSummarize(false);
  };

  const submit = async (forceOverride = false) => {
    if (question.trim().length < 3 || sending || configState !== "ready" || !configurationRunnable || (hasDemoSeats && !demoAcknowledged)) return;
    setSending(true);
    setError("");
    try {
      let assessment = readiness;
      if (!assessment) {
        try {
          assessment = await api.readiness(question.trim(), highRisk);
          setReadiness(assessment);
        } catch {
          assessment = {
            ready: false,
            task_labels: ["readiness_unavailable"],
            checks: [],
            clarification_questions: ["目标：这次具体要做出什么决定？", "约束：时间、预算或不能触碰的边界是什么？", "选项：目前有哪些候选方案？", "成功标准：怎样的结果才算值得执行？"],
            recommended_mode: "full_council",
            rules_version: "readiness_unavailable",
          };
          setReadiness(assessment);
        }
      }
      const mustUseHighRisk = Boolean(highRisk || selectedTemplate?.requires_high_risk || selectedContract?.requires_high_risk || assessment.recommended_mode === "high_risk_council");
      if (mustUseHighRisk && !highRisk) {
        setHighRisk(true);
        setAutoSummarize(false);
      }
      if (!assessment.ready && !mustUseHighRisk && !readinessOverride && !forceOverride) {
        setSending(false);
        return;
      }
      const run = await api.createRun({
        question: question.trim(),
        mode,
        ...(workflowStrategy === "independent" ? { workflow_strategy: "independent" as const } : {}),
        use_saved_assignments: true,
        template_id: templateId,
        ...(outputContract === "general_decision" ? {} : { output_contract: outputContract }),
        ...(selectedMemoryIds.length ? { selected_memory_ids: selectedMemoryIds } : {}),
        ...(autoSummarize && !mustUseHighRisk ? { auto_summarize: true } : {}),
        ...(mustUseHighRisk ? { high_risk: true } : {}),
        ...(!assessment.ready && !mustUseHighRisk && (readinessOverride || forceOverride) ? { readiness_override: true, readiness_override_reason: "用户查看准备度缺口后选择继续" } : {}),
      });
      router.push(`/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法创建审议任务");
      setSending(false);
    }
  };

  return <div className="page-wrap home-page">
    <header className="topbar"><div><span className="top-kicker">工作台 / 新建审议</span><span className="top-title">Council 圆桌</span></div><div className={`top-meta ${hasDemoSeats || configState === "error" ? "demo" : ""}`}><span className="status-dot" />{topStatus}</div></header>

    <section className="home-command">
      <div><h1>四种视角，你也在场。</h1><p>依次发言、公开回应；短定义与确定性计算会自动精简调用。</p></div>
      <div className="council-sequence" aria-label="审议顺序"><span title="分析"><b>析</b><small>分析</small></span><ChevronRight size={12} /><span title="追问"><b>诘</b><small>追问</small></span><ChevronRight size={12} /><span title="构建"><b>构</b><small>构建</small></span><ChevronRight size={12} /><span title="反观"><b>观</b><small>反观</small></span><ChevronRight size={12} /><strong title="结论"><b>答</b><small>结论</small></strong></div>
    </section>

    <section className={`home-workbench ${hasDemoSeats ? "demo-workbench" : ""} ${setupNotice ? "has-setup-notice" : ""}`} aria-label="新建审议">
      {setupNotice && <div className="setup-complete-notice" role="status"><CircleCheck size={15} /><span><strong>五席已配置完成</strong><small>现在可以直接输入问题开始审议。</small></span><button type="button" aria-label="关闭配置完成提示" title="关闭" onClick={() => setSetupNotice(false)}>×</button></div>}
      {configState === "loading" ? <div className="first-run-gate" role="status" aria-label="正在读取席位配置">
        <div className="first-run-mark"><LoaderCircle className="spin" size={23} /></div>
        <div className="first-run-copy"><span className="section-label">席位检查</span><h2>正在读取五席配置。</h2><p>配置确认前不会开放提问，避免使用尚未就绪或来源不明的席位。</p></div>
      </div> : configState === "error" ? <div className="first-run-gate" role="alert" aria-label="席位配置读取失败">
        <div className="first-run-mark"><CircleAlert size={23} /></div>
        <div className="first-run-copy"><span className="section-label">读取失败</span><h2>暂时无法确认五席配置。</h2><p>{loadError}。配置恢复前不会开放提问。</p></div>
        <div className="first-run-actions"><button type="button" className="send-button" onClick={() => void loadConfiguration()}><RefreshCw size={15} />重新读取</button></div>
      </div> : !configurationRunnable ? <div className="first-run-gate" role="region" aria-label="席位配置未就绪">
        <div className="first-run-mark"><CircleAlert size={23} /></div>
        <div className="first-run-copy"><span className="section-label">尚未就绪</span><h2>五席配置还不能运行。</h2><p>{unreadyRealSeatCount > 0 ? `${unreadyRealSeatCount} 个真实 AI 席位的 Provider 尚未通过就绪检查。` : "席位数量或 Provider 引用不完整。"} 请先检查 Provider，再确认五个席位的选择。</p></div>
        <div className="first-run-actions">
          <Link className="send-button" href="/settings/providers"><Settings2 size={15} />检查 Provider<ChevronRight size={14} /></Link>
          <Link className="quiet-button" href="/settings/agents">调整席位</Link>
        </div>
      </div> : hasDemoSeats && !demoAcknowledged ? <div className="first-run-gate" role="region" aria-label="本地演示席确认">
        <div className="first-run-mark"><Bot size={23} /></div>
        <div className="first-run-copy"><span className="section-label">第一次使用</span><h2>{mockSeatCount === 5 ? "无需 API Key，先完成一次决策。" : `当前配置包含 ${mockSeatCount} 个本地演示席。`}</h2><p>{mockSeatCount === 5 ? "本地演示使用预设回复，不联网、不产生模型费用。你可以先走完整个圆桌流程，再决定是否连接真实 AI。" : `${demoDisclosure} 继续前请确认你接受这套混合席位配置。`}</p></div>
        <div className="first-run-actions">
          <button type="button" className="send-button" onClick={() => setDemoAcknowledged(true)}>{mockSeatCount === 5 ? <><Play size={15} />开始本地演示</> : <>确认混合配置并继续<ChevronRight size={14} /></>}</button>
          <Link className="quiet-button" href={setupHref}><Settings2 size={15} />{setupLabel}</Link>
        </div>
      </div> : <>
        {hasDemoSeats && <div className="demo-disclosure"><CircleAlert size={15} /><span><strong>{mockSeatCount === 5 ? "本地演示模式" : `混合配置 · ${mockSeatCount} 个本地演示席`}</strong> · {demoDisclosure}</span><Link href={setupHref}>{setupLabel}<ChevronRight size={13} /></Link></div>}
        <div className="composer-section">
          <div className="composer-head">
            <div><span className="section-label">你需要做什么决定？</span><span className="section-hint">写清目标、约束、选项和成功标准，结论会更可靠</span></div>
            <label className="template-select"><span>决策类型</span><select aria-label="审议模板" value={templateId} onChange={(event) => { const nextTemplate = event.target.value; const definition = templates.find((item) => item.id === nextTemplate); setTemplateId(nextTemplate); if (definition?.default_output_contract) setOutputContract(definition.default_output_contract); if (definition?.requires_high_risk) { setHighRisk(true); setAutoSummarize(false); } }}><optgroup label="通用">{generalTemplates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</optgroup>{professionalTemplates.length > 0 && <optgroup label="专业领域">{professionalTemplates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</optgroup>}</select></label>
            <button type="button" className={`advanced-home-toggle ${advancedOpen ? "open" : ""}`} aria-expanded={advancedOpen} aria-controls="advanced-run-settings" onClick={() => setAdvancedOpen((value) => !value)}><SlidersHorizontal size={14} /><span>高级设置</span><ChevronDown size={14} /></button>
            <span className="composer-count">{question.length.toString().padStart(3, "0")} / 12000</span>
          </div>
          {advancedOpen && <div id="advanced-run-settings" className="advanced-run-settings">
            <label className="template-select"><span>发言策略</span><select aria-label="发言策略" value={workflowStrategy} onChange={(event) => setWorkflowStrategy(event.target.value as "sequential" | "independent")}><option value="sequential">连续审议</option><option value="independent">先独立初答</option></select></label>
            <label className="template-select contract-select"><span>结果结构</span><select aria-label="输出契约" value={outputContract} onChange={(event) => { const nextContract = event.target.value as OutputContractId; const definition = outputContracts.find((item) => item.id === nextContract); setOutputContract(nextContract); if (definition?.requires_high_risk) { setHighRisk(true); setAutoSummarize(false); } }}>{generalContracts.map((contract) => <option key={contract.id} value={contract.id}>{contract.name}</option>)}{professionalContracts.length > 0 && <optgroup label="专业领域">{professionalContracts.map((contract) => <option key={contract.id} value={contract.id}>{contract.name}</option>)}</optgroup>}</select></label>
            <span>默认设置适合大多数决策；更改只影响本次圆桌。</span>
          </div>}
          <div className="composer-input">
            <textarea aria-label="你的问题" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit(); }} placeholder={selectedTemplate?.prompt_hint || "写下需要四席共同审议的问题"} title={selectedContract?.prompt_hint} rows={5} />
            {question.length === 0 && <div className="prompt-starters" aria-label="示例决策"><span>从一个实际问题开始</span><div>{exampleDecisions.map((example) => <button key={example.label} type="button" onClick={() => useExample(example)}>{example.label}<ChevronRight size={13} /></button>)}</div></div>}
          </div>
          {readiness && <section className={`readiness-panel ${readiness.ready ? "ready" : "needs-input"}`} aria-label="决策准备度"><header><div><strong>{readiness.ready ? "可以开始审议" : readiness.rules_version === "readiness_unavailable" ? "准备度检查暂时不可用" : "开始前还有信息缺口"}</strong><small>{readiness.rules_version === "readiness_unavailable" ? "请先自行确认这些关键信息" : `系统建议：${readinessModeLabel(readiness.recommended_mode)}`}</small></div><span>{readiness.task_labels.map(readinessTaskLabel).join(" · ")}</span></header>{readiness.clarification_questions.length > 0 && <ul>{readiness.clarification_questions.map((item) => <li key={item}>{item}</li>)}</ul>}{!readiness.ready && (professionalModeRequired ? <footer><span>该问题必须进入高风险控制面补充关键事实，系统会自动启用证据与专业复核流程。</span></footer> : <footer><span>{readiness.rules_version === "readiness_unavailable" ? "系统无法代你检查；确认信息足够后，仍可明确选择继续。" : "你可以补充问题，也可以明确保留这些缺口并继续。"}</span><button type="button" className="quiet-button" onClick={() => { setReadinessOverride(true); void submit(true); }}>仍然继续</button></footer>)}</section>}
          {memories.length > 0 && <section className="memory-picker" aria-label="本次使用的已批准记忆"><header><div><strong>本次可用的已批准记忆</strong><small>默认不注入，只有你明确勾选的内容才会进入本次 Run。</small></div><span>{selectedMemoryIds.length} / {memories.length}</span></header><div>{memories.map((item) => <label key={item.memory.id}><input type="checkbox" checked={selectedMemoryIds.includes(item.memory.id)} onChange={(event) => setSelectedMemoryIds((current) => event.target.checked ? [...current, item.memory.id] : current.filter((id) => id !== item.memory.id))} /><span><strong>{item.memory.type}</strong>{item.memory.content}</span></label>)}</div>{memoryPreview && selectedMemoryIds.length > 0 && <details><summary>查看实际注入快照</summary><pre>{memoryPreview.rendered_context || "所选记忆当前不可用，不会注入。"}</pre></details>}</section>}
          <div className="composer-footer"><label className={`risk-mode-toggle ${highRisk || professionalModeRequired ? "active" : ""}`}><input type="checkbox" checked={highRisk || professionalModeRequired} disabled={professionalModeRequired} onChange={(event) => { const checked = event.target.checked; setHighRisk(checked); if (checked) setAutoSummarize(false); }} /><span className={`toggle ${highRisk || professionalModeRequired ? "on" : ""}`} /><span><strong>高风险决策支持</strong><small>{professionalModeRequired ? "专业领域强制开启" : highRisk ? "关键事实与人工审批" : "关闭"}</small></span></label>{!highRisk && !professionalModeRequired && <label className={`risk-mode-toggle ${autoSummarize ? "active" : ""}`}><input type="checkbox" checked={autoSummarize} onChange={(event) => setAutoSummarize(event.target.checked)} /><span className={`toggle ${autoSummarize ? "on" : ""}`} /><span><strong>自动总结</strong><small>{autoSummarize ? "讨论席结束后直接生成答案" : "默认等待你的确认"}</small></span></label>}<button type="button" className="send-button" disabled={question.trim().length < 3 || sending || !configurationRunnable || (hasDemoSeats && !demoAcknowledged)} onClick={() => submit()}>{sending ? "正在入席" : "进入圆桌"}<ArrowUp size={17} /></button></div>
          {error && <p className="form-error" role="alert">{error}</p>}
        </div>
      </>}
    </section>

    <section className="mode-section"><div className="mode-heading"><div><span className="section-label">审议深度</span><span className="section-hint">标准评审适合大多数决策</span></div><span className="section-hint">问题越复杂，越需要更多上下文和交叉检验</span></div><div className="mode-grid">{modes.map(({ id, label, detail, budget, duration, icon: Icon }) => <button key={id} type="button" aria-label={`${label}，${detail}，${duration}，${budget} 上下文`} aria-pressed={mode === id} className={`mode-option ${mode === id ? "selected" : ""}`} onClick={() => setMode(id)}><span className="mode-icon"><Icon size={16} /></span><span><strong>{label}</strong><small>{detail}</small></span><span className="mode-duration">{duration}</span><span className="radio-dot" /></button>)}</div><div className="estimate-line"><span><span className="estimate-bar" />{selectedMode.duration} · 通常 5 次调用，短任务自动精简为 2 次</span><span>{selectedMode.budget} 席位上下文 · 实际耗时与费用由 Provider 决定 · {configState === "loading" ? "配置加载中" : configState === "error" ? "配置读取失败" : configurationReady ? `${activeProviderNames.size} 个 Provider 已就绪` : configurationRunnable ? `${mockSeatCount} 个本地演示席` : "席位未就绪"}</span></div></section>
  </div>;
}