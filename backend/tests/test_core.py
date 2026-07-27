import asyncio
import sqlite3

import pytest

from app.context import build_context_window, context_budget_for_mode, estimate_tokens
from app.credentials import delete_provider_secret, get_provider_secret, save_provider_secret
from app.models import DiscussionAction, DiscussionTurn, ProviderCreate, ProviderProfile, ProviderType, RunCreate
from app.orchestrator import Orchestrator, analyze_question, describe_run_error, reasoning_effort_for_mode
from app.paths import data_dir, database_path
from app.provider_catalog import builtin_providers
from app.providers import DEFAULT_CCSWITCH_URL, Generation, OpenAICompatibleProvider, build_responses_payload, discover_ccswitch_models, extract_model_ids, extract_responses_text, is_loopback_url, normalize_base_url, validate_base_url
from app.store import Store, serialize_public_provider


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
    assert catalog["deepseek"].default_model == "deepseek-v4-flash"
    assert catalog["zhipu"].default_model == "glm-5.2"
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
    analysis = analyze_question("请计算这个公式", "standard")
    assert analysis.question_type == "mathematical"
    assert analysis.needs_math
    assert analysis.recommended_agents == 4


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
    payload = build_responses_payload("ping", "system", "gpt-5.6-sol", "ultra")
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
    assert "较早讨论摘要" in window.prompt
    assert estimate_tokens(window.prompt) <= window.token_budget


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
        if current and current.status == "completed":
            break
        await asyncio.sleep(0.02)

    assert current is not None
    assert current.reasoning_effort == "high"
    assert captured_efforts == ["high"]


async def test_four_agents_debate_in_order_user_can_interject_and_final_is_automatic(tmp_path, monkeypatch):
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
        if current and current.status == "completed":
            break
        await asyncio.sleep(0.02)

    assert current is not None
    assert current.status == "completed"
    assert current.workflow_engine == "langgraph"
    assert current.checkpoint_count >= 5
    assert current.context_snapshot.total_turns >= 3
    assert current.context_snapshot.estimated_tokens <= current.context_snapshot.token_budget
    with sqlite3.connect(store.checkpoint_path) as checkpoint_conn:
        persisted_checkpoints = checkpoint_conn.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id=?", (current.id,)
        ).fetchone()[0]
    assert persisted_checkpoints == current.checkpoint_count
    assert [turn.speaker_name for turn in current.discussion_turns] == ["你", "析理", "诘问", "构策", "观澜"]
    assert current.final_decision is not None
    assert current.final_decision.final_answer == "自动形成的最终答案"
    assert "我的中途观点" in backend.prompts[1]
    assert "明确表态" in backend.systems[1]
    assert "认同" in backend.systems[1]
    assert "反驳" in backend.systems[1]
    events = []
    queue = store.queue(run.id)
    while not queue.empty():
        events.append((await queue.get()).type)
    assert events.count("agent_turn_completed") == 4
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
    assert "超过 120 秒" in (current.error or "")

    backend.fail_second = False
    restarted_orchestrator = Orchestrator(store, {"mock": profile})
    resumed = await restarted_orchestrator.retry_turn(run.id)
    assert resumed is not None
    assert resumed.status == "running"
    for _ in range(100):
        current = await store.get_run(run.id)
        if current and current.status == "completed":
            break
        await asyncio.sleep(0.02)

    assert current is not None
    assert current.status == "completed"
    assert current.workflow_engine == "langgraph"
    assert current.checkpoint_count >= 5
    assert backend.calls == 6
    assert [turn.speaker_name for turn in current.discussion_turns] == ["析理", "诘问", "构策", "观澜"]
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
        if current and current.status == "completed":
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
    profile = ProviderProfile(id="ccswitch", display_name="CC Switch", provider_type=ProviderType.CCSWITCH)
    orchestrator = Orchestrator(store, {"ccswitch": profile, "mock": profile})
    run = await orchestrator.start(RunCreate(question="验证自动降档", mode="rigorous", provider_id="ccswitch"))

    for _ in range(100):
        current = await store.get_run(run.id)
        if current and current.status in {"completed", "failed"}:
            break
        await asyncio.sleep(0.02)

    await orchestrator.tasks[run.id]

    assert current is not None
    assert current.status == "completed"
    assert current.reasoning_effort == "low"
    assert current.degraded is True
    assert calls[:3] == ["ultra", "high", "low"]
    assert calls[3:] == ["low", "low", "low", "low"]
    route_turns = [turn for turn in current.discussion_turns if turn.speaker_type == "system"]
    assert [turn.content for turn in route_turns] == [
        "Ultra 档上游超时，已自动降为 High 档继续当前席位。",
        "High 档上游超时，已自动降为 Low 档继续当前席位。",
    ]


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
    profile = ProviderProfile(id="ccswitch", display_name="CC Switch", provider_type=ProviderType.CCSWITCH)
    orchestrator = Orchestrator(store, {"ccswitch": profile, "mock": profile})
    run = await orchestrator.start(RunCreate(question="验证上游兼容性错误降档", mode="rigorous", provider_id="ccswitch"))

    for _ in range(100):
        current = await store.get_run(run.id)
        if current and current.status in {"completed", "failed"}:
            break
        await asyncio.sleep(0.02)

    await orchestrator.tasks[run.id]

    assert current is not None
    assert current.status == "completed"
    assert current.reasoning_effort == "high"
    assert current.degraded is True
    assert calls == ["ultra", "high", "high", "high", "high", "high"]
    route_turns = [turn for turn in current.discussion_turns if turn.speaker_type == "system"]
    assert [turn.content for turn in route_turns] == [
        "Ultra 档上游暂不可用，已自动降为 High 档继续当前席位。",
    ]
