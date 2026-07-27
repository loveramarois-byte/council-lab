"use client";

import { ArrowUp, ChevronDown, FilePlus2, Globe2, LockKeyhole, Paperclip, Plus, ShieldCheck, Sparkles, TerminalSquare, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Provider } from "../lib/api";

const modes = [{ id: "quick", label: "引导", detail: "4 席 · Low", icon: Zap }, { id: "standard", label: "圆桌", detail: "4 席 · High", icon: ShieldCheck }, { id: "rigorous", label: "深挖", detail: "4 席 · Ultra", icon: Sparkles }];

export default function HomePage() {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("standard");
  const [tools, setTools] = useState(false);
  const [provider, setProvider] = useState<Provider | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.providers().then((items) => setProvider(items.find((item) => item.is_active && item.default_model) || items.find((item) => item.id === "mock") || items[0])).catch(() => setProvider({ id: "mock", preset_id: "mock", display_name: "本地演示", description: "不联网", provider_type: "mock", protocol_mode: "auto", base_url: "", default_model: "council-mock", reasoning_effort: "low", available_models: ["council-mock"], local_only: true, has_api_key: false, credential_source: "none", supports_api_key: false, requires_api_key: false, is_active: true })); }, []);
  const selectedMode = useMemo(() => modes.find((item) => item.id === mode)!, [mode]);
  const submit = async () => { if (question.trim().length < 3 || sending) return; setSending(true); setError(""); try { const run = await api.createRun({ question: question.trim(), mode, provider_id: provider?.id || "mock", model: provider?.default_model || "council-mock", tools_enabled: tools }); router.push(`/runs/${run.id}`); } catch (err) { setError(err instanceof Error ? err.message : "无法创建审议任务"); setSending(false); } };
  return <div className="page-wrap home-page">
    <header className="topbar"><div><span className="top-kicker">工作台 / 新建圆桌</span><span className="top-title">四种视角，你也在场</span></div><div className="top-meta"><span className="status-dot" />本地优先 <span className="meta-divider" /> <span>{provider?.display_name || "连接中"}</span></div></header>
    <section className="home-intro"><p className="eyebrow terracotta">COUNCIL / 01</p><h1>不是四份答案，<em>是一场讨论。</em></h1><p className="intro-copy">四位 AI 逐个发言、互相回应，第四位结束后自动形成最终答案。你全程都能看到，并可随时插话、反驳或点名追问。</p></section>
    <section className="composer-section" aria-label="新建审议">
      <div className="composer-head"><div><span className="section-label">你的问题</span><span className="section-hint">先写下真正想确认的事</span></div><span className="composer-count">{question.length.toString().padStart(3, "0")} / 12000</span></div>
      <textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit(); }} placeholder="例如：我们应该如何评估这次迁移方案的风险？" rows={5} />
      <div className="composer-footer"><div className="composer-tools"><button type="button" className="quiet-button" title="添加附件"><Paperclip size={16} />附件</button><button type="button" className={`quiet-button ${tools ? "selected" : ""}`} title="启用外部工具" onClick={() => setTools(!tools)}><Globe2 size={16} />联网核验<span className={`toggle ${tools ? "on" : ""}`} /></button><button type="button" className="quiet-button" title="仅允许后端沙箱执行代码"><TerminalSquare size={16} />代码沙箱</button></div><button type="button" className="send-button" disabled={question.trim().length < 3 || sending} onClick={submit}>{sending ? "正在入席" : "进入圆桌"}<ArrowUp size={17} /></button></div>
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>
    <section className="mode-section"><div className="mode-heading"><div><span className="section-label">运行模式</span><span className="section-hint">复杂度会影响速度、成本与交叉检查深度</span></div><button className="link-button"><LockKeyhole size={14} />预算与权限</button></div><div className="mode-grid">{modes.map(({ id, label, detail, icon: Icon }) => <button key={id} type="button" className={`mode-option ${mode === id ? "selected" : ""}`} onClick={() => setMode(id)}><span className="mode-icon"><Icon size={17} /></span><span><strong>{label}</strong><small>{detail}</small></span><span className="radio-dot" /></button>)}</div><div className="estimate-line"><span><span className="estimate-bar" />预计 {selectedMode.detail}</span><span className="estimate-note">{provider?.display_name || "Provider 连接中"}{provider?.id === "mock" ? " · 不产生外部费用" : ` · ${provider?.default_model}`} <ChevronDown size={14} /></span></div></section>
    <section className="home-note"><div className="note-mark"><Plus size={16} /></div><p>第一位先回答，后三位依次认同、反驳或补充；第四位发言后，系统自动综合公开讨论。</p><a href="/settings/providers">检查 Provider <ArrowUp size={14} /></a></section>
  </div>;
}
