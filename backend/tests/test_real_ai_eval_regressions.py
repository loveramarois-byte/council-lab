import asyncio

import pytest

from app.models import ProviderProfile, ProviderType, RunCreate
from app.orchestrator import Orchestrator, analyze_question
from app.providers import Generation
from app.store import Store


def test_short_task_analysis_is_conservative_and_exposes_call_budget():
    definition = analyze_question("请用一句话解释什么是向量数据库", "quick")
    arithmetic = analyze_question("200 打 8 折再减 20 是多少？", "quick")

    assert definition.recommended_agents == 1
    assert definition.expected_model_calls == 2
    assert definition.short_task_route is True
    assert arithmetic.recommended_agents == 1
    assert arithmetic.expected_model_calls == 2
    assert arithmetic.short_task_route is True

    for question in (
        "这个 API 商业模式是否合理？",
        "多少用户会喜欢这个功能？",
        "预测今年 GDP 增速是多少？",
        "请评估是否应该上线付费订阅",
        "Python 3.12-3.13 哪个更稳定？",
        "iPhone 15 Pro+ 值得买吗？",
        "什么是生产事故应急响应？",
        "Python 3.12 增加了哪些功能？",
        "投资 100 元获得 10% 收益是否合理？",
    ):
        analysis = analyze_question(question, "quick")
        assert analysis.recommended_agents == 4, question
        assert analysis.expected_model_calls == 5, question
        assert analysis.short_task_route is False, question


@pytest.mark.asyncio
async def test_auto_summarize_never_publishes_manual_confirmation_state(tmp_path, monkeypatch):
    calls = 0

    class ImmediateBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            nonlocal calls
            calls += 1
            return Generation(text="最终答案" if "记录员" in system else "席位发言")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: ImmediateBackend())
    store = Store(tmp_path / "auto-summary.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})

    run = await orchestrator.start(
        RunCreate(
            question="请评估是否应该上线付费订阅",
            mode="quick",
            provider_id="mock",
            auto_summarize=True,
        )
    )
    await orchestrator.tasks[run.id]

    current = await store.get_run(run.id)
    events = [event.type for event in await store.list_events(run.id)]
    assert current is not None
    assert current.status == "completed"
    assert current.awaiting_user is False
    assert "awaiting_final_input" not in events
    assert events[-1] == "final_completed"
    assert calls == 5


@pytest.mark.asyncio
async def test_cancel_response_is_terminal_and_preserves_completed_work(tmp_path, monkeypatch):
    generation_started = asyncio.Event()

    class BlockingBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            generation_started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: BlockingBackend())
    store = Store(tmp_path / "cancel.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})

    run = await orchestrator.start(RunCreate(question="请评估 monorepo 迁移风险", provider_id="mock"))
    await asyncio.wait_for(generation_started.wait(), timeout=1)
    await asyncio.sleep(0.01)
    returned = await orchestrator.cancel(run.id)

    assert returned is not None
    assert returned.status == "cancelled"
    assert returned.awaiting_user is False
    assert returned.usage.duration_ms > 0
    persisted = await store.get_run(run.id)
    assert persisted is not None and persisted.status == "cancelled"
    events = [event.type for event in await store.list_events(run.id)]
    assert events.count("run_cancelled") == 1


@pytest.mark.asyncio
async def test_short_definition_uses_one_seat_plus_finalizer(tmp_path, monkeypatch):
    systems: list[str] = []

    class RecordingBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            systems.append(system)
            return Generation(text="最终答案" if "记录员" in system else "一句话解释")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: RecordingBackend())
    store = Store(tmp_path / "short-route.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})

    run = await orchestrator.start(
        RunCreate(
            question="请用一句话解释什么是向量数据库",
            mode="quick",
            provider_id="mock",
            auto_summarize=True,
        )
    )
    await orchestrator.tasks[run.id]

    current = await store.get_run(run.id)
    assert current is not None and current.status == "completed"
    assert [participant["id"] for participant in current.participant_roles] == ["analyst"]
    assert current.analysis is not None and current.analysis.expected_model_calls == 2
    assert current.usage.model_calls == 2
    assert len(systems) == 2
    assert "本次 1 席圆桌" in systems[0]
    assert "四人圆桌" not in systems[0]
    assert current.final_decision is not None
    assert [item["role"] for item in current.final_decision.provider_summary["seat_providers"]] == ["analyst"]


@pytest.mark.asyncio
async def test_challenger_and_observer_prompts_require_real_critical_work(tmp_path, monkeypatch):
    systems: list[str] = []

    class RecordingBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            systems.append(system)
            return Generation(text="表态：部分认同。席位发言")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: RecordingBackend())
    store = Store(tmp_path / "prompt-contract.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})

    run = await orchestrator.start(RunCreate(question="请评估是否应该上线付费订阅", provider_id="mock"))
    await orchestrator.tasks[run.id]

    assert "至少给出一个可证伪的反例" in systems[1]
    assert "什么证据会推翻当前判断" in systems[1]
    assert "未解决分歧" in systems[3]
    assert "不得为了完成格式而虚构冲突" in systems[3]
