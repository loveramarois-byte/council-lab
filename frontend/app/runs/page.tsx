"use client";

import Link from "next/link";
import { ArrowUpRight, Filter, LoaderCircle, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, Run, RunSummary } from "../../lib/api";

const PAGE_SIZE = 50;

export default function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [loadingMore, setLoadingMore] = useState(false);

  const load = () => {
    setLoadError("");
    setRuns(null);
    void api.runs(PAGE_SIZE, 0)
      .then((result) => { setRuns(result.items); setTotal(result.total); })
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
  const groupedRuns = useMemo(() => groupRunsByDay(visibleRuns), [visibleRuns]);
  const loadedCount = runs?.length || 0;
  const attentionCount = (runs || []).filter((run) => ["failed", "stopped", "awaiting_final_input"].includes(run.status)).length;

  const loadMore = async () => {
    if (loadingMore || !runs) return;
    setLoadingMore(true);
    try {
      if (runs.length < total) {
        const result = await api.runs(PAGE_SIZE, runs.length);
        setRuns((items) => [...(items || []), ...result.items]);
        setTotal(result.total);
      }
      setVisibleCount((count) => count + PAGE_SIZE);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "更多历史记录读取失败");
    } finally {
      setLoadingMore(false);
    }
  };

  const remove = async (id: string) => {
    await api.deleteRun(id);
    setRuns((items) => (items || []).filter((item) => item.id !== id));
    setTotal((count) => Math.max(0, count - 1));
  };

  return <div className="page-wrap">
    <header className="topbar"><div><span className="top-kicker">工作台 / 记录</span><span className="top-title">历史审议</span></div><Link href="/" className="top-action"><span>新建</span><ArrowUpRight size={15} /></Link></header>
    <div className="list-intro"><p className="eyebrow terracotta">判断卷宗</p><h1>每一次判断，都有来路。</h1><p>按日期回看问题、公开发言、分歧和最终结论。</p><div className="archive-summary" aria-label="历史记录摘要"><span><strong>{total}</strong> 全部记录</span><span><strong>{loadedCount}</strong> 已载入</span>{attentionCount > 0 && <span className="needs-attention"><strong>{attentionCount}</strong> 待处理</span>}</div></div>
    <div className="list-toolbar">
      <label className="search-box"><Search size={16} /><input placeholder="搜索问题或关键词" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <label className="filter-box"><Filter size={15} /><select aria-label="按状态筛选历史记录" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">全部状态</option><option value="queued">排队中</option><option value="running">进行中</option><option value="awaiting_final_input">等待确认</option><option value="completed">已完成</option><option value="cancelled">已取消</option><option value="failed">可恢复失败</option><option value="stopped">达到限制</option></select></label>
      <output className="filter-result" aria-live="polite">显示 {visibleRuns.length} / {filtered.length}</output>
    </div>
    <div className="run-list">
      {runs === null ? <div className="empty-state run-loading" role="status"><LoaderCircle className="spin" size={22} /><h2>正在读取历史记录</h2><p>本地记录较多时可能需要片刻。</p></div>
        : loadError ? <div className="empty-state"><span className="empty-number">!</span><h2>历史记录暂时无法读取</h2><p>{loadError}</p><button className="text-action" onClick={load}>重新读取</button></div>
        : filtered.length === 0 ? <div className="empty-state"><span className="empty-number">00</span><h2>{runs.length === 0 ? "还没有审议记录" : "没有匹配的审议记录"}</h2><p>{runs.length === 0 ? "从一个具体问题开始，答案会在这里留下轨迹。" : "清除搜索词或切回全部状态后再试。"}</p>{runs.length === 0 ? <Link href="/" className="text-action">开始第一份审议 <ArrowUpRight size={14} /></Link> : <button className="text-action" onClick={() => { setQuery(""); setStatus("all"); }}>清除筛选</button>}{runs.length < total && <button className="text-action" onClick={loadMore} disabled={loadingMore}>{loadingMore ? "正在继续查找" : "继续加载更多记录"}</button>}</div>
        : <>{groupedRuns.map((group) => <section key={group.key} className="run-day-group" aria-labelledby={`run-day-${group.key}`}><header className="run-day-heading"><div><span>{group.stamp}</span><h2 id={`run-day-${group.key}`}>{group.label}</h2></div><small>{group.items.length} 份审议</small></header>{group.items.map((run) => <article key={run.id} className="run-row"><div className="row-marker"><span className={`status-pill-dot status-${run.status}`} /></div><div className="row-main"><Link href={`/runs/${run.id}`} className="row-question">{run.question}</Link><div className="row-meta"><span className="row-status-label">{runStatusLabel(run.status)}</span><span>{run.mode === "standard" ? "标准" : run.mode === "quick" ? "快速" : "严谨"}</span><time dateTime={run.created_at}>{new Date(run.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time><span>{activeProviderCount(run)} 个 Provider</span></div></div><div className="row-status">{runStatusLabel(run.status)}<small>{run.has_final_decision ? "未外部核验 · " : ""}{run.usage.model_calls} 次调用 · {(run.usage.input_tokens + run.usage.output_tokens).toLocaleString()} Token</small></div><button className="icon-button row-delete" onClick={() => remove(run.id)} title="删除记录" aria-label={`删除：${run.question}`}><Trash2 size={15} /></button><ArrowUpRight className="row-arrow" size={17} /></article>)}</section>)}
          {(visibleCount < filtered.length || runs.length < total) && <div className="run-load-more"><button className="text-action" onClick={loadMore} disabled={loadingMore}>{loadingMore ? "正在读取更多记录" : `加载更多（已显示 ${visibleRuns.length} / ${total}）`}</button></div>}</>}
    </div>
  </div>;
}

function groupRunsByDay(runs: RunSummary[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const groups = new Map<string, { key: string; stamp: string; label: string; items: RunSummary[] }>();
  for (const run of runs) {
    const date = new Date(run.created_at);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    const day = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
    const dayOffset = Math.round((today - day) / 86_400_000);
    const label = dayOffset === 0 ? "今天" : dayOffset === 1 ? "昨天" : date.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
    const group = groups.get(key) || { key, stamp: `${String(date.getMonth() + 1).padStart(2, "0")}.${String(date.getDate()).padStart(2, "0")}`, label, items: [] };
    group.items.push(run);
    groups.set(key, group);
  }
  return [...groups.values()];
}

function activeProviderCount(run: RunSummary): number {
  const activeRoles = new Set(run.participant_roles.map((participant) => participant.id));
  const assignments = run.seat_assignments?.filter((assignment) => activeRoles.size === 0 || activeRoles.has(assignment.role)) || [];
  return new Set(assignments.length > 0 ? assignments.map((assignment) => assignment.provider_id) : [run.provider_id]).size;
}

function runStatusLabel(status: Run["status"]): string {
  return ({ queued: "排队中", running: "进行中", awaiting_final_input: "等待确认", completed: "已完成", failed: "可恢复", stopped: "达到限制", cancelled: "已取消" } as Record<Run["status"], string>)[status];
}
