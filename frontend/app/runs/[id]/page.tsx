"use client";

import Link from "next/link";
import { AlertTriangle, ArrowLeft, Bot, Check, CheckCircle2, Clock3, FileCheck2, Gauge, GitBranch, LoaderCircle, MessageCircle, RefreshCw, RotateCcw, Save, Send, Sparkles, UserRound, X } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, Participant, Run, subscribeToRun } from "../../../lib/api";

export default function RunDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const transcriptRef = useRef<HTMLDivElement>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [draft, setDraft] = useState("");
  const [target, setTarget] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [waitingNoticeDismissed, setWaitingNoticeDismissed] = useState(false);

  const refresh = () => params.id && api.run(params.id).then(setRun).catch(() => router.push("/runs"));
  useEffect(() => { refresh(); }, [params.id]);
  useEffect(() => {
    if (!run || run.status !== "running") return;
    const unsubscribe = subscribeToRun(run.id, () => refresh());
    const timer = window.setInterval(refresh, 2500);
    return () => { unsubscribe(); window.clearInterval(timer); };
  }, [run?.id, run?.status]);
  useEffect(() => {
    if (!transcriptRef.current) return;
    transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
  }, [run?.discussion_turns.length, run?.awaiting_user, run?.status]);
  useEffect(() => {
    if (!run || run.status !== "running" || run.awaiting_user) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [run?.id, run?.status, run?.awaiting_user, run?.updated_at]);
  useEffect(() => { setWaitingNoticeDismissed(false); }, [run?.updated_at]);

  const nextParticipant = useMemo(() => run?.participant_roles[run.current_speaker_index], [run]);
  const selectedParticipant = run?.participant_roles.find((item) => item.id === target) || null;
  const agentTurnCount = run?.discussion_turns.filter((turn) => turn.speaker_type === "agent").length || 0;
  const completedSpeakerIds = useMemo(() => new Set(run?.discussion_turns.filter((turn) => turn.speaker_type === "agent").map((turn) => turn.speaker_id) || []), [run?.discussion_turns]);
  const debateActive = run?.status === "running" && agentTurnCount < 4;
  const runFailed = run?.status === "failed";
  const waitingSeconds = run && run.status === "running" && !run.awaiting_user
    ? Math.max(0, Math.floor((now - Date.parse(run.updated_at)) / 1000))
    : 0;
  const showWaitingRecovery = run?.provider_id === "ccswitch" && waitingSeconds >= 45 && !waitingNoticeDismissed;

  const act = async (action: "interject" | "question") => {
    if (!run || busy || !debateActive || !draft.trim()) return;
    setBusy(true); setError("");
    try {
      const value = await api.interjectRun(run.id, { action, message: draft.trim(), target_agent: action === "question" ? target || undefined : undefined });
      setRun(value); setDraft(""); setTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "这一轮没有发出去");
    } finally { setBusy(false); }
  };

  const retryTurn = async () => {
    if (!run || busy || !["running", "failed"].includes(run.status) || run.awaiting_user) return;
    setBusy(true); setError("");
    try {
      setRun(await api.retryTurn(run.id));
      setNow(Date.now());
      setWaitingNoticeDismissed(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "当前席位没有重试成功");
    } finally { setBusy(false); }
  };

  if (!run) return <div className="loading-state"><LoaderCircle className="spin" size={22} />正在进入圆桌…</div>;

  return <div className="council-page">
    <header className="council-topbar">
      <Link href="/" className="back-link"><ArrowLeft size={15} />退出圆桌</Link>
      <div className="council-session"><span className={`status-dot ${run.status === "completed" ? "success" : runFailed ? "failed" : ""}`} />{run.status === "completed" ? "讨论完成" : runFailed ? "调用失败" : `第 ${Math.max(1, run.discussion_round)} 轮`} <span /> {run.model} · {run.reasoning_effort}</div>
      <button className="icon-button" aria-label="结束讨论" title="结束讨论" onClick={() => api.cancelRun(run.id).then(setRun)} disabled={run.status !== "running"}><X size={16} /></button>
    </header>

    <main className="council-stage">
      <section className="council-question">
        <span>本次议题</span>
        <h1>{run.question}</h1>
        <p>{run.status === "completed" ? "四席独立调用完成，最终答案与过程均已保留。" : runFailed ? `${nextParticipant?.name || "记录员"}调用失败，已保留前面的公开讨论。` : agentTurnCount >= 4 ? "四席调用完成，记录员正在综合公开讨论。" : `${nextParticipant?.name || "成员"}正在独立调用中，你可随时插话。`}</p>
      </section>

      <section className="council-callboard" aria-label="AI 独立调用顺序">
        <div className="callboard-meta"><Bot size={14} /><strong>4 次独立调用</strong><span>同一模型</span><span>共享公开记录</span><div className="runtime-meta"><span title="工作流引擎"><GitBranch size={12} />{run.workflow_engine === "langgraph" ? "LangGraph" : "Council"}</span><span title="持久检查点"><Save size={12} />{run.checkpoint_count || 0} 个检查点</span><span title="当前工作上下文"><Gauge size={12} />{run.context_snapshot?.estimated_tokens || 0} / {run.context_snapshot?.token_budget || 0} Token</span></div></div>
        <div className="council-seats">
          {run.participant_roles.map((participant, index) => <Seat key={participant.id} participant={participant} index={index} selected={target === participant.id} status={completedSpeakerIds.has(participant.id) ? "completed" : runFailed && run.current_speaker_index === index ? "failed" : debateActive && run.current_speaker_index === index ? "active" : "queued"} onSelect={() => debateActive && setTarget(target === participant.id ? null : participant.id)} />)}
          <div className={`summary-node ${run.status === "completed" ? "completed" : runFailed && agentTurnCount >= 4 ? "failed" : agentTurnCount >= 4 ? "active" : "queued"}`} aria-label="第 5 次调用：记录员总结">
            <FileCheck2 size={17} /><span><strong>最终答案</strong><small>第 5 次调用</small></span>
          </div>
        </div>
      </section>

      <section className="council-dialogue">
        <div className="dialogue-header">
          <div><MessageCircle size={15} /><strong>公开讨论</strong><span>{agentTurnCount} 次 AI 发言 · {run.discussion_turns.filter((turn) => turn.speaker_type === "user").length} 次你的参与</span></div>
          <span className={`discussion-state ${runFailed ? "failed" : ""}`}>{run.status === "completed" ? "已完成" : runFailed ? "调用失败" : debateActive ? "全程可插话" : "生成答案"}</span>
        </div>

        <div className="dialogue-scroll" ref={transcriptRef} aria-live="polite">
          <article className="opening-question"><span>你提出</span><p>{run.question}</p></article>
          {run.discussion_turns.map((turn) => <article key={turn.id} className={`discussion-turn ${turn.speaker_type} speaker-${turn.speaker_id}`}>
            <header><span className="speaker-avatar">{turn.speaker_type === "user" ? <UserRound size={15} /> : turn.speaker_name.slice(0, 1)}</span><div><strong>{turn.speaker_name}</strong><small>{turn.role_label || "参与者"} · 第 {turn.round} 轮</small></div></header>
            <RichText content={turn.content} />
          </article>)}
          {run.status === "running" && <article className="discussion-thinking">
            <LoaderCircle className="spin" size={17} />
            <div className="discussion-thinking-copy">
              <span><strong>{debateActive ? nextParticipant?.name || "下一位成员" : "记录员"}</strong>{run.provider_id === "ccswitch" && waitingSeconds >= 10 ? "CC Switch 正在切换上游" : debateActive ? "正在阅读并回应前面的发言" : "正在综合四席讨论"}</span>
              <small><Clock3 size={12} />已等待 {waitingSeconds} 秒{run.provider_id === "ccswitch" ? " · 请求已进入 CC Switch，故障转移由它处理" : ""}</small>
              {showWaitingRecovery && <div className="discussion-recovery">
                <span>上游响应较慢，你可以继续等，或中止这次请求并重试当前席位。</span>
                <button className="quiet-button" onClick={() => setWaitingNoticeDismissed(true)}>继续等待</button>
                <button className="quiet-button" onClick={retryTurn} disabled={busy}>{busy ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}重试本席</button>
              </div>}
            </div>
          </article>}
          {run.status === "completed" && run.final_decision && <article className="roundtable-summary"><header><Check size={16} /><span><strong>圆桌最终答案</strong><small>第 5 次独立调用 · 综合四席讨论与你的插话</small></span></header><RichText content={run.final_decision.final_answer} /></article>}
        </div>

        {runFailed && <div className="failed-actions" role="alert">
          <AlertTriangle size={18} />
          <div><strong>{nextParticipant?.name || "记录员"}没有完成调用</strong><span>{run.error || "当前上游请求未完成，前面的公开讨论已经保留。"}</span></div>
          <button className="send-button" onClick={retryTurn} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}重试{nextParticipant?.name || "总结"}</button>
        </div>}

        {run.status === "running" && <div className="participation-dock">
          <div className="participation-context">
            {selectedParticipant ? <button onClick={() => setTarget(null)}><span>正在点名</span><strong>{selectedParticipant.name}</strong><X size={13} /></button> : <span>写下你的观点，或点击上方任一席位点名追问</span>}
            <small>AI 会依次连续发言；你的插话会进入后续成员的上下文。</small>
          </div>
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} disabled={!debateActive || busy} placeholder={selectedParticipant ? `向${selectedParticipant.name}追问…` : "我想补充 / 反驳 / 改变讨论方向…"} rows={2} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") act(selectedParticipant ? "question" : "interject"); }} />
          <div className="participation-actions">
            <span className="debate-progress">{debateActive ? `已完成 ${agentTurnCount} / 4 席` : "四席发言完成"}</span>
            <span />
            <button className="send-button" disabled={!debateActive || busy || !draft.trim()} onClick={() => act(selectedParticipant ? "question" : "interject")}>{busy ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />}{selectedParticipant ? `问${selectedParticipant.name}` : "加入讨论"}</button>
          </div>
          {(error || run.error) && <p className="discussion-error">{error || run.error}</p>}
        </div>}

        {run.status === "completed" && <div className="completed-actions"><button className="quiet-button" onClick={async () => { const next = await api.rerun(run.id); router.push(`/runs/${next.id}`); }}><RotateCcw size={15} />重新开一桌</button><Link className="send-button" href="/">讨论新问题<Sparkles size={15} /></Link></div>}
      </section>
    </main>
  </div>;
}

function Seat({ participant, index, selected, status, onSelect }: { participant: Participant; index: number; selected: boolean; status: "queued" | "active" | "completed" | "failed"; onSelect: () => void }) {
  const statusLabel = status === "failed" ? "调用失败" : status === "completed" ? "已完成" : status === "active" ? "调用中" : selected ? "已点名" : "待调用";
  return <button type="button" className={`council-seat seat-${participant.id} ${selected ? "selected" : ""} ${status}`} onClick={onSelect} aria-pressed={selected}>
    <span className="seat-number">{String(index + 1).padStart(2, "0")}</span>
    <span className="seat-avatar">{participant.name.slice(0, 1)}</span>
    <span className="seat-copy"><strong>{participant.name}</strong><small>{participant.role}</small></span>
    <span className="seat-status">{status === "completed" ? <CheckCircle2 size={12} /> : status === "active" ? <LoaderCircle className="spin" size={12} /> : status === "failed" ? <AlertTriangle size={12} /> : null}{statusLabel}</span>
  </button>;
}

function RichText({ content }: { content: string }) {
  const lines = content.replace(/\r/g, "").split("\n");
  const blocks: React.ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) { index += 1; continue; }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const Tag = `h${Math.min(heading[1].length + 2, 5)}` as "h3" | "h4" | "h5";
      blocks.push(<Tag key={index}>{inlineMarkdown(heading[2])}</Tag>);
      index += 1;
      continue;
    }
    const listMatch = line.match(/^(?:[-*+]\s+|(\d+)[.)]\s+)(.+)$/);
    if (listMatch) {
      const ordered = Boolean(listMatch[1]);
      const items: React.ReactNode[] = [];
      while (index < lines.length) {
        const item = lines[index].trim().match(ordered ? /^\d+[.)]\s+(.+)$/ : /^[-*+]\s+(.+)$/);
        if (!item) break;
        items.push(<li key={index}>{inlineMarkdown(item[1])}</li>);
        index += 1;
      }
      blocks.push(ordered ? <ol key={`list-${index}`}>{items}</ol> : <ul key={`list-${index}`}>{items}</ul>);
      continue;
    }
    const paragraph: string[] = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,3})\s+/.test(lines[index].trim()) && !/^(?:[-*+]\s+|\d+[.)]\s+)/.test(lines[index].trim())) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push(<p key={`p-${index}`}>{inlineMarkdown(paragraph.join("\n"))}</p>);
  }

  return <div className="rich-text">{blocks}</div>;
}

function inlineMarkdown(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => part.startsWith("**") && part.endsWith("**") ? <strong key={index}>{part.slice(2, -2)}</strong> : part);
}
