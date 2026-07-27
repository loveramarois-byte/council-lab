"use client";

import Link from "next/link";
import { ArrowUp, Check, ChevronRight, FileText, FolderOpen, Library, LoaderCircle, Plus, ShieldCheck, Sparkles, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AgentAssignmentsConfig, api, DeliberationTemplate, Project, ProjectSource, Provider } from "../lib/api";

const modes = [
  { id: "quick", label: "引导", detail: "4 席 · 1.8k 上下文", icon: Zap },
  { id: "standard", label: "圆桌", detail: "4 席 · 4k 上下文", icon: ShieldCheck },
  { id: "rigorous", label: "深挖", detail: "4 席 · 7k 上下文", icon: Sparkles },
];

export default function HomePage() {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState("standard");
  const [provider, setProvider] = useState<Provider | null>(null);
  const [assignments, setAssignments] = useState<AgentAssignmentsConfig | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [sources, setSources] = useState<ProjectSource[]>([]);
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [templates, setTemplates] = useState<DeliberationTemplate[]>([]);
  const [templateId, setTemplateId] = useState("open_discussion");
  const [includeHistory, setIncludeHistory] = useState(true);
  const [sending, setSending] = useState(false);
  const [loadingSources, setLoadingSources] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.providers(), api.assignments(), api.projects(), api.templates()]).then(([items, config, spaces, templateItems]) => {
      setAssignments(config);
      setProjects(spaces);
      setTemplates(templateItems);
      const primary = items.find((item) => item.id === config.seats[0]?.provider_id);
      setProvider(primary || items.find((item) => item.id === "mock") || items[0]);
      if (spaces.length) setProjectId(spaces[0].id);
    }).catch(() => setProvider({ id: "mock", preset_id: "mock", display_name: "本地演示", description: "不联网", provider_type: "mock", protocol_mode: "auto", base_url: "", default_model: "council-mock", reasoning_effort: "low", available_models: ["council-mock"], model_source: "built_in", local_only: true, has_api_key: false, credential_source: "none", supports_api_key: false, requires_api_key: false, is_active: true }));
  }, []);

  useEffect(() => {
    if (!projectId) { setSources([]); setSourceIds([]); return; }
    setLoadingSources(true);
    api.projectSources(projectId).then((items) => {
      setSources(items);
      setSourceIds(items.map((item) => item.id));
    }).catch(() => { setSources([]); setSourceIds([]); }).finally(() => setLoadingSources(false));
  }, [projectId]);

  const selectedMode = useMemo(() => modes.find((item) => item.id === mode)!, [mode]);
  const selectedTemplate = templates.find((item) => item.id === templateId);
  const selectedProject = projects.find((item) => item.id === projectId);
  const toggleSource = (id: string) => setSourceIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);

  const submit = async () => {
    if (question.trim().length < 3 || sending) return;
    setSending(true); setError("");
    try {
      const run = await api.createRun({
        question: question.trim(),
        mode,
        use_saved_assignments: true,
        project_id: projectId || undefined,
        source_ids: projectId ? sourceIds : undefined,
        include_project_history: projectId ? includeHistory : false,
        template_id: templateId,
      });
      router.push(`/runs/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法创建审议任务");
      setSending(false);
    }
  };

  return <div className="page-wrap home-page">
    <header className="topbar"><div><span className="top-kicker">工作台 / 新建审议</span><span className="top-title">Council 圆桌</span></div><div className="top-meta"><span className="status-dot" />本地优先 <span className="meta-divider" /> <span>{provider?.display_name || "连接中"}</span></div></header>

    <section className="home-command">
      <div><h1>四种视角，你也在场。</h1><p>依次发言、公开回应，由你确认后再形成答案。</p></div>
      <div className="council-sequence" aria-label="四席顺序"><span>析</span><ChevronRight size={12} /><span>诘</span><ChevronRight size={12} /><span>构</span><ChevronRight size={12} /><span>观</span><ChevronRight size={12} /><strong>答</strong></div>
    </section>

    <section className="home-workbench" aria-label="新建审议">
      <aside className="context-setup">
        <div className="setup-title"><Library size={15} /><strong>讨论上下文</strong><Link href="/projects" title="管理资料空间" aria-label="管理资料空间"><Plus size={15} /></Link></div>
        <label className="compact-field"><span>资料空间</span><select aria-label="资料空间" value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">不使用资料空间</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
        <label className="compact-field"><span>审议模板</span><select aria-label="审议模板" value={templateId} onChange={(event) => setTemplateId(event.target.value)}>{templates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</select><small>{selectedTemplate?.description || "开放讨论"}</small></label>
        <div className="source-picker">
          <div><span>本次资料</span>{projectId && sources.length > 0 && <button type="button" onClick={() => setSourceIds(sourceIds.length === sources.length ? [] : sources.map((item) => item.id))}>{sourceIds.length === sources.length ? "清空" : "全选"}</button>}</div>
          <div className="source-picker-list">
            {loadingSources ? <span className="picker-empty"><LoaderCircle className="spin" size={13} />加载资料</span> : !projectId ? <span className="picker-empty"><FolderOpen size={14} />未选择空间</span> : !sources.length ? <Link className="picker-empty" href="/projects"><Plus size={14} />添加第一份资料</Link> : sources.map((source) => <label key={source.id} className="source-choice"><input type="checkbox" checked={sourceIds.includes(source.id)} onChange={() => toggleSource(source.id)} /><span><FileText size={13} />{source.title}</span><Check size={12} /></label>)}
          </div>
        </div>
        <label className={`history-toggle ${!projectId ? "disabled" : ""}`}><input type="checkbox" checked={includeHistory} disabled={!projectId} onChange={(event) => setIncludeHistory(event.target.checked)} /><span className={`toggle ${includeHistory && projectId ? "on" : ""}`} /><span>带入最近 3 次结论</span></label>
      </aside>

      <div className="composer-section">
        <div className="composer-head"><div><span className="section-label">你的问题</span><span className="section-hint">{selectedProject ? selectedProject.name : "独立审议"} · {selectedTemplate?.name || "开放讨论"}</span></div><span className="composer-count">{question.length.toString().padStart(3, "0")} / 12000</span></div>
        <textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit(); }} placeholder={selectedTemplate?.prompt_hint || "写下需要四席共同审议的问题"} rows={5} />
        <div className="composer-footer"><span className="source-summary">{projectId ? `${sourceIds.length} 份资料 · ${includeHistory ? "包含历史" : "不含历史"}` : "不附加资料"}</span><button type="button" className="send-button" disabled={question.trim().length < 3 || sending} onClick={submit}>{sending ? "正在入席" : "进入圆桌"}<ArrowUp size={17} /></button></div>
        {error && <p className="form-error" role="alert">{error}</p>}
      </div>
    </section>

    <section className="mode-section"><div className="mode-heading"><div><span className="section-label">运行档位</span><span className="section-hint">控制上下文与推理预算</span></div><span className="section-hint">正常 5 次调用 · 失败最多重试 3 次</span></div><div className="mode-grid">{modes.map(({ id, label, detail, icon: Icon }) => <button key={id} type="button" className={`mode-option ${mode === id ? "selected" : ""}`} onClick={() => setMode(id)}><span className="mode-icon"><Icon size={16} /></span><span><strong>{label}</strong><small>{detail}</small></span><span className="radio-dot" /></button>)}</div><div className="estimate-line"><span><span className="estimate-bar" />预计 {selectedMode.detail}</span><span>{assignments ? `${new Set(assignments.seats.map((item) => item.provider_id)).size} 个 Provider 配置` : provider?.display_name || "席位配置加载中"}</span></div></section>
  </div>;
}
