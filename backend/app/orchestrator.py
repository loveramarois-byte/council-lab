from __future__ import annotations

import asyncio
import hashlib
import random
import time
import uuid
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from .context import build_context_window, context_budget_for_mode
from .models import (
    CandidateAnswer,
    ContextSnapshot,
    Critique,
    DiscussionAction,
    DiscussionTurn,
    FinalDecision,
    JudgeScore,
    QuestionAnalysis,
    RevisedAnswer,
    RunCreate,
    RunEvent,
    RunRecord,
    UsageSummary,
    VerificationResult,
    VerificationTask,
    utc_now,
)
from .providers import build_backend
from .store import Store


MODE_REASONING_EFFORT = {
    "quick": "low",
    "standard": "high",
    "rigorous": "ultra",
}

CCSWITCH_EFFORT_FALLBACKS = {
    "ultra": [("ultra", 0.375), ("high", 0.375), ("low", 0.25)],
    "high": [("high", 0.625), ("low", 0.375)],
    "low": [("low", 1.0)],
}

EFFORT_LABELS = {
    "ultra": "Ultra",
    "high": "High",
    "low": "Low",
}


class DebateWorkflowState(TypedDict):
    run_id: str
    next_speaker_index: int


def reasoning_effort_for_mode(mode: str) -> str:
    return MODE_REASONING_EFFORT.get(mode, "high")


def describe_run_error(exc: Exception, timeout_seconds: int | float = 120) -> str:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return f"当前席位等待上游超过 {int(timeout_seconds)} 秒，CC Switch 未能在时限内返回结果。请重试当前席位。"
    message = str(exc).strip()
    return message or f"{type(exc).__name__}：当前席位调用失败，请重试。"


def analyze_question(question: str, mode: str) -> QuestionAnalysis:
    lower = question.lower()
    question_type = "coding" if any(token in lower for token in ("代码", "python", "javascript", "bug", "api")) else "mathematical" if any(token in lower for token in ("计算", "多少", "几率", "equation")) else "current_factual" if any(token in lower for token in ("今天", "最新", "当前", "now", "latest")) else "factual"
    high_risk = any(token in lower for token in ("法律", "医疗", "诊断", "投资", "金融"))
    needs_math = question_type == "mathematical"
    needs_code = question_type == "coding"
    agents = 4
    return QuestionAnalysis(question_type=question_type, needs_realtime=question_type == "current_factual", needs_web=question_type in {"current_factual", "factual"}, needs_code_execution=needs_code, needs_math=needs_math, high_risk_domain=high_risk, recommended_agents=agents, recommended_mode=mode, expected_model_calls=agents + 4, expected_token_limit=12000 if mode != "rigorous" else 20000, expected_tool_calls=1 if needs_math or needs_code else 0)


def make_candidate(candidate_id: str, question: str, role: str, model: str, provider: str, text: str, usage: UsageSummary) -> CandidateAnswer:
    return CandidateAnswer(candidate_id=candidate_id, answer=text, key_reasons=["将结论拆成可检查的条件和依据", "显式保留上下文不足带来的不确定性"], assumptions=["问题中的关键术语按通常含义理解"], claims_to_verify=[f"关于“{question[:100]}”的核心判断需要与可靠来源或确定性测试核对"], uncertainties=["没有外部资料时无法确认时效性细节"], risks=["如果题目省略关键约束，结论需要重新评估"], proposed_sources=["官方文档或第一方资料", "可复现的本地测试"], model=model, provider=provider, usage=usage, status="completed")


def critique(candidate: CandidateAnswer, analysis: QuestionAnalysis) -> Critique:
    issue_type = "missing_context" if analysis.question_type in {"factual", "current_factual"} else "verification_gap"
    return Critique(candidate_id=candidate.candidate_id, severity="medium", issue_type=issue_type, issue="结论仍依赖题目未提供的上下文，不能把条件化判断写成确定事实。", affected_claim=candidate.claims_to_verify[0], suggested_check="补充来源日期、适用范围或运行最小复现。", possible_counterexample="改变一个未声明的边界条件可能让结果不同。", confidence=0.84)


def verify(task: VerificationTask, analysis: QuestionAnalysis) -> VerificationResult:
    if analysis.question_type == "mathematical":
        return VerificationResult(task_id=task.task_id, claim=task.claim, status="partially_verified", evidence_summary="已确认需要确定性复算，但当前输入没有提供完整公式或数值。", tool="deterministic_math", confidence=0.55, limitations=["缺少可执行的完整表达式"])
    if analysis.question_type == "coding":
        return VerificationResult(task_id=task.task_id, claim=task.claim, status="partially_verified", evidence_summary="已将验证目标转成可运行测试方向；没有收到仓库或代码片段，暂不能宣称通过。", tool="test_plan", confidence=0.5, limitations=["没有实际代码输入"])
    return VerificationResult(task_id=task.task_id, claim=task.claim, status="unverifiable", evidence_summary="当前 Mock 运行未联网，未将语言模型意见冒充外部事实核验。", tool="mock_no_network", confidence=0.25, limitations=["需要用户启用联网工具或配置可访问的来源"])


def score_candidate(candidate: CandidateAnswer, critiques: list[Critique], verifications: list[VerificationResult]) -> JudgeScore:
    evidence = 58.0 if any(v.status == "verified" for v in verifications) else 42.0
    reasoning = 74.0
    coverage = 68.0
    risk = 80.0 if not critiques else 62.0
    clarity = 78.0
    weighted = round(evidence * 0.35 + reasoning * 0.25 + coverage * 0.2 + risk * 0.1 + clarity * 0.1, 2)
    return JudgeScore(candidate_id=candidate.candidate_id, evidence_score=evidence, reasoning_score=reasoning, coverage_score=coverage, risk_score=risk, clarity_score=clarity, weighted_total=weighted, disqualifying_issues=[], explanation="证据覆盖仍有限，因此权重集中体现可验证边界、推理完整度和风险披露。")


class Orchestrator:
    def __init__(self, store: Store, providers: dict[str, Any]):
        self.store = store
        self.providers = providers
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.cancel_events: dict[str, asyncio.Event] = {}
        self.run_locks: dict[str, asyncio.Lock] = {}
        self.retrying_runs: set[str] = set()
        self.live_runs: dict[str, RunRecord] = {}

    PARTICIPANTS = [
        {"id": "analyst", "name": "析理", "role": "拆解者", "brief": "澄清问题、条件和真正的决策目标"},
        {"id": "challenger", "name": "诘问", "role": "挑战者", "brief": "寻找反例、漏洞和被忽略的代价"},
        {"id": "builder", "name": "构策", "role": "方案师", "brief": "提出可执行方案、取舍和验证步骤"},
        {"id": "observer", "name": "观澜", "role": "观察者", "brief": "连接各方观点、指出分歧，但不提前裁决"},
    ]

    async def start(self, request: RunCreate) -> RunRecord:
        profile = self.providers.get(request.provider_id) or self.providers["mock"]
        run_id = str(uuid.uuid4())
        model = request.model or profile.default_model
        run = RunRecord(id=run_id, question=request.question, mode=request.mode, provider_id=profile.id, model=model, reasoning_effort=reasoning_effort_for_mode(request.mode), workflow_engine="langgraph", status="queued", created_at=utc_now(), updated_at=utc_now(), protocol=profile.protocol_mode, participant_roles=self.PARTICIPANTS)
        await self.store.save_run(run)
        self.live_runs[run_id] = run
        await self.store.seed_events(run_id)
        cancel = asyncio.Event()
        self.cancel_events[run_id] = cancel
        self.run_locks[run_id] = asyncio.Lock()
        self.tasks[run_id] = asyncio.create_task(self.execute(run, request, self._profile_for_run(profile, run), cancel))
        return run

    @staticmethod
    def _profile_for_run(profile: Any, run: RunRecord) -> Any:
        return profile.model_copy(update={"reasoning_effort": run.reasoning_effort})

    async def emit(self, run: RunRecord, event_type: str, stage: str, message: str, progress: int, data: dict[str, Any] | None = None) -> None:
        run.updated_at = utc_now()
        await self.store.save_run(run)
        await self.store.publish(RunEvent(event_id=str(uuid.uuid4()), run_id=run.id, type=event_type, stage=stage, message=message, progress=progress, data=data or {}))

    async def execute(self, run: RunRecord, request: RunCreate, profile: Any, cancel: asyncio.Event) -> None:
        started = time.perf_counter()
        try:
            run.status = "running"
            await self.emit(run, "question_analyzed", "analysis", "问题已放上圆桌，第一位成员正在准备发言", 8)
            analysis = analyze_question(request.question, request.mode)
            run.analysis = analysis
            await self._run_debate_graph(run, request, profile, cancel, resume=False)
            run.usage.duration_ms = int((time.perf_counter() - started) * 1000)
        except asyncio.CancelledError:
            if run.id not in self.retrying_runs:
                run.status = "cancelled"
                run.error = "任务已取消"
                await self.emit(run, "run_cancelled", "cancelled", "审议已取消，已保留当前进度", 100)
        except Exception as exc:
            run.status = "failed"
            run.degraded = True
            run.error = describe_run_error(exc, request.limits.timeout_seconds)
            await self.emit(run, "run_failed", "error", "当前席位调用失败，已保留讨论进度", 100, {"error": run.error, "speaker_index": run.current_speaker_index})
        finally:
            run.updated_at = utc_now()
            await self.store.save_run(run)

    def _transcript(self, run: RunRecord) -> str:
        if not run.discussion_turns:
            return "（尚无发言）"
        return "\n\n".join(f"{turn.speaker_name}：{turn.content}" for turn in run.discussion_turns[-16:])

    async def _run_debate_graph(self, run: RunRecord, request: RunCreate, profile: Any, cancel: asyncio.Event, resume: bool) -> None:
        backends: dict[str, Any] = {}

        async def run_turn(state: DebateWorkflowState) -> dict[str, int]:
            if cancel.is_set():
                raise asyncio.CancelledError
            speaker_index = state["next_speaker_index"]
            await self._generate_turn(run, request, profile, backends, speaker_index)
            run.checkpoint_count = max(run.checkpoint_count, run.current_speaker_index)
            await self.store.save_run(run)
            return {"next_speaker_index": run.current_speaker_index}

        async def finalize(_: DebateWorkflowState) -> dict[str, int]:
            if cancel.is_set():
                raise asyncio.CancelledError
            await self._finalize_debate(run, request, profile, backends)
            run.checkpoint_count = max(run.checkpoint_count, len(self.PARTICIPANTS) + 1)
            await self.store.save_run(run)
            return {"next_speaker_index": len(self.PARTICIPANTS)}

        async def dispatch(_: DebateWorkflowState) -> dict[str, int]:
            return {}

        def route(state: DebateWorkflowState) -> str:
            return "turn" if state["next_speaker_index"] < len(self.PARTICIPANTS) else "finalize"

        builder = StateGraph(DebateWorkflowState)
        builder.add_node("dispatch", dispatch)
        builder.add_node("turn", run_turn)
        builder.add_node("finalize", finalize)
        builder.add_edge(START, "dispatch")
        builder.add_conditional_edges("dispatch", route, {"turn": "turn", "finalize": "finalize"})
        builder.add_conditional_edges("turn", route, {"turn": "turn", "finalize": "finalize"})
        builder.add_edge("finalize", END)

        config = {"configurable": {"thread_id": run.id}}
        async with AsyncSqliteSaver.from_conn_string(self.store.checkpoint_path) as saver:
            await saver.conn.execute("PRAGMA busy_timeout=5000")
            graph = builder.compile(checkpointer=saver)
            checkpoint = await saver.aget_tuple(config)
            graph_input: DebateWorkflowState | None = None if resume and checkpoint else {
                "run_id": run.id,
                "next_speaker_index": run.current_speaker_index,
            }
            graph_completed = False
            try:
                await graph.ainvoke(graph_input, config)
                graph_completed = True
            finally:
                run.checkpoint_count = len([item async for item in saver.alist(config)])
                if graph_completed and run.final_decision is not None:
                    run.status = "completed"
                    run.awaiting_user = False
                    await self.emit(run, "final_completed", "complete", "四席辩论与最终答案已完成", 100, {"confidence": "medium"})
                else:
                    await self.store.save_run(run)

    @staticmethod
    def _is_retryable_generation_error(exc: Exception) -> bool:
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return True
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code in {429, 500, 502, 503, 504}:
            return True
        if status_code != 400 or response is None:
            return False
        try:
            payload = response.json()
        except Exception:
            return False
        error = payload.get("error") if isinstance(payload, dict) else None
        return isinstance(error, dict) and error.get("code") == "cc_switch_upstream_error"

    async def _generate_with_fallback(self, run: RunRecord, request: RunCreate, profile: Any, backends: dict[str, Any], prompt: str, system: str) -> Any:
        provider_type = getattr(profile.provider_type, "value", profile.provider_type)
        plan = CCSWITCH_EFFORT_FALLBACKS.get(run.reasoning_effort, [(run.reasoning_effort, 1.0)]) if provider_type == "ccswitch_local" else [(run.reasoning_effort, 1.0)]

        for index, (effort, timeout_fraction) in enumerate(plan):
            attempt_profile = profile.model_copy(update={"reasoning_effort": effort})
            if effort not in backends:
                backends[effort] = build_backend(attempt_profile)
            try:
                return await asyncio.wait_for(
                    backends[effort].generate(prompt, system, run.model),
                    timeout=max(1.0, request.limits.timeout_seconds * timeout_fraction),
                )
            except Exception as exc:
                if index >= len(plan) - 1 or not self._is_retryable_generation_error(exc):
                    raise
                next_effort = plan[index + 1][0]
                run.degraded = True
                run.reasoning_effort = next_effort
                current_label = EFFORT_LABELS.get(effort, effort.title())
                next_label = EFFORT_LABELS.get(next_effort, next_effort.title())
                reason = "上游超时" if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) else "上游暂不可用"
                turn = DiscussionTurn(
                    id=str(uuid.uuid4()),
                    speaker_type="system",
                    speaker_id="route",
                    speaker_name="路由",
                    role_label="自动故障转移",
                    content=f"{current_label} 档{reason}，已自动降为 {next_label} 档继续当前席位。",
                    round=run.discussion_round,
                )
                run.discussion_turns.append(turn)
                await self.emit(
                    run,
                    "provider_degraded",
                    "discussion",
                    f"CC Switch {current_label} 档{reason}，正在以 {next_label} 档继续当前席位",
                    min(88, 15 + len(run.discussion_turns) * 7),
                    {"from_effort": effort, "to_effort": next_effort, "speaker_index": run.current_speaker_index},
                )

        raise RuntimeError("CC Switch 档位降级流程未能生成结果")

    async def _generate_turn(self, run: RunRecord, request: RunCreate, profile: Any, backends: dict[str, Any], speaker_index: int) -> None:
        participant = self.PARTICIPANTS[speaker_index]
        run.awaiting_user = False
        context_window = build_context_window(run.question, run.discussion_turns, context_budget_for_mode(run.mode))
        run.context_snapshot = ContextSnapshot(
            token_budget=context_window.token_budget,
            estimated_tokens=context_window.estimated_tokens,
            included_turns=context_window.included_turns,
            total_turns=context_window.total_turns,
            compacted=context_window.compacted,
            summary=context_window.summary,
        )
        await self.emit(run, "agent_turn_started", "discussion", f"{participant['name']}正在组织这一轮发言", min(82, 15 + len(run.discussion_turns) * 7), {"speaker": participant})
        if speaker_index == 0:
            debate_instruction = "你是第一位发言者。直接回答用户问题，给出清楚的初步观点和依据，为后续辩论建立起点。"
        else:
            debate_instruction = (
                "你必须先回应前面各位的公开观点并明确表态。开头使用‘表态：认同’、‘表态：部分认同’或‘表态：反驳’之一；"
                "确有不同意见就指出具体哪一点、为什么，若没有可反驳之处就明确认同，不要为了制造冲突而强行反驳。"
                "随后补充自己的新依据、修正或方案。"
            )
        system = (
            f"你是四人圆桌中的{participant['name']}，角色是{participant['role']}：{participant['brief']}。\n"
            f"{debate_instruction}"
            "这是用户全程可参与的公开讨论。必须回应记录中最新的用户插话。"
            "不要替全体宣布最终答案，不展示隐藏思维链，控制在220字以内。"
        )
        generation = await self._generate_with_fallback(run, request, profile, backends, context_window.prompt, system)
        turn = DiscussionTurn(id=str(uuid.uuid4()), speaker_type="agent", speaker_id=participant["id"], speaker_name=participant["name"], role_label=participant["role"], content=generation.text.strip(), round=run.discussion_round)
        run.discussion_turns.append(turn)
        run.current_speaker_index = speaker_index + 1
        candidate = make_candidate(f"candidate-{participant['id']}", run.question, participant["role"], run.model, profile.display_name, generation.text, UsageSummary(model_calls=1, input_tokens=generation.input_tokens, output_tokens=generation.output_tokens))
        candidate.anonymous_label = participant["name"]
        run.candidates = [item for item in run.candidates if item.candidate_id != candidate.candidate_id] + [candidate]
        run.usage.model_calls += 1
        run.usage.input_tokens += generation.input_tokens
        run.usage.output_tokens += generation.output_tokens
        next_speaker = self.PARTICIPANTS[run.current_speaker_index] if run.current_speaker_index < len(self.PARTICIPANTS) else None
        await self.emit(run, "agent_turn_completed", "discussion", f"{participant['name']}发言完毕，下一位将继续回应；你可随时插话", min(88, 20 + len(run.discussion_turns) * 14), {"turn": turn.model_dump(mode="json"), "next_speaker": next_speaker})

    async def _finalize_debate(self, run: RunRecord, request: RunCreate, profile: Any, backends: dict[str, Any]) -> None:
        started = time.perf_counter()
        context_window = build_context_window(run.question, run.discussion_turns, context_budget_for_mode(run.mode))
        run.context_snapshot = ContextSnapshot(
            token_budget=context_window.token_budget,
            estimated_tokens=context_window.estimated_tokens,
            included_turns=context_window.included_turns,
            total_turns=context_window.total_turns,
            compacted=context_window.compacted,
            summary=context_window.summary,
        )
        await self.emit(run, "summary_started", "summary", "四席辩论完成，正在根据公开讨论形成最终答案", 94)
        generation = await self._generate_with_fallback(
            run,
            request,
            profile,
            backends,
            context_window.prompt,
            "你是圆桌记录员。根据四位成员和用户的完整公开讨论，直接给出最终答案。先综合已经形成的共识，再处理明确分歧，最后给出可执行答案和必要边界。不要声称不存在的共识，不展示隐藏思维链。",
        )
        run.usage.model_calls += 1
        run.usage.input_tokens += generation.input_tokens
        run.usage.output_tokens += generation.output_tokens
        run.usage.duration_ms += int((time.perf_counter() - started) * 1000)
        provider_type = getattr(profile.provider_type, "value", profile.provider_type)
        run.final_decision = FinalDecision(
            final_answer=generation.text.strip(),
            key_reasons=["四席按顺序公开回应", "认同与反驳均保留在完整记录中"],
            disagreements=[turn.content for turn in run.discussion_turns if turn.speaker_type == "agent"],
            risks_and_limitations=["最终答案综合公开讨论，不代表四个独立模型的统计投票。"],
            confidence={"level": "medium", "score": 65, "explanation": "置信度取决于讨论覆盖与输入信息，不代表事实概率。"},
            provider_summary={"provider": profile.display_name, "protocol": "mock" if provider_type == "mock" else "openai_compatible", "model": run.model, "used_ccswitch": provider_type == "ccswitch_local", "degraded": run.degraded},
            usage=run.usage,
        )

    async def interject(self, run_id: str, action: DiscussionAction) -> RunRecord | None:
        run = self.live_runs.get(run_id) or await self.store.get_run(run_id)
        if not run:
            return None
        if run.status != "running" or not action.message.strip():
            return run
        target = next((item for item in self.PARTICIPANTS if item["id"] == action.target_agent), None)
        prefix = f"问{target['name']}：" if action.action == "question" and target else ""
        run.discussion_turns.append(DiscussionTurn(id=str(uuid.uuid4()), speaker_type="user", speaker_id="user", speaker_name="你", role_label="参与者", content=prefix + action.message.strip(), round=run.discussion_round))
        run.updated_at = utc_now()
        await self.store.save_run(run)
        await self.store.publish(RunEvent(event_id=str(uuid.uuid4()), run_id=run.id, type="user_interjected", stage="discussion", message="你的观点已进入公开讨论，后续成员将会看到", progress=min(90, 12 + len(run.discussion_turns) * 12), data={"target_agent": action.target_agent}))
        return run

    async def advance(self, run_id: str, action: DiscussionAction) -> RunRecord | None:
        run = self.live_runs.get(run_id) or await self.store.get_run(run_id)
        if not run:
            return None
        if run.status != "running":
            return run
        if action.action in {"interject", "question"}:
            return await self.interject(run_id, action)
        return run

    async def retry_turn(self, run_id: str) -> RunRecord | None:
        run = self.live_runs.get(run_id) or await self.store.get_run(run_id)
        if not run:
            return None
        if run.status not in {"running", "failed"}:
            return run

        active_task = self.tasks.get(run_id)
        if active_task and not active_task.done():
            self.retrying_runs.add(run_id)
            active_task.cancel()
            try:
                await active_task
            except asyncio.CancelledError:
                pass
            finally:
                self.retrying_runs.discard(run_id)

        run = self.live_runs.get(run_id) or await self.store.get_run(run_id)
        if not run:
            return None
        run.status = "running"
        run.awaiting_user = False
        run.error = None
        run.updated_at = utc_now()
        await self.store.save_run(run)

        profile = self._profile_for_run(self.providers.get(run.provider_id) or self.providers["mock"], run)
        request = RunCreate(question=run.question, mode=run.mode, provider_id=run.provider_id, model=run.model)
        cancel = asyncio.Event()
        self.cancel_events[run_id] = cancel
        self.tasks[run_id] = asyncio.create_task(self._resume_debate(run, request, profile, cancel))
        return run

    async def _resume_debate(self, run: RunRecord, request: RunCreate, profile: Any, cancel: asyncio.Event) -> None:
        lock = self.run_locks.setdefault(run.id, asyncio.Lock())
        async with lock:
            try:
                await self._run_debate_graph(run, request, profile, cancel, resume=True)
            except Exception as exc:
                run.degraded = True
                run.status = "failed"
                run.error = describe_run_error(exc, request.limits.timeout_seconds)
                await self.emit(run, "run_failed", "discussion", "当前席位重试失败，已保留公开讨论记录", 50, {"error": run.error, "speaker_index": run.current_speaker_index})
            finally:
                await self.store.save_run(run)

    async def summarize(self, run_id: str) -> RunRecord | None:
        run = await self.store.get_run(run_id)
        if not run:
            return None
        if run.status != "running" or not run.awaiting_user:
            return run
        run.awaiting_user = False
        await self.store.save_run(run)
        profile = self._profile_for_run(self.providers.get(run.provider_id) or self.providers["mock"], run)
        self.tasks[run_id] = asyncio.create_task(self._summarize_task(run, profile))
        return run

    async def _summarize_task(self, run: RunRecord, profile: Any) -> None:
        started = time.perf_counter()
        try:
            await self.emit(run, "summary_started", "summary", "收到你的指令，正在整理共识、分歧和下一步", 92)
            generation = await build_backend(profile).generate(
                f"原始问题：{run.question}\n\n公开圆桌记录：\n{self._transcript(run)}",
                "你是圆桌记录员。只根据公开对话总结：1.暂时共识；2.关键分歧；3.仍缺信息；4.建议下一步。不要伪造事实或一致意见。",
                run.model,
            )
            run.usage.model_calls += 1
            run.usage.input_tokens += generation.input_tokens
            run.usage.output_tokens += generation.output_tokens
            run.usage.duration_ms += int((time.perf_counter() - started) * 1000)
            provider_type = getattr(profile.provider_type, "value", profile.provider_type)
            run.final_decision = FinalDecision(final_answer=generation.text.strip(), key_reasons=["结论仅在你主动要求总结后生成", "保留圆桌中的分歧和未决信息"], verified_claims=[], partially_verified_claims=[], contradicted_claims=[], unverified_claims=["圆桌观点尚未经过外部事实核验"] if not run.analysis or run.analysis.needs_web else [], disagreements=[turn.content for turn in run.discussion_turns if turn.speaker_type == "agent"][-4:], risks_and_limitations=["这是讨论纪要，不是四个独立模型的统计投票。"], confidence={"level": "medium", "score": 65, "explanation": "置信度取决于讨论覆盖，不代表事实概率。"}, sources=[], provider_summary={"provider": profile.display_name, "protocol": "mock" if provider_type == "mock" else "openai_compatible", "model": run.model, "used_ccswitch": provider_type == "ccswitch_local", "degraded": run.degraded}, usage=run.usage)
            run.status = "completed"
            run.awaiting_user = False
            await self.emit(run, "final_completed", "complete", "圆桌纪要已按你的要求生成", 100, {"confidence": "medium"})
        except Exception as exc:
            run.awaiting_user = True
            run.error = str(exc)
            await self.emit(run, "agent_turn_failed", "summary", "总结请求未完成，讨论记录已保留", 92, {"error": str(exc)})
        finally:
            await self.store.save_run(run)

    async def cancel(self, run_id: str) -> RunRecord | None:
        run = await self.store.get_run(run_id)
        if run and run.status in {"queued", "running"}:
            self.cancel_events.setdefault(run_id, asyncio.Event()).set()
            task = self.tasks.get(run_id)
            if task:
                task.cancel()
        return await self.store.get_run(run_id)

    async def delete(self, run_id: str) -> bool:
        run = self.live_runs.get(run_id) or await self.store.get_run(run_id)
        if not run:
            return False

        task = self.tasks.get(run_id)
        if task and not task.done():
            if run.status in {"queued", "running"}:
                self.cancel_events.setdefault(run_id, asyncio.Event()).set()
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        deleted = await self.store.delete_run(run_id)
        self.tasks.pop(run_id, None)
        self.cancel_events.pop(run_id, None)
        self.run_locks.pop(run_id, None)
        self.live_runs.pop(run_id, None)
        self.retrying_runs.discard(run_id)
        return deleted
