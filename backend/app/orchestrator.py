from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from .context import build_context_window, context_budget_for_mode
from .credentials import get_provider_secret
from .models import (
    AgentAssignmentsConfig,
    AgentModelAssignment,
    CandidateAnswer,
    ContextSnapshot,
    DiscussionAction,
    DiscussionTurn,
    FinalDecision,
    QuestionAnalysis,
    ResolvedAgentAssignment,
    RunCreate,
    RunEvent,
    RunLimits,
    RunRecord,
    RunSourceSnapshot,
    UsageSummary,
    utc_now,
)
from .providers import ModelBackend, build_backend
from .store import Store
from .templates import get_template


MODE_WORKFLOW_EFFORT = {
    "quick": "low",
    "standard": "high",
    "rigorous": "ultra",
}

CCSWITCH_EFFORT_FALLBACKS = {
    "ultra": [("ultra", 0.375), ("high", 0.375), ("low", 0.25)],
    "high": [("high", 0.625), ("low", 0.375)],
    "low": [("low", 1.0)],
}

EFFORT_LABELS = {"ultra": "Ultra", "high": "High", "low": "Low"}


class DebateWorkflowState(TypedDict):
    run_id: str
    next_speaker_index: int


class RunLimitReached(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def reasoning_effort_for_mode(mode: str) -> str:
    """Legacy-compatible workflow tier; only capable Responses providers receive it upstream."""
    return MODE_WORKFLOW_EFFORT.get(mode, "high")


def describe_run_error(exc: Exception, timeout_seconds: int | float = 120) -> str:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return f"完整审议运行超过 {int(timeout_seconds)} 秒时间上限。已保留完成的发言，可重新开一桌或重试未完成席位。"
    message = str(exc).strip()
    return message or f"{type(exc).__name__}：当前席位调用失败，请重试。"


def analyze_question(question: str, mode: str, token_limit: int = 40000) -> QuestionAnalysis:
    lower = question.lower()
    question_type = (
        "coding"
        if any(token in lower for token in ("代码", "python", "javascript", "bug", "api"))
        else "mathematical"
        if any(token in lower for token in ("计算", "多少", "几率", "equation"))
        else "current_factual"
        if any(token in lower for token in ("今天", "最新", "当前", "now", "latest"))
        else "factual"
    )
    high_risk = any(token in lower for token in ("法律", "医疗", "诊断", "投资", "金融"))
    return QuestionAnalysis(
        question_type=question_type,
        needs_realtime=question_type == "current_factual",
        needs_web=question_type in {"current_factual", "factual"},
        needs_code_execution=question_type == "coding",
        needs_math=question_type == "mathematical",
        high_risk_domain=high_risk,
        recommended_agents=4,
        recommended_mode=mode,
        expected_model_calls=5,
        expected_token_limit=token_limit,
        expected_tool_calls=0,
    )


def make_candidate(
    candidate_id: str,
    question: str,
    role: str,
    model: str,
    provider: str,
    text: str,
    usage: UsageSummary,
) -> CandidateAnswer:
    return CandidateAnswer(
        candidate_id=candidate_id,
        answer=text,
        key_reasons=["将结论拆成可检查的条件和依据", "显式保留上下文不足带来的不确定性"],
        assumptions=["问题中的关键术语按通常含义理解"],
        claims_to_verify=[f"关于“{question[:100]}”的核心判断尚未经过外部事实核验"],
        uncertainties=["当前版本只进行模型间公开审议，不执行外部事实核验"],
        risks=["如果题目省略关键约束，结论需要重新评估"],
        proposed_sources=[],
        model=model,
        provider=provider,
        usage=usage,
        status="completed",
    )


class Orchestrator:
    PARTICIPANTS = [
        {"id": "analyst", "name": "析理", "role": "拆解者", "brief": "澄清问题、条件和真正的决策目标"},
        {"id": "challenger", "name": "诘问", "role": "挑战者", "brief": "寻找反例、漏洞和被忽略的代价"},
        {"id": "builder", "name": "构策", "role": "方案师", "brief": "提出可执行方案、取舍和验证步骤"},
        {"id": "observer", "name": "观澜", "role": "观察者", "brief": "连接各方观点、指出分歧，但不提前裁决"},
    ]

    def __init__(self, store: Store, providers: dict[str, Any]):
        self.store = store
        self.providers = providers
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.cancel_events: dict[str, asyncio.Event] = {}
        self.run_locks: dict[str, asyncio.Lock] = {}
        self.retrying_runs: set[str] = set()
        self.live_runs: dict[str, RunRecord] = {}
        self.shutting_down = False

    def default_assignment_config(self, provider_id: str, model: str | None = None, mode: str = "standard") -> AgentAssignmentsConfig:
        profile = self.providers.get(provider_id)
        if not profile:
            raise ValueError(f"Provider 不存在：{provider_id}")
        selected_model = model or profile.default_model
        if not selected_model:
            raise ValueError(f"Provider {profile.display_name} 尚未配置模型")
        effort = reasoning_effort_for_mode(mode)
        seats = [
            AgentModelAssignment(
                role=participant["id"],
                provider_id=profile.id,
                model=selected_model,
                protocol=profile.protocol_mode,
                reasoning_effort=effort,
                timeout_seconds=profile.timeout_seconds,
            )
            for participant in self.PARTICIPANTS
        ]
        finalizer = AgentModelAssignment(
            role="finalizer",
            provider_id=profile.id,
            model=selected_model,
            protocol=profile.protocol_mode,
            reasoning_effort=effort,
            timeout_seconds=profile.timeout_seconds,
        )
        return AgentAssignmentsConfig(seats=seats, finalizer=finalizer)

    def _resolve_assignment(self, assignment: AgentModelAssignment) -> ResolvedAgentAssignment:
        profile = self.providers.get(assignment.provider_id)
        if not profile:
            raise ValueError(f"Provider 不存在：{assignment.provider_id}")
        model = assignment.model or profile.default_model
        if not model:
            raise ValueError(f"Provider {profile.display_name} 尚未配置模型")
        snapshot = profile.model_copy(
            deep=True,
            update={
                "protocol_mode": assignment.protocol,
                "reasoning_effort": assignment.reasoning_effort,
                "timeout_seconds": assignment.timeout_seconds,
                "default_model": model,
            },
        )
        return ResolvedAgentAssignment(
            role=assignment.role,
            provider_id=profile.id,
            provider_name=profile.display_name,
            model=model,
            protocol=assignment.protocol,
            reasoning_effort=assignment.reasoning_effort,
            max_output_tokens=assignment.max_output_tokens,
            temperature=assignment.temperature,
            timeout_seconds=assignment.timeout_seconds,
            provider_snapshot=snapshot,
        )

    def _resolve_config(self, request: RunCreate) -> tuple[list[ResolvedAgentAssignment], ResolvedAgentAssignment]:
        config = request.assignment_config or self.default_assignment_config(request.provider_id, request.model, request.mode)
        if [item.role for item in config.seats] != [item["id"] for item in self.PARTICIPANTS]:
            raise ValueError("四席配置顺序必须为 analyst、challenger、builder、observer")
        if config.finalizer.role != "finalizer":
            raise ValueError("总结席角色必须为 finalizer")
        return [self._resolve_assignment(item) for item in config.seats], self._resolve_assignment(config.finalizer)

    async def start(
        self,
        request: RunCreate,
        *,
        frozen_sources: list[RunSourceSnapshot] | None = None,
        frozen_project_name: str = "",
        frozen_project_context: str | None = None,
    ) -> RunRecord:
        seats, finalizer = self._resolve_config(request)
        project = None
        source_snapshots: list[RunSourceSnapshot] = []
        project_context = ""
        project_name = ""
        if frozen_sources is not None:
            source_snapshots = [source.model_copy(deep=True) for source in frozen_sources]
            project_context = frozen_project_context or ""
            project_name = frozen_project_name
        elif request.project_id:
            project = await self.store.get_project(request.project_id)
            if not project:
                raise ValueError("资料空间不存在")
            project_name = project.name
            project_sources = await self.store.list_sources(project.id)
            requested_ids = set(request.source_ids or [])
            selected_sources = (
                [source for source in project_sources if source.id in requested_ids]
                if request.source_ids is not None
                else project_sources[:20]
            )
            if requested_ids - {source.id for source in selected_sources}:
                raise ValueError("部分资料不存在或不属于当前资料空间")
            for source in selected_sources:
                if not source.content:
                    continue
                source_snapshots.append(
                    RunSourceSnapshot(
                        id=source.id,
                        kind=source.kind,
                        title=source.title,
                        content=source.content,
                        url=source.url,
                        filename=source.filename,
                        sha256=source.sha256,
                    )
                )
            context_parts = []
            if project.instructions.strip():
                context_parts.append(f"资料空间固定说明：{project.instructions.strip()}")
            if request.include_project_history:
                previous_runs = [
                    run
                    for run in await self.store.list_runs()
                    if run.project_id == project.id and run.status == "completed" and run.final_decision
                ][:3]
                for index, previous in enumerate(reversed(previous_runs), 1):
                    context_parts.append(
                        f"历史审议 {index}：{previous.question}\n结论：{previous.final_decision.final_answer[:1600]}"
                    )
            project_context = "\n\n".join(context_parts)[:12_000]
        elif request.source_ids:
            raise ValueError("选择资料前必须先选择资料空间")
        template = get_template(request.template_id)
        run_id = str(uuid.uuid4())
        primary = seats[0]
        run = RunRecord(
            id=run_id,
            question=request.question,
            mode=request.mode,
            provider_id=primary.provider_id,
            model=primary.model,
            reasoning_effort=reasoning_effort_for_mode(request.mode),
            workflow_engine="langgraph",
            status="queued",
            created_at=utc_now(),
            updated_at=utc_now(),
            protocol=primary.protocol,
            participant_roles=self.PARTICIPANTS,
            limits=request.limits,
            seat_assignments=seats,
            finalizer_assignment=finalizer,
            auto_summarize=request.auto_summarize,
            project_id=request.project_id if frozen_sources is not None else project.id if project else None,
            project_name=project_name,
            project_context=project_context,
            template_id=template.id,
            template_name=template.name,
            source_snapshots=source_snapshots,
        )
        await self.store.save_run(run)
        self.live_runs[run_id] = run
        await self.store.seed_events(run_id)
        cancel = asyncio.Event()
        self.cancel_events[run_id] = cancel
        self.run_locks[run_id] = asyncio.Lock()
        self.tasks[run_id] = asyncio.create_task(self.execute(run, cancel))
        return run

    @staticmethod
    def _evidence_context(run: RunRecord) -> str:
        sections = []
        for index, source in enumerate(run.source_snapshots, 1):
            origin = source.url or source.filename or "本地文字资料"
            sections.append(f"[S{index}] {source.title}\n来源：{origin}\n{source.content}")
        return "\n\n".join(sections)

    async def emit(
        self,
        run: RunRecord,
        event_type: str,
        stage: str,
        message: str,
        progress: int,
        data: dict[str, Any] | None = None,
    ) -> None:
        run.updated_at = utc_now()
        await self.store.save_run(run)
        await self.store.publish(
            RunEvent(
                event_id=str(uuid.uuid4()),
                run_id=run.id,
                type=event_type,
                stage=stage,
                message=message,
                progress=progress,
                data=data or {},
            )
        )

    async def execute(self, run: RunRecord, cancel: asyncio.Event) -> None:
        started = time.perf_counter()
        try:
            run.status = "running"
            run.recoverable = False
            await self.emit(run, "question_analyzed", "analysis", "问题已放上圆桌，第一位成员正在准备发言", 8)
            run.analysis = analyze_question(run.question, run.mode, run.limits.max_tokens)
            async with asyncio.timeout(run.limits.timeout_seconds):
                await self._run_debate_graph(run, cancel, resume=False)
                if run.status == "awaiting_final_input" and run.auto_summarize:
                    await self._finalize_once(run)
        except RunLimitReached as exc:
            await self._stop_for_limit(run, exc)
        except asyncio.CancelledError:
            if self.shutting_down:
                run.status = "running"
                run.recoverable = True
            elif run.id not in self.retrying_runs:
                run.status = "cancelled"
                run.error = "任务已取消"
                await self.emit(run, "run_cancelled", "cancelled", "审议已取消，已保留当前进度", 100)
        except Exception as exc:
            run.status = "failed"
            run.degraded = True
            run.recoverable = True
            run.error = describe_run_error(exc, run.limits.timeout_seconds)
            await self.emit(
                run,
                "run_failed",
                "error",
                "当前席位调用失败，已保留讨论进度",
                100,
                {"error": run.error, "speaker_index": run.current_speaker_index},
            )
        finally:
            run.usage.duration_ms += int((time.perf_counter() - started) * 1000)
            run.updated_at = utc_now()
            await self.store.save_run(run)

    async def _stop_for_limit(self, run: RunRecord, exc: RunLimitReached) -> None:
        run.status = "stopped"
        run.awaiting_user = False
        run.recoverable = False
        run.limit_reason = exc.code
        run.error = str(exc)
        await self.emit(
            run,
            "run_limit_reached",
            "limits",
            str(exc),
            100,
            {"limit": exc.code, "speaker_index": run.current_speaker_index},
        )

    async def _run_debate_graph(self, run: RunRecord, cancel: asyncio.Event, resume: bool) -> None:
        backends: dict[str, ModelBackend] = {}

        async def run_turn(state: DebateWorkflowState) -> dict[str, int]:
            if cancel.is_set():
                raise asyncio.CancelledError
            speaker_index = state["next_speaker_index"]
            if speaker_index < run.current_speaker_index:
                return {"next_speaker_index": run.current_speaker_index}
            if speaker_index >= len(self.PARTICIPANTS):
                return {"next_speaker_index": speaker_index}
            participant = self.PARTICIPANTS[speaker_index]
            candidate_id = f"candidate-{participant['id']}"
            if any(item.candidate_id == candidate_id for item in run.candidates):
                run.current_speaker_index = max(run.current_speaker_index, speaker_index + 1)
                await self.store.save_run(run)
                return {"next_speaker_index": run.current_speaker_index}
            await self._generate_turn(run, backends, speaker_index)
            run.checkpoint_count = max(run.checkpoint_count, run.current_speaker_index)
            await self.store.save_run(run)
            return {"next_speaker_index": run.current_speaker_index}

        async def dispatch(_: DebateWorkflowState) -> dict[str, int]:
            return {}

        def route(state: DebateWorkflowState) -> str:
            return "turn" if state["next_speaker_index"] < len(self.PARTICIPANTS) else "done"

        builder = StateGraph(DebateWorkflowState)
        builder.add_node("dispatch", dispatch)
        builder.add_node("turn", run_turn)
        builder.add_node("done", lambda _: {})
        builder.add_edge(START, "dispatch")
        builder.add_conditional_edges("dispatch", route, {"turn": "turn", "done": "done"})
        builder.add_conditional_edges("turn", route, {"turn": "turn", "done": "done"})
        builder.add_edge("done", END)

        config = {"configurable": {"thread_id": run.id}}
        try:
            async with AsyncSqliteSaver.from_conn_string(self.store.checkpoint_path) as saver:
                await saver.conn.execute("PRAGMA busy_timeout=5000")
                graph = builder.compile(checkpointer=saver)
                checkpoint = await saver.aget_tuple(config)
                graph_input: DebateWorkflowState | None = None if resume and checkpoint else {
                    "run_id": run.id,
                    "next_speaker_index": run.current_speaker_index,
                }
                await graph.ainvoke(graph_input, config)
                run.checkpoint_count = len([item async for item in saver.alist(config)])
        finally:
            await self._close_backends(backends)

        if run.current_speaker_index >= len(self.PARTICIPANTS) and run.final_decision is None:
            run.status = "awaiting_final_input"
            run.awaiting_user = True
            await self.emit(
                run,
                "awaiting_final_input",
                "discussion",
                "四席发言完成。你可以补充信息，确认后再生成最终答案",
                90,
            )

    @staticmethod
    async def _close_backends(backends: dict[str, ModelBackend]) -> None:
        unique = {id(backend): backend for backend in backends.values()}
        if unique:
            close_calls = []
            for backend in unique.values():
                close = getattr(backend, "aclose", None)
                if close:
                    close_calls.append(close())
            if close_calls:
                await asyncio.gather(*close_calls, return_exceptions=True)

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

    @staticmethod
    def _check_call_limits(run: RunRecord) -> None:
        if run.usage.model_calls >= run.limits.max_model_calls:
            raise RunLimitReached("max_model_calls", f"已达到模型调用上限（{run.limits.max_model_calls} 次），未继续请求下一席。")
        used_tokens = run.usage.input_tokens + run.usage.output_tokens
        if used_tokens >= run.limits.max_tokens:
            raise RunLimitReached("max_tokens", f"已达到 Token 上限（{run.limits.max_tokens}），未继续请求下一席。")

    async def _generate_with_fallback(
        self,
        run: RunRecord,
        assignment: ResolvedAgentAssignment,
        backends: dict[str, ModelBackend],
        prompt: str,
        system: str,
    ) -> Any:
        provider_type = getattr(assignment.provider_snapshot.provider_type, "value", assignment.provider_snapshot.provider_type)
        native_effort = assignment.provider_snapshot.capabilities.supports_reasoning_effort
        plan = (
            CCSWITCH_EFFORT_FALLBACKS.get(assignment.reasoning_effort, [(assignment.reasoning_effort, 1.0)])
            if provider_type == "ccswitch_local" and native_effort
            else [(assignment.reasoning_effort, 1.0)]
        )

        for index, (effort, timeout_fraction) in enumerate(plan):
            self._check_call_limits(run)
            attempt_profile = assignment.provider_snapshot.model_copy(update={"reasoning_effort": effort})
            backend_key = f"{assignment.role}:{assignment.provider_id}:{assignment.model}:{effort}"
            if backend_key not in backends:
                backends[backend_key] = build_backend(attempt_profile)
            run.usage.model_calls += 1
            await self.store.save_run(run)
            try:
                generation = await asyncio.wait_for(
                    backends[backend_key].generate(
                        prompt,
                        system,
                        assignment.model,
                        temperature=assignment.temperature,
                    ),
                    timeout=max(1.0, min(assignment.timeout_seconds, run.limits.timeout_seconds) * timeout_fraction),
                )
                run.usage.input_tokens += generation.input_tokens
                run.usage.output_tokens += generation.output_tokens
                return generation
            except Exception as exc:
                if index >= len(plan) - 1 or not self._is_retryable_generation_error(exc):
                    raise
                next_effort = plan[index + 1][0]
                run.degraded = True
                run.reasoning_effort = next_effort
                for pending in run.seat_assignments[run.current_speaker_index:]:
                    if pending.provider_id == assignment.provider_id and pending.reasoning_effort == effort:
                        pending.reasoning_effort = next_effort
                        pending.provider_snapshot.reasoning_effort = next_effort
                if run.finalizer_assignment and run.finalizer_assignment.provider_id == assignment.provider_id and run.finalizer_assignment.reasoning_effort == effort:
                    run.finalizer_assignment.reasoning_effort = next_effort
                    run.finalizer_assignment.provider_snapshot.reasoning_effort = next_effort
                current_label = EFFORT_LABELS.get(effort, effort.title())
                next_label = EFFORT_LABELS.get(next_effort, next_effort.title())
                reason = "上游超时" if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) else "上游暂不可用"
                run.discussion_turns.append(
                    DiscussionTurn(
                        id=str(uuid.uuid4()),
                        speaker_type="system",
                        speaker_id="route",
                        speaker_name="路由",
                        role_label="自动重试",
                        content=f"{current_label} 原生推理档{reason}，已自动降为 {next_label} 档重试当前席位。",
                        round=run.discussion_round,
                        provider_id=assignment.provider_id,
                        provider_name=assignment.provider_name,
                        model=assignment.model,
                    )
                )
                await self.emit(
                    run,
                    "provider_degraded",
                    "discussion",
                    f"{assignment.provider_name} {current_label} 档{reason}，正在以 {next_label} 档重试",
                    min(88, 15 + len(run.discussion_turns) * 7),
                    {"from_effort": effort, "to_effort": next_effort, "speaker_index": run.current_speaker_index},
                )

        raise RuntimeError("Provider 重试流程未能生成结果")

    async def _generate_turn(
        self,
        run: RunRecord,
        backends: dict[str, ModelBackend],
        speaker_index: int,
    ) -> None:
        participant = self.PARTICIPANTS[speaker_index]
        assignment = run.seat_assignments[speaker_index]
        run.awaiting_user = False
        context_window = build_context_window(
            run.question,
            run.discussion_turns,
            context_budget_for_mode(run.mode),
            self._evidence_context(run),
            run.project_context,
        )
        run.context_snapshot = ContextSnapshot(
            token_budget=context_window.token_budget,
            estimated_tokens=context_window.estimated_tokens,
            included_turns=context_window.included_turns,
            total_turns=context_window.total_turns,
            compacted=context_window.compacted,
            summary=context_window.summary,
            source_tokens=context_window.source_tokens,
            history_tokens=context_window.history_tokens,
        )
        await self.emit(
            run,
            "agent_turn_started",
            "discussion",
            f"{participant['name']}正在通过 {assignment.provider_name} / {assignment.model} 组织发言",
            min(82, 15 + len(run.discussion_turns) * 7),
            {"speaker": participant, "provider_id": assignment.provider_id, "model": assignment.model},
        )
        if speaker_index == 0:
            debate_instruction = "你是第一位发言者。直接回答用户问题，给出清楚的初步观点和依据，为后续辩论建立起点。"
        else:
            debate_instruction = (
                "你必须先回应前面各位的公开观点并明确表态。开头使用‘表态：认同’、‘表态：部分认同’或‘表态：反驳’之一；"
                "确有不同意见就指出具体哪一点、为什么，若没有可反驳之处就明确认同，不要为了制造冲突而强行反驳。"
                "随后补充自己的新依据、修正或方案。"
            )
        template = get_template(run.template_id)
        source_instruction = (
            "已提供带 [S编号] 的资料。涉及资料中的事实时引用对应编号；没有资料支持的内容必须标为推断或未知，禁止编造来源。"
            if run.source_snapshots
            else "当前没有附加资料，不得声称结论已经过外部核验。"
        )
        system = (
            f"你是四人圆桌中的{participant['name']}，角色是{participant['role']}：{participant['brief']}。\n"
            f"{debate_instruction}\n本次模板要求：{template.system_guidance}\n{source_instruction}"
            "这是用户全程可参与的公开讨论。必须回应记录中最新的用户插话。"
            "不要替全体宣布最终答案，不展示隐藏思维链，控制在220字以内。"
        )
        generation = await self._generate_with_fallback(run, assignment, backends, context_window.prompt, system)
        turn = DiscussionTurn(
            id=str(uuid.uuid4()),
            speaker_type="agent",
            speaker_id=participant["id"],
            speaker_name=participant["name"],
            role_label=participant["role"],
            content=generation.text.strip(),
            round=run.discussion_round,
            provider_id=assignment.provider_id,
            provider_name=assignment.provider_name,
            model=assignment.model,
        )
        run.discussion_turns.append(turn)
        run.current_speaker_index = speaker_index + 1
        candidate = make_candidate(
            f"candidate-{participant['id']}",
            run.question,
            participant["role"],
            assignment.model,
            assignment.provider_name,
            generation.text,
            UsageSummary(
                model_calls=1,
                input_tokens=generation.input_tokens,
                output_tokens=generation.output_tokens,
            ),
        )
        candidate.anonymous_label = participant["name"]
        run.candidates = [item for item in run.candidates if item.candidate_id != candidate.candidate_id] + [candidate]
        next_speaker = self.PARTICIPANTS[run.current_speaker_index] if run.current_speaker_index < len(self.PARTICIPANTS) else None
        await self.emit(
            run,
            "agent_turn_completed",
            "discussion",
            f"{participant['name']}发言完毕，下一位将继续回应；你可随时插话",
            min(88, 20 + len(run.discussion_turns) * 14),
            {"turn": turn.model_dump(mode="json"), "next_speaker": next_speaker},
        )

    @staticmethod
    def _explicit_disagreements(run: RunRecord) -> list[str]:
        markers = ("表态：反驳", "表态:反驳", "表态：部分认同", "表态:部分认同")
        return [
            turn.content
            for turn in run.discussion_turns
            if turn.speaker_type == "agent" and turn.content.lstrip().startswith(markers)
        ]

    async def _finalize_debate(
        self,
        run: RunRecord,
        assignment: ResolvedAgentAssignment,
        backends: dict[str, ModelBackend],
    ) -> None:
        if run.final_decision is not None:
            return
        context_window = build_context_window(
            run.question,
            run.discussion_turns,
            context_budget_for_mode(run.mode),
            self._evidence_context(run),
            run.project_context,
        )
        run.context_snapshot = ContextSnapshot(
            token_budget=context_window.token_budget,
            estimated_tokens=context_window.estimated_tokens,
            included_turns=context_window.included_turns,
            total_turns=context_window.total_turns,
            compacted=context_window.compacted,
            summary=context_window.summary,
            source_tokens=context_window.source_tokens,
            history_tokens=context_window.history_tokens,
        )
        await self.emit(run, "summary_started", "summary", "正在根据四席公开讨论和你的最终补充形成答案", 94)
        template = get_template(run.template_id)
        citation_instruction = (
            "附加资料使用 [S编号] 引用；只引用上下文中真实存在的编号。资料没有覆盖的事实必须保留为未知。"
            if run.source_snapshots
            else "没有附加资料，不得声称答案已通过外部事实核验。"
        )
        generation = await self._generate_with_fallback(
            run,
            assignment,
            backends,
            context_window.prompt,
            "你是圆桌记录员。根据四位成员和用户的完整公开讨论，直接给出最终答案。"
            "先综合已经形成的共识，再处理明确分歧，最后给出可执行答案和必要边界。"
            f"本次模板要求：{template.system_guidance} {citation_instruction}"
            "不要声称不存在的共识，不展示隐藏思维链。",
        )
        provider_type = getattr(assignment.provider_snapshot.provider_type, "value", assignment.provider_snapshot.provider_type)
        sources = [
            f"[S{index}] {source.title}" + (f" — {source.url}" if source.url else f" — {source.filename}" if source.filename else "")
            for index, source in enumerate(run.source_snapshots, 1)
        ]
        run.final_decision = FinalDecision(
            final_answer=generation.text.strip(),
            key_reasons=[
                "四席按顺序公开回应",
                "用户在最终综合前确认了讨论上下文",
                *([f"本次固化了 {len(sources)} 份资料快照"] if sources else []),
            ],
            unverified_claims=[
                "附加资料已进入公开上下文，但 Council 未独立验证来源真实性"
                if sources
                else "模型共识尚未经过外部事实核验"
            ],
            disagreements=self._explicit_disagreements(run),
            risks_and_limitations=["模型共识不等于事实验证；关键结论仍需使用第一方资料或可复现测试核对。"],
            confidence={
                "level": "source_grounded" if sources else "unverified",
                "explanation": "答案引用了用户提供的资料，但资料真实性仍需人工确认。"
                if sources
                else "当前没有外部证据，因此不提供百分比置信度。",
            },
            sources=sources,
            provider_summary={
                "provider": assignment.provider_name,
                "protocol": "mock" if provider_type == "mock" else "openai_compatible",
                "model": assignment.model,
                "used_ccswitch": provider_type == "ccswitch_local",
                "degraded": run.degraded,
                "seat_providers": [
                    {"role": item.role, "provider": item.provider_name, "model": item.model}
                    for item in run.seat_assignments
                ],
            },
            usage=run.usage,
        )

    async def _finalize_once(self, run: RunRecord) -> None:
        if not run.finalizer_assignment:
            raise RuntimeError("此运行缺少总结席配置快照")
        backends: dict[str, ModelBackend] = {}
        try:
            await self._finalize_debate(run, run.finalizer_assignment, backends)
        finally:
            await self._close_backends(backends)
        run.status = "completed"
        run.awaiting_user = False
        run.recoverable = False
        await self.emit(run, "final_completed", "complete", "圆桌最终答案已生成", 100, {"verification": "unverified"})

    async def interject(self, run_id: str, action: DiscussionAction) -> RunRecord | None:
        run = self.live_runs.get(run_id) or await self.store.get_run(run_id)
        if not run:
            return None
        can_interject = run.status == "awaiting_final_input" or (
            run.status == "running" and run.current_speaker_index < len(self.PARTICIPANTS)
        )
        if not can_interject or not action.message.strip():
            return run
        target = next((item for item in self.PARTICIPANTS if item["id"] == action.target_agent), None)
        prefix = f"问{target['name']}：" if action.action == "question" and target else ""
        run.discussion_turns.append(
            DiscussionTurn(
                id=str(uuid.uuid4()),
                speaker_type="user",
                speaker_id="user",
                speaker_name="你",
                role_label="最终补充" if run.status == "awaiting_final_input" else "参与者",
                content=prefix + action.message.strip(),
                round=run.discussion_round,
            )
        )
        await self.emit(
            run,
            "user_interjected",
            "discussion",
            "你的补充已进入公开讨论",
            90 if run.status == "awaiting_final_input" else min(90, 12 + len(run.discussion_turns) * 12),
            {"target_agent": action.target_agent},
        )
        return run

    async def advance(self, run_id: str, action: DiscussionAction) -> RunRecord | None:
        if action.action in {"interject", "question"}:
            return await self.interject(run_id, action)
        return self.live_runs.get(run_id) or await self.store.get_run(run_id)

    async def retry_turn(self, run_id: str) -> RunRecord | None:
        run = self.live_runs.get(run_id) or await self.store.get_run(run_id)
        if not run:
            return None
        if run.status not in {"running", "failed"}:
            return run

        return await self._restart_debate(run_id)

    async def resume_with_limits(self, run_id: str, limits: RunLimits) -> RunRecord | None:
        run = self.live_runs.get(run_id) or await self.store.get_run(run_id)
        if not run:
            return None
        if run.status != "stopped" or run.limit_reason not in {"max_tokens", "max_model_calls"}:
            raise ValueError("只有达到模型调用或 Token 上限而停止的运行可以提额续跑。")

        used_tokens = run.usage.input_tokens + run.usage.output_tokens
        if limits.max_tokens <= used_tokens:
            raise ValueError(f"新的 Token 上限必须高于当前累计用量（{used_tokens}）。")
        if limits.max_model_calls <= run.usage.model_calls:
            raise ValueError(f"新的模型调用上限必须高于当前调用次数（{run.usage.model_calls}）。")

        return await self._restart_debate(run_id, limits)

    async def _restart_debate(self, run_id: str, limits: RunLimits | None = None) -> RunRecord | None:
        run = self.live_runs.get(run_id) or await self.store.get_run(run_id)
        if not run:
            return None

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
        self._ensure_run_assignments(run)
        self._ensure_credentials(run)
        if limits is not None:
            run.limits = limits
        run.status = "running"
        run.awaiting_user = False
        run.error = None
        run.limit_reason = None
        run.recoverable = False
        await self.store.save_run(run)
        cancel = asyncio.Event()
        self.cancel_events[run_id] = cancel
        self.tasks[run_id] = asyncio.create_task(self._resume_debate(run, cancel))
        return run

    async def _resume_debate(self, run: RunRecord, cancel: asyncio.Event) -> None:
        lock = self.run_locks.setdefault(run.id, asyncio.Lock())
        async with lock:
            started = time.perf_counter()
            try:
                async with asyncio.timeout(run.limits.timeout_seconds):
                    await self._run_debate_graph(run, cancel, resume=True)
                    if run.status == "awaiting_final_input" and run.auto_summarize:
                        await self._finalize_once(run)
            except RunLimitReached as exc:
                await self._stop_for_limit(run, exc)
            except asyncio.CancelledError:
                if self.shutting_down:
                    run.status = "running"
                    run.recoverable = True
                else:
                    raise
            except Exception as exc:
                run.degraded = True
                run.status = "failed"
                run.recoverable = True
                run.error = describe_run_error(exc, run.limits.timeout_seconds)
                await self.emit(
                    run,
                    "run_failed",
                    "discussion",
                    "当前席位恢复失败，已保留公开讨论记录",
                    100,
                    {"error": run.error, "speaker_index": run.current_speaker_index},
                )
            finally:
                run.usage.duration_ms += int((time.perf_counter() - started) * 1000)
                await self.store.save_run(run)

    async def summarize(self, run_id: str) -> RunRecord | None:
        run = self.live_runs.get(run_id) or await self.store.get_run(run_id)
        if not run:
            return None
        if run.status != "awaiting_final_input" or not run.awaiting_user:
            return run
        self._ensure_run_assignments(run)
        self._ensure_credentials(run, finalizer_only=True)
        run.status = "running"
        run.awaiting_user = False
        run.error = None
        await self.store.save_run(run)
        self.tasks[run_id] = asyncio.create_task(self._summarize_task(run))
        return run

    async def _summarize_task(self, run: RunRecord) -> None:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(run.limits.timeout_seconds):
                await self._finalize_once(run)
        except RunLimitReached as exc:
            await self._stop_for_limit(run, exc)
        except Exception as exc:
            run.status = "awaiting_final_input"
            run.awaiting_user = True
            run.recoverable = True
            run.error = describe_run_error(exc, run.limits.timeout_seconds)
            await self.emit(
                run,
                "agent_turn_failed",
                "summary",
                "最终综合未完成，讨论记录和你的补充已保留",
                92,
                {"error": run.error},
            )
        finally:
            run.usage.duration_ms += int((time.perf_counter() - started) * 1000)
            await self.store.save_run(run)

    def _ensure_run_assignments(self, run: RunRecord) -> None:
        if len(run.seat_assignments) == len(self.PARTICIPANTS) and run.finalizer_assignment:
            return
        config = self.default_assignment_config(run.provider_id, run.model, run.mode)
        run.seat_assignments = [self._resolve_assignment(item) for item in config.seats]
        run.finalizer_assignment = self._resolve_assignment(config.finalizer)

    @staticmethod
    def _ensure_credentials(run: RunRecord, finalizer_only: bool = False) -> None:
        assignments = [run.finalizer_assignment] if finalizer_only else [*run.seat_assignments, run.finalizer_assignment]
        for assignment in assignments:
            if not assignment:
                continue
            profile = assignment.provider_snapshot
            if profile.requires_api_key and not get_provider_secret(profile):
                raise RuntimeError(f"{assignment.provider_name} 的凭据缺失，未回退到 Mock。请补充 API Key 后重试。")

    async def recover_incomplete_runs(self) -> list[str]:
        recovered: list[str] = []
        for run in await self.store.list_runs():
            if run.status not in {"queued", "running"}:
                continue
            self.live_runs[run.id] = run
            self.run_locks[run.id] = asyncio.Lock()
            try:
                self._ensure_run_assignments(run)
                self._ensure_credentials(run)
                if not self.store.has_checkpoint(run.id):
                    raise RuntimeError("找不到有效工作流 checkpoint，无法安全自动恢复。")
            except Exception as exc:
                run.status = "failed"
                run.recoverable = True
                run.error = str(exc)
                await self.emit(run, "run_failed", "recovery", "启动恢复未执行模型调用", 100, {"error": run.error})
                continue
            cancel = asyncio.Event()
            self.cancel_events[run.id] = cancel
            self.tasks[run.id] = asyncio.create_task(self._resume_debate(run, cancel))
            recovered.append(run.id)
        return recovered

    async def cancel(self, run_id: str) -> RunRecord | None:
        run = self.live_runs.get(run_id) or await self.store.get_run(run_id)
        if not run:
            return None
        if run.status == "awaiting_final_input":
            run.status = "cancelled"
            run.awaiting_user = False
            run.error = "任务已取消"
            await self.emit(run, "run_cancelled", "cancelled", "审议已取消，已保留当前进度", 100)
            return run
        if run.status in {"queued", "running"}:
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
            except (asyncio.CancelledError, Exception):
                pass
        deleted = await self.store.delete_run(run_id)
        self.tasks.pop(run_id, None)
        self.cancel_events.pop(run_id, None)
        self.run_locks.pop(run_id, None)
        self.live_runs.pop(run_id, None)
        self.retrying_runs.discard(run_id)
        return deleted

    async def shutdown(self) -> None:
        self.shutting_down = True
        active = [task for task in self.tasks.values() if not task.done()]
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
