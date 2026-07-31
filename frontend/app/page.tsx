"use client";

import Link from "next/link";
import { ArrowUp, Bot, ChevronRight, CircleAlert, LoaderCircle, RefreshCw, Settings2, ShieldCheck, Sparkles, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AgentAssignmentsConfig, api, DeliberationTemplate, providerIsReady, Provider } from "../lib/api";

const modes = [
  { id: "quick", label: "引导", detail: "4 席 · 1.8k 上下文", icon: Zap },
  { id: "standard", label: "圆桌", detail: "4 席 · 4k 上下文", icon: ShieldCheck },
  { id: "rigorous", label: "深挖", detail: "4 席 · 7k 上下文", icon: Sparkles },
];

export default function HomePage() {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("standard");
  const [highRisk, setHighRisk] = useState(false);
  const [autoSummarize, setAutoSummarize] = useState(false);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [assignments, setAssignments] = useState<AgentAssignmentsConfig | null>(null);
  const [templates, setTemplates] = useState<DeliberationTemplate[]>([]);
  const [templateId, setTemplateId] = useState("open_discussion");
  const [demoAcknowledged, setDemoAcknowledged] = useState(false);
  const [configState, setConfigState] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  const loadConfiguration = useCallback(async () => {
    setConfigState("loading");
    setLoadError("");
    try {
      const [items, config, templateItems] = await Promise.all([api.providers(), api.assignments(), api.templates()]);
      setProviders(items);
      setAssignments(config);
      setTemplates(templateItems);
      setDemoAcknowledged(false);
      setConfigState("ready");
    } catch (nextError) {
      setConfigState("error");
      setLoadError(nextError instanceof Error ? nextError.message : "无法读取本地配置");
    }
  }, []);

  useEffect(() => { void loadConfiguration(); }, [loadConfiguration]);

  const selectedMode = useMemo(() => modes.find((item) => item.id === mode)!, [mode]);
  const selectedTemplate = templates.find((item) => item.id === templateId);
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

  const submit = async () => {
    if (question.trim().length < 3 || sending || configState !== "ready" || !configurationRunnable || (hasDemoSeats && !demoAcknowledged)) return;
    setSending(true);
    setError("");
    try {
      const run = await api.createRun({
        question: question.trim(),
        mode,
        use_saved_assignments: true,
        template_id: templateId,
        ...(autoSummarize && !highRisk ? { auto_summarize: true } : {}),
        ...(highRisk ? { high_risk: true } : {}),
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
          <div className="composer-head"><div><span className="section-label">你的问题</span><span className="section-hint">{selectedTemplate?.name || "开放讨论"}</span></div><label className="template-select"><span>审议方式</span><select aria-label="审议模板" value={templateId} onChange={(event) => setTemplateId(event.target.value)}>{templates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</select></label><span className="composer-count">{question.length.toString().padStart(3, "0")} / 12000</span></div>
          <textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit(); }} placeholder={selectedTemplate?.prompt_hint || "写下需要四席共同审议的问题"} rows={5} />
          <div className="composer-footer"><label className={`risk-mode-toggle ${highRisk ? "active" : ""}`}><input type="checkbox" checked={highRisk} onChange={(event) => { const checked = event.target.checked; setHighRisk(checked); if (checked) setAutoSummarize(false); }} /><span className={`toggle ${highRisk ? "on" : ""}`} /><span><strong>高风险决策支持</strong><small>{highRisk ? "关键事实与人工审批" : "关闭"}</small></span></label>{!highRisk && <label className={`risk-mode-toggle ${autoSummarize ? "active" : ""}`}><input type="checkbox" checked={autoSummarize} onChange={(event) => setAutoSummarize(event.target.checked)} /><span className={`toggle ${autoSummarize ? "on" : ""}`} /><span><strong>自动总结</strong><small>{autoSummarize ? "讨论席结束后直接生成答案" : "默认等待你的确认"}</small></span></label>}<button type="button" className="send-button" disabled={question.trim().length < 3 || sending || !configurationRunnable || (hasDemoSeats && !demoAcknowledged)} onClick={submit}>{sending ? "正在入席" : "进入圆桌"}<ArrowUp size={17} /></button></div>
          {error && <p className="form-error" role="alert">{error}</p>}
        </div>
      </>}
    </section>

    <section className="mode-section"><div className="mode-heading"><div><span className="section-label">运行档位</span><span className="section-hint">控制上下文与推理预算</span></div><span className="section-hint">决策通常 5 次调用 · 快速短任务 2 次</span></div><div className="mode-grid">{modes.map(({ id, label, detail, icon: Icon }) => <button key={id} type="button" className={`mode-option ${mode === id ? "selected" : ""}`} onClick={() => setMode(id)}><span className="mode-icon"><Icon size={16} /></span><span><strong>{label}</strong><small>{detail}</small></span><span className="radio-dot" /></button>)}</div><div className="estimate-line"><span><span className="estimate-bar" />预计 {selectedMode.detail}</span><span>{configState === "loading" ? "席位配置加载中" : configState === "error" ? "席位配置读取失败" : configurationReady ? `${activeProviderNames.size} 个 Provider · 五席真实 AI` : configurationRunnable ? `${mockSeatCount} 个本地演示席 · 需明确确认` : "席位配置未就绪"}</span></div></section>
  </div>;
}
