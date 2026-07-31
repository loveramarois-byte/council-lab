"use client";

import Link from "next/link";
import { AlertTriangle, ArrowLeft, Bot, Check, CheckCircle2, ClipboardCheck, Clock3, Download, FileCheck2, Gauge, GitBranch, Layers3, LoaderCircle, LockKeyhole, Maximize2, MessageCircle, Minimize2, RefreshCw, RotateCcw, Save, Send, ShieldAlert, Sparkles, UserRound, X } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, CouncilApiError, DecisionBrief, DecisionBriefComparison, DecisionClaimView, DecisionReviewInput, ForkCheckpoint, HighRiskApproval, HighRiskAuditEvent, HighRiskRun, MemoryProposalView, Participant, RequiredFact, ResolvedAssignment, Run, RunForkLineage, runExportUrl, subscribeToRun } from "../../../lib/api";

const DEFAULT_RUN_LIMITS = { max_model_calls: 8, max_tokens: 40000, timeout_seconds: 120 };
const EMPTY_REVIEW: DecisionReviewInput = { selected_decision: "", expected_result: "", review_date: null, actual_result: "", outcome_status: "pending", seat_outcomes: [] };

export default function RunDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const pageRef = useRef<HTMLDivElement>(null);
  const immersiveTriggerRef = useRef<HTMLButtonElement>(null);
  const immersiveExitRef = useRef<HTMLButtonElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const fullscreenOwnedRef = useRef(false);
  const immersiveDesiredRef = useRef(false);
  const immersiveRequestRef = useRef(0);
  const highRiskProbeRef = useRef<{ runId: string; result: "unknown" | "pending" | "present" | "absent" }>({ runId: "", result: "unknown" });
  const [run, setRun] = useState<Run | null>(null);
  const [decisionBrief, setDecisionBrief] = useState<DecisionBrief | null>(null);
  const [lineage, setLineage] = useState<RunForkLineage>({ children: [] });
  const [comparison, setComparison] = useState<DecisionBriefComparison | null>(null);
  const [claims, setClaims] = useState<DecisionClaimView[]>([]);
  const [forkOpen, setForkOpen] = useState(false);
  const [forkCheckpoint, setForkCheckpoint] = useState<ForkCheckpoint>("before_deliberation");
  const [forkReason, setForkReason] = useState("");
  const [forkPrompt, setForkPrompt] = useState("");
  const [forkBusy, setForkBusy] = useState(false);
  const [forkError, setForkError] = useState("");
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [memoryProposals, setMemoryProposals] = useState<MemoryProposalView[]>([]);
  const [memoryDrafts, setMemoryDrafts] = useState<Record<string, string>>({});
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [memoryError, setMemoryError] = useState("");
  const [immersive, setImmersive] = useState(false);
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
  const [highRisk, setHighRisk] = useState<HighRiskRun | null>(null);
  const [highRiskApproval, setHighRiskApproval] = useState<HighRiskApproval | null>(null);
  const [highRiskAudit, setHighRiskAudit] = useState<HighRiskAuditEvent[]>([]);
  const [highRiskOpen, setHighRiskOpen] = useState(false);
  const [factDraft, setFactDraft] = useState<Record<string, string>>({});
  const [reportDraft, setReportDraft] = useState("");
  const [reviewerId, setReviewerId] = useState("");
  const [reviewerKey, setReviewerKey] = useState("");
  const [approvalReason, setApprovalReason] = useState("");
  const [highRiskBusy, setHighRiskBusy] = useState(false);
  const [highRiskError, setHighRiskError] = useState("");

  const refreshHighRiskAudit = async (runId: string) => {
    try { setHighRiskAudit(await api.highRiskAudit(runId)); }
    catch {}
  };

  const refresh = async (): Promise<void> => {
    if (!params.id) return;
    try {
      const nextRun = await api.run(params.id);
      setRun(nextRun);
      if (nextRun.status === "completed") {
        try { setDecisionBrief(await api.decisionBrief(params.id)); }
        catch (briefError) {
          if (briefError instanceof CouncilApiError && briefError.status === 404) setDecisionBrief(null);
          else throw briefError;
        }
        try {
          const nextLineage = await api.runLineage(params.id);
          setLineage(nextLineage);
          if (nextLineage.parent) {
            try { setComparison(await api.compareRuns(nextLineage.parent.parent_run_id, params.id)); }
            catch { setComparison(null); }
          } else setComparison(null);
        } catch { setLineage({ children: [] }); setComparison(null); }
        try { setClaims(await api.decisionClaims(params.id)); } catch { setClaims([]); }
        try {
          const proposals = await api.memoryProposals(params.id);
          setMemoryProposals(proposals);
          setMemoryDrafts((current) => ({ ...Object.fromEntries(proposals.map((item) => [item.proposal.id, item.proposal.content])), ...current }));
        } catch { setMemoryProposals([]); }
      } else { setDecisionBrief(null); setComparison(null); setClaims([]); }
      if (highRiskProbeRef.current.runId !== params.id) {
        highRiskProbeRef.current = { runId: params.id, result: "unknown" };
      }
      const shouldLoadHighRisk = nextRun.high_risk_control === true
        || (nextRun.high_risk_control == null && ["unknown", "present"].includes(highRiskProbeRef.current.result));
      if (!shouldLoadHighRisk) {
        setHighRisk(null);
        setHighRiskApproval(null);
        setHighRiskAudit([]);
        return;
      }
      try {
        if (nextRun.high_risk_control == null && highRiskProbeRef.current.result === "unknown") {
          highRiskProbeRef.current.result = "pending";
        }
        const nextHighRisk = await api.highRiskRun(params.id);
        highRiskProbeRef.current.result = "present";
        setHighRisk(nextHighRisk);
        await refreshHighRiskAudit(params.id);
        if (nextHighRisk.decision?.report) setReportDraft(nextHighRisk.decision.report);
        setFactDraft((current) => Object.keys(current).length ? current : Object.fromEntries(nextHighRisk.required_facts.map((fact) => [fact.fact_id, fact.value || ""])));
        try { setHighRiskApproval(await api.highRiskApproval(params.id)); }
        catch (approvalError) {
          if (approvalError instanceof CouncilApiError && approvalError.code === "APPROVAL_NOT_FOUND") setHighRiskApproval(null);
          else throw approvalError;
        }
      } catch (highRiskLoadError) {
        if (highRiskLoadError instanceof CouncilApiError && highRiskLoadError.code === "HIGH_RISK_RUN_NOT_FOUND") {
          highRiskProbeRef.current.result = "absent";
          setHighRisk(null);
          setHighRiskApproval(null);
          setHighRiskAudit([]);
        } else throw highRiskLoadError;
      }
    } catch {
      router.push("/runs");
    }
  };
  useEffect(() => { setHighRiskAudit([]); setDecisionBrief(null); setLineage({ children: [] }); setComparison(null); setClaims([]); setMemoryProposals([]); refresh(); }, [params.id]);
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
  useEffect(() => {
    if (!immersive) return;
    const frame = window.requestAnimationFrame(() => immersiveExitRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [immersive]);
  useEffect(() => {
    const onFullscreenChange = () => {
      const ownsFullscreen = document.fullscreenElement === pageRef.current;
      if (ownsFullscreen) {
        fullscreenOwnedRef.current = true;
        if (immersiveDesiredRef.current) setImmersive(true);
        else void document.exitFullscreen().catch(() => undefined);
      } else if (fullscreenOwnedRef.current) {
        fullscreenOwnedRef.current = false;
        immersiveDesiredRef.current = false;
        immersiveRequestRef.current += 1;
        setImmersive(false);
        window.requestAnimationFrame(() => immersiveTriggerRef.current?.focus());
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || !immersive) return;
      immersiveDesiredRef.current = false;
      immersiveRequestRef.current += 1;
      fullscreenOwnedRef.current = false;
      setImmersive(false);
      window.requestAnimationFrame(() => immersiveTriggerRef.current?.focus());
      if (document.fullscreenElement === pageRef.current) void document.exitFullscreen().catch(() => undefined);
    };
    document.addEventListener("fullscreenchange", onFullscreenChange);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [immersive]);

  const nextParticipant = useMemo(() => run?.participant_roles[run.current_speaker_index], [run]);
  const selectedParticipant = run?.participant_roles.find((item) => item.id === target) || null;
  const agentTurnCount = run?.discussion_turns.filter((turn) => turn.speaker_type === "agent").length || 0;
  const seatCount = run?.participant_roles.length || 4;
  const summaryCallNumber = seatCount + 1;
  const expectedModelCalls = run?.analysis?.expected_model_calls || summaryCallNumber;
  const discussionComplete = agentTurnCount >= seatCount;
  const activeAssignment = run
    ? agentTurnCount < seatCount
      ? run.seat_assignments?.[run.current_speaker_index]
      : run.finalizer_assignment
    : undefined;
  const activeProviderId = activeAssignment?.provider_id || run?.provider_id;
  const currentRequestUsesCCSwitch = activeProviderId === "ccswitch";
  const completedSpeakerIds = useMemo(() => new Set(run?.discussion_turns.filter((turn) => turn.speaker_type === "agent").map((turn) => turn.speaker_id) || []), [run?.discussion_turns]);
  const debateActive = run?.status === "running" && agentTurnCount < seatCount;
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
  const missingCriticalFacts = highRisk?.required_facts.filter((fact) => fact.required && fact.materiality === "critical" && !fact.value).length || 0;

  const openHighRiskControl = () => {
    if (highRisk && !reportDraft && run) {
      setReportDraft(run.discussion_turns.map((turn) => `${turn.speaker_name}：${turn.content}`).join("\n\n"));
    }
    setHighRiskError("");
    setHighRiskOpen(true);
  };

  const saveHighRiskFacts = async () => {
    if (!highRisk || highRiskBusy) return;
    setHighRiskBusy(true); setHighRiskError("");
    try {
      const facts: RequiredFact[] = highRisk.required_facts.map((fact) => ({ ...fact, value: factDraft[fact.fact_id]?.trim() || null }));
      setHighRisk(await api.updateHighRiskFacts(highRisk.run_id, facts));
      await refreshHighRiskAudit(highRisk.run_id);
    } catch (err) { setHighRiskError(err instanceof Error ? err.message : "关键事实没有保存成功"); }
    finally { setHighRiskBusy(false); }
  };

  const submitHighRiskReview = async () => {
    if (!highRisk || highRiskBusy || !reportDraft.trim()) return;
    setHighRiskBusy(true); setHighRiskError("");
    try {
      setHighRisk(await api.prepareHighRiskReview(highRisk.run_id, reportDraft.trim()));
      const approval = await api.requestHighRiskApproval(highRisk.run_id);
      setHighRiskApproval(approval);
      setHighRisk(await api.highRiskRun(highRisk.run_id));
      await refreshHighRiskAudit(highRisk.run_id);
    } catch (err) { setHighRiskError(err instanceof Error ? err.message : "报告没有进入人工复核"); }
    finally { setHighRiskBusy(false); }
  };

  const requestHighRiskApproval = async () => {
    if (!highRisk || highRiskBusy) return;
    setHighRiskBusy(true); setHighRiskError("");
    try {
      const approval = await api.requestHighRiskApproval(highRisk.run_id);
      setHighRiskApproval(approval);
      setHighRisk(await api.highRiskRun(highRisk.run_id));
      await refreshHighRiskAudit(highRisk.run_id);
    } catch (err) { setHighRiskError(err instanceof Error ? err.message : "审批申请没有创建成功"); }
    finally { setHighRiskBusy(false); }
  };

  const decideHighRisk = async (decision: "approved" | "rejected") => {
    if (!highRisk || !highRiskApproval || highRiskBusy || !reviewerId.trim() || !reviewerKey || !approvalReason.trim()) return;
    setHighRiskBusy(true); setHighRiskError("");
    try {
      setHighRiskApproval(await api.decideHighRiskApproval(highRisk.run_id, highRiskApproval.approval_id, reviewerId.trim(), reviewerKey, decision, approvalReason.trim()));
      setReviewerKey("");
      setHighRisk(await api.highRiskRun(highRisk.run_id));
      await refreshHighRiskAudit(highRisk.run_id);
    } catch (err) {
      setHighRiskError(err instanceof Error ? err.message : "审批决定没有保存成功");
      await refresh();
    }
    finally { setHighRiskBusy(false); }
  };

  const completeHighRisk = async () => {
    if (!highRisk || !highRiskApproval || highRiskBusy) return;
    setHighRiskBusy(true); setHighRiskError("");
    try {
      setHighRisk(await api.completeHighRiskRun(highRisk.run_id, highRiskApproval.approval_id));
      await refreshHighRiskAudit(highRisk.run_id);
    }
    catch (err) {
      setHighRiskError(err instanceof Error ? err.message : "高风险报告没有完成");
      await refresh();
    }
    finally { setHighRiskBusy(false); }
  };

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
      setClaims(await api.decisionClaims(run.id));
      setReviewOpen(false);
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : "回访没有保存成功");
    } finally { setReviewBusy(false); }
  };

  const createFork = async () => {
    if (!run || forkBusy || forkReason.trim().length < 3) return;
    setForkBusy(true); setForkError("");
    try {
      const child = await api.forkRun(run.id, {
        checkpoint: forkCheckpoint,
        reason: forkReason.trim(),
        prompt_append: forkPrompt.trim(),
        auto_summarize: false,
      });
      setForkOpen(false);
      router.push(`/runs/${child.id}`);
    } catch (err) {
      setForkError(err instanceof Error ? err.message : "分叉没有创建成功");
    } finally { setForkBusy(false); }
  };

  const openMemory = async () => {
    if (!run) return;
    setMemoryOpen(true); setMemoryBusy(true); setMemoryError("");
    try {
      const proposals = memoryProposals.length ? memoryProposals : await api.createMemoryProposals(run.id);
      setMemoryProposals(proposals);
      setMemoryDrafts(Object.fromEntries(proposals.map((item) => [item.proposal.id, item.proposal.content])));
    } catch (err) { setMemoryError(err instanceof Error ? err.message : "无法生成记忆候选"); }
    finally { setMemoryBusy(false); }
  };

  const decideMemory = async (proposalId: string, decision: "approve" | "reject") => {
    setMemoryBusy(true); setMemoryError("");
    try {
      if (decision === "approve") await api.approveMemoryProposal(proposalId, memoryDrafts[proposalId]?.trim());
      else await api.rejectMemoryProposal(proposalId);
      if (run) setMemoryProposals(await api.memoryProposals(run.id));
    } catch (err) { setMemoryError(err instanceof Error ? err.message : "记忆候选处理失败"); }
    finally { setMemoryBusy(false); }
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

  const enterImmersive = async () => {
    immersiveDesiredRef.current = true;
    const requestId = immersiveRequestRef.current + 1;
    immersiveRequestRef.current = requestId;
    setImmersive(true);
    const supportsDesktopFullscreen = window.matchMedia("(min-width: 681px)").matches && document.fullscreenEnabled && pageRef.current?.requestFullscreen;
    if (!supportsDesktopFullscreen) return;
    try {
      await pageRef.current!.requestFullscreen();
      if (!immersiveDesiredRef.current || immersiveRequestRef.current !== requestId) {
        if (document.fullscreenElement === pageRef.current) await document.exitFullscreen().catch(() => undefined);
        return;
      }
      fullscreenOwnedRef.current = true;
    } catch {
      fullscreenOwnedRef.current = false;
    }
  };

  const exitImmersive = async () => {
    immersiveDesiredRef.current = false;
    immersiveRequestRef.current += 1;
    setImmersive(false);
    fullscreenOwnedRef.current = false;
    window.requestAnimationFrame(() => immersiveTriggerRef.current?.focus());
    if (document.fullscreenElement === pageRef.current) {
      try { await document.exitFullscreen(); } catch { /* CSS immersion has already exited. */ }
    }
  };

  if (!run) return <div className="loading-state"><LoaderCircle className="spin" size={22} />正在进入圆桌…</div>;

  return <div ref={pageRef} className={`council-page ${immersive ? "immersive" : ""}`}>
    <header className="council-topbar">
      <Link href="/" className="back-link"><ArrowLeft size={15} />退出圆桌</Link>
      <div className="council-session"><span className={`status-dot ${run.status === "completed" ? "success" : runFailed || runStopped ? "failed" : ""}`} />{run.status === "completed" ? "讨论完成" : awaitingFinal ? "等待你的确认" : runStopped ? "达到运行限制" : runFailed ? "调用失败" : `第 ${Math.max(1, run.discussion_round)} 轮`} <span /> {highRisk ? "高风险决策支持" : run.mode === "quick" ? "引导模式" : run.mode === "rigorous" ? "深挖模式" : "圆桌模式"}</div>
      <div className="council-top-actions"><button ref={immersiveTriggerRef} className="icon-button immersive-enter" type="button" aria-label="进入沉浸模式" title="进入沉浸模式" aria-pressed={immersive} onClick={enterImmersive}><Maximize2 size={16} /></button><a className="icon-button" href={runExportUrl(run.id, "markdown")} download title="下载 Markdown 报告" aria-label="下载 Markdown 报告"><Download size={15} /></a><a className="icon-button" href={runExportUrl(run.id, "html")} download title="下载 HTML 报告" aria-label="下载 HTML 报告"><FileCheck2 size={15} /></a><button className="icon-button" aria-label="结束讨论" title="结束讨论" onClick={() => { if (highRisk) void api.cancelHighRiskRun(run.id).then((value) => { setHighRisk(value); void refresh(); }); else void api.cancelRun(run.id).then(setRun); }} disabled={!['running', 'awaiting_final_input'].includes(run.status)}><X size={16} /></button></div>
    </header>

    {immersive && <button ref={immersiveExitRef} className="immersive-exit icon-button" type="button" aria-label="退出沉浸模式" title="退出沉浸模式" aria-pressed={true} onClick={exitImmersive}><Minimize2 size={17} /></button>}

    <main className={`council-stage ${highRisk ? "has-high-risk" : ""}`}>
      <section className="council-question">
        <span>本次议题</span>
        <h1>{run.question}</h1>
        <p>{run.status === "completed" ? `${seatCount} 席与总结席调用完成，答案和过程均已保留。` : awaitingFinal ? `${seatCount} 席已完成；补充信息或直接确认生成最终答案。` : runStopped ? run.error : runFailed ? `${nextParticipant?.name || "记录员"}调用失败，已保留前面的公开讨论。` : discussionComplete ? "总结席正在综合公开讨论。" : `${nextParticipant?.name || "成员"}正在调用中，你可随时插话。`}</p>
      </section>

      <section className="council-callboard" aria-label="AI 独立调用顺序">
        <div className="callboard-meta"><Bot size={14} /><strong>{seatCount} 席顺序调用</strong><span>{run.analysis?.short_task_route ? "短任务精简路线" : "各席独立配置"}</span><span>{run.template_name || "开放讨论"}</span>{run.project_name && <span>{run.project_name} · {run.source_snapshots?.length || 0} 份资料</span>}<div className="runtime-meta"><span title="工作流引擎"><GitBranch size={12} />{run.workflow_engine === "langgraph" ? "LangGraph" : "Council"}</span><span title="持久检查点"><Save size={12} />{run.checkpoint_count || 0} 个检查点</span><span title="成功模型调用的实际次数和系统预计总次数"><Gauge size={12} />调用 {run.usage.model_calls} / 预计 {expectedModelCalls}</span><span title={`本席发送的讨论上下文；${run.context_snapshot?.token_estimator_exact ? "使用模型精确 tokenizer" : "使用偏保守估算"}`}><Layers3 size={12} />上下文 {run.context_snapshot?.estimated_tokens || 0} / {run.context_snapshot?.token_budget || 0} · {run.context_snapshot?.token_estimator_exact ? "精确" : "估算"}</span><span title="Provider 返回的全程累计用量，包含上游基础指令"><Gauge size={12} />上游累计 {providerTokens.toLocaleString()} / {runLimits.max_tokens.toLocaleString()}</span></div></div>
        <div className="council-seats">
          {run.participant_roles.map((participant, index) => <Seat key={participant.id} participant={participant} assignment={run.seat_assignments?.[index]} index={index} selected={target === participant.id} status={completedSpeakerIds.has(participant.id) ? "completed" : runFailed && run.current_speaker_index === index ? "failed" : debateActive && run.current_speaker_index === index ? "active" : "queued"} onSelect={() => debateActive && setTarget(target === participant.id ? null : participant.id)} />)}
          <div className={`summary-node ${run.status === "completed" ? "completed" : runFailed && discussionComplete ? "failed" : discussionComplete ? "active" : "queued"}`} aria-label={`第 ${summaryCallNumber} 次调用：记录员总结`}>
            <FileCheck2 size={17} /><span><strong>最终答案</strong><small>第 {summaryCallNumber} 次调用</small></span>
          </div>
        </div>
      </section>

      {highRisk && <section className={`high-risk-gate status-${highRisk.status.toLowerCase()}`} aria-label="高风险决策支持状态">
        <ShieldAlert size={17} />
        <div><strong>{highRiskStatusLabel(highRisk.status)}</strong><span>{highRisk.risk_assessment.risk_tier.toUpperCase()} · {highRisk.risk_assessment.detected_domains.map(domainLabel).join(" / ")} · {missingCriticalFacts ? `${missingCriticalFacts} 项关键事实缺失` : "关键事实已填写"}</span></div>
        <LockKeyhole size={14} /><span>外部动作禁止</span>
        <button type="button" className="quiet-button" onClick={openHighRiskControl}>打开控制面</button>
      </section>}

      <section className={`council-dialogue ${run.source_snapshots?.length ? "with-sources" : ""}`}>
        <div className="dialogue-header">
          <div><MessageCircle size={15} /><strong>公开讨论</strong><span>{agentTurnCount} 次 AI 发言 · {run.discussion_turns.filter((turn) => turn.speaker_type === "user").length} 次你的参与</span></div>
          <span className={`discussion-state ${runFailed || runStopped ? "failed" : ""}`}>{run.status === "completed" ? "已完成" : awaitingFinal ? "等待确认" : runStopped ? "已停止" : runFailed ? "调用失败" : debateActive ? "全程可插话" : "生成答案"}</span>
        </div>

        {Boolean(run.source_snapshots?.length) && <div className="source-strip" aria-label="本次资料快照"><strong>资料快照</strong>{run.source_snapshots!.map((source, index) => <span key={source.id} title={`${source.url || source.filename || "本地文字"}\nSHA-256 ${source.sha256}`}><b>[S{index + 1}]</b>{source.title}</span>)}</div>}
        {Boolean(run.memory_snapshot?.length) && <div className="source-strip memory-snapshot-strip" aria-label="本次已批准记忆快照"><strong>已批准记忆</strong>{run.memory_snapshot!.map((item) => <span key={item.memory_id} title={`来源 Run ${item.source_run_id}`}><b>{item.type}</b>{item.content}</span>)}</div>}

        <div className="dialogue-scroll" ref={transcriptRef} aria-live="polite">
          <article className="opening-question"><span>你提出</span><p>{run.question}</p></article>
          {run.discussion_turns.map((turn) => <article key={turn.id} className={`discussion-turn ${turn.speaker_type} speaker-${turn.speaker_id}`}>
            <header><span className="speaker-avatar">{turn.speaker_type === "user" ? <UserRound size={15} /> : turn.speaker_name.slice(0, 1)}</span><div><strong>{turn.speaker_name}</strong><small>{turn.role_label || "参与者"} · 第 {turn.round} 轮{turn.provider_name ? ` · ${turn.provider_name} / ${turn.model}` : ""}{turn.reused_from_run_id ? " · 复用父 Run" : ""}</small></div></header>
            <RichText content={turn.content} />
          </article>)}
          {run.status === "running" && <article className="discussion-thinking">
            <LoaderCircle className="spin" size={17} />
            <div className="discussion-thinking-copy">
              <span><strong>{debateActive ? nextParticipant?.name || "下一位成员" : "记录员"}</strong>{currentRequestUsesCCSwitch && waitingSeconds >= 10 ? "正在等待 CC Switch 返回上游响应" : debateActive ? "正在阅读并回应前面的发言" : `正在综合 ${seatCount} 席讨论`}</span>
              <small><Clock3 size={12} />已等待 {waitingSeconds} 秒{currentRequestUsesCCSwitch ? " · 请求由 CC Switch 路由；若已配置故障转移，将由它处理" : ""}</small>
              {showWaitingRecovery && <div className="discussion-recovery">
                <span>上游响应较慢，你可以继续等，或中止这次请求并重试当前席位。</span>
                <button className="quiet-button" onClick={() => setWaitingNoticeDismissed(true)}>继续等待</button>
                <button className="quiet-button" onClick={retryTurn} disabled={busy}>{busy ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}重试本席</button>
              </div>}
            </div>
          </article>}
          {run.status === "completed" && decisionBrief && <DecisionBriefView brief={decisionBrief} />}
          {run.status === "completed" && claims.length > 0 && <DecisionClaimsView claims={claims} />}
          {run.status === "completed" && comparison && <DecisionComparisonView comparison={comparison} />}
          {run.status === "completed" && run.final_decision && (decisionBrief
            ? <details className="roundtable-summary raw-summary"><summary>查看原始综合文本</summary><RichText content={run.final_decision.final_answer} /></details>
            : <article className="roundtable-summary"><header><Check size={16} /><span><strong>圆桌最终答案</strong><small>第 {summaryCallNumber} 次调用 · 共 {run.usage.model_calls} 次模型调用</small></span></header><div className="verification-warning" role="note"><AlertTriangle size={16} /><span><strong>未经过外部事实核验</strong><small>模型共识不等于事实。关键结论请使用第一方资料或可复现测试核对。</small></span></div><RichText content={run.final_decision.final_answer} /></article>)}
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
            <small>{awaitingFinal ? `这些补充会进入第 ${summaryCallNumber} 次总结调用。` : "席位会依次发言；你的插话会进入后续上下文。"}</small>
          </div>
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} disabled={!canWrite || busy} placeholder={awaitingFinal ? "最终答案生成前，我还想补充…" : selectedParticipant ? `向${selectedParticipant.name}追问…` : "我想补充 / 反驳 / 改变讨论方向…"} rows={2} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") act(selectedParticipant ? "question" : "interject"); }} />
          <div className="participation-actions">
            <span className="debate-progress">{debateActive ? `已完成 ${agentTurnCount} / ${seatCount} 席` : `${seatCount} 席完成${run.auto_summarize ? "，正在自动总结" : "，等待你的确认"}`}</span>
            <span />
            <button className="quiet-button" disabled={!canWrite || busy || !draft.trim()} onClick={() => act(selectedParticipant ? "question" : "interject")}>{busy ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />}{awaitingFinal ? "加入最终补充" : selectedParticipant ? `问${selectedParticipant.name}` : "加入讨论"}</button>
            {awaitingFinal && !highRisk && <button className="send-button" disabled={busy} onClick={finalize}>{busy ? <LoaderCircle className="spin" size={15} /> : <FileCheck2 size={15} />}生成最终答案</button>}
            {awaitingFinal && highRisk && <button className="send-button" disabled={highRiskBusy} onClick={openHighRiskControl}><LockKeyhole size={15} />进入人工复核</button>}
          </div>
          {(error || run.error) && <p className="discussion-error">{error || run.error}</p>}
        </div>}

        {run.status === "completed" && <div className="completed-actions"><a className="quiet-button" href={runExportUrl(run.id, "markdown")} download><Download size={15} />Markdown</a><a className="quiet-button" href={runExportUrl(run.id, "html")} download><FileCheck2 size={15} />HTML 报告</a><button className="quiet-button" onClick={openDecisionReview}><ClipboardCheck size={15} />{run.decision_review ? "编辑回访" : "结果回访"}</button><button className="quiet-button" onClick={openMemory}><Save size={15} />沉淀记忆</button>{lineage.parent && <Link className="quiet-button" href={`/runs/${lineage.parent.parent_run_id}`}><GitBranch size={15} />父 Run</Link>}{lineage.children.length > 0 && <span className="fork-child-count">{lineage.children.length} 个分支</span>}<span /><button className="quiet-button" onClick={() => { setForkError(""); setForkOpen(true); }}><GitBranch size={15} />创建情景分叉</button><button className="quiet-button" onClick={async () => { const next = await api.rerun(run.id); router.push(`/runs/${next.id}`); }}><RotateCcw size={15} />重新开一桌</button><Link className="send-button" href="/">讨论新问题<Sparkles size={15} /></Link></div>}
      </section>
    </main>
    {highRisk && highRiskOpen && <div className="high-risk-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setHighRiskOpen(false); }}>
      <section className="high-risk-dialog" role="dialog" aria-modal="true" aria-labelledby="high-risk-title">
        <header><div><span>HIGH-RISK CONTROL</span><h2 id="high-risk-title">高风险决策支持</h2><p>{highRiskStatusLabel(highRisk.status)} · 版本 {highRisk.version}</p></div><button className="icon-button" onClick={() => setHighRiskOpen(false)} aria-label="关闭高风险控制面"><X size={16} /></button></header>
        <div className="high-risk-scroll">
          <section className="risk-assessment-line"><ShieldAlert size={17} /><div><strong>{highRisk.risk_assessment.risk_tier.toUpperCase()}</strong><span>{highRisk.risk_assessment.reasons.join("；")}</span></div></section>
          <section className="required-facts-form"><header><div><strong>关键事实</strong><span>{missingCriticalFacts ? `${missingCriticalFacts} 项缺失，系统保持阻断` : "已达到事实门禁"}</span></div><button className="quiet-button" onClick={saveHighRiskFacts} disabled={highRiskBusy || ["REJECTED", "ACTION_BLOCKED", "COMPLETED", "CANCELLED"].includes(highRisk.status)}>{highRiskBusy ? <LoaderCircle className="spin" size={14} /> : <Save size={14} />}保存事实</button></header>{highRisk.required_facts.map((fact) => <label key={fact.fact_id}><span><strong>{fact.name}</strong><small>{fact.materiality === "critical" ? "关键" : fact.materiality}</small></span><p>{fact.description}</p><textarea rows={2} maxLength={4000} value={factDraft[fact.fact_id] || ""} onChange={(event) => setFactDraft({ ...factDraft, [fact.fact_id]: event.target.value })} disabled={["REJECTED", "ACTION_BLOCKED", "COMPLETED", "CANCELLED"].includes(highRisk.status)} /></label>)}</section>

          {highRisk.status === "EVIDENCE_REQUIRED" && <section className="review-report-form"><header><strong>非约束性决策支持报告</strong><span>正文保存在本地记录，安全审计只保存 SHA-256。</span></header><textarea aria-label="高风险决策支持报告" rows={7} maxLength={50000} value={reportDraft} onChange={(event) => setReportDraft(event.target.value)} /><button className="send-button" onClick={submitHighRiskReview} disabled={highRiskBusy || !reportDraft.trim()}>{highRiskBusy ? <LoaderCircle className="spin" size={15} /> : <ClipboardCheck size={15} />}提交并请求人工审批</button></section>}

          {highRisk.status === "APPROVAL_REQUIRED" && highRiskApproval?.status === "pending" && <section className="approval-form"><header><strong>独立复核</strong><span>审批 {highRiskApproval.approval_id.slice(0, 8)} · {new Date(highRiskApproval.expires_at).toLocaleString()}</span></header><div><label><span>复核人 ID</span><input value={reviewerId} onChange={(event) => setReviewerId(event.target.value)} maxLength={128} autoComplete="off" /></label><label><span>服务端复核凭据</span><input type="password" value={reviewerKey} onChange={(event) => setReviewerKey(event.target.value)} autoComplete="off" /></label></div><label><span>审批理由</span><textarea rows={2} maxLength={1000} value={approvalReason} onChange={(event) => setApprovalReason(event.target.value)} /></label><footer><button className="quiet-button danger" onClick={() => decideHighRisk("rejected")} disabled={highRiskBusy || !reviewerId.trim() || !reviewerKey || !approvalReason.trim()}>拒绝</button><button className="send-button" onClick={() => decideHighRisk("approved")} disabled={highRiskBusy || !reviewerId.trim() || !reviewerKey || !approvalReason.trim()}><LockKeyhole size={15} />批准报告</button></footer></section>}
          {["APPROVAL_REQUIRED", "APPROVED"].includes(highRisk.status) && highRiskApproval && ["expired", "revoked"].includes(highRiskApproval.status) && <section className="approval-result blocked"><AlertTriangle size={20} /><div><strong>原审批已{highRiskApproval.status === "expired" ? "过期" : "撤销"}</strong><span>报告正文和绑定哈希未改变，可以重新申请独立审批。</span></div><button className="send-button" onClick={requestHighRiskApproval} disabled={highRiskBusy}>重新申请审批</button></section>}

          {highRisk.status === "APPROVED" && highRiskApproval?.status === "approved" && <section className="approval-result approved"><CheckCircle2 size={20} /><div><strong>内容绑定审批已通过</strong><span>审批不会执行外部动作；完成后仅固化本地决策支持状态。</span></div><button className="send-button" onClick={completeHighRisk} disabled={highRiskBusy}>完成记录</button></section>}
          {highRisk.status === "COMPLETED" && <section className="approval-result approved"><CheckCircle2 size={20} /><div><strong>高风险记录已完成</strong><span>报告、动作草案与审批哈希已绑定，审计记录保持追加写入。</span></div></section>}
          {highRisk.status === "PROFESSIONAL_ESCALATION_REQUIRED" && <section className="approval-result blocked"><AlertTriangle size={20} /><div><strong>需要专业人员接管</strong><span>系统不会形成最终建议或执行任何动作。</span></div></section>}
          {["REJECTED", "ACTION_BLOCKED", "CANCELLED"].includes(highRisk.status) && <section className="approval-result blocked"><AlertTriangle size={20} /><div><strong>{highRiskStatusLabel(highRisk.status)}</strong><span>当前记录不能继续进入审批或执行路径。</span></div></section>}
          <section className="high-risk-audit" aria-label="高风险审计时间线">
            <header><strong>审计时间线</strong><span>仅显示脱敏状态元数据</span></header>
            {highRiskAudit.length ? <ol>{highRiskAudit.map((event) => <li key={event.event_id}>
              <span className="audit-sequence">#{event.sequence}</span>
              <div><strong>{auditEventLabel(event.event_type)}</strong><span>{auditTransitionLabel(event.previous_status, event.new_status)} · {auditActorLabel(event.actor_type)}</span></div>
              <time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleString()}</time>
            </li>)}</ol> : <p>暂无可显示的审计事件</p>}
          </section>
          {highRiskError && <p className="high-risk-error" role="alert">{highRiskError}</p>}
        </div>
        <footer><LockKeyhole size={14} /><span>非约束性决策支持 · 关键事实缺失时停止 · P0 不执行外部动作</span></footer>
      </section>
    </div>}
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
    {forkOpen && <div className="decision-review-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setForkOpen(false); }}>
      <section className="decision-review-dialog fork-dialog" role="dialog" aria-modal="true" aria-labelledby="fork-title">
        <header><div><span>IMMUTABLE FORK</span><h2 id="fork-title">创建情景分叉</h2><p>父 Run、原发言、审批和简报都不会被改写。</p></div><button className="icon-button" onClick={() => setForkOpen(false)} aria-label="关闭情景分叉"><X size={16} /></button></header>
        <div className="decision-review-fields">
          <label className="review-field review-wide"><span>从哪个检查点继续</span><select aria-label="分叉检查点" value={forkCheckpoint} onChange={(event) => setForkCheckpoint(event.target.value as ForkCheckpoint)}><option value="before_deliberation">讨论开始前</option>{run.participant_roles.map((seat, index) => <option key={seat.id} value={`after_seat_${index + 1}`}>复用到第 {index + 1} 席 · {seat.name}</option>)}<option value="before_synthesis">四席完成后、总结前</option></select></label>
          <label className="review-field review-wide"><span>分叉原因</span><textarea aria-label="分叉原因" rows={2} minLength={3} maxLength={1000} value={forkReason} onChange={(event) => setForkReason(event.target.value)} placeholder="例如：预算从 50 万调整为 20 万" /></label>
          <label className="review-field review-wide"><span>新增情景约束（可选）</span><textarea aria-label="新增情景约束" rows={4} maxLength={6000} value={forkPrompt} onChange={(event) => setForkPrompt(event.target.value)} placeholder="只写变化，不用重复原问题" /></label>
        </div>
        <footer>{forkError ? <span className="review-error">{forkError}</span> : <span>{highRisk ? "高风险分叉会创建全新的控制记录，旧审批不会继承。" : "复用内容会明确标记，不计入新 Run 的模型用量。"}</span>}<button className="send-button" onClick={createFork} disabled={forkBusy || forkReason.trim().length < 3}>{forkBusy ? <LoaderCircle className="spin" size={15} /> : <GitBranch size={15} />}创建新 Run</button></footer>
      </section>
    </div>}
    {memoryOpen && <div className="decision-review-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setMemoryOpen(false); }}>
      <section className="decision-review-dialog memory-dialog" role="dialog" aria-modal="true" aria-labelledby="memory-title">
        <header><div><span>USER-APPROVED MEMORY</span><h2 id="memory-title">沉淀长期记忆</h2><p>系统只提出候选；未经你逐条批准的内容永远不会跨 Run 注入。</p></div><button className="icon-button" onClick={() => setMemoryOpen(false)} aria-label="关闭长期记忆"><X size={16} /></button></header>
        <div className="memory-proposal-list">{memoryBusy && memoryProposals.length === 0 ? <p>正在生成候选…</p> : memoryProposals.map((item) => <article key={item.proposal.id} data-status={item.status}><header><span>{item.proposal.type}</span><small>{item.status === "pending" ? "待你决定" : item.status === "approved" ? "已批准" : "已拒绝"}</small></header><textarea aria-label={`记忆候选 ${item.proposal.type}`} rows={3} maxLength={3000} value={memoryDrafts[item.proposal.id] ?? item.proposal.content} disabled={item.status !== "pending" || memoryBusy} onChange={(event) => setMemoryDrafts({ ...memoryDrafts, [item.proposal.id]: event.target.value })} /><p>{item.proposal.rationale}</p>{item.status === "pending" && <footer><button className="quiet-button danger" disabled={memoryBusy} onClick={() => decideMemory(item.proposal.id, "reject")}>拒绝</button><button className="send-button" disabled={memoryBusy || !(memoryDrafts[item.proposal.id] || "").trim()} onClick={() => decideMemory(item.proposal.id, "approve")}>批准此条</button></footer>}</article>)}</div>
        <footer>{memoryError ? <span className="review-error">{memoryError}</span> : <span>批准记录与后续停用、删除操作都保留追加式审计轨迹。</span>}</footer>
      </section>
    </div>}
  </div>;
}

function DecisionComparisonView({ comparison }: { comparison: DecisionBriefComparison }) {
  return <article className="decision-comparison" aria-label="父子 Run 结果比较">
    <header><GitBranch size={16} /><div><strong>与父 Run 的结构化比较</strong><span>{comparison.related ? "同一情景树" : "独立 Run"} · {comparison.changed_fields.length ? `变化：${comparison.changed_fields.join("、")}` : "关键字段未变化"}</span></div></header>
    <div><section><span>父 Run</span><strong>{comparison.left.recommendation}</strong><small>{comparison.left.status} · {comparison.left.support}</small></section><section><span>当前分叉</span><strong>{comparison.right.recommendation}</strong><small>{comparison.right.status} · {comparison.right.support}</small></section></div>
    {(comparison.unresolved_added.length > 0 || comparison.unresolved_removed.length > 0) && <footer>{comparison.unresolved_added.length > 0 && <span>新增未决：{comparison.unresolved_added.join("；")}</span>}{comparison.unresolved_removed.length > 0 && <span>已消除：{comparison.unresolved_removed.join("；")}</span>}</footer>}
  </article>;
}

function DecisionClaimsView({ claims }: { claims: DecisionClaimView[] }) {
  const labels: Record<DecisionClaimView["current_basis"], string> = {
    user_provided: "用户提供",
    model_inference: "模型推断",
    cited_unverified: "有引用，未核验",
    seat_disputed: "席位间有争议",
    outcome_supported: "后续结果支持",
    outcome_contradicted: "后续结果反驳",
  };
  return <article className="decision-claims" aria-label="关键主张与依据"><header><strong>关键主张与依据</strong><span>席位共识不会自动变成事实验证</span></header><ul>{claims.map((item) => <li key={item.claim.id}><span data-basis={item.current_basis}>{labels[item.current_basis]}</span><p>{item.claim.text}</p>{item.claim.citation && <a href={item.claim.citation.url} target="_blank" rel="noreferrer">模型给出的引用 · 未外部核验</a>}</li>)}</ul></article>;
}

function DecisionBriefView({ brief }: { brief: DecisionBrief }) {
  const status = {
    proceed: { label: "可以推进", detail: "当前没有结构化阻塞项" },
    conditional: { label: "满足条件后推进", detail: "执行前仍需处理未验证信息或分歧" },
    no_decision: { label: "暂不形成决定", detail: "存在阻塞性矛盾，当前不应执行" },
  }[brief.status];
  const support = { unanimous: "一致支持", majority: "多数支持", contested: "存在明确反对" }[brief.support];
  const basis = { user_input: "用户输入", model_inference: "模型推断", cited_unverified: "引用未核验", outcome_verified: "结果已验证" };
  return <article className={`decision-brief-card status-${brief.status}`} aria-label="结构化决策简报">
    <header><div><span>DECISION BRIEF · v{brief.version}</span><h2>结构化决策简报</h2></div><div className="decision-brief-status"><strong>{status.label}</strong><small>{status.detail}</small></div></header>
    <div className="decision-brief-support"><strong>{support}</strong><span>只表示公开讨论中的可观察表态，不代表事实正确概率。</span></div>
    <section className="decision-recommendation"><span>当前建议</span><RichText content={brief.recommendation} /></section>
    {brief.contract_extension && <ContractExtensionView extension={brief.contract_extension} />}
    <div className="decision-brief-grid">
      {brief.decisive_reasons.length > 0 && <BriefSection title="决定性理由" items={brief.decisive_reasons.map((item) => item.summary)} />}
      {brief.unresolved.length > 0 && <section><h3>尚未解决的问题</h3><ul>{brief.unresolved.map((item) => <li key={item.id} className={item.blocking ? "blocking" : ""}>{item.blocking && <strong>阻塞</strong>}<span>{item.issue}</span>{item.resolution_method && <small>{item.resolution_method}</small>}</li>)}</ul></section>}
      {brief.actions.length > 0 && <BriefSection title="下一步行动" items={brief.actions.map((item) => item.action)} />}
      {brief.reopen_triggers.length > 0 && <BriefSection title="重新审议条件" items={brief.reopen_triggers.map((item) => item.condition)} />}
      {brief.assumptions.length > 0 && <section><h3>假设与依据</h3><ul>{brief.assumptions.map((item) => <li key={item.id}><span>{item.claim}</span><small>{basis[item.basis]}{item.validation_method ? ` · ${item.validation_method}` : ""}</small></li>)}</ul></section>}
      {brief.minority_report && <section className="minority-report"><h3>少数意见</h3><p>{brief.minority_report.summary}</p><small>反对席位：{brief.minority_report.seat_ids.join("、")}</small></section>}
      <BriefSection title="限制" items={brief.limitations} />
    </div>
  </article>;
}

function ContractExtensionView({ extension }: { extension: NonNullable<DecisionBrief["contract_extension"]> }) {
  if (extension.contract === "product_review") {
    return <section className="contract-extension-card" role="region" aria-label="产品评审契约">
      <header><strong>产品评审契约</strong><span>用户、价值、验证与停止条件</span></header>
      <div className="contract-extension-grid">
        <section><h3>用户问题</h3><p>{extension.user_problem}</p><h3>价值主张</h3><p>{extension.value_proposition}</p></section>
        <BriefSection title="目标用户" items={extension.target_users} />
        <BriefSection title="失败条件" items={extension.failure_conditions} />
        <section><h3>验证实验</h3><ul>{extension.validation_experiments.map((item, index) => <li key={`experiment-${index}`}><span>{item.hypothesis}</span><small>{item.method} · 成功阈值：{item.success_threshold}</small></li>)}</ul></section>
        <BriefSection title="停止条件" items={extension.stop_conditions} />
      </div>
    </section>;
  }
  if (extension.contract === "technical_architecture") {
    return <section className="contract-extension-card" role="region" aria-label="技术架构评审契约">
      <header><strong>技术架构评审契约</strong><span>需求、故障、迁移与回滚</span></header>
      <div className="contract-extension-grid">
        <section className="contract-wide"><h3>建议架构</h3><RichText content={extension.proposed_architecture} /></section>
        <BriefSection title="需求" items={extension.requirements} />
        <BriefSection title="约束" items={extension.constraints} />
        <BriefSection title="故障模式" items={extension.failure_modes} />
        <BriefSection title="迁移计划" items={extension.migration_plan} />
        <BriefSection title="回滚计划" items={extension.rollback_plan} />
        <BriefSection title="可观测性" items={extension.observability_requirements} />
      </div>
    </section>;
  }
  return <section className="contract-extension-card" role="region" aria-label="一般决策契约">
    <header><strong>一般决策契约</strong><span>决策标准与关键取舍</span></header>
    <div className="contract-extension-grid"><BriefSection title="决策标准" items={extension.decision_criteria} /><BriefSection title="关键取舍" items={extension.key_tradeoffs} /></div>
  </section>;
}

function BriefSection({ title, items }: { title: string; items: string[] }) {
  return <section><h3>{title}</h3><ul>{items.map((item, index) => <li key={`${title}-${index}`}><span>{item}</span></li>)}</ul></section>;
}

function highRiskStatusLabel(status: string) {
  const labels: Record<string, string> = {
    DRAFT: "草案",
    RISK_ASSESSMENT_REQUIRED: "等待风险评估",
    MORE_INFORMATION_REQUIRED: "需要补充关键信息",
    EVIDENCE_REQUIRED: "等待报告与证据复核",
    INDEPENDENT_ANALYSIS: "独立分析",
    CROSS_EXAMINATION: "交叉审查",
    PROFESSIONAL_ESCALATION_REQUIRED: "需要专业人员接管",
    READY_FOR_HUMAN_REVIEW: "可以提交人工复核",
    APPROVAL_REQUIRED: "等待独立人工审批",
    APPROVED: "已批准，等待固化",
    REJECTED: "审批已拒绝",
    ACTION_BLOCKED: "动作已阻止",
    COMPLETED: "高风险记录已完成",
    CANCELLED: "高风险记录已取消",
  };
  return labels[status] || status.replaceAll("_", " ");
}

function domainLabel(domain: string) {
  return ({ medical: "医疗", legal: "法律", investment: "投资", compliance: "合规", production_incident: "生产事故", general_high_risk: "通用高风险" } as Record<string, string>)[domain] || domain;
}

function auditEventLabel(eventType: string) {
  return ({
    high_risk_created: "创建高风险记录",
    risk_assessed: "完成风险评估",
    required_facts_evaluated: "检查关键事实",
    required_facts_updated: "更新关键事实",
    review_prepared: "提交决策支持报告",
    approval_requested: "请求独立审批",
    approval_decided: "记录审批决定",
    approval_expired: "审批已过期",
    approval_revoked: "审批已撤销",
    high_risk_completed: "完成高风险记录",
    high_risk_cancelled: "取消高风险记录",
    status_transitioned: "更新控制状态",
    transition_denied: "拒绝状态变更",
    normal_route_denied: "阻止普通流程绕过",
    approval_decision_denied: "拒绝无效审批",
    reviewer_authorization_denied: "拒绝未授权复核",
    persistence_failure_blocked: "持久化失败并阻断",
    risk_overridden: "人工调整风险等级",
  } as Record<string, string>)[eventType] || eventType.replaceAll("_", " ");
}

function auditTransitionLabel(previousStatus?: string | null, newStatus?: string | null) {
  if (!previousStatus && !newStatus) return "记录事件";
  if (previousStatus === newStatus) return previousStatus ? highRiskStatusLabel(previousStatus) : "状态未变化";
  const previous = previousStatus ? highRiskStatusLabel(previousStatus) : "无状态";
  const next = newStatus ? highRiskStatusLabel(newStatus) : "无状态";
  return `${previous} -> ${next}`;
}

function auditActorLabel(actorType: HighRiskAuditEvent["actor_type"]) {
  return ({ user: "用户操作", reviewer: "独立复核", system: "系统控制", model: "模型记录", tool: "工具记录" } as Record<HighRiskAuditEvent["actor_type"], string>)[actorType];
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
