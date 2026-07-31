import pytest

from app.context import build_context_window as real_build_context_window
from app.models import DiscussionTurn, ProviderProfile, ProviderType, RunCreate
from app.orchestrator import Orchestrator
from app.store import Store


def test_workflow_strategy_is_explicit_and_validated():
    assert RunCreate(question="独立初答", workflow_strategy="independent").workflow_strategy == "independent"
    assert RunCreate(question="默认兼容").workflow_strategy == "sequential"
    with pytest.raises(ValueError):
        RunCreate(question="非法策略", workflow_strategy="hybrid")


def test_independent_context_contract_excludes_public_turns():
    previous = DiscussionTurn(
        id="turn-1", speaker_type="agent", speaker_id="analyst", speaker_name="析理",
        role_label="分析", content="不应泄露给独立初答席位", stage="initial_opinion",
    )
    sequential = real_build_context_window("同一个问题", [previous], 1000)
    independent = real_build_context_window("同一个问题", [], 1000)
    assert "不应泄露给独立初答席位" in sequential.prompt
    assert "不应泄露给独立初答席位" not in independent.prompt
    assert independent.total_turns == 0


def test_legacy_provider_profile_remains_constructible():
    # Keeps this milestone independent from provider setup and documents the
    # compatibility boundary for source installs.
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    assert profile.id == "mock"


@pytest.mark.asyncio
async def test_independent_run_never_passes_prior_turns_to_initial_seats(tmp_path, monkeypatch):
    observed_turn_counts: list[int] = []

    def recording_context(question, turns, *args, **kwargs):
        observed_turn_counts.append(len(turns))
        return real_build_context_window(question, turns, *args, **kwargs)

    monkeypatch.setattr("app.orchestrator.build_context_window", recording_context)
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})
    run = await orchestrator.start(
        RunCreate(question="四席分别判断是否灰度发布", provider_id="mock", workflow_strategy="independent")
    )
    await orchestrator.tasks[run.id]
    saved = await store.get_run(run.id)
    await orchestrator.shutdown()
    store.close()

    assert saved is not None
    assert saved.status == "awaiting_final_input"
    assert observed_turn_counts == [0] * len(saved.participant_roles)
    assert all(turn.stage == "initial_opinion" for turn in saved.discussion_turns if turn.speaker_type == "agent")
