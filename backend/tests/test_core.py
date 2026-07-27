import asyncio
import sqlite3

import pytest

from app.context import build_context_window, context_budget_for_mode, estimate_tokens
from app.credentials import delete_provider_secret, get_provider_secret, save_provider_secret
from app.models import AgentAssignmentsConfig, AgentModelAssignment, CandidateAnswer, DiscussionAction, DiscussionTurn, ProviderCapabilities, ProviderCreate, ProviderProfile, ProviderType, RunCreate, RunLimits, RunRecord, UsageSummary, utc_now
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
    assert "重试未完成席位" in describe_run_error(asyncio.TimeoutError(), 120)


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
    assert "最终补充条件" in backend.prompts[-1]
    assert "score" not in current.final_decision.confidence
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


async def test_global_run_timeout_covers_the_whole_active_run(tmp_path, monkeypatch):
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
