"use client";

import Link from "next/link";
import { AlertTriangle, ArrowLeft, Bot, Check, CheckCircle2, ClipboardCheck, Clock3, Download, FileCheck2, Gauge, GitBranch, Layers3, LoaderCircle, MessageCircle, RefreshCw, RotateCcw, Save, Send, Sparkles, UserRound, X } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, DecisionReviewInput, Participant, ResolvedAssignment, Run, runExportUrl, subscribeToRun } from "../../../lib/api";

const DEFAULT_RUN_LIMITS = { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 };
const EMPTY_REVIEW: DecisionReviewInput = { selected_decision: "", expected_result: "", review_date: null, actual_result: "", outcome_status: "pending", seat_outcomes: [] };

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
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewDraft, setReviewDraft] = useState<DecisionReviewInput>(EMPTY_REVIEW);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewError, setReviewError] = useState("");

  const refresh = async (): Promise<void> => {
    if (!params.id) return;
    try {
      setRun(await api.run(params.id));
    } catch {
      router.push("/runs");
    }
  };
  useEffect(() => { refresh(); }, [params.id]);
  useEffect(() => {
    if (!run || run.status !== "running") return;
    const unsubscribe = subscribeToRun(run.id, () => refresh(), undefined, refresh);
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
  const activeAssignment = run
    ? agentTurnCount < 4
      ? run.seat_assignments?.[run.current_speaker_index]
      : run.finalizer_assignment
    : undefined;
  const activeProviderId = activeAssignment?.provider_id || run?.provider_id;
  const currentRequestUsesCCSwitch = activeProviderId === "ccswitch";
  const completedSpeakerIds = useMemo(() => new Set(run?.discussion_turns.filter((turn) => turn.speaker_type === "agent").map((turn) => turn.speaker_id) || []), [run?.discussion_turns]);
  const debateActive = run?.status === "running" && agentTurnCount < 4;
  const awaitingFinal = run?.status === "awaiting_final_input";
  const canWrite = Boolean(debateActive || awaitingFinal);
  const runFailed = run?.status === "failed";
  const runStopped = run?.status === "stopped";
  const providerTokens = (run?.usage.input_tokens || 0) + (run?.usage.output_tokens || 0);
  const runLimits = run?.limits || DEFAULT_RUN_LIMITS;
  const canResumeLimit = Boolean(runStopped && ["max_tokens", "max_model_calls"].includes(run?.limit_reason || ""));
  const suggestedTokenLimit = Math.min(100000, Math.max(40000, Math.ceil((providerTokens + 20000) / 10000) * 10000));
  const waitingSeconds = run && run.status === "running" && !run.awaiting_user
    ? Math.max(0, Math.floor((now - Date.parse(run.updated_at)) / 1000))
    : 0;
  const showWaitingRecovery = currentRequestUsesCCSwitch && waitingSeconds >= 45 && !waitingNoticeDismissed;

  const openDecisionReview = () => {
    if (!run?.final_decision) return;
    setReviewDraft(run.decision_review ? {
      selected_decision: run.decision_review.selected_decision,
      expected_result: run.decision_review.expected_result,
      review_date: run.decision_review.review_date || null,
      actual_result: run.decision_review.actual_result,
      outcome_status: run.decision_review.outcome_status,
      seat_outcomes: run.decision_review.seat_outcomes,
    } : {
      selected_decision: run.final_decision.final_answer.slice(0, 6000),
      expected_result: "",
      review_date: null,
      actual_result: "",
      outcome_status: "pending",
      seat_outcomes: run.participant_roles.map((item) => ({ role: item.id as "analyst" | "challenger" | "builder" | "observer", status: "pending", note: "" })),
    });
    setReviewError("");
    setReviewOpen(true);
  };

  const saveDecisionReview = async () => {
    if (!run || reviewBusy || !reviewDraft.selected_decision.trim() || !reviewDraft.expected_result.trim()) return;
    setReviewBusy(true); setReviewError("");
    try {
      setRun(await api.saveDecisionReview(run.id, reviewDraft));
      setReviewOpen(false);
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : "回访没有保存成功");
    } finally { setReviewBusy(false); }
  };

  const act = async (action: "interject" | "question") => {
    if (!run || busy || !canWrite || !draft.trim()) return;
    setBusy(true); setError("");
    try {
      const value = await api.interjectRun(run.id, { action, message: draft.trim(), target_agent: action === "question" ? target || undefined : undefined });
      setRun(value); setDraft(""); setTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "这一轮没有发出去");
    } finally { setBusy(false); }
  };

  const finalize = async () => {
    if (!run || busy || !awaitingFinal) return;
    setBusy(true); setError("");
    try { setRun(await api.summarizeRun(run.id)); }
    catch (err) { setError(err instanceof Error ? err.message : "最终答案没有生成成功"); }
    finally { setBusy(false); }
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

  const resumeAfterLimit = async () => {
    if (!run || busy || !canResumeLimit) return;
    setBusy(true); setError("");
    try {
      setRun(await api.resumeRun(run.id, {
        max_model_calls: Math.min(50, Math.max(runLimits.max_model_calls, run.usage.model_calls + 3)),
        max_tokens: suggestedTokenLimit,
        timeout_seconds: runLimits.timeout_seconds,
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "提高限额后仍未能继续");
    } finally { setBusy(false); }
  };

  if (!run) return <div className="loading-state"><LoaderCircle className="spin" size={22} />正在进入圆桌…</div>;

  return <div className="council-page">
    <header className="council-topbar">
      <Link href="/" className="back-link"><ArrowLeft size={15} />退出圆桌</Link>
      <div className="council-session"><span className={`status-dot ${run.status === "completed" ? "success" : runFailed || runStopped ? "failed" : ""}`} />{run.status === "completed" ? "讨论完成" : awaitingFinal ? "等待你的确认" : runStopped ? "达到运行限制" : runFailed ? "调用失败" : `第 ${Math.max(1, run.discussion_round)} 轮`} <span /> {run.mode === "quick" ? "引导" : run.mode === "rigorous" ? "深挖" : "圆桌"}模式</div>
      <div className="council-top-actions"><a className="icon-button" href={runExportUrl(run.id, "markdown")} download title="下载 Markdown 报告" aria-label="下载 Markdown 报告"><Download size={15} /></a><a className="icon-button" href={runExportUrl(run.id, "html")} download title="下载 HTML 报告" aria-label="下载 HTML 报告"><FileCheck2 size={15} /></a><button className="icon-button" aria-label="结束讨论" title="结束讨论" onClick={() => api.cancelRun(run.id).then(setRun)} disabled={!['running', 'awaiting_final_input'].includes(run.status)}><X size={16} /></button></div>
    </header>

    <main className="council-stage">
      <section className="council-question">
        <span>本次议题</span>
        <h1>{run.question}</h1>
        <p>{run.status === "completed" ? "四席与总结席调用完成，答案和过程均已保留。" : awaitingFinal ? "四席已完成；补充信息或直接确认生成最终答案。" : runStopped ? run.error : runFailed ? `${nextParticipant?.name || "记录员"}调用失败，已保留前面的公开讨论。` : agentTurnCount >= 4 ? "总结席正在综合公开讨论。" : `${nextParticipant?.name || "成员"}正在调用中，你可随时插话。`}</p>
      </section>

      <section className="council-callboard" aria-label="AI 独立调用顺序">
        <div className="callboard-meta"><Bot size={14} /><strong>4 席顺序调用</strong><span>各席独立配置</span><span>{run.template_name || "开放讨论"}</span>{run.project_name && <span>{run.project_name} · {run.source_snapshots?.length || 0} 份资料</span>}<div className="runtime-meta"><span title="工作流引擎"><GitBranch size={12} />{run.workflow_engine === "langgraph" ? "LangGraph" : "Council"}</span><span title="持久检查点"><Save size={12} />{run.checkpoint_count || 0} 个检查点</span><span title="本席发送的讨论上下文"><Layers3 size={12} />上下文 {run.context_snapshot?.estimated_tokens || 0} / {run.context_snapshot?.token_budget || 0}</span><span title="Provider 返回的全程累计用量，包含上游基础指令"><Gauge size={12} />上游累计 {providerTokens.toLocaleString()} / {runLimits.max_tokens.toLocaleString()}</span></div></div>
        <div className="council-seats">
          {run.participant_roles.map((participant, index) => <Seat key={participant.id} participant={participant} assignment={run.seat_assignments?.[index]} index={index} selected={target === participant.id} status={completedSpeakerIds.has(participant.id) ? "completed" : runFailed && run.current_speaker_index === index ? "failed" : debateActive && run.current_speaker_index === index ? "active" : "queued"} onSelect={() => debateActive && setTarget(target === participant.id ? null : participant.id)} />)}
          <div className={`summary-node ${run.status === "completed" ? "completed" : runFailed && agentTurnCount >= 4 ? "failed" : agentTurnCount >= 4 ? "active" : "queued"}`} aria-label="第 5 次调用：记录员总结">
            <FileCheck2 size={17} /><span><strong>最终答案</strong><small>第 5 次调用</small></span>
          </div>
        </div>
      </section>

      <section className={`council-dialogue ${run.source_snapshots?.length ? "with-sources" : ""}`}>
        <div className="dialogue-header">
          <div><MessageCircle size={15} /><strong>公开讨论</strong><span>{agentTurnCount} 次 AI 发言 · {run.discussion_turns.filter((turn) => turn.speaker_type === "user").length} 次你的参与</span></div>
          <span className={`discussion-state ${runFailed || runStopped ? "failed" : ""}`}>{run.status === "completed" ? "已完成" : awaitingFinal ? "等待确认" : runStopped ? "已停止" : runFailed ? "调用失败" : debateActive ? "全程可插话" : "生成答案"}</span>
        </div>

        {Boolean(run.source_snapshots?.length) && <div className="source-strip" aria-label="本次资料快照"><strong>资料快照</strong>{run.source_snapshots!.map((source, index) => <span key={source.id} title={`${source.url || source.filename || "本地文字"}\nSHA-256 ${source.sha256}`}><b>[S{index + 1}]</b>{source.title}</span>)}</div>}

        <div className="dialogue-scroll" ref={transcriptRef} aria-live="polite">
          <article className="opening-question"><span>你提出</span><p>{run.question}</p></article>
          {run.discussion_turns.map((turn) => <article key={turn.id} className={`discussion-turn ${turn.speaker_type} speaker-${turn.speaker_id}`}>
            <header><span className="speaker-avatar">{turn.speaker_type === "user" ? <UserRound size={15} /> : turn.speaker_name.slice(0, 1)}</span><div><strong>{turn.speaker_name}</strong><small>{turn.role_label || "参与者"} · 第 {turn.round} 轮{turn.provider_name ? ` · ${turn.provider_name} / ${turn.model}` : ""}</small></div></header>
            <RichText content={turn.content} />
          </article>)}
          {run.status === "running" && <article className="discussion-thinking">
            <LoaderCircle className="spin" size={17} />
            <div className="discussion-thinking-copy">
              <span><strong>{debateActive ? nextParticipant?.name || "下一位成员" : "记录员"}</strong>{currentRequestUsesCCSwitch && waitingSeconds >= 10 ? "正在等待 CC Switch 返回上游响应" : debateActive ? "正在阅读并回应前面的发言" : "正在综合四席讨论"}</span>
              <small><Clock3 size={12} />已等待 {waitingSeconds} 秒{currentRequestUsesCCSwitch ? " · 请求由 CC Switch 路由；若已配置故障转移，将由它处理" : ""}</small>
              {showWaitingRecovery && <div className="discussion-recovery">
                <span>上游响应较慢，你可以继续等，或中止这次请求并重试当前席位。</span>
                <button className="quiet-button" onClick={() => setWaitingNoticeDismissed(true)}>继续等待</button>
                <button className="quiet-button" onClick={retryTurn} disabled={busy}>{busy ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}重试本席</button>
              </div>}
            </div>
          </article>}
          {run.status === "completed" && run.final_decision && <article className="roundtable-summary"><header><Check size={16} /><span><strong>圆桌最终答案</strong><small>第 5 次调用 · 模型共识未经过外部事实核验</small></span></header><RichText content={run.final_decision.final_answer} /></article>}
        </div>

        {runFailed && <div className="failed-actions" role="alert">
          <AlertTriangle size={18} />
          <div><strong>{nextParticipant?.name || "记录员"}没有完成调用</strong><span>{run.error || "当前上游请求未完成，前面的公开讨论已经保留。"}</span></div>
          <button className="send-button" onClick={retryTurn} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}重试{nextParticipant?.name || "总结"}</button>
        </div>}

        {runStopped && <div className="failed-actions" role="status"><Gauge size={18} /><div><strong>运行已按后端限制停止，已完成内容不会重复调用</strong><span>{error || run.error}</span></div>{canResumeLimit ? <button className="send-button" onClick={resumeAfterLimit} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}提高到 {suggestedTokenLimit.toLocaleString()} Token 并继续</button> : <Link className="send-button" href="/settings/budget">查看限制</Link>}</div>}

        {(run.status === "running" || awaitingFinal) && <div className="participation-dock">
          <div className="participation-context">
            {selectedParticipant ? <button onClick={() => setTarget(null)}><span>正在点名</span><strong>{selectedParticipant.name}</strong><X size={13} /></button> : <span>写下你的观点，或点击上方任一席位点名追问</span>}
            <small>{awaitingFinal ? "这些补充会进入第五次总结调用。" : "席位会依次发言；你的插话会进入后续上下文。"}</small>
          </div>
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} disabled={!canWrite || busy} placeholder={awaitingFinal ? "最终答案生成前，我还想补充…" : selectedParticipant ? `向${selectedParticipant.name}追问…` : "我想补充 / 反驳 / 改变讨论方向…"} rows={2} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") act(selectedParticipant ? "question" : "interject"); }} />
          <div className="participation-actions">
            <span className="debate-progress">{debateActive ? `已完成 ${agentTurnCount} / 4 席` : "四席完成，等待你的确认"}</span>
            <span />
            <button className="quiet-button" disabled={!canWrite || busy || !draft.trim()} onClick={() => act(selectedParticipant ? "question" : "interject")}>{busy ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />}{awaitingFinal ? "加入最终补充" : selectedParticipant ? `问${selectedParticipant.name}` : "加入讨论"}</button>
            {awaitingFinal && <button className="send-button" disabled={busy} onClick={finalize}>{busy ? <LoaderCircle className="spin" size={15} /> : <FileCheck2 size={15} />}生成最终答案</button>}
          </div>
          {(error || run.error) && <p className="discussion-error">{error || run.error}</p>}
        </div>}

        {run.status === "completed" && <div className="completed-actions"><a className="quiet-button" href={runExportUrl(run.id, "markdown")} download><Download size={15} />Markdown</a><a className="quiet-button" href={runExportUrl(run.id, "html")} download><FileCheck2 size={15} />HTML 报告</a><button className="quiet-button" onClick={openDecisionReview}><ClipboardCheck size={15} />{run.decision_review ? "编辑回访" : "结果回访"}</button><span /><button className="quiet-button" onClick={async () => { const next = await api.rerun(run.id); router.push(`/runs/${next.id}`); }}><RotateCcw size={15} />重新开一桌</button><Link className="send-button" href="/">讨论新问题<Sparkles size={15} /></Link></div>}
      </section>
    </main>
    {reviewOpen && <div className="decision-review-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setReviewOpen(false); }}>
      <section className="decision-review-dialog" role="dialog" aria-modal="true" aria-labelledby="decision-review-title">
        <header><div><span>DECISION FOLLOW-UP</span><h2 id="decision-review-title">结果回访</h2><p>把当时的判断和后来发生的事放在一起。</p></div><button className="icon-button" onClick={() => setReviewOpen(false)} aria-label="关闭结果回访"><X size={16} /></button></header>
        <div className="decision-review-fields">
          <label className="review-field review-wide"><span>最终采用的决定</span><textarea aria-label="最终采用的决定" rows={2} maxLength={6000} value={reviewDraft.selected_decision} onChange={(event) => setReviewDraft({ ...reviewDraft, selected_decision: event.target.value })} /></label>
          <label className="review-field review-wide"><span>预期结果</span><textarea aria-label="预期结果" rows={2} maxLength={6000} value={reviewDraft.expected_result} onChange={(event) => setReviewDraft({ ...reviewDraft, expected_result: event.target.value })} placeholder="当时希望发生什么" /></label>
          <label className="review-field"><span>复盘日期</span><input aria-label="复盘日期" type="date" value={reviewDraft.review_date || ""} onChange={(event) => setReviewDraft({ ...reviewDraft, review_date: event.target.value || null })} /></label>
          <label className="review-field"><span>实际结果</span><select aria-label="结果状态" value={reviewDraft.outcome_status} onChange={(event) => setReviewDraft({ ...reviewDraft, outcome_status: event.target.value as DecisionReviewInput["outcome_status"] })}><option value="pending">等待回访</option><option value="successful">达到预期</option><option value="partial">部分达到</option><option value="unsuccessful">未达到</option><option value="unclear">暂不明确</option></select></label>
          <label className="review-field review-wide"><span>实际发生了什么</span><textarea aria-label="实际发生了什么" rows={2} maxLength={6000} value={reviewDraft.actual_result} onChange={(event) => setReviewDraft({ ...reviewDraft, actual_result: event.target.value })} placeholder="可以稍后再填写" /></label>
        </div>
        <div className="seat-review-list"><span>四席观点验证</span>{reviewDraft.seat_outcomes.map((item, index) => {
          const participant = run.participant_roles.find((entry) => entry.id === item.role);
          return <div key={item.role}><strong>{participant?.name || item.role}</strong><select aria-label={`${participant?.name || item.role}观点验证`} value={item.status} onChange={(event) => { const next = [...reviewDraft.seat_outcomes]; next[index] = { ...item, status: event.target.value as typeof item.status }; setReviewDraft({ ...reviewDraft, seat_outcomes: next }); }}><option value="pending">待验证</option><option value="supported">得到支持</option><option value="mixed">部分成立</option><option value="contradicted">被结果反驳</option></select><input aria-label={`${participant?.name || item.role}验证备注`} value={item.note} maxLength={1000} onChange={(event) => { const next = [...reviewDraft.seat_outcomes]; next[index] = { ...item, note: event.target.value }; setReviewDraft({ ...reviewDraft, seat_outcomes: next }); }} placeholder="备注（可选）" /></div>;
        })}</div>
        <footer>{reviewError ? <span className="review-error">{reviewError}</span> : <span>回访会写入本地记录和导出报告。</span>}<button className="send-button" onClick={saveDecisionReview} disabled={reviewBusy || !reviewDraft.selected_decision.trim() || !reviewDraft.expected_result.trim()}>{reviewBusy ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}保存回访</button></footer>
      </section>
    </div>}
  </div>;
}

function Seat({ participant, assignment, index, selected, status, onSelect }: { participant: Participant; assignment?: ResolvedAssignment; index: number; selected: boolean; status: "queued" | "active" | "completed" | "failed"; onSelect: () => void }) {
  const statusLabel = status === "failed" ? "调用失败" : status === "completed" ? "已完成" : status === "active" ? "调用中" : selected ? "已点名" : "待调用";
  return <button type="button" className={`council-seat seat-${participant.id} ${selected ? "selected" : ""} ${status}`} onClick={onSelect} aria-pressed={selected}>
    <span className="seat-number">{String(index + 1).padStart(2, "0")}</span>
    <span className="seat-avatar">{participant.name.slice(0, 1)}</span>
    <span className="seat-copy"><strong>{participant.name}</strong><small title={assignment ? `${assignment.provider_name} / ${assignment.model}` : participant.role}>{assignment ? `${assignment.provider_name} · ${assignment.model}` : participant.role}</small></span>
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
