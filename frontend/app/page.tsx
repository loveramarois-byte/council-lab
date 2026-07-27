"use client";

import { ArrowUp, ChevronDown, Plus, ShieldCheck, Sparkles, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AgentAssignmentsConfig, api, Provider } from "../lib/api";

const modes = [{ id: "quick", label: "引导", detail: "4 席 · 1.8k 上下文", icon: Zap }, { id: "standard", label: "圆桌", detail: "4 席 · 4k 上下文", icon: ShieldCheck }, { id: "rigorous", label: "深挖", detail: "4 席 · 7k 上下文", icon: Sparkles }];

export default function HomePage() {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("standard");
  const [provider, setProvider] = useState<Provider | null>(null);
  const [assignments, setAssignments] = useState<AgentAssignmentsConfig | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([api.providers(), api.assignments()]).then(([items, config]) => {
      setAssignments(config);
      const primary = items.find((item) => item.id === config.seats[0]?.provider_id);
      setProvider(primary || items.find((item) => item.id === "mock") || items[0]);
    }).catch(() => setProvider({ id: "mock", preset_id: "mock", display_name: "本地演示", description: "不联网", provider_type: "mock", protocol_mode: "auto", base_url: "", default_model: "council-mock", reasoning_effort: "low", available_models: ["council-mock"], local_only: true, has_api_key: false, credential_source: "none", supports_api_key: false, requires_api_key: false, is_active: true }));
  }, []);
  const selectedMode = useMemo(() => modes.find((item) => item.id === mode)!, [mode]);
  const submit = async () => { if (question.trim().length < 3 || sending) return; setSending(true); setError(""); try { const run = await api.createRun({ question: question.trim(), mode, use_saved_assignments: true }); router.push(`/runs/${run.id}`); } catch (err) { setError(err instanceof Error ? err.message : "无法创建审议任务"); setSending(false); } };
  return <div className="page-wrap home-page">
    <header className="topbar"><div><span className="top-kicker">工作台 / 新建圆桌</span><span className="top-title">四种视角，你也在场</span></div><div className="top-meta"><span className="status-dot" />本地优先 <span className="meta-divider" /> <span>{provider?.display_name || "连接中"}</span></div></header>
    <section className="home-intro"><p className="eyebrow terracotta">COUNCIL / 01</p><h1>不是四份答案，<em>是一场讨论。</em></h1><p className="intro-copy">四个席位逐个调用已配置模型并互相回应。第四席结束后会等你确认或补充，再生成最终答案。</p></section>
    <section className="composer-section" aria-label="新建审议">
      <div className="composer-head"><div><span className="section-label">你的问题</span><span className="section-hint">先写下真正想确认的事</span></div><span className="composer-count">{question.length.toString().padStart(3, "0")} / 12000</span></div>
      <textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit(); }} placeholder="例如：我们应该如何评估这次迁移方案的风险？" rows={5} />
      <div className="composer-footer"><div className="composer-tools"><span className="section-hint">当前版本只进行公开审议，不执行外部事实核验</span></div><button type="button" className="send-button" disabled={question.trim().length < 3 || sending} onClick={submit}>{sending ? "正在入席" : "进入圆桌"}<ArrowUp size={17} /></button></div>
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>
    <section className="mode-section"><div className="mode-heading"><div><span className="section-label">运行模式</span><span className="section-hint">模式控制上下文预算；仅支持 Responses 的 Provider 会使用原生推理档位</span></div><span className="section-hint">正常 5 次调用；含失败重试最多 8 次</span></div><div className="mode-grid">{modes.map(({ id, label, detail, icon: Icon }) => <button key={id} type="button" className={`mode-option ${mode === id ? "selected" : ""}`} onClick={() => setMode(id)}><span className="mode-icon"><Icon size={17} /></span><span><strong>{label}</strong><small>{detail}</small></span><span className="radio-dot" /></button>)}</div><div className="estimate-line"><span><span className="estimate-bar" />预计 {selectedMode.detail}</span><span className="estimate-note">{assignments ? `${new Set(assignments.seats.map((item) => item.provider_id)).size} 个 Provider 配置` : provider?.display_name || "席位配置加载中"} <ChevronDown size={14} /></span></div></section>
    <section className="home-note"><div className="note-mark"><Plus size={16} /></div><p>第一席先回答，后三席依次认同、反驳或补充；第四席后由你确认，再执行总结席。</p><a href="/settings/agents">配置五个席位 <ArrowUp size={14} /></a></section>
  </div>;
}
