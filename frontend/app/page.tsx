"use client";

import Link from "next/link";
import { ArrowUp, Bot, ChevronRight, CircleAlert, LoaderCircle, RefreshCw, Settings2, ShieldCheck, Sparkles, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AgentAssignmentsConfig, api, DecisionReadiness, DeliberationTemplate, MemoryPreview, MemoryView, OutputContractDefinition, OutputContractId, providerIsReady, Provider } from "../lib/api";

const modes = [
  { id: "quick", label: "引导", detail: "4 席 · 1.8k 上下文", icon: Zap },
  { id: "standard", label: "圆桌", detail: "4 席 · 4k 上下文", icon: ShieldCheck },
  { id: "rigorous", label: "深挖", detail: "4 席 · 7k 上下文", icon: Sparkles },
];

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
    let cancelled = false;
    void api.memoryPreview(selectedMemoryIds).then((value) => { if (!cancelled) setMemoryPreview(value); }).catch(() => { if (!cancelled) setMemoryPreview(null); });
    return () => { cancelled = true; };
  }, [selectedMemoryIds]);
  useEffect(() => { setReadiness(null); setReadinessOverride(false); }, [question, highRisk]);

  const selectedMode = useMemo(() => modes.find((item) => item.id === mode)!, [mode]);
  const selectedTemplate = templates.find((item) => item.id === templateId);
  const selectedContract = outputContracts.find((item) => item.id === outputContract);
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
          ? `${mockSeatCount} 个本地演示席 · 需确认`
          : "席位配置未就绪";

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
          assessment = { ready: true, task_labels: ["analysis"], checks: [], clarification_questions: [], recommended_mode: "full_council", rules_version: "server_fallback" };
        }
      }
      if (!assessment.ready && !highRisk && !readinessOverride && !forceOverride) {
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
        ...(autoSummarize && !highRisk ? { auto_summarize: true } : {}),
        ...(highRisk ? { high_risk: true } : {}),
        ...(!assessment.ready && !highRisk && (readinessOverride || forceOverride) ? { readiness_override: true, readiness_override_reason: "用户查看准备度缺口后选择继续" } : {}),
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
      <div className="council-sequence" aria-label="四席顺序"><span>析</span><ChevronRight size={12} /><span>诘</span><ChevronRight size={12} /><span>构</span><ChevronRight size={12} /><span>观</span><ChevronRight size={12} /><strong>答</strong></div>
    </section>

    <section className={`home-workbench ${hasDemoSeats ? "demo-workbench" : ""}`} aria-label="新建审议">
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
        <div className="first-run-copy"><span className="section-label">开始之前</span><h2>{mockSeatCount === 5 ? "当前五席还是本地演示。" : `当前五席含 ${mockSeatCount} 个本地演示席。`}</h2><p>{demoDisclosure} 正式使用前，请连接模型并为五个席位选择已就绪的 Provider 与模型。</p></div>
        <div className="first-run-actions">
          <Link className="send-button" href={setupHref}><Settings2 size={15} />{setupLabel}<ChevronRight size={14} /></Link>
          <button type="button" className="quiet-button" onClick={() => setDemoAcknowledged(true)}>{mockSeatCount === 5 ? "仅体验本地演示" : "接受混合配置并继续"}</button>
        </div>
      </div> : <>
        {hasDemoSeats && <div className="demo-disclosure"><CircleAlert size={15} /><span><strong>{mockSeatCount === 5 ? "本地演示模式" : `混合配置 · ${mockSeatCount} 个本地演示席`}</strong> · {demoDisclosure}</span><Link href={setupHref}>{setupLabel}<ChevronRight size={13} /></Link></div>}
        <div className="composer-section">
          <div className="composer-head"><div><span className="section-label">你的问题</span><span className="section-hint">{selectedTemplate?.name || "开放讨论"} · {selectedContract?.name || "一般决策"}</span></div><label className="template-select"><span>审议方式</span><select aria-label="审议模板" value={templateId} onChange={(event) => setTemplateId(event.target.value)}>{templates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</select></label><label className="template-select"><span>发言策略</span><select aria-label="发言策略" value={workflowStrategy} onChange={(event) => setWorkflowStrategy(event.target.value as "sequential" | "independent")}><option value="sequential">连续审议</option><option value="independent">先独立初答</option></select></label><label className="template-select contract-select"><span>结果类型</span><select aria-label="输出契约" value={outputContract} onChange={(event) => setOutputContract(event.target.value as OutputContractId)}>{outputContracts.map((contract) => <option key={contract.id} value={contract.id}>{contract.name}</option>)}</select></label><span className="composer-count">{question.length.toString().padStart(3, "0")} / 12000</span></div>
          <textarea aria-label="你的问题" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit(); }} placeholder={selectedTemplate?.prompt_hint || "写下需要四席共同审议的问题"} title={selectedContract?.prompt_hint} rows={5} />
          {readiness && <section className={`readiness-panel ${readiness.ready ? "ready" : "needs-input"}`} aria-label="决策准备度"><header><div><strong>{readiness.ready ? "可以开始审议" : "开始前还有信息缺口"}</strong><small>系统建议：{readiness.recommended_mode}</small></div><span>{readiness.task_labels.join(" · ")}</span></header>{readiness.clarification_questions.length > 0 && <ul>{readiness.clarification_questions.map((item) => <li key={item}>{item}</li>)}</ul>}{!readiness.ready && <footer><span>你可以补充问题，也可以明确保留这些缺口并继续。</span><button type="button" className="quiet-button" onClick={() => { setReadinessOverride(true); void submit(true); }}>仍然继续</button></footer>}</section>}
          {memories.length > 0 && <section className="memory-picker" aria-label="本次使用的已批准记忆"><header><div><strong>本次可用的已批准记忆</strong><small>默认不注入，只有你明确勾选的内容才会进入本次 Run。</small></div><span>{selectedMemoryIds.length} / {memories.length}</span></header><div>{memories.map((item) => <label key={item.memory.id}><input type="checkbox" checked={selectedMemoryIds.includes(item.memory.id)} onChange={(event) => setSelectedMemoryIds((current) => event.target.checked ? [...current, item.memory.id] : current.filter((id) => id !== item.memory.id))} /><span><strong>{item.memory.type}</strong>{item.memory.content}</span></label>)}</div>{memoryPreview && selectedMemoryIds.length > 0 && <details><summary>查看实际注入快照</summary><pre>{memoryPreview.rendered_context || "所选记忆当前不可用，不会注入。"}</pre></details>}</section>}
          <div className="composer-footer"><label className={`risk-mode-toggle ${highRisk ? "active" : ""}`}><input type="checkbox" checked={highRisk} onChange={(event) => { const checked = event.target.checked; setHighRisk(checked); if (checked) setAutoSummarize(false); }} /><span className={`toggle ${highRisk ? "on" : ""}`} /><span><strong>高风险决策支持</strong><small>{highRisk ? "关键事实与人工审批" : "关闭"}</small></span></label>{!highRisk && <label className={`risk-mode-toggle ${autoSummarize ? "active" : ""}`}><input type="checkbox" checked={autoSummarize} onChange={(event) => setAutoSummarize(event.target.checked)} /><span className={`toggle ${autoSummarize ? "on" : ""}`} /><span><strong>自动总结</strong><small>{autoSummarize ? "讨论席结束后直接生成答案" : "默认等待你的确认"}</small></span></label>}<button type="button" className="send-button" disabled={question.trim().length < 3 || sending || !configurationRunnable || (hasDemoSeats && !demoAcknowledged)} onClick={() => submit()}>{sending ? "正在入席" : "进入圆桌"}<ArrowUp size={17} /></button></div>
          {error && <p className="form-error" role="alert">{error}</p>}
        </div>
      </>}
    </section>

    <section className="mode-section"><div className="mode-heading"><div><span className="section-label">运行档位</span><span className="section-hint">控制上下文与推理预算</span></div><span className="section-hint">决策通常 5 次调用 · 快速短任务 2 次</span></div><div className="mode-grid">{modes.map(({ id, label, detail, icon: Icon }) => <button key={id} type="button" className={`mode-option ${mode === id ? "selected" : ""}`} onClick={() => setMode(id)}><span className="mode-icon"><Icon size={16} /></span><span><strong>{label}</strong><small>{detail}</small></span><span className="radio-dot" /></button>)}</div><div className="estimate-line"><span><span className="estimate-bar" />预计 {selectedMode.detail}</span><span>{configState === "loading" ? "席位配置加载中" : configState === "error" ? "席位配置读取失败" : configurationReady ? `${activeProviderNames.size} 个 Provider · 五席真实 AI` : configurationRunnable ? `${mockSeatCount} 个本地演示席 · 需明确确认` : "席位配置未就绪"}</span></div></section>
  </div>;
}
