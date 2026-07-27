"use client";

import { FileText, FileUp, FolderOpen, Globe2, Link2, LoaderCircle, Plus, Save, Trash2, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, Project, ProjectSource } from "../../lib/api";

type SourceMode = "text" | "file" | "url";

export default function ProjectsPage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [project, setProject] = useState<Project | null>(null);
  const [sources, setSources] = useState<ProjectSource[]>([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [sourceMode, setSourceMode] = useState<SourceMode>("text");
  const [sourceTitle, setSourceTitle] = useState("");
  const [sourceContent, setSourceContent] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const refreshProjects = async (preferredId?: string) => {
    const items = await api.projects();
    setProjects(items);
    const nextId = preferredId || (items.some((item) => item.id === projectId) ? projectId : items[0]?.id || "");
    setProjectId(nextId);
  };

  useEffect(() => { refreshProjects().catch(() => setMessage("资料空间加载失败。")); }, []);
  useEffect(() => {
    if (!projectId) { setProject(null); setSources([]); return; }
    Promise.all([api.project(projectId), api.projectSources(projectId)]).then(([item, sourceItems]) => {
      setProject(item); setSources(sourceItems); setMessage("");
    }).catch(() => setMessage("当前资料空间加载失败。"));
  }, [projectId]);

  const createProject = async () => {
    if (!newName.trim() || busy) return;
    setBusy(true); setMessage("");
    try {
      const created = await api.createProject({ name: newName.trim(), description: "", instructions: "" });
      setNewName(""); setCreating(false);
      await refreshProjects(created.id);
    } catch (error) { setMessage(error instanceof Error ? error.message : "新建失败"); }
    finally { setBusy(false); }
  };

  const saveProject = async () => {
    if (!project || !project.name.trim() || busy) return;
    setBusy(true); setMessage("");
    try {
      const saved = await api.patchProject(project.id, { name: project.name.trim(), description: project.description, instructions: project.instructions });
      setProject(saved); await refreshProjects(saved.id); setMessage("资料空间已保存。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存失败"); }
    finally { setBusy(false); }
  };

  const deleteProject = async () => {
    if (!project || busy || !window.confirm(`删除“${project.name}”及其中全部资料？历史审议中的资料快照不会删除。`)) return;
    setBusy(true); setMessage("");
    try { await api.deleteProject(project.id); setProject(null); setSources([]); await refreshProjects(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "删除失败"); }
    finally { setBusy(false); }
  };

  const addSource = async () => {
    if (!project || busy) return;
    setBusy(true); setMessage("");
    try {
      if (sourceMode === "text") {
        if (!sourceTitle.trim() || !sourceContent.trim()) throw new Error("填写资料名称和正文。")
        await api.addTextSource(project.id, { title: sourceTitle.trim(), content: sourceContent.trim() });
      } else if (sourceMode === "url") {
        if (!sourceUrl.trim()) throw new Error("填写公开网页地址。")
        await api.addUrlSource(project.id, { title: sourceTitle.trim() || undefined, url: sourceUrl.trim() });
      } else {
        if (!file) throw new Error("先选择文件。")
        await api.addFileSource(project.id, file);
      }
      setSourceTitle(""); setSourceContent(""); setSourceUrl(""); setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      setSources(await api.projectSources(project.id));
      await refreshProjects(project.id);
      setMessage("资料已加入。")
    } catch (error) { setMessage(error instanceof Error ? error.message : "资料添加失败"); }
    finally { setBusy(false); }
  };

  const deleteSource = async (source: ProjectSource) => {
    if (!project || busy || !window.confirm(`删除资料“${source.title}”？已创建的历史审议仍保留快照。`)) return;
    setBusy(true); setMessage("");
    try {
      await api.deleteSource(project.id, source.id);
      setSources((items) => items.filter((item) => item.id !== source.id));
      await refreshProjects(project.id);
    } catch (error) { setMessage(error instanceof Error ? error.message : "删除失败"); }
    finally { setBusy(false); }
  };

  return <div className="page-wrap projects-page">
    <header className="topbar"><div><span className="top-kicker">工作台 / 资料空间</span><span className="top-title">项目与证据</span></div><div className="top-meta"><span className="status-dot success" />本地保存 <span className="meta-divider" /> {projects.length} 个空间</div></header>
    <div className="projects-workspace">
      <aside className="project-directory">
        <div className="directory-head"><strong>资料空间</strong><button className="icon-button" type="button" title="新建资料空间" aria-label="新建资料空间" onClick={() => setCreating(true)}><Plus size={15} /></button></div>
        {creating && <div className="new-project-row"><input autoFocus aria-label="资料空间名称" value={newName} onChange={(event) => setNewName(event.target.value)} onKeyDown={(event) => event.key === "Enter" && createProject()} placeholder="空间名称" /><button onClick={createProject} aria-label="确认新建"><Save size={14} /></button><button onClick={() => setCreating(false)} aria-label="取消新建"><X size={14} /></button></div>}
        <div className="project-list">{projects.map((item) => <button key={item.id} className={`project-list-item ${item.id === projectId ? "active" : ""}`} onClick={() => setProjectId(item.id)}><FolderOpen size={15} /><span><strong>{item.name}</strong><small>{item.source_count} 份资料 · {item.run_count} 次审议</small></span></button>)}{!projects.length && !creating && <button className="project-empty-action" onClick={() => setCreating(true)}><Plus size={16} />新建第一个资料空间</button>}</div>
      </aside>

      <main className="project-detail">
        {!project ? <div className="project-blank"><FolderOpen size={28} /><strong>选择或新建资料空间</strong></div> : <>
          <section className="project-editor">
            <div className="project-editor-fields"><label><span>名称</span><input aria-label="空间名称" value={project.name} onChange={(event) => setProject({ ...project, name: event.target.value })} /></label><label><span>说明</span><input aria-label="空间说明" value={project.description} onChange={(event) => setProject({ ...project, description: event.target.value })} placeholder="可选" /></label><label className="wide"><span>固定说明</span><input aria-label="固定说明" value={project.instructions} onChange={(event) => setProject({ ...project, instructions: event.target.value })} placeholder="每次审议都应遵守的边界或术语" /></label></div>
            <div className="project-editor-actions"><button className="quiet-button danger" onClick={deleteProject} title="删除资料空间"><Trash2 size={14} />删除</button><button className="send-button" onClick={saveProject} disabled={busy || !project.name.trim()}>{busy ? <LoaderCircle className="spin" size={14} /> : <Save size={14} />}保存</button></div>
          </section>

          <section className="source-studio">
            <div className="source-compose">
              <div className="segmented" aria-label="资料类型">{([{ id: "text", label: "文字", icon: FileText }, { id: "file", label: "文件", icon: FileUp }, { id: "url", label: "网页", icon: Globe2 }] as const).map(({ id, label, icon: Icon }) => <button key={id} type="button" className={sourceMode === id ? "active" : ""} onClick={() => setSourceMode(id)}><Icon size={14} />{label}</button>)}</div>
              {sourceMode === "text" && <div className="source-form"><input aria-label="文字资料名称" value={sourceTitle} onChange={(event) => setSourceTitle(event.target.value)} placeholder="资料名称" /><textarea aria-label="文字资料正文" value={sourceContent} onChange={(event) => setSourceContent(event.target.value)} placeholder="粘贴正文" rows={5} /></div>}
              {sourceMode === "url" && <div className="source-form"><input aria-label="网页资料名称" value={sourceTitle} onChange={(event) => setSourceTitle(event.target.value)} placeholder="名称（可选，留空自动识别）" /><div className="url-input"><Link2 size={14} /><input aria-label="网页地址" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://example.com/article" /></div></div>}
              {sourceMode === "file" && <div className="file-drop"><input ref={fileRef} id="source-file" type="file" accept=".txt,.md,.markdown,.csv,.json,.pdf,.docx" onChange={(event) => setFile(event.target.files?.[0] || null)} /><label htmlFor="source-file"><Upload size={18} /><strong>{file?.name || "选择文件"}</strong><small>TXT · Markdown · CSV · JSON · PDF · DOCX · 10 MB</small></label></div>}
              <button className="send-button source-add" onClick={addSource} disabled={busy}>{busy ? <LoaderCircle className="spin" size={14} /> : <Plus size={14} />}{sourceMode === "url" ? "导入网页" : sourceMode === "file" ? "上传文件" : "加入文字"}</button>
            </div>

            <div className="source-library"><div className="source-library-head"><strong>已保存资料</strong><span>{sources.length} 份</span></div><div className="source-list">{sources.map((source) => <article key={source.id} className="source-row"><span className={`source-kind ${source.kind}`}>{source.kind === "url" ? <Globe2 size={14} /> : source.kind === "file" ? <FileUp size={14} /> : <FileText size={14} />}</span><div><strong>{source.title}</strong><small>{source.url || source.filename || "本地文字"} · {formatBytes(source.size_bytes)}</small><code>SHA-256 {source.sha256.slice(0, 16)}…</code></div><button className="icon-button" title="删除资料" aria-label={`删除资料 ${source.title}`} onClick={() => deleteSource(source)}><Trash2 size={14} /></button></article>)}{!sources.length && <div className="source-empty"><FileText size={22} /><strong>还没有资料</strong></div>}</div></div>
          </section>
        </>}
        {message && <div className="project-message" role="status">{message}</div>}
      </main>
    </div>
  </div>;
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
