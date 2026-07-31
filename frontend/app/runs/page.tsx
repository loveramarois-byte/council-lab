"use client";

import Link from "next/link";
import { ArrowUpRight, Filter, LoaderCircle, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, Run } from "../../lib/api";

const PAGE_SIZE = 30;

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const load = () => {
    setLoadError("");
    setRuns(null);
    void api.runs()
      .then(setRuns)
      .catch((error) => {
        setRuns([]);
        setLoadError(error instanceof Error ? error.message : "历史记录读取失败");
      });
  };

  useEffect(load, []);
  useEffect(() => setVisibleCount(PAGE_SIZE), [query, status]);

  const filtered = useMemo(() => (runs || []).filter((run) => (
    (status === "all" || run.status === status)
    && (!query || run.question.toLowerCase().includes(query.toLowerCase()))
  )), [runs, status, query]);
  const visibleRuns = filtered.slice(0, visibleCount);

  const remove = async (id: string) => {
    await api.deleteRun(id);
    setRuns((items) => (items || []).filter((item) => item.id !== id));
  };

  return <div className="page-wrap">
    <header className="topbar"><div><span className="top-kicker">工作台 / 记录</span><span className="top-title">历史审议</span></div><Link href="/" className="top-action"><span>新建</span><ArrowUpRight size={15} /></Link></header>
    <div className="list-intro"><p className="eyebrow terracotta">ARCHIVE / 02</p><h1>留下判断的来路。</h1><p>每一次审议都保存问题、公开发言、席位模型、分歧和运行限制。</p></div>
    <div className="list-toolbar">
      <label className="search-box"><Search size={16} /><input placeholder="搜索问题" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <label className="filter-box"><Filter size={15} /><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">全部状态</option><option value="queued">排队中</option><option value="running">进行中</option><option value="awaiting_final_input">等待确认</option><option value="completed">已完成</option><option value="cancelled">已取消</option><option value="failed">可恢复失败</option><option value="stopped">达到限制</option></select></label>
    </div>
    <div className="run-list">
      {runs === null ? <div className="empty-state run-loading" role="status"><LoaderCircle className="spin" size={22} /><h2>正在读取历史记录</h2><p>本地记录较多时可能需要片刻。</p></div>
        : loadError ? <div className="empty-state"><span className="empty-number">!</span><h2>历史记录暂时无法读取</h2><p>{loadError}</p><button className="text-action" onClick={load}>重新读取</button></div>
        : filtered.length === 0 ? <div className="empty-state"><span className="empty-number">00</span><h2>{runs.length === 0 ? "还没有审议记录" : "没有匹配的审议记录"}</h2><p>{runs.length === 0 ? "从一个具体问题开始，答案会在这里留下轨迹。" : "调整搜索词或状态筛选后再试。"}</p>{runs.length === 0 && <Link href="/" className="text-action">开始第一份审议 <ArrowUpRight size={14} /></Link>}</div>
        : <>{visibleRuns.map((run) => <article key={run.id} className="run-row"><div className="row-marker"><span className={`status-pill-dot status-${run.status}`} /></div><div className="row-main"><Link href={`/runs/${run.id}`} className="row-question">{run.question}</Link><div className="row-meta"><span>{run.mode === "standard" ? "标准" : run.mode === "quick" ? "快速" : "严谨"}</span><span>{new Date(run.created_at).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span><span>{activeProviderCount(run)} 个 Provider</span></div></div><div className="row-status">{runStatusLabel(run.status)}<small>{run.final_decision ? "未外部核验 · " : ""}{run.usage.model_calls} 次调用 · {(run.usage.input_tokens + run.usage.output_tokens).toLocaleString()} Token</small></div><button className="icon-button row-delete" onClick={() => remove(run.id)} title="删除记录"><Trash2 size={15} /></button><ArrowUpRight className="row-arrow" size={17} /></article>)}
          {visibleCount < filtered.length && <div className="run-load-more"><button className="text-action" onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}>加载更多（已显示 {visibleRuns.length} / {filtered.length}）</button></div>}</>}
    </div>
  </div>;
}

function activeProviderCount(run: Run): number {
  const activeRoles = new Set(run.participant_roles.map((participant) => participant.id));
  const assignments = run.seat_assignments?.filter((assignment) => activeRoles.size === 0 || activeRoles.has(assignment.role)) || [];
  return new Set(assignments.length > 0 ? assignments.map((assignment) => assignment.provider_id) : [run.provider_id]).size;
}

function runStatusLabel(status: Run["status"]): string {
  return ({ queued: "排队中", running: "进行中", awaiting_final_input: "等待确认", completed: "已完成", failed: "可恢复", stopped: "达到限制", cancelled: "已取消" } as Record<Run["status"], string>)[status];
}
