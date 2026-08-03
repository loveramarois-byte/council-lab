import asyncio
import io
import json
import sqlite3
import time

import pytest

from app.context import (
    _truncate_tokens,
    _truncate_tokens_with_tail,
    build_context_window,
    context_budget_for_mode,
    estimate_tokens,
    token_estimator_for,
)
from app.credentials import delete_provider_secret, get_provider_secret, save_provider_secret
from app.evidence import content_hash, extract_file_text, validate_public_url
from app.models import (
    AgentAssignmentsConfig,
    AgentModelAssignment,
    CandidateAnswer,
    DiscussionAction,
    DiscussionTurn,
    FinalDecision,
    DecisionReview,
    ProjectRecord,
    ProjectSource,
    ProviderCapabilities,
    ProviderCreate,
    ProviderProfile,
    ProviderType,
    RunCreate,
    RunLimits,
    RunRecord,
    RunSourceSnapshot,
    UsageSummary,
    utc_now,
)
from app.orchestrator import Orchestrator, analyze_question, describe_run_error, reasoning_effort_for_mode
from app.paths import data_dir, database_path
from app.provider_catalog import builtin_providers
from app.providers import DEFAULT_CCSWITCH_URL, Generation, OpenAICompatibleProvider, build_responses_payload, discover_ccswitch_models, extract_model_ids, extract_responses_text, is_loopback_url, normalize_base_url, replace_model_catalog, resolve_model_catalog, validate_base_url
from app.reports import run_html, run_markdown
from app.runtime_config import assignment_config_is_valid, restore_provider_profiles
from app.store import Store, serialize_public_provider
from evals.scoring import STRATEGIES, aggregate_execution, blind_labels, load_dataset, summarize_human_reviews
from evals.run_benchmark import estimate_provider_cost, provider_reality


def test_data_directory_can_be_overridden(tmp_path, monkeypatch):
    monkeypatch.setenv("COUNCIL_DATA_DIR", str(tmp_path / "private-data"))
    assert data_dir() == (tmp_path / "private-data").resolve()
    assert database_path() == (tmp_path / "private-data" / "council.sqlite3").resolve()


def test_provider_accepts_key_environment_name_and_masks_plaintext_key():
    provider = ProviderCreate(
        display_name="Compatible API",
        provider_type=ProviderType.COMPATIBLE,
        api_key_env="MY_PROVIDER_API_KEY",
        api_key="secret-value",
    )
    assert provider.api_key_env == "MY_PROVIDER_API_KEY"
    assert provider.api_key is not None
    assert provider.api_key.get_secret_value() == "secret-value"
    assert "secret-value" not in str(provider)


def test_builtin_provider_catalog_uses_official_api_roots():
    catalog = builtin_providers()
    assert catalog["deepseek"].base_url == "https://api.deepseek.com"
    assert catalog["zhipu"].base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert catalog["kimi"].base_url == "https://api.moonshot.cn/v1"
    assert catalog["ccswitch"].default_model == ""
    assert catalog["deepseek"].default_model == "deepseek-chat"
    assert catalog["deepseek"].model_source == "recommended"
    assert catalog["zhipu"].default_model == "glm-4-flash"
    assert not any("5.6" in model or "v4-" in model or "k3" in model for profile in catalog.values() for model in [profile.default_model, *profile.available_models])
    assert normalize_base_url(catalog["zhipu"].base_url, ProviderType.COMPATIBLE) == catalog["zhipu"].base_url


def test_provider_secret_uses_system_credential_store_without_public_exposure(monkeypatch):
    secrets: dict[tuple[str, str], str] = {}
    monkeypatch.setattr("app.credentials.keyring.set_password", lambda service, account, value: secrets.__setitem__((service, account), value))
    monkeypatch.setattr("app.credentials.keyring.get_password", lambda service, account: secrets.get((service, account)))
    monkeypatch.setattr("app.credentials.keyring.delete_password", lambda service, account: secrets.pop((service, account)))

    profile = builtin_providers()["deepseek"]
    save_provider_secret(profile.id, "secret-value")
    profile.credential_saved = True
    assert get_provider_secret(profile) == "secret-value"
    public = serialize_public_provider(profile)
    assert public["has_api_key"] is True
    assert "secret-value" not in str(public)
    delete_provider_secret(profile.id)


async def test_compatible_backend_reads_key_from_environment(monkeypatch):
    profile = builtin_providers()["zhipu"]
    monkeypatch.setenv("ZHIPU_API_KEY", "test-key-123")
    backend = OpenAICompatibleProvider(profile)
    try:
        assert backend.client.headers["Authorization"] == "Bearer test-key-123"
        assert str(backend.client.base_url) == "https://open.bigmodel.cn/api/paas/v4/"
    finally:
        await backend.client.aclose()


def test_ccswitch_default_url():
    assert normalize_base_url("", ProviderType.CCSWITCH) == DEFAULT_CCSWITCH_URL
    assert normalize_base_url("http://127.0.0.1:17777", ProviderType.CCSWITCH).endswith("/v1")


def test_loopback_and_ssrf():
    assert is_loopback_url("http://127.0.0.1:15721/v1")
    assert not is_loopback_url("https://example.com/v1")
    with pytest.raises(ValueError):
        validate_base_url("http://169.254.169.254/latest", local_only=False)


def test_question_analysis():
    analysis = analyze_question("请计算这个公式", "standard", 45000)
    assert analysis.question_type == "mathematical"
    assert analysis.needs_math
    assert analysis.recommended_agents == 4
    assert analysis.expected_token_limit == 45000


def test_discussion_models_support_user_participation():
    action = DiscussionAction(action="question", message="这个假设成立吗？", target_agent="challenger")
    turn = DiscussionTurn(id="turn-1", speaker_type="user", speaker_id="user", speaker_name="你", content=action.message)
    assert action.target_agent == "challenger"
    assert turn.speaker_type == "user"
    assert len(Orchestrator.PARTICIPANTS) == 4


def test_model_list_formats():
    assert extract_model_ids({"data": [{"id": "gpt-test"}]}) == ["gpt-test"]
    assert extract_model_ids({"models": ["gpt-a", {"id": "gpt-b"}]}) == ["gpt-a", "gpt-b"]
    assert extract_model_ids({"models": [{"slug": "gpt-c"}, {"model": "gpt-d"}]}) == ["gpt-c", "gpt-d"]


def test_empty_model_catalog_replaces_stale_live_models_with_honest_fallback():
    profile = ProviderProfile(
        id="deepseek",
        display_name="DeepSeek",
        provider_type=ProviderType.COMPATIBLE,
        default_model="stale-live-model",
        available_models=["stale-live-model"],
        model_source="provider",
    )

    models, source, fetched = resolve_model_catalog([], ["recommended-model"], "recommended")
    replace_model_catalog(profile, models, source)

    assert fetched == 0
    assert profile.available_models == ["recommended-model"]
    assert profile.model_source == "recommended"
    assert profile.default_model == "stale-live-model"

    models, source, fetched = resolve_model_catalog([], [], "ccswitch_history")
    replace_model_catalog(profile, models, source)
    assert (models, source, fetched) == ([], "none", 0)
    assert profile.available_models == []
    assert profile.model_source == "none"


def test_runtime_restore_rejects_legacy_unverified_models_for_app_and_evals():
    saved = ProviderProfile(
        id="deepseek",
        preset_id="deepseek",
        display_name="Old DeepSeek",
        provider_type=ProviderType.COMPATIBLE,
        default_model="deepseek-v4-pro",
        available_models=["deepseek-v4-pro"],
        model_source="recommended",
    )
    profiles = restore_provider_profiles([saved])
    assert profiles["deepseek"].default_model == "deepseek-chat"
    assert "deepseek-v4-pro" not in profiles["deepseek"].available_models

    invalid = AgentAssignmentsConfig(
        seats=[AgentModelAssignment(role=role, provider_id="deepseek", model="deepseek-v4-pro") for role in ["analyst", "challenger", "builder", "observer"]],
        finalizer=AgentModelAssignment(role="finalizer", provider_id="deepseek", model="deepseek-v4-pro"),
    )
    assert assignment_config_is_valid(invalid, profiles) is False


def test_runtime_restore_preserves_ccswitch_models_verified_by_success_history():
    saved = ProviderProfile(
        id="ccswitch",
        preset_id="ccswitch",
        display_name="CC Switch",
        provider_type=ProviderType.CCSWITCH,
        default_model="gpt-5.6-sol",
        available_models=["gpt-5.6-sol", "deepseek-v4-pro"],
        model_source="ccswitch_history",
    )

    profiles = restore_provider_profiles([saved])

    assert profiles["ccswitch"].default_model == "gpt-5.6-sol"
    assert profiles["ccswitch"].available_models == ["gpt-5.6-sol", "deepseek-v4-pro"]
    assert profiles["ccswitch"].model_source == "ccswitch_history"

    valid = AgentAssignmentsConfig(
        seats=[AgentModelAssignment(role=role, provider_id="ccswitch", model="gpt-5.6-sol") for role in ["analyst", "challenger", "builder", "observer"]],
        finalizer=AgentModelAssignment(role="finalizer", provider_id="ccswitch", model="deepseek-v4-pro"),
    )
    assert assignment_config_is_valid(valid, profiles) is True

    valid.seats[0].model = "deepseek-v4-flash"
    assert assignment_config_is_valid(valid, profiles) is False


def test_ccswitch_model_discovery_uses_recent_successful_requests(tmp_path):
    db_path = tmp_path / "cc-switch.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """CREATE TABLE proxy_request_logs (
            request_model TEXT, model TEXT, app_type TEXT, status_code INTEGER, created_at INTEGER
        )"""
    )
    connection.executemany(
        "INSERT INTO proxy_request_logs VALUES (?, ?, ?, ?, ?)",
        [
            ("gpt-new", "gpt-new", "codex", 200, 30),
            ("gpt-old", "gpt-old", "codex", 200, 10),
            ("gpt-failed", "gpt-failed", "codex", 500, 40),
            ("claude-model", "claude-model", "claude", 200, 50),
        ],
    )
    connection.commit()
    connection.close()

    assert discover_ccswitch_models(db_path) == ["gpt-new", "gpt-old"]


def test_responses_payload_uses_highest_reasoning_effort():
    payload = build_responses_payload("ping", "system", "test-reasoning-model", "ultra")
    assert payload["reasoning"] == {"effort": "ultra"}
    assert "temperature" not in payload


def test_extract_responses_text_skips_reasoning_items():
    payload = {
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": "FULL_FLOW_OK"}]},
        ]
    }
    assert extract_responses_text(payload) == "FULL_FLOW_OK"


def test_timeout_error_has_actionable_message():
    assert "超过 120 秒" in describe_run_error(asyncio.TimeoutError(), 120)
    assert "重试当前席位" in describe_run_error(asyncio.TimeoutError(), 120)


def test_context_window_compacts_long_discussion_and_preserves_latest_user_input():
    turns = [
        DiscussionTurn(
            id=f"turn-{index}",
            speaker_type="user" if index == 27 else "agent",
            speaker_id="user" if index == 27 else f"agent-{index % 4}",
            speaker_name="你" if index == 27 else f"成员{index % 4}",
            content=("这是一段需要被上下文预算管理的较长讨论内容。" * 18) + f" 编号 {index}",
        )
        for index in range(30)
    ]
    window = build_context_window("如何做出可靠决策？", turns, token_budget=420)

    assert window.compacted
    assert window.total_turns == 30
    assert window.included_turns < window.total_turns
    assert "编号 27" in window.prompt
    assert "较早发言摘录（确定性裁剪）" in window.prompt
    assert estimate_tokens(window.prompt) <= window.token_budget


def test_context_with_long_evidence_never_truncates_latest_user_input_from_tail():
    marker = "LATEST_USER_TAIL_MARKER"
    turns = [
        DiscussionTurn(
            id=f"turn-{index}",
            speaker_type="user" if index == 8 else "agent",
            speaker_id="user" if index == 8 else f"agent-{index}",
            speaker_name="你" if index == 8 else f"成员{index}",
            content=(("用户补充" * 80) + marker) if index == 8 else ("历史观点" * 120),
        )
        for index in range(10)
    ]
    window = build_context_window(
        "原始问题也必须保留",
        turns,
        token_budget=420,
        evidence_context="[S1] 超长资料\n" + ("证据正文" * 1000),
        project_history="历史结论" * 800,
    )

    assert "原始问题也必须保留" in window.prompt
    assert marker in window.prompt
    assert estimate_tokens(window.prompt) <= window.token_budget


def test_token_estimator_selection_reports_accuracy_truthfully():
    exact = token_estimator_for("openai", "gpt-4o")
    compatible = token_estimator_for("openai", "future-openai-model")
    conservative = token_estimator_for("deepseek", "deepseek-chat")

    assert exact.name == "tiktoken:o200k_base"
    assert exact.exact is True
    assert compatible.name == "tiktoken:o200k_base_compatible"
    assert compatible.exact is False
    assert compatible.count("mixed 中文 JSON 🚀" * 10) > exact.count("mixed 中文 JSON 🚀" * 10)
    assert conservative.name == "conservative_utf8"
    assert conservative.exact is False


def test_token_estimator_degrades_when_tiktoken_registry_is_unavailable(monkeypatch):
    monkeypatch.setattr("app.context.tiktoken.encoding_for_model", lambda _: (_ for _ in ()).throw(ValueError("no plugin")))
    estimator = token_estimator_for("openai", "gpt-4o")

    assert estimator.name == "conservative_utf8"
    assert estimator.exact is False


def test_token_truncation_obeys_even_tiny_budgets():
    text = "mixed 中文 JSON 🚀 LATEST"
    for estimator in (
        token_estimator_for("openai", "gpt-4o"),
        token_estimator_for("deepseek", "deepseek-chat"),
    ):
        for limit in range(16):
            assert estimator.count(_truncate_tokens(text, limit, estimator)) <= limit
            assert estimator.count(_truncate_tokens_with_tail(text, limit, estimator)) <= limit


@pytest.mark.parametrize(
    "content",
    [
        "中英文 mixed context 需要稳定裁剪。" * 80,
        "def solve(value: int) -> dict:\n    return {'result': value * 2}\n" * 60,
        '{"event":"council.run","ok":true,"items":[1,2,3,4]}\n' * 70,
        "https://example.com/api/v1/runs?include=turns%2Csources&limit=100\n" * 60,
        "状态 ✅ 🚀 👨‍💻 🧪 ⚠️" * 100,
    ],
)
@pytest.mark.parametrize(
    "estimator",
    [
        pytest.param(token_estimator_for("openai", "gpt-4o"), id="openai-exact"),
        pytest.param(token_estimator_for("deepseek", "deepseek-chat"), id="provider-conservative"),
    ],
)
def test_context_never_exceeds_selected_estimator_budget(content, estimator):
    marker = "LATEST_USER_TAIL_MARKER"
    turns = [
        DiscussionTurn(
            id="agent-1",
            speaker_type="agent",
            speaker_id="analyst",
            speaker_name="分析者",
            content=content,
        ),
        DiscussionTurn(
            id="user-1",
            speaker_type="user",
            speaker_id="user",
            speaker_name="你",
            content=content + marker,
        ),
    ]

    window = build_context_window(
        content,
        turns,
        token_budget=420,
        evidence_context="[S1] " + content,
        project_history=content,
        estimator=estimator,
    )

    assert marker in window.prompt
    assert window.estimated_tokens == estimator.count(window.prompt)
    assert window.estimated_tokens <= window.token_budget
    assert window.token_estimator == estimator.name
    assert window.token_estimator_exact is estimator.exact


def test_context_budget_regression_corpus_covers_100_mixed_samples():
    components = [
        "Council 需要保留最新问题和关键结论。",
        "```python\nresult = {'ok': True, 'value': 42}\n```",
        '{"type":"run.updated","sequence":17,"active":true}',
        "https://example.com/docs?q=context%20window&lang=zh-CN",
        "✅ 🚀 👨‍💻 🧪 ⚠️",
    ]
    estimators = [
        token_estimator_for("openai", "gpt-4o"),
        token_estimator_for("deepseek", "deepseek-chat"),
    ]

    for index in range(100):
        rotated = components[index % len(components) :] + components[: index % len(components)]
        sample = f"case-{index:03d}\n" + "\n".join(
            value * (2 + ((index + offset) % 5)) for offset, value in enumerate(rotated)
        )
        estimator = estimators[index % len(estimators)]
        marker = f"LATEST-{index:03d}"
        turns = [
            DiscussionTurn(
                id=f"agent-{index}",
                speaker_type="agent",
                speaker_id="analyst",
                speaker_name="分析者",
                content=sample * 3,
            ),
            DiscussionTurn(
                id=f"user-{index}",
                speaker_type="user",
                speaker_id="user",
                speaker_name="你",
                content=sample * 3 + marker,
            ),
        ]

        window = build_context_window(sample, turns, token_budget=520, estimator=estimator)

        assert marker in window.prompt
        assert estimator.count(window.prompt) <= window.token_budget


def test_context_budget_scales_with_mode():
    assert context_budget_for_mode("quick") < context_budget_for_mode("standard") < context_budget_for_mode("rigorous")


@pytest.mark.parametrize(
    ("mode", "expected_effort"),
    [("quick", "low"), ("standard", "high"), ("rigorous", "ultra")],
)
def test_run_mode_selects_actual_reasoning_effort(mode, expected_effort):
    assert reasoning_effort_for_mode(mode) == expected_effort


async def test_standard_run_builds_backend_with_high_effort(tmp_path, monkeypatch):
    captured_efforts = []

    class ImmediateBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            return Generation(text="最终答案" if "记录员" in system else "席位发言")

    def capture_backend(profile):
        captured_efforts.append(profile.reasoning_effort)
        return ImmediateBackend()

    monkeypatch.setattr("app.orchestrator.build_backend", capture_backend)
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="ccswitch", display_name="CC Switch", provider_type=ProviderType.CCSWITCH, reasoning_effort="ultra")
    orchestrator = Orchestrator(store, {"ccswitch": profile})

    run = await orchestrator.start(RunCreate(question="验证圆桌档位", mode="standard", provider_id="ccswitch"))
    for _ in range(100):
        current = await store.get_run(run.id)
        if current and current.status == "awaiting_final_input":
            break
        await asyncio.sleep(0.02)

    assert current is not None
    assert current.reasoning_effort == "high"
    assert captured_efforts == ["high"] * 4


async def test_four_agents_debate_in_order_user_can_interject_and_confirm_final(tmp_path, monkeypatch):
    class ControlledBackend:
        def __init__(self):
            self.calls = 0
            self.first_started = asyncio.Event()
            self.release_first = asyncio.Event()
            self.prompts = []
            self.systems = []

        async def generate(self, prompt, system, model, temperature=0.2):
            self.calls += 1
            self.prompts.append(prompt)
            self.systems.append(system)
            if self.calls == 1:
                self.first_started.set()
                await self.release_first.wait()
            if self.calls <= 4:
                return Generation(text=f"第{self.calls}席：认同或反驳前文后给出观点")
            return Generation(text="自动形成的最终答案")

    backend = ControlledBackend()
    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: backend)
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})

    run = await orchestrator.start(RunCreate(question="请让四席依次辩论", provider_id="mock"))
    await asyncio.wait_for(backend.first_started.wait(), timeout=1)
    interjected = await orchestrator.interject(run.id, DiscussionAction(action="interject", message="我的中途观点"))
    assert interjected is not None
    backend.release_first.set()

    for _ in range(100):
        current = await store.get_run(run.id)
        if current and current.status == "awaiting_final_input":
            break
        await asyncio.sleep(0.02)

    assert current is not None
    assert current.status == "awaiting_final_input"
    assert current.workflow_engine == "langgraph"
    assert current.checkpoint_count >= 4
    assert current.context_snapshot.total_turns >= 3
    assert current.context_snapshot.estimated_tokens <= current.context_snapshot.token_budget
    with sqlite3.connect(store.checkpoint_path) as checkpoint_conn:
        persisted_checkpoints = checkpoint_conn.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id=?", (current.id,)
        ).fetchone()[0]
    assert persisted_checkpoints == current.checkpoint_count
    assert [turn.speaker_name for turn in current.discussion_turns] == ["你", "析理", "诘问", "构策", "观澜"]
    assert current.final_decision is None
    assert "我的中途观点" in backend.prompts[1]
    assert "明确表态" in backend.systems[1]
    assert "认同" in backend.systems[1]
    assert "反驳" in backend.systems[1]
    final_input = await orchestrator.interject(run.id, DiscussionAction(action="interject", message="最终补充条件"))
    assert final_input is not None
    await orchestrator.summarize(run.id)
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)
    assert current is not None and current.status == "completed"
    assert current.final_decision is not None
    assert current.final_decision.final_answer == "自动形成的最终答案"
    brief = await store.get_decision_brief(run.id)
    assert brief is not None and brief.recommendation == "自动形成的最终答案"
    assert "最终补充条件" in backend.prompts[-1]
    assert "score" not in current.final_decision.confidence
    events = [event.type for event in await store.list_events(run.id)]
    assert events.count("agent_turn_completed") == 4
    assert events.index("decision_brief_generated") < events.index("final_completed")
    assert events.index("final_completed") > max(index for index, event in enumerate(events) if event == "agent_turn_completed")


async def test_failed_run_can_resume_from_current_speaker(tmp_path, monkeypatch):
    class FlakyBackend:
        def __init__(self):
            self.calls = 0
            self.fail_second = True

        async def generate(self, prompt, system, model, temperature=0.2):
            self.calls += 1
            if self.calls == 2 and self.fail_second:
                raise asyncio.TimeoutError
            return Generation(text="最终答案" if "记录员" in system else f"第{self.calls}席发言")

    backend = FlakyBackend()
    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: backend)
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})

    run = await orchestrator.start(RunCreate(question="测试失败后续跑", provider_id="mock"))
    for _ in range(100):
        current = await store.get_run(run.id)
        if current and current.status == "failed":
            break
        await asyncio.sleep(0.02)

    assert current is not None
    assert current.status == "failed"
    assert current.current_speaker_index == 1
    assert "当前席位等待上游超过 30 秒" in (current.error or "")

    backend.fail_second = False
    restarted_orchestrator = Orchestrator(store, {"mock": profile})
    resumed = await restarted_orchestrator.retry_turn(run.id)
    assert resumed is not None
    assert resumed.status == "running"
    for _ in range(100):
        current = await store.get_run(run.id)
        if current and current.status == "awaiting_final_input":
            break
        await asyncio.sleep(0.02)

    assert current is not None
    assert current.status == "awaiting_final_input"
    assert current.workflow_engine == "langgraph"
    assert current.checkpoint_count >= 5
    assert backend.calls == 5
    assert [turn.speaker_name for turn in current.discussion_turns] == ["析理", "诘问", "构策", "观澜"]
    await restarted_orchestrator.summarize(run.id)
    await restarted_orchestrator.tasks[run.id]
    current = await store.get_run(run.id)
    assert current is not None and current.status == "completed"
    assert backend.calls == 6
    assert current.final_decision is not None


async def test_deleting_run_removes_persisted_workflow_checkpoints(tmp_path, monkeypatch):
    class ImmediateBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            return Generation(text="最终答案" if "记录员" in system else "席位发言")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: ImmediateBackend())
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})
    run = await orchestrator.start(RunCreate(question="验证检查点清理", provider_id="mock"))

    for _ in range(100):
        current = await store.get_run(run.id)
        if current and current.status == "awaiting_final_input":
            break
        await asyncio.sleep(0.02)

    assert current is not None and current.checkpoint_count > 0
    assert await orchestrator.delete(run.id)
    with sqlite3.connect(store.checkpoint_path) as checkpoint_conn:
        remaining = checkpoint_conn.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id=?", (run.id,)
        ).fetchone()[0]
    assert remaining == 0


async def test_deleting_completed_run_waits_for_final_save(tmp_path, monkeypatch):
    class ImmediateBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            return Generation(text="最终答案" if "记录员" in system else "席位发言")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: ImmediateBackend())
    store = Store(tmp_path / "council.sqlite3")
    original_save = store.save_run
    later_completed_save_started = asyncio.Event()
    release_final_save = asyncio.Event()
    completed_saves = 0

    async def delayed_save(run):
        nonlocal completed_saves
        if run.status == "completed":
            completed_saves += 1
            if completed_saves == 2:
                later_completed_save_started.set()
                await release_final_save.wait()
        await original_save(run)

    monkeypatch.setattr(store, "save_run", delayed_save)
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})
    run = await orchestrator.start(RunCreate(question="验证删除写入竞态", provider_id="mock"))

    for _ in range(100):
        current = await store.get_run(run.id)
        if current and current.status == "awaiting_final_input":
            break
        await asyncio.sleep(0.02)
    await orchestrator.summarize(run.id)

    await asyncio.wait_for(later_completed_save_started.wait(), timeout=2)
    deletion = asyncio.create_task(orchestrator.delete(run.id))
    await asyncio.sleep(0)
    assert not deletion.done()

    release_final_save.set()
    assert await asyncio.wait_for(deletion, timeout=2)
    assert await store.get_run(run.id) is None


async def test_ccswitch_timeout_downgrades_reasoning_and_completes(tmp_path, monkeypatch):
    calls: list[str] = []

    class EffortBackend:
        def __init__(self, effort: str):
            self.effort = effort

        async def generate(self, prompt, system, model, temperature=0.2):
            calls.append(self.effort)
            if self.effort in {"ultra", "high"}:
                raise asyncio.TimeoutError
            return Generation(text="最终答案" if "记录员" in system else "席位发言")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: EffortBackend(profile.reasoning_effort))
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="ccswitch", display_name="CC Switch", provider_type=ProviderType.CCSWITCH, capabilities=ProviderCapabilities(supports_reasoning_effort=True))
    orchestrator = Orchestrator(store, {"ccswitch": profile, "mock": profile})
    run = await orchestrator.start(RunCreate(question="验证自动降档", mode="rigorous", provider_id="ccswitch", limits=RunLimits(max_model_calls=10)))

    for _ in range(100):
        current = await store.get_run(run.id)
        if current and current.status in {"awaiting_final_input", "failed", "stopped"}:
            break
        await asyncio.sleep(0.02)

    await orchestrator.tasks[run.id]

    assert current is not None
    assert current.status == "awaiting_final_input"
    assert current.reasoning_effort == "low"
    assert current.degraded is True
    assert calls[:3] == ["ultra", "high", "low"]
    assert calls[3:] == ["low", "low", "low"]
    route_turns = [turn for turn in current.discussion_turns if turn.speaker_type == "system"]
    assert [turn.content for turn in route_turns] == [
        "Ultra 原生推理档上游超时，已自动降为 High 档重试当前席位。",
        "High 原生推理档上游超时，已自动降为 Low 档重试当前席位。",
    ]


async def test_ccswitch_medium_timeout_downgrades_to_low(tmp_path, monkeypatch):
    calls: list[str] = []

    class EffortBackend:
        def __init__(self, effort: str):
            self.effort = effort

        async def generate(self, prompt, system, model, temperature=0.2):
            calls.append(self.effort)
            if self.effort == "medium":
                raise asyncio.TimeoutError
            return Generation(text="席位发言")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: EffortBackend(profile.reasoning_effort))
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(
        id="ccswitch",
        display_name="CC Switch",
        provider_type=ProviderType.CCSWITCH,
        reasoning_effort="medium",
        capabilities=ProviderCapabilities(supports_reasoning_effort=True),
    )
    orchestrator = Orchestrator(store, {"ccswitch": profile})
    run = await orchestrator.start(
        RunCreate(
            question="验证 Medium 超时降档",
            provider_id="ccswitch",
            assignment_config=AgentAssignmentsConfig(
                seats=[
                    AgentModelAssignment(
                        role=role,
                        provider_id="ccswitch",
                        model="test-model",
                        reasoning_effort="medium",
                    )
                    for role in ("analyst", "challenger", "builder", "observer")
                ],
                finalizer=AgentModelAssignment(
                    role="finalizer",
                    provider_id="ccswitch",
                    model="test-model",
                    reasoning_effort="medium",
                ),
            ),
        )
    )
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)

    assert current is not None and current.status == "awaiting_final_input"
    assert current.degraded is True
    assert current.reasoning_effort == "low"
    assert calls[:2] == ["medium", "low"]
    route_turns = [turn for turn in current.discussion_turns if turn.speaker_type == "system"]
    assert route_turns[0].content == "Medium 原生推理档上游超时，已自动降为 Low 档重试当前席位。"


async def test_ccswitch_fallbacks_share_one_seat_timeout(tmp_path, monkeypatch):
    calls: list[str] = []

    class SlowTimeoutBackend:
        def __init__(self, effort: str):
            self.effort = effort

        async def generate(self, prompt, system, model, temperature=0.2):
            calls.append(self.effort)
            await asyncio.sleep(0.55)
            raise asyncio.TimeoutError

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: SlowTimeoutBackend(profile.reasoning_effort))
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(
        id="ccswitch",
        display_name="CC Switch",
        provider_type=ProviderType.CCSWITCH,
        capabilities=ProviderCapabilities(supports_reasoning_effort=True),
    )
    orchestrator = Orchestrator(store, {"ccswitch": profile})

    started = time.perf_counter()
    run = await orchestrator.start(
        RunCreate(
            question="验证降档共享单席时限",
            mode="rigorous",
            provider_id="ccswitch",
            limits=RunLimits(timeout_seconds=1),
        )
    )
    await orchestrator.tasks[run.id]
    elapsed = time.perf_counter() - started
    current = await store.get_run(run.id)

    assert elapsed < 1.35
    assert calls == ["ultra", "high"]
    assert current is not None and current.status == "failed"
    assert "超过 1 秒" in (current.error or "")


async def test_ccswitch_wrapped_upstream_400_downgrades_reasoning(tmp_path, monkeypatch):
    calls: list[str] = []

    class WrappedUpstreamResponse:
        status_code = 400

        @staticmethod
        def json():
            return {"error": {"code": "cc_switch_upstream_error", "provider": "Sub2API-0.04"}}

    class WrappedUpstreamError(Exception):
        response = WrappedUpstreamResponse()

    class EffortBackend:
        def __init__(self, effort: str):
            self.effort = effort

        async def generate(self, prompt, system, model, temperature=0.2):
            calls.append(self.effort)
            if self.effort == "ultra":
                raise WrappedUpstreamError("CC Switch upstream HTTP 400")
            return Generation(text="最终答案" if "记录员" in system else "席位发言")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: EffortBackend(profile.reasoning_effort))
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="ccswitch", display_name="CC Switch", provider_type=ProviderType.CCSWITCH, capabilities=ProviderCapabilities(supports_reasoning_effort=True))
    orchestrator = Orchestrator(store, {"ccswitch": profile, "mock": profile})
    run = await orchestrator.start(RunCreate(question="验证上游兼容性错误降档", mode="rigorous", provider_id="ccswitch", limits=RunLimits(max_model_calls=10)))

    for _ in range(100):
        current = await store.get_run(run.id)
        if current and current.status in {"awaiting_final_input", "failed", "stopped"}:
            break
        await asyncio.sleep(0.02)

    await orchestrator.tasks[run.id]

    assert current is not None
    assert current.status == "awaiting_final_input"
    assert current.reasoning_effort == "high"
    assert current.degraded is True
    assert calls == ["ultra", "high", "high", "high", "high"]
    route_turns = [turn for turn in current.discussion_turns if turn.speaker_type == "system"]
    assert [turn.content for turn in route_turns] == [
        "Ultra 原生推理档上游暂不可用，已自动降为 High 档重试当前席位。",
    ]


def test_chat_compatible_responses_payload_does_not_claim_native_effort():
    payload = build_responses_payload("ping", "system", "compatible-model", None)
    assert "reasoning" not in payload


def test_provider_dns_resolution_blocks_metadata_alias_and_allows_local_custom(monkeypatch):
    def fake_getaddrinfo(host, port, type=0):
        if host == "alias.example":
            return [(2, 1, 6, "", ("169.254.169.254", port))]
        if host == "local-provider.test":
            return [(2, 1, 6, "", ("127.0.0.1", port))]
        raise AssertionError(host)

    monkeypatch.setattr("app.providers.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="metadata|link-local"):
        validate_base_url("http://alias.example/v1")
    with pytest.raises(ValueError, match="云元数据"):
        validate_base_url("http://METADATA.GOOGLE.INTERNAL./computeMetadata/v1")
    validate_base_url("http://local-provider.test/v1", local_only=False)


async def test_model_call_limit_stops_before_third_provider_request(tmp_path, monkeypatch):
    calls = 0

    class CountingBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            nonlocal calls
            calls += 1
            return Generation(text=f"发言 {calls}", input_tokens=10, output_tokens=10)

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: CountingBackend())
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})
    run = await orchestrator.start(RunCreate(question="验证调用上限", provider_id="mock", limits=RunLimits(max_model_calls=2)))
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)

    assert current is not None
    assert current.status == "stopped"
    assert current.limit_reason == "max_model_calls"
    assert current.current_speaker_index == 2
    assert calls == 2


async def test_token_limit_stops_before_next_provider_request(tmp_path, monkeypatch):
    calls = 0

    class TokenBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            nonlocal calls
            calls += 1
            return Generation(text="高 Token 发言", input_tokens=100, output_tokens=50)

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: TokenBackend())
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})
    run = await orchestrator.start(RunCreate(question="验证 Token 上限", provider_id="mock", limits=RunLimits(max_tokens=128)))
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)

    assert current is not None
    assert current.status == "stopped"
    assert current.limit_reason == "max_tokens"
    assert current.current_speaker_index == 1
    assert calls == 1


async def test_default_token_limit_covers_five_council_calls_with_codex_overhead(tmp_path, monkeypatch):
    calls = 0

    class CodexSizedBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            nonlocal calls
            calls += 1
            return Generation(
                text="最终答案" if "记录员" in system else f"第{calls}席发言",
                input_tokens=5000,
                output_tokens=250,
            )

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: CodexSizedBackend())
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="ccswitch", display_name="CC Switch", provider_type=ProviderType.CCSWITCH)
    orchestrator = Orchestrator(store, {"ccswitch": profile})
    run = await orchestrator.start(RunCreate(question="验证 Codex 固定指令开销", provider_id="ccswitch"))
    await orchestrator.tasks[run.id]

    current = await store.get_run(run.id)
    assert current is not None and current.status == "awaiting_final_input"
    await orchestrator.summarize(run.id)
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)

    assert current is not None and current.status == "completed"
    assert current.limits.max_tokens == 40000
    assert current.usage.input_tokens + current.usage.output_tokens == 26250
    assert calls == 5


async def test_token_limited_run_can_raise_limit_and_resume_without_repeating_turns(tmp_path, monkeypatch):
    calls = 0

    class CodexSizedBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            nonlocal calls
            calls += 1
            return Generation(text=f"第{calls}席发言", input_tokens=5000, output_tokens=200)

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: CodexSizedBackend())
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="ccswitch", display_name="CC Switch", provider_type=ProviderType.CCSWITCH)
    orchestrator = Orchestrator(store, {"ccswitch": profile})
    run = await orchestrator.start(
        RunCreate(question="验证提额续跑", provider_id="ccswitch", limits=RunLimits(max_tokens=12000))
    )
    await orchestrator.tasks[run.id]

    stopped = await store.get_run(run.id)
    assert stopped is not None and stopped.status == "stopped"
    assert stopped.current_speaker_index == 3
    assert calls == 3

    with pytest.raises(ValueError, match="必须高于当前累计用量"):
        await orchestrator.resume_with_limits(
            run.id,
            RunLimits(max_model_calls=8, max_tokens=15000, timeout_seconds=120),
        )

    resumed = await orchestrator.resume_with_limits(
        run.id,
        RunLimits(max_model_calls=8, max_tokens=40000, timeout_seconds=120),
    )
    assert resumed is not None and resumed.status == "running"
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)

    assert current is not None and current.status == "awaiting_final_input"
    assert current.limit_reason is None
    assert [turn.speaker_name for turn in current.discussion_turns] == ["析理", "诘问", "构策", "观澜"]
    assert calls == 4
    event_types = [event.type for event in await store.list_events(run.id)]
    assert event_types.index("run_limit_reached") < len(event_types) - 1
    assert event_types[-1] == "awaiting_final_input"


async def test_limit_resume_keeps_recovery_state_when_credentials_are_missing(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(
        id="custom",
        display_name="Custom",
        provider_type=ProviderType.COMPATIBLE,
        base_url="https://example.com/v1",
        requires_api_key=True,
    )
    orchestrator = Orchestrator(store, {"custom": profile})
    run = RunRecord(
        id="limit-resume-missing-credential",
        question="验证续跑凭据检查",
        mode="standard",
        provider_id="custom",
        model="test-model",
        status="stopped",
        created_at=utc_now(),
        updated_at=utc_now(),
        limit_reason="max_tokens",
        error="已达到 Token 上限",
        limits=RunLimits(max_tokens=12000),
        usage=UsageSummary(input_tokens=13000, output_tokens=100),
    )
    orchestrator._ensure_run_assignments(run)
    await store.save_run(run)

    with pytest.raises(RuntimeError, match="API Key"):
        await orchestrator.resume_with_limits(run.id, RunLimits(max_tokens=40000))

    current = await store.get_run(run.id)
    assert current is not None
    assert current.status == "stopped"
    assert current.limit_reason == "max_tokens"
    assert current.error == "已达到 Token 上限"
    assert current.limits.max_tokens == 12000


async def test_run_timeout_applies_to_each_active_model_call(tmp_path, monkeypatch):
    class BlockingBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            await asyncio.sleep(2)
            return Generation(text="不应完成")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: BlockingBackend())
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})
    run = await orchestrator.start(RunCreate(question="验证完整运行超时", provider_id="mock", limits=RunLimits(timeout_seconds=1)))
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)

    assert current is not None
    assert current.status == "failed"
    assert current.recoverable is True
    assert "超过 1 秒" in (current.error or "")


async def test_stale_assignment_timeout_is_upgraded_before_finalizer(tmp_path, monkeypatch):
    backend_timeouts: list[float] = []

    class FinalizerBackend:
        def __init__(self, timeout_seconds: float):
            backend_timeouts.append(timeout_seconds)

        async def generate(self, prompt, system, model, temperature=0.2):
            return Generation(text="迁移旧时限后生成的最终答案" if "记录员" in system else "表态：认同。席位发言")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: FinalizerBackend(profile.timeout_seconds))
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK, timeout_seconds=120)
    assignments = Orchestrator(store, {"mock": profile}).default_assignment_config("mock", "council-mock", "standard")
    assignments.schema_version = 1
    for assignment in [*assignments.seats, assignments.finalizer]:
        assignment.timeout_seconds = 30

    orchestrator = Orchestrator(store, {"mock": profile})
    run = await orchestrator.start(
        RunCreate(
            question="验证旧席位时限迁移",
            provider_id="mock",
            assignment_config=assignments,
            limits=RunLimits(timeout_seconds=120),
        )
    )
    await orchestrator.tasks[run.id]
    assert run.finalizer_assignment is not None
    run.assignment_schema_version = 1
    for assignment in [*run.seat_assignments, run.finalizer_assignment]:
        assignment.timeout_seconds = 30
        assignment.provider_snapshot.timeout_seconds = 30
    await store.save_run(run)
    await orchestrator.summarize(run.id)
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)

    assert current is not None
    assert current.status == "completed"
    assert current.error is None
    assert current.final_decision is not None
    assert current.final_decision.final_answer == "迁移旧时限后生成的最终答案"
    assert backend_timeouts == [120, 120, 120, 120, 120]
    assert [assignment.timeout_seconds for assignment in current.seat_assignments] == [120, 120, 120, 120]
    assert current.finalizer_assignment is not None and current.finalizer_assignment.timeout_seconds == 120
    assert current.assignment_schema_version == 2

    profile.timeout_seconds = 180
    orchestrator._ensure_run_assignments(current)
    assert [assignment.timeout_seconds for assignment in current.seat_assignments] == [120, 120, 120, 120]
    assert current.finalizer_assignment.timeout_seconds == 120


async def test_explicit_assignment_timeout_overrides_provider_profile_timeout(tmp_path, monkeypatch):
    backend_timeouts: list[float] = []

    class CapturingBackend:
        def __init__(self, profile):
            backend_timeouts.append(profile.timeout_seconds)

        async def generate(self, prompt, system, model, temperature=0.2):
            return Generation(text="席位发言")

    monkeypatch.setattr("app.orchestrator.build_backend", CapturingBackend)
    store = Store(tmp_path / "assignment-timeout.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK, timeout_seconds=30)
    orchestrator = Orchestrator(store, {"mock": profile})
    assignments = orchestrator.default_assignment_config("mock", "council-mock", "standard")
    for item in [*assignments.seats, assignments.finalizer]:
        item.timeout_seconds = 120

    run = await orchestrator.start(
        RunCreate(
            question="验证显式席位时限",
            provider_id="mock",
            assignment_config=assignments,
            limits=RunLimits(timeout_seconds=120),
        )
    )
    await orchestrator.tasks[run.id]
    assert backend_timeouts == [120, 120, 120, 120]


async def test_explicit_v2_thirty_second_assignment_is_preserved(tmp_path):
    store = Store(tmp_path / "explicit-thirty.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK, timeout_seconds=120)
    orchestrator = Orchestrator(store, {"mock": profile})
    config = orchestrator.default_assignment_config("mock", "council-mock", "standard")
    for assignment in [*config.seats, config.finalizer]:
        assignment.timeout_seconds = 30

    normalized = orchestrator.normalize_assignment_config(config)

    assert normalized.schema_version == 2
    assert [assignment.timeout_seconds for assignment in normalized.seats] == [30, 30, 30, 30]
    assert normalized.finalizer.timeout_seconds == 30


async def test_missing_legacy_finalizer_preserves_historical_seat_snapshots(tmp_path):
    store = Store(tmp_path / "missing-finalizer.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK, timeout_seconds=120)
    orchestrator = Orchestrator(store, {"mock": profile})
    config = orchestrator.default_assignment_config("mock", "council-mock", "standard")
    seats, _ = orchestrator._resolve_config(RunCreate(question="构造历史席位", assignment_config=config))
    seats[0].model = "historical-model"
    seats[0].provider_snapshot.default_model = "historical-model"
    run = RunRecord(
        id="missing-finalizer",
        question="只补总结席",
        mode="standard",
        provider_id="mock",
        model="council-mock",
        status="awaiting_final_input",
        created_at=utc_now(),
        updated_at=utc_now(),
        seat_assignments=seats,
        finalizer_assignment=None,
    )

    orchestrator._ensure_run_assignments(run)

    assert run.assignment_schema_version == 2
    assert run.seat_assignments[0].model == "historical-model"
    assert run.seat_assignments[0].provider_snapshot.default_model == "historical-model"
    assert run.finalizer_assignment is not None
    assert run.finalizer_assignment.model == "council-mock"


async def test_failed_finalizer_retry_clears_error_without_duplicate_turns(tmp_path, monkeypatch):
    finalizer_calls = 0

    class FlakyFinalizerBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            nonlocal finalizer_calls
            if "记录员" in system:
                finalizer_calls += 1
                if finalizer_calls == 1:
                    await asyncio.sleep(1.1)
                return Generation(text="重试后的最终答案")
            return Generation(text="表态：认同。席位发言")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: FlakyFinalizerBackend())
    store = Store(tmp_path / "retry-finalizer.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK, timeout_seconds=1)
    orchestrator = Orchestrator(store, {"mock": profile})
    run = await orchestrator.start(RunCreate(question="验证最终答案重试", provider_id="mock"))
    await orchestrator.tasks[run.id]

    await orchestrator.summarize(run.id)
    await orchestrator.tasks[run.id]
    failed = await store.get_run(run.id)
    assert failed is not None and failed.status == "awaiting_final_input"
    assert "超过 1 秒" in (failed.error or "")
    assert len([turn for turn in failed.discussion_turns if turn.speaker_type == "agent"]) == 4

    await orchestrator.summarize(run.id)
    await orchestrator.tasks[run.id]
    completed = await store.get_run(run.id)

    assert completed is not None and completed.status == "completed"
    assert completed.error is None
    assert completed.final_decision is not None
    assert completed.final_decision.final_answer == "重试后的最终答案"
    assert finalizer_calls == 2
    assert completed.usage.model_calls == 6
    assert len([turn for turn in completed.discussion_turns if turn.speaker_type == "agent"]) == 4


async def test_total_debate_duration_may_exceed_per_seat_timeout(tmp_path, monkeypatch):
    class SlowButHealthyBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            await asyncio.sleep(0.3)
            return Generation(text="表态：认同。席位在单次时限内完成")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: SlowButHealthyBackend())
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})

    started = time.perf_counter()
    run = await orchestrator.start(
        RunCreate(question="验证整桌没有总倒计时", provider_id="mock", limits=RunLimits(timeout_seconds=1))
    )
    await orchestrator.tasks[run.id]
    elapsed = time.perf_counter() - started
    current = await store.get_run(run.id)

    assert elapsed > 1
    assert current is not None
    assert current.status == "awaiting_final_input"
    assert current.error is None
    assert len([turn for turn in current.discussion_turns if turn.speaker_type == "agent"]) == 4


async def test_backends_close_after_completed_failed_and_cancelled_paths(tmp_path, monkeypatch):
    closed = 0
    blockers: list[asyncio.Event] = []
    mode = "complete"

    class CloseTrackingBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            if mode == "fail":
                raise RuntimeError("provider failed")
            if mode == "block":
                event = asyncio.Event()
                blockers.append(event)
                await event.wait()
            return Generation(text="表态：认同。席位发言")

        async def aclose(self):
            nonlocal closed
            closed += 1

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: CloseTrackingBackend())
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)

    complete_store = Store(tmp_path / "complete.sqlite3")
    complete = Orchestrator(complete_store, {"mock": profile})
    run = await complete.start(RunCreate(question="完成关闭", provider_id="mock"))
    await complete.tasks[run.id]
    assert closed == 4
    await complete.summarize(run.id)
    await complete.tasks[run.id]
    assert closed == 5

    mode = "fail"
    failed_store = Store(tmp_path / "failed.sqlite3")
    failed = Orchestrator(failed_store, {"mock": profile})
    failed_run = await failed.start(RunCreate(question="失败关闭", provider_id="mock"))
    await failed.tasks[failed_run.id]
    assert closed == 6

    mode = "block"
    cancelled_store = Store(tmp_path / "cancelled.sqlite3")
    cancelled = Orchestrator(cancelled_store, {"mock": profile})
    cancelled_run = await cancelled.start(RunCreate(question="取消关闭", provider_id="mock"))
    for _ in range(100):
        if blockers:
            break
        await asyncio.sleep(0.01)
    await cancelled.cancel(cancelled_run.id)
    await cancelled.tasks[cancelled_run.id]
    assert closed == 7


async def test_startup_recovery_skips_business_turn_ahead_of_checkpoint(tmp_path, monkeypatch):
    class FlakyBackend:
        def __init__(self):
            self.calls = 0

        async def generate(self, prompt, system, model, temperature=0.2):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("crash after first checkpoint")
            return Generation(text=f"表态：认同。调用 {self.calls}")

    backend = FlakyBackend()
    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: backend)
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    first = Orchestrator(store, {"mock": profile})
    run = await first.start(RunCreate(question="验证业务库领先 checkpoint", provider_id="mock"))
    await first.tasks[run.id]
    current = await store.get_run(run.id)
    assert current is not None and current.status == "failed" and current.current_speaker_index == 1

    current.discussion_turns.append(DiscussionTurn(id="business-second", speaker_type="agent", speaker_id="challenger", speaker_name="诘问", role_label="挑战者", content="表态：认同。业务库已完整写入第二席", provider_id="mock", provider_name="Mock", model="council-mock"))
    current.candidates.append(CandidateAnswer(candidate_id="candidate-challenger", answer="业务库已完整写入第二席", model="council-mock", provider="Mock", usage=UsageSummary(model_calls=1)))
    current.current_speaker_index = 2
    current.status = "running"
    await store.save_run(current)

    restarted = Orchestrator(store, {"mock": profile})
    recovered = await restarted.recover_incomplete_runs()
    assert recovered == [run.id]
    await restarted.tasks[run.id]
    current = await store.get_run(run.id)
    assert current is not None and current.status == "awaiting_final_input"
    assert backend.calls == 4
    assert [turn.speaker_id for turn in current.discussion_turns if turn.speaker_type == "agent"].count("challenger") == 1


async def test_startup_recovery_without_checkpoint_becomes_recoverable_failure(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    now = utc_now()
    run = RunRecord(id="missing-checkpoint", question="缺少 checkpoint", mode="standard", provider_id="mock", model="council-mock", status="running", created_at=now, updated_at=now)
    await store.save_run(run)
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})

    assert await orchestrator.recover_incomplete_runs() == []
    current = await store.get_run(run.id)
    assert current is not None
    assert current.status == "failed"
    assert current.recoverable is True
    assert "checkpoint" in (current.error or "")


async def test_startup_recovery_missing_credential_never_falls_back_to_mock(tmp_path, monkeypatch):
    class ImmediateBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            return Generation(text="表态：认同。席位发言")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: ImmediateBackend())
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    first = Orchestrator(store, {"mock": profile})
    run = await first.start(RunCreate(question="凭据恢复", provider_id="mock"))
    await first.tasks[run.id]
    current = await store.get_run(run.id)
    assert current is not None and current.finalizer_assignment
    current.status = "running"
    current.finalizer_assignment.provider_name = "需要密钥的 Provider"
    current.finalizer_assignment.provider_snapshot.requires_api_key = True
    current.finalizer_assignment.provider_snapshot.credential_saved = False
    current.finalizer_assignment.provider_snapshot.api_key_reference = None
    await store.save_run(current)

    restarted = Orchestrator(store, {"mock": profile})
    assert await restarted.recover_incomplete_runs() == []
    current = await store.get_run(run.id)
    assert current is not None and current.status == "failed"
    assert "凭据缺失" in (current.error or "")
    assert "未回退到 Mock" in (current.error or "")


async def test_assignment_settings_persist_across_store_restart(tmp_path):
    path = tmp_path / "council.sqlite3"
    store = Store(path)
    config = AgentAssignmentsConfig(
        seats=[AgentModelAssignment(role=role, provider_id="mock", model=f"model-{role}") for role in ["analyst", "challenger", "builder", "observer"]],
        finalizer=AgentModelAssignment(role="finalizer", provider_id="mock", model="model-final"),
    )
    await store.save_assignment_config(config)
    store.close()

    reopened = Store(path)
    assert reopened.load_assignment_config() == config


async def test_legacy_assignment_settings_load_as_v1_and_migrate_once(tmp_path):
    path = tmp_path / "legacy-assignments.sqlite3"
    store = Store(path)
    config = AgentAssignmentsConfig(
        seats=[AgentModelAssignment(role=role, provider_id="mock", model=f"model-{role}") for role in ["analyst", "challenger", "builder", "observer"]],
        finalizer=AgentModelAssignment(role="finalizer", provider_id="mock", model="model-final"),
    )
    legacy_payload = config.model_dump(mode="json", exclude={"schema_version"})
    store.conn.execute(
        "INSERT OR REPLACE INTO app_settings(key,payload) VALUES('agent_assignments',?)",
        (json.dumps(legacy_payload),),
    )
    store.conn.commit()

    loaded = store.load_assignment_config()
    assert loaded is not None and loaded.schema_version == 1
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK, timeout_seconds=120)
    normalized = Orchestrator(store, {"mock": profile}).normalize_assignment_config(loaded)

    assert normalized.schema_version == 2
    assert [assignment.timeout_seconds for assignment in normalized.seats] == [120, 120, 120, 120]
    assert normalized.finalizer.timeout_seconds == 120
    await store.save_assignment_config(normalized)
    store.close()

    reopened = Store(path)
    persisted = reopened.load_assignment_config()
    assert persisted is not None and persisted.schema_version == 2
    profile.timeout_seconds = 180
    stable = Orchestrator(reopened, {"mock": profile}).normalize_assignment_config(persisted)
    assert [assignment.timeout_seconds for assignment in stable.seats] == [120, 120, 120, 120]
    assert stable.finalizer.timeout_seconds == 120


def test_assignment_config_rejects_unsupported_future_schema():
    with pytest.raises(ValueError, match="schema_version"):
        AgentAssignmentsConfig(
            schema_version=999,
            seats=[AgentModelAssignment(role=role, provider_id="mock", model="council-mock") for role in ["analyst", "challenger", "builder", "observer"]],
            finalizer=AgentModelAssignment(role="finalizer", provider_id="mock", model="council-mock"),
        )


def test_run_create_treats_assignment_payload_without_schema_as_legacy():
    config = AgentAssignmentsConfig(
        seats=[AgentModelAssignment(role=role, provider_id="mock", model="council-mock") for role in ["analyst", "challenger", "builder", "observer"]],
        finalizer=AgentModelAssignment(role="finalizer", provider_id="mock", model="council-mock"),
    )

    request = RunCreate.model_validate(
        {
            "question": "旧客户端请求如何迁移？",
            "assignment_config": config.model_dump(mode="json", exclude={"schema_version"}),
        }
    )

    assert request.assignment_config is not None
    assert request.assignment_config.schema_version == 1


async def test_each_seat_and_finalizer_use_independent_persisted_snapshots(tmp_path, monkeypatch):
    calls: list[tuple[str, str, str]] = []

    class IdentifiedBackend:
        def __init__(self, provider_id: str):
            self.provider_id = provider_id

        async def generate(self, prompt, system, model, temperature=0.2):
            calls.append((self.provider_id, model, prompt))
            text = "第一席观点" if "第一位发言者" in system else "表态：认同。没有明确反驳"
            return Generation(text=text)

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: IdentifiedBackend(profile.id))
    store = Store(tmp_path / "council.sqlite3")
    providers = {
        "p1": ProviderProfile(id="p1", display_name="Provider One", provider_type=ProviderType.MOCK, default_model="one"),
        "p2": ProviderProfile(id="p2", display_name="Provider Two", provider_type=ProviderType.MOCK, default_model="two"),
    }
    config = AgentAssignmentsConfig(
        seats=[
            AgentModelAssignment(role="analyst", provider_id="p1", model="one-a"),
            AgentModelAssignment(role="challenger", provider_id="p2", model="two-b"),
            AgentModelAssignment(role="builder", provider_id="p1", model="one-c"),
            AgentModelAssignment(role="observer", provider_id="p2", model="two-d"),
        ],
        finalizer=AgentModelAssignment(role="finalizer", provider_id="p2", model="two-final"),
    )
    orchestrator = Orchestrator(store, providers)
    run = await orchestrator.start(RunCreate(question="验证独立席位", assignment_config=config))
    providers["p1"].display_name = "Changed Later"
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)
    assert current is not None and current.status == "awaiting_final_input"
    assert [(turn.provider_id, turn.model) for turn in current.discussion_turns if turn.speaker_type == "agent"] == [
        ("p1", "one-a"), ("p2", "two-b"), ("p1", "one-c"), ("p2", "two-d")
    ]
    assert current.seat_assignments[0].provider_name == "Provider One"
    await orchestrator.interject(run.id, DiscussionAction(action="interject", message="最终确认补充"))
    await orchestrator.summarize(run.id)
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)
    assert current is not None and current.status == "completed"
    assert calls[-1][0:2] == ("p2", "two-final")
    assert "最终确认补充" in calls[-1][2]
    assert current.final_decision is not None
    assert current.final_decision.disagreements == []
    assert current.final_decision.confidence["level"] == "unverified"
    assert "score" not in current.final_decision.confidence


def test_evidence_file_limits_hashing_and_text_extraction():
    raw = "标题\n一条可引用的事实".encode("utf-8")
    text, media_type = extract_file_text("notes.md", raw)
    assert text == "标题\n一条可引用的事实"
    assert media_type == "text/plain"
    assert content_hash(raw) == "624cb7a6a3bac5a51195ade8f43f71f274b1625c1fd544cdece47ae8aba056b4"

    from docx import Document

    document = Document()
    document.add_paragraph("DOCX 中的项目资料")
    buffer = io.BytesIO()
    document.save(buffer)
    docx_text, docx_media_type = extract_file_text("brief.docx", buffer.getvalue())
    assert "DOCX 中的项目资料" in docx_text
    assert "wordprocessingml" in docx_media_type

    with pytest.raises(ValueError, match="支持 TXT"):
        extract_file_text("payload.exe", b"not allowed")
    with pytest.raises(ValueError, match="10 MB"):
        extract_file_text("large.txt", b"x" * (10 * 1024 * 1024 + 1))


def test_web_evidence_rejects_private_and_dns_rebinding_targets(monkeypatch):
    for url in [
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "http://localhost:8000/",
    ]:
        with pytest.raises(ValueError, match="公开互联网|不能访问"):
            validate_public_url(url)

    monkeypatch.setattr(
        "app.evidence.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("10.20.30.40", 443))],
    )
    with pytest.raises(ValueError, match="内网"):
        validate_public_url("https://public-looking.example/source")


async def test_project_and_source_crud_is_scoped_and_counted(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    first = ProjectRecord(id="project-a", name="产品决策", description="长期上下文")
    second = ProjectRecord(id="project-b", name="风险审计")
    await store.save_project(first)
    await store.save_project(second)
    source = ProjectSource(
        id="source-a",
        project_id=first.id,
        kind="text",
        title="约束",
        content="预算不超过十万元",
        size_bytes=30,
        sha256="abc123",
    )
    await store.save_source(source)

    projects = {project.id: project for project in await store.list_projects()}
    assert projects[first.id].source_count == 1
    assert projects[second.id].source_count == 0
    assert await store.list_sources(second.id) == []
    assert await store.delete_source(second.id, source.id) is False
    assert await store.get_source(source.id) is not None
    assert await store.delete_project(first.id) is True
    assert await store.get_source(source.id) is None


async def test_run_freezes_sources_uses_citations_and_replays_deleted_material(tmp_path, monkeypatch):
    prompts: list[str] = []
    systems: list[str] = []

    class CaptureBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            prompts.append(prompt)
            systems.append(system)
            return Generation(text="表态：认同。根据 [S1]，应先验证预算约束。")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: CaptureBackend())
    store = Store(tmp_path / "council.sqlite3")
    project = ProjectRecord(id="project-a", name="迁移计划", instructions="先保护可回滚性")
    frozen_tail = "FULL_SNAPSHOT_TAIL"
    source_content = "本季度预算上限为十万元。" + ("完整附件正文" * 6000) + frozen_tail
    source = ProjectSource(
        id="source-a",
        project_id=project.id,
        kind="text",
        title="预算说明",
        content=source_content,
        size_bytes=39,
        sha256="snapshot-sha",
    )
    await store.save_project(project)
    await store.save_source(source)
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})

    run = await orchestrator.start(
        RunCreate(
            question="是否现在迁移？",
            provider_id="mock",
            project_id=project.id,
            source_ids=[source.id],
            template_id="research_synthesis",
        )
    )
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)
    assert current is not None and current.status == "awaiting_final_input"
    assert current.template_name == "资料研判"
    assert current.source_snapshots[0].content == source_content
    assert current.source_snapshots[0].content.endswith(frozen_tail)
    assert "[S1] 预算说明" in prompts[0]
    assert "资料本身尚未经过 Council 独立核验" in prompts[0]
    assert "禁止编造来源" in systems[0]

    await store.delete_source(project.id, source.id)
    replay = await orchestrator.start(
        RunCreate(
            question=current.question,
            provider_id="mock",
            project_id=current.project_id,
            template_id=current.template_id,
        ),
        frozen_sources=current.source_snapshots,
        frozen_project_name=current.project_name,
        frozen_project_context=current.project_context,
    )
    await orchestrator.tasks[replay.id]
    replayed = await store.get_run(replay.id)
    assert replayed is not None
    assert replayed.source_snapshots[0].sha256 == "snapshot-sha"
    assert replayed.project_name == "迁移计划"

    other = ProjectRecord(id="project-b", name="其他空间")
    await store.save_project(other)
    with pytest.raises(ValueError, match="不属于当前资料空间"):
        await orchestrator.start(
            RunCreate(
                question="跨项目引用",
                provider_id="mock",
                project_id=other.id,
                source_ids=["source-a"],
            )
        )


async def test_project_history_enters_context_and_reports_keep_sources(tmp_path, monkeypatch):
    class ImmediateBackend:
        async def generate(self, prompt, system, model, temperature=0.2):
            return Generation(text="表态：认同。继续验证历史结论。")

    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: ImmediateBackend())
    store = Store(tmp_path / "council.sqlite3")
    project = ProjectRecord(id="project-a", name="长期研究")
    await store.save_project(project)
    now = utc_now()
    previous = RunRecord(
        id="previous",
        question="上一轮的问题",
        mode="standard",
        provider_id="mock",
        model="council-mock",
        status="completed",
        created_at=now,
        updated_at=now,
        project_id=project.id,
        project_name=project.name,
        final_decision=FinalDecision(
            final_answer="上一轮的明确结论",
            confidence={"level": "unverified", "explanation": "测试"},
            provider_summary={"provider": "Mock"},
            usage=UsageSummary(),
        ),
    )
    await store.save_run(previous)
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})
    run = await orchestrator.start(
        RunCreate(question="根据历史继续判断", provider_id="mock", project_id=project.id)
    )
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)
    assert current is not None
    assert "上一轮的问题" in current.project_context
    assert "上一轮的明确结论" in current.project_context

    current.source_snapshots = [
        RunSourceSnapshot(
            id="source-1",
            kind="text",
            title="一手资料",
            content="事实正文",
            sha256="source-hash",
        )
    ]
    current.final_decision = FinalDecision(
        final_answer="最终答案引用 [S1]。",
        disagreements=["仍需验证一个条件"],
        confidence={"level": "source_grounded", "explanation": "测试"},
        provider_summary={"provider": "Mock"},
        usage=UsageSummary(),
    )
    current.decision_review = DecisionReview(
        selected_decision="先做小范围试点",
        expected_result="两周内验证关键假设",
        actual_result="关键假设得到部分支持",
        outcome_status="partial",
    )
    markdown = run_markdown(current)
    html = run_html(current)
    assert "[S1]" in markdown and "source-hash" in markdown
    assert "事实正文" in markdown
    assert "最终答案引用 [S1]" in markdown
    assert "[S1] 一手资料" in html and "最终答案引用 [S1]" in html
    assert "未经过外部事实核验" in markdown
    assert "未经过外部事实核验" in html
    assert "决策回访" in markdown and "两周内验证关键假设" in html


def test_source_snapshot_reads_legacy_excerpt_without_losing_content():
    snapshot = RunSourceSnapshot.model_validate({
        "id": "legacy",
        "kind": "text",
        "title": "旧快照",
        "excerpt": "旧版本保存的正文",
    })
    assert snapshot.content == "旧版本保存的正文"
    assert snapshot.model_dump()["content"] == "旧版本保存的正文"


def test_benchmark_dataset_is_balanced_and_blinding_is_deterministic():
    dataset = load_dataset("evals/council_benchmark_v1.json")
    categories = [case["category"] for case in dataset["cases"]]
    assert len(dataset["cases"]) == 12
    assert {category: categories.count(category) for category in set(categories)} == {
        "decision": 3,
        "fact_check": 3,
        "risk": 3,
        "planning": 3,
    }
    variants = [f"{strategy}:r{repeat}" for strategy in STRATEGIES for repeat in range(1, 4)]
    labels = blind_labels("run-1", "case-1", variants)
    assert labels == blind_labels("run-1", "case-1", variants)
    assert len(set(labels.values())) == len(STRATEGIES) * 3


def test_benchmark_execution_and_human_scores_remain_separate():
    variants = [
        {"strategy": "direct", "blind_label": "B", "status": "completed", "answer": "B answer", "model_calls": 1, "input_tokens": 100, "output_tokens": 30, "duration_ms": 500},
        {"strategy": "same_model_council", "blind_label": "A", "status": "completed", "answer": "A answer", "model_calls": 5, "input_tokens": 600, "output_tokens": 120, "duration_ms": 2400},
        {"strategy": "cross_model_council", "blind_label": "C", "status": "completed", "answer": "C answer", "model_calls": 2, "input_tokens": 200, "output_tokens": 20, "duration_ms": 1800},
    ]
    result = {
        "run_id": "eval-run",
        "benchmark_version": "council-benchmark-v1",
        "quality_claims_allowed": True,
        "cases": [{"id": "case-1", "variants": variants}],
    }
    execution = aggregate_execution(result["cases"])
    assert execution["direct"]["model_calls"] == 1
    assert execution["cross_model_council"]["failure_rate"] == 0
    assert execution["direct"]["tokens_per_run"]["samples"] == 1

    score = {field: 4 for field in ["accuracy", "evidence_use", "critical_coverage", "actionability", "uncertainty"]}
    reviews = {"run_id": "eval-run", "reviews": [{
        "case_id": "case-1",
        "scores": {"A": score, "B": score, "C": score},
        "citation_checks": {"A": {"supported": 3, "total": 4}, "B": {"supported": 2, "total": 2}, "C": {"supported": 0, "total": 0}},
        "unsupported_claims": {"A": 1, "B": 0, "C": 2},
        "preferred": "A",
    }]}
    summary = summarize_human_reviews(result, reviews)
    assert summary["quality_scored"] is True
    assert summary["quality_claims_allowed"] is True
    assert summary["quality"]["same_model_council"]["preferred_cases"] == 1
    assert summary["quality"]["direct"]["accuracy"] == 4
    assert summary["quality"]["same_model_council"]["citation_accuracy"] == 0.75
    assert summary["quality"]["direct"]["unsupported_claims"] == 0

    failed_result = {
        **result,
        "cases": [{"id": "case-1", "variants": [{**variant, "status": "failed", "answer": ""} if variant["strategy"] == "cross_model_council" else variant for variant in variants]}],
    }
    failed_summary = summarize_human_reviews(failed_result, reviews)
    assert failed_summary["all_variants_completed"] is False
    assert failed_summary["quality_claims_allowed"] is False

    incomplete_metrics = {**reviews, "reviews": [{**reviews["reviews"][0], "citation_checks": {"A": {"supported": 3, "total": 4}}}]}
    incomplete_summary = summarize_human_reviews(result, incomplete_metrics)
    assert incomplete_summary["complete_review_metrics"] is False
    assert incomplete_summary["quality_claims_allowed"] is False

    invalid = {"run_id": "eval-run", "reviews": [{"case_id": "case-1", "scores": {"A": {**score, "accuracy": 6}}}]}
    with pytest.raises(ValueError, match="必须为 1-5"):
        summarize_human_reviews(result, invalid)


def test_quality_claims_require_all_real_providers_and_complete_blind_review():
    profiles = {
        "real": ProviderProfile(id="real", display_name="Real", provider_type=ProviderType.COMPATIBLE),
        "mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK),
    }
    assert provider_reality(profiles, {"real"}) == (True, True)
    assert provider_reality(profiles, {"real", "mock"}) == (True, False)
    assert provider_reality(profiles, {"mock"}) == (False, False)

    score = {field: 4 for field in ["accuracy", "evidence_use", "critical_coverage", "actionability", "uncertainty"]}
    result = {
        "run_id": "partial-review",
        "benchmark_version": "council-benchmark-v1",
        "quality_claims_allowed": True,
        "cases": [
            {"id": "case-1", "variants": [{"strategy": "direct", "blind_label": "A", "status": "completed"}]},
            {"id": "case-2", "variants": [{"strategy": "direct", "blind_label": "B", "status": "completed"}]},
        ],
    }
    summary = summarize_human_reviews(result, {"run_id": "partial-review", "reviews": [{"case_id": "case-1", "scores": {"A": score}}]})
    assert summary["complete_blind_review"] is False
    assert summary["quality_claims_allowed"] is False


def test_repeated_five_strategy_review_can_complete():
    score = {field: 4 for field in ["accuracy", "evidence_use", "critical_coverage", "actionability", "uncertainty"]}
    variants = []
    scores = {}
    citation_checks = {}
    unsupported_claims = {}
    for strategy_index, strategy in enumerate(STRATEGIES):
        for repetition in (1, 2):
            label = chr(65 + strategy_index * 2 + repetition - 1)
            variants.append({
                "strategy": strategy,
                "repetition": repetition,
                "blind_label": label,
                "status": "completed",
                "answer": f"{strategy} answer {repetition}",
            })
            scores[label] = score
            citation_checks[label] = {"supported": 1, "total": 1}
            unsupported_claims[label] = 0
    result = {
        "run_id": "repeated-eval",
        "benchmark_version": "council-benchmark-v1",
        "strategies": list(STRATEGIES),
        "repetitions": 2,
        "quality_claims_allowed": True,
        "cases": [{"id": "case-1", "variants": variants}],
    }
    reviews = {"run_id": "repeated-eval", "reviews": [{
        "case_id": "case-1",
        "scores": scores,
        "citation_checks": citation_checks,
        "unsupported_claims": unsupported_claims,
        "preferred": "A",
    }]}

    summary = summarize_human_reviews(result, reviews)
    assert summary["complete_blind_review"] is True
    assert summary["quality_claims_allowed"] is True
    assert summary["quality"]["self_refine"]["score_distributions"]["accuracy"]["samples"] == 2

    duplicate_repeat = {
        **result,
        "cases": [{
            "id": "case-1",
            "variants": [{**variant, "repetition": 1} if variant["strategy"] == "direct" else variant for variant in variants],
        }],
    }
    assert summarize_human_reviews(duplicate_repeat, reviews)["quality_claims_allowed"] is False


def test_cost_estimation_requires_explicit_prices_for_every_model():
    usage = [
        {"provider_id": "deepseek", "model": "model-a", "input_tokens": 1_000_000, "output_tokens": 500_000},
        {"provider_id": "zhipu", "model": "model-b", "input_tokens": 500_000, "output_tokens": 100_000},
    ]
    pricing = {
        "deepseek:model-a": {"input_per_million": 1.0, "output_per_million": 2.0},
        "zhipu": {"input_per_million": 2.0, "output_per_million": 5.0},
    }
    assert estimate_provider_cost(usage, pricing) == (3.5, [])
    cost, missing = estimate_provider_cost(usage, {"deepseek:model-a": pricing["deepseek:model-a"]})
    assert cost is None
    assert missing == ["zhipu:model-b"]
