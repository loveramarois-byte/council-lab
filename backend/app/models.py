from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import date, datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from .traditional_references import TRADITIONAL_REFERENCE_BOOK_IDS
from .traditional_rules import TRADITIONAL_RULE_PROFILE_IDS


CURRENT_ASSIGNMENT_SCHEMA_VERSION = 2
OutputContractId = Literal["general_decision", "product_review", "technical_architecture"]
CouncilMode = Literal["general", "traditional_culture"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProviderType(str, Enum):
    CCSWITCH = "ccswitch_local"
    OPENAI = "openai_official"
    COMPATIBLE = "openai_compatible"
    MOCK = "mock"


class ProtocolMode(str, Enum):
    AUTO = "auto"
    RESPONSES = "responses"
    CHAT_COMPLETIONS = "chat_completions"


class ProviderCapabilities(BaseModel):
    supports_responses: bool = False
    supports_chat_completions: bool = True
    supports_streaming: bool = True
    supports_structured_output: bool = False
    supports_tool_calling: bool = False
    supports_parallel_tool_calls: bool = False
    supports_usage: bool = False
    supports_model_listing: bool = False
    supports_hosted_web_search: bool = False
    supports_file_input: bool = False
    supports_vision: bool = False
    supports_reasoning_effort: bool = False


class ProviderProfile(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str
    preset_id: str = "custom"
    display_name: str
    description: str = ""
    key_url: str = ""
    docs_url: str = ""
    provider_type: ProviderType
    protocol_mode: ProtocolMode = ProtocolMode.AUTO
    base_url: str = ""
    api_key_reference: str | None = None
    credential_saved: bool = False
    supports_api_key: bool = True
    requires_api_key: bool = False
    default_model: str = "council-mock"
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"] = "high"
    available_models: list[str] = Field(default_factory=list)
    model_source: Literal["none", "recommended", "provider", "ccswitch_history", "built_in", "saved"] = "none"
    timeout_seconds: float = Field(default=30, ge=1, le=180)
    max_retries: int = Field(default=1, ge=0, le=4)
    enabled: bool = True
    is_active: bool = False
    local_only: bool = False
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities)
    last_health_check: datetime | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("base_url")
    @classmethod
    def clean_url(cls, value: str) -> str:
        return value.rstrip("/")


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str
    provider_type: ProviderType
    protocol_mode: ProtocolMode = ProtocolMode.AUTO
    base_url: str = ""
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    api_key: SecretStr | None = Field(default=None, min_length=8)
    default_model: str = ""
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"] = "high"
    timeout_seconds: float = Field(default=30, ge=1, le=180)
    max_retries: int = Field(default=1, ge=0, le=4)
    enabled: bool = True


class ProviderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    protocol_mode: ProtocolMode | None = None
    base_url: str | None = None
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    api_key: SecretStr | None = Field(default=None, min_length=8)
    default_model: str | None = None
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"] | None = None
    timeout_seconds: float | None = Field(default=None, ge=1, le=180)
    max_retries: int | None = Field(default=None, ge=0, le=4)
    enabled: bool | None = None


class AgentModelAssignment(BaseModel):
    role: str
    provider_id: str
    model: str
    protocol: ProtocolMode = ProtocolMode.AUTO
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"] = "medium"
    max_output_tokens: int = Field(default=1200, ge=128, le=8000)
    temperature: float = Field(default=0.2, ge=0, le=2)
    timeout_seconds: float = Field(default=30, ge=1, le=180)


class AgentAssignmentsConfig(BaseModel):
    schema_version: int = Field(default=CURRENT_ASSIGNMENT_SCHEMA_VERSION, ge=1, le=CURRENT_ASSIGNMENT_SCHEMA_VERSION)
    seats: list[AgentModelAssignment] = Field(min_length=4, max_length=4)
    finalizer: AgentModelAssignment


def mark_missing_assignment_schema_as_legacy(value: Any) -> Any:
    if isinstance(value, dict) and "schema_version" not in value:
        return {**value, "schema_version": 1}
    return value


AgentAssignmentsPayload = Annotated[
    AgentAssignmentsConfig,
    BeforeValidator(mark_missing_assignment_schema_as_legacy),
]


class ResolvedAgentAssignment(BaseModel):
    role: str
    provider_id: str
    provider_name: str
    model: str
    protocol: ProtocolMode = ProtocolMode.AUTO
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"] = "medium"
    max_output_tokens: int = Field(default=1200, ge=128, le=8000)
    temperature: float = Field(default=0.2, ge=0, le=2)
    timeout_seconds: float = Field(default=30, ge=1, le=180)
    provider_snapshot: ProviderProfile


class RunLimits(BaseModel):
    max_model_calls: int = Field(default=8, ge=1, le=50)
    max_tokens: int = Field(default=40000, ge=128, le=100000)
    timeout_seconds: int = Field(default=120, ge=1, le=900)


class TraditionalCultureProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_type: Literal["solar"] = "solar"
    birth_date: date
    birth_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    time_precision: Literal["exact", "approximate"] = "exact"
    gender: Literal["male", "female"]
    birth_place: str = Field(default="", max_length=120)
    birth_place_normalized: str | None = Field(default=None, min_length=1, max_length=20, pattern=r"^[\u3400-\u9fff]+$")
    birth_latitude: float | None = Field(default=None, ge=-90, le=90)
    birth_longitude: float | None = Field(default=None, ge=-180, le=180)
    birth_place_source: Literal["offline_city_catalog", "manual_coordinates", "unresolved"] = "unresolved"
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    true_solar_time_applied: bool = False
    focus_topics: list[Literal["temperament", "career", "relationships", "timing"]] = Field(
        default_factory=list,
        max_length=4,
    )
    interpretation_framework: Literal["comparative_research", "bazi_classical", "ziwei_classical"] = "comparative_research"
    reference_book_ids: list[str] = Field(default_factory=list, max_length=15)

    @field_validator("birth_date")
    @classmethod
    def validate_birth_date(cls, value: date) -> date:
        if value < date(1900, 1, 1) or value > date.today():
            raise ValueError("出生日期必须在 1900-01-01 至今天之间")
        return value

    @field_validator("birth_place", "birth_place_normalized")
    @classmethod
    def validate_birth_place(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if any(unicodedata.category(character).startswith("C") for character in value):
            raise ValueError("出生地不能包含控制字符或不可见格式字符")
        return value

    @field_validator("reference_book_ids")
    @classmethod
    def validate_reference_book_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("传统文化参考典籍不能重复选择")
        unknown = sorted(set(value) - TRADITIONAL_REFERENCE_BOOK_IDS)
        if unknown:
            raise ValueError("传统文化参考典籍 ID 无效")
        return value

    @field_validator("interpretation_framework", mode="before")
    @classmethod
    def validate_interpretation_framework(cls, value: str) -> str:
        if value not in TRADITIONAL_RULE_PROFILE_IDS:
            raise ValueError("传统文化解释体系 ID 无效")
        return value


class TraditionalCultureEngine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Literal["lunar-javascript", "iztro"]
    version: str = Field(min_length=1, max_length=30)
    source_url: str = Field(pattern=r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    license: Literal["MIT"] = "MIT"


class TraditionalCultureCalendarFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    solar_datetime: str = Field(min_length=10, max_length=30)
    civil_solar_datetime: str | None = Field(default=None, min_length=10, max_length=30)
    true_solar_datetime: str | None = Field(default=None, min_length=10, max_length=30)
    true_solar_time_offset_minutes: int | None = Field(default=None, ge=-180, le=180)
    lunar_date: str = Field(min_length=1, max_length=80)
    zodiac: str = Field(min_length=1, max_length=20)
    constellation: str = Field(min_length=1, max_length=30)
    eight_char: str = Field(min_length=7, max_length=40)
    pillars: list[Annotated[str, Field(min_length=1, max_length=12)]] = Field(min_length=4, max_length=4)
    pillar_wuxing: list[Annotated[str, Field(min_length=1, max_length=12)]] = Field(min_length=4, max_length=4)
    heavenly_stem_ten_gods: list[Annotated[str, Field(min_length=1, max_length=20)]] = Field(min_length=4, max_length=4)


class TraditionalCultureSolarTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=20)
    datetime: str = Field(min_length=10, max_length=30)


class TraditionalCultureTimingFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_civil_datetime: str = Field(min_length=10, max_length=30)
    reference_true_solar_datetime: str = Field(min_length=10, max_length=30)
    reference_true_solar_offset_minutes: int = Field(ge=-180, le=180)
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    time_source: Literal["network", "local_fallback"]
    time_provider: Literal["https_consensus", "timeapi.io", "system_clock"]
    time_source_url: str = Field(default="", max_length=300)
    time_proof: str | None = Field(default=None, pattern=r"^v1\.[a-f0-9]{64}$")
    synced: bool
    lunar_date: str = Field(min_length=1, max_length=80)
    year_pillar: str = Field(min_length=2, max_length=12)
    month_pillar: str = Field(min_length=2, max_length=12)
    day_pillar: str = Field(min_length=2, max_length=12)
    hour_pillar: str = Field(min_length=2, max_length=12)
    current_solar_term: str = Field(default="", max_length=20)
    previous_solar_term: TraditionalCultureSolarTerm
    next_solar_term: TraditionalCultureSolarTerm

    @model_validator(mode="after")
    def validate_time_provenance(self) -> "TraditionalCultureTimingFacts":
        if self.synced:
            valid_status = self.time_source == "network" and self.time_provider in {"https_consensus", "timeapi.io"}
        else:
            valid_status = self.time_source == "local_fallback" and self.time_provider == "system_clock"
        if not valid_status:
            raise ValueError("联网校时状态与来源不一致")
        if self.time_provider == "https_consensus":
            allowed_sources = {
                "https://www.cloudflare.com/",
                "https://www.google.com/generate_204",
                "https://www.baidu.com/",
            }
            sources = self.time_source_url.split(",")
            if len(set(sources)) < 2 or any(source not in allowed_sources for source in sources):
                raise ValueError("联网多源校时缺少一致来源")
        if self.time_provider == "timeapi.io" and not self.time_source_url.startswith("https://timeapi.io/"):
            raise ValueError("联网校时来源地址无效")
        if not self.synced and self.time_source_url:
            raise ValueError("本机时间回退不能标记为联网来源")
        if self.time_provider != "https_consensus" and self.time_proof is not None:
            raise ValueError("非多源联网校时不能携带服务端时间证明")
        return self


class TraditionalCultureZiweiPalace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0, le=11)
    name: str = Field(min_length=1, max_length=20)
    heavenly_stem: str = Field(min_length=1, max_length=4)
    earthly_branch: str = Field(min_length=1, max_length=4)
    is_body_palace: bool = False
    is_original_palace: bool = False
    major_stars: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(default_factory=list, max_length=20)
    minor_stars: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(default_factory=list, max_length=30)
    changsheng12: str = Field(default="", max_length=20)
    decadal_range: list[Annotated[int, Field(ge=0, le=200)]] = Field(default_factory=list, max_length=2)


class TraditionalCultureZiweiChart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    solar_date: str = Field(min_length=8, max_length=20)
    lunar_date: str = Field(min_length=1, max_length=80)
    chinese_date: str = Field(min_length=1, max_length=60)
    time_label: str = Field(min_length=1, max_length=20)
    time_range: str = Field(min_length=1, max_length=30)
    five_elements_class: str = Field(min_length=1, max_length=30)
    soul_star: str = Field(min_length=1, max_length=20)
    body_star: str = Field(min_length=1, max_length=20)
    soul_palace_branch: str = Field(min_length=1, max_length=4)
    body_palace_branch: str = Field(min_length=1, max_length=4)
    palaces: list[TraditionalCultureZiweiPalace] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def validate_palace_indexes(self) -> "TraditionalCultureZiweiChart":
        if sorted(item.index for item in self.palaces) != list(range(12)):
            raise ValueError("紫微十二宫索引必须完整且不能重复")
        return self


class TraditionalCultureSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2] = 1
    calculation_source: Literal["local_browser", "local_service"] = "local_browser"
    calculated_at: datetime
    profile: TraditionalCultureProfile
    engines: list[TraditionalCultureEngine] = Field(min_length=2, max_length=2)
    calendar_facts: TraditionalCultureCalendarFacts
    timing_facts: TraditionalCultureTimingFacts | None = None
    ziwei_chart: TraditionalCultureZiweiChart
    notices: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(default_factory=list, min_length=2, max_length=12)
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot_proof: str | None = Field(default=None, pattern=r"^v1\.[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_provenance_and_hash(self) -> "TraditionalCultureSnapshot":
        versions = {item.id: item.version for item in self.engines}
        if versions != {"lunar-javascript": "1.7.7", "iztro": "2.5.8"}:
            raise ValueError("传统文化计算引擎版本与当前发行版不一致")
        if self.schema_version == 2:
            if self.timing_facts is None:
                raise ValueError("新版传统文化快照缺少流年流月流日字段")
            if self.profile.true_solar_time_applied:
                if (
                    not self.profile.birth_place
                    or not self.profile.birth_place_normalized
                    or self.profile.birth_latitude is None
                    or self.profile.birth_longitude is None
                    or self.profile.birth_place_source == "unresolved"
                    or self.calendar_facts.true_solar_datetime is None
                    or self.calendar_facts.true_solar_time_offset_minutes is None
                ):
                    raise ValueError("真太阳时校正缺少可追溯的出生地或时间字段")
        payload = self.model_dump(mode="json", exclude={"snapshot_sha256", "snapshot_proof"})
        time_proof = None
        if self.timing_facts is not None:
            # The proof authenticates fresh network time separately. It is
            # process-keyed and must not make an otherwise identical snapshot
            # hash change after the backend restarts.
            time_proof = payload["timing_facts"].pop("time_proof", None)
        if self.schema_version == 1:
            for key in ("birth_place_normalized", "birth_latitude", "birth_longitude", "birth_place_source"):
                payload["profile"].pop(key, None)
            for key in ("civil_solar_datetime", "true_solar_datetime", "true_solar_time_offset_minutes"):
                payload["calendar_facts"].pop(key, None)
            payload.pop("timing_facts", None)
        payload_variants = [payload]
        if time_proof is not None and self.schema_version == 2:
            # Compatibility for development builds that briefly included the
            # process-keyed proof in the digest before v0.15.0 shipped.
            proof_bound_payload = json.loads(json.dumps(payload, ensure_ascii=False))
            proof_bound_payload["timing_facts"]["time_proof"] = time_proof
            payload_variants.append(proof_bound_payload)

        valid_hashes: set[str] = set()
        # Older v1 snapshots predate the optional reference index and default
        # comparative framework. Keep compatibility for those default-only
        # shapes; non-default framework selections remain hash-bound.
        for base_payload in payload_variants:
            profile_omissions = [()]
            if not self.profile.reference_book_ids:
                profile_omissions.append(("reference_book_ids",))
            if self.profile.interpretation_framework == "comparative_research":
                profile_omissions.append(("interpretation_framework",))
                if not self.profile.reference_book_ids:
                    profile_omissions.append(("reference_book_ids", "interpretation_framework"))
            for omissions in profile_omissions:
                compatible_payload = json.loads(json.dumps(base_payload, ensure_ascii=False))
                for key in omissions:
                    compatible_payload["profile"].pop(key, None)
                canonical = json.dumps(
                    compatible_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                valid_hashes.add(hashlib.sha256(canonical).hexdigest())
        if self.snapshot_sha256 not in valid_hashes:
            raise ValueError("传统文化计算快照校验失败，请重新排盘")
        return self


class RunCreate(BaseModel):
    question: str = Field(min_length=3, max_length=12000)
    mode: Literal["quick", "standard", "rigorous"] = "standard"
    council_mode: CouncilMode = "general"
    workflow_strategy: Literal["sequential", "independent"] = "sequential"
    provider_id: str = "mock"
    model: str | None = None
    assignment_config: AgentAssignmentsPayload | None = None
    use_saved_assignments: bool = False
    auto_summarize: bool = False
    high_risk: bool = False
    project_id: str | None = None
    source_ids: list[str] | None = Field(default=None, max_length=20)
    include_project_history: bool = True
    template_id: str = "open_discussion"
    output_contract: OutputContractId = "general_decision"
    selected_memory_ids: list[str] = Field(default_factory=list, max_length=20)
    readiness_override: bool = False
    readiness_override_reason: str = Field(default="", max_length=1000)
    traditional_culture_snapshot: TraditionalCultureSnapshot | None = None
    traditional_culture_consent: bool = False
    limits: RunLimits = Field(default_factory=RunLimits)

    @model_validator(mode="after")
    def validate_readiness_override(self) -> "RunCreate":
        if self.readiness_override and len(self.readiness_override_reason.strip()) < 3:
            raise ValueError("继续准备度不足的 Run 时必须说明原因")
        if self.council_mode == "traditional_culture":
            if not self.traditional_culture_consent or self.traditional_culture_snapshot is None:
                raise ValueError("传统文化联合研判需要本地排盘快照和明确的数据发送确认")
            if self.high_risk:
                raise ValueError("传统文化联合研判不能与高风险决策支持同时启用")
            if self.workflow_strategy != "independent":
                raise ValueError("传统文化联合研判必须先由四席独立初答")
            if self.template_id != "traditional_culture_review":
                raise ValueError("传统文化联合研判必须使用专用审议模板")
            if self.output_contract != "general_decision":
                raise ValueError("传统文化联合研判不能生成决策或专业评审契约")
            if self.auto_summarize:
                raise ValueError("传统文化联合研判必须保留用户最终确认点")
            if self.selected_memory_ids:
                raise ValueError("传统文化联合研判不能注入历史决策记忆")
        elif self.traditional_culture_snapshot is not None or self.traditional_culture_consent:
            raise ValueError("普通圆桌不能携带传统文化出生资料")
        return self


class DiscussionAction(BaseModel):
    action: Literal["continue", "interject", "question"] = "continue"
    message: str = Field(default="", max_length=6000)
    target_agent: str | None = None


class DiscussionTurn(BaseModel):
    id: str
    speaker_type: Literal["user", "agent", "system"]
    speaker_id: str
    speaker_name: str
    role_label: str = ""
    content: str
    provider_id: str | None = None
    provider_name: str | None = None
    model: str | None = None
    round: int = 1
    stage: Literal["initial_opinion", "discussion", "user_input", "system"] = "discussion"
    reused_from_run_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class QuestionAnalysis(BaseModel):
    question_type: str
    needs_realtime: bool = False
    needs_web: bool = False
    needs_external_evidence: bool = False
    needs_code_execution: bool = False
    needs_math: bool = False
    needs_file: bool = False
    high_risk_domain: bool = False
    high_risk_domains: list[str] = Field(default_factory=list)
    faulty_premise: bool = False
    suitable_for_multi_agent: bool = True
    recommended_agents: int = 3
    recommended_mode: str = "standard"
    expected_model_calls: int = 8
    expected_token_limit: int = 40000
    expected_tool_calls: int = 0
    confidence: float = Field(default=0.5, ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    short_task_route: bool = False


class ReadinessCheck(BaseModel):
    id: Literal[
        "goal_defined",
        "constraints_defined",
        "options_defined",
        "success_criteria_defined",
        "critical_facts_available",
    ]
    status: Literal["pass", "warning", "fail"]
    message: str


class DecisionReadiness(BaseModel):
    ready: bool
    task_labels: list[Literal[
        "simple_answer",
        "decision",
        "analysis",
        "creative",
        "needs_current_data",
        "needs_external_evidence",
        "needs_calculation",
        "high_risk",
    ]]
    checks: list[ReadinessCheck]
    clarification_questions: list[str]
    recommended_mode: Literal["direct", "quick_council", "full_council", "high_risk_council"]
    rules_version: Literal["decision-readiness-v1"] = "decision-readiness-v1"


class UsageSummary(BaseModel):
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float | None = None
    duration_ms: int = 0


class ProviderAttempt(BaseModel):
    """A non-sensitive record of one HTTP request sent to a model provider."""

    role: str = Field(default="", max_length=40)
    provider_id: str = Field(min_length=1, max_length=80)
    provider_name: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=200)
    endpoint: str = Field(min_length=1, max_length=120)
    attempt: int = Field(ge=1, le=20)
    status_code: int | None = Field(default=None, ge=100, le=599)
    duration_ms: int = Field(default=0, ge=0)
    upstream_request_id: str | None = Field(default=None, max_length=300)
    error_kind: str | None = Field(default=None, max_length=120)


class ContextSnapshot(BaseModel):
    strategy: str = "deterministic_context_clipping"
    token_budget: int = 0
    estimated_tokens: int = 0
    included_turns: int = 0
    total_turns: int = 0
    compacted: bool = False
    summary: str = ""
    source_tokens: int = 0
    history_tokens: int = 0
    token_estimator: str = "conservative_utf8"
    token_estimator_exact: bool = False


class ProjectRecord(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=4000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    source_count: int = 0
    run_count: int = 0


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=4000)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, max_length=4000)


class SourceTextCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=200000)


class SourceURLCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    title: str = Field(default="", max_length=160)


class ProjectSource(BaseModel):
    id: str
    project_id: str
    kind: Literal["text", "file", "url"]
    title: str
    content: str = ""
    url: str = ""
    filename: str = ""
    media_type: str = "text/plain"
    size_bytes: int = 0
    sha256: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class RunSourceSnapshot(BaseModel):
    id: str
    kind: Literal["text", "file", "url"]
    title: str
    content: str = Field(validation_alias=AliasChoices("content", "excerpt"))
    url: str = ""
    filename: str = ""
    sha256: str = ""


class SeatOutcomeReview(BaseModel):
    role: Literal["analyst", "challenger", "builder", "observer"]
    status: Literal["pending", "supported", "mixed", "contradicted"] = "pending"
    note: str = Field(default="", max_length=1000)


class DecisionReviewUpdate(BaseModel):
    selected_decision: str = Field(min_length=1, max_length=6000)
    expected_result: str = Field(min_length=1, max_length=6000)
    review_date: date | None = None
    actual_result: str = Field(default="", max_length=6000)
    outcome_status: Literal["pending", "successful", "partial", "unsuccessful", "unclear"] = "pending"
    seat_outcomes: list[SeatOutcomeReview] = Field(default_factory=list, max_length=4)

    @field_validator("seat_outcomes")
    @classmethod
    def unique_seats(cls, value: list[SeatOutcomeReview]) -> list[SeatOutcomeReview]:
        roles = [item.role for item in value]
        if len(roles) != len(set(roles)):
            raise ValueError("每个席位只能记录一次回访结果")
        return value


class DecisionReview(DecisionReviewUpdate):
    updated_at: datetime = Field(default_factory=utc_now)


class RunMemorySnapshotItem(BaseModel):
    memory_id: str
    source_run_id: str
    type: Literal[
        "decision",
        "assumption",
        "risk",
        "unresolved_question",
        "action",
        "outcome",
        "superseded_decision",
    ]
    content: str
    verification_status: str


class DeliberationTemplate(BaseModel):
    id: str
    name: str
    description: str
    prompt_hint: str
    system_guidance: str


class OutputContractDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: OutputContractId
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    input_checks: list[str] = Field(min_length=1, max_length=20)
    prompt_hint: str = Field(min_length=1, max_length=500)
    system_guidance: str = Field(min_length=1, max_length=4000)


class CandidateAnswer(BaseModel):
    candidate_id: str
    answer: str
    structure_source: Literal["agent_output", "postprocessed", "manual", "legacy_default", "none"]
    key_reasons: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    claims_to_verify: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    proposed_sources: list[str] = Field(default_factory=list)
    model: str
    provider: str
    usage: UsageSummary = Field(default_factory=UsageSummary)
    status: str = "completed"
    anonymous_label: str | None = None

    @model_validator(mode="before")
    @classmethod
    def mark_missing_structure_source_as_legacy(cls, value: Any) -> Any:
        if isinstance(value, dict) and "structure_source" not in value:
            return {**value, "structure_source": "legacy_default"}
        return value

    @model_validator(mode="after")
    def validate_structure_provenance(self) -> "CandidateAnswer":
        attributed_fields = (
            self.key_reasons,
            self.assumptions,
            self.claims_to_verify,
            self.uncertainties,
            self.risks,
            self.proposed_sources,
        )
        if self.structure_source == "none" and any(attributed_fields):
            raise ValueError("structure_source=none requires all structured Candidate fields to be empty")
        return self


class Critique(BaseModel):
    candidate_id: str
    severity: Literal["low", "medium", "high"]
    issue_type: str
    issue: str
    affected_claim: str = ""
    suggested_check: str = ""
    possible_counterexample: str = ""
    confidence: float = Field(default=0.7, ge=0, le=1)


class VerificationTask(BaseModel):
    task_id: str
    claim: str
    method: str
    priority: Literal["low", "medium", "high"] = "medium"


class VerificationResult(BaseModel):
    task_id: str
    claim: str
    status: Literal["verified", "partially_verified", "contradicted", "unverifiable", "not_required", "tool_failed"]
    evidence_summary: str
    sources: list[str] = Field(default_factory=list)
    tool: str = "deterministic_review"
    checked_at: datetime = Field(default_factory=utc_now)
    confidence: float = Field(default=0.6, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)
    error: str | None = None


class RevisedAnswer(BaseModel):
    candidate_id: str
    revised_answer: str
    accepted_critiques: list[str] = Field(default_factory=list)
    rejected_critiques: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    corrected_claims: list[str] = Field(default_factory=list)
    remaining_uncertainties: list[str] = Field(default_factory=list)
    final_sources: list[str] = Field(default_factory=list)


class JudgeScore(BaseModel):
    candidate_id: str
    evidence_score: float
    reasoning_score: float
    coverage_score: float
    risk_score: float
    clarity_score: float
    weighted_total: float
    disqualifying_issues: list[str] = Field(default_factory=list)
    explanation: str


class FinalDecision(BaseModel):
    final_answer: str
    key_reasons: list[str] = Field(default_factory=list)
    verified_claims: list[str] = Field(default_factory=list)
    partially_verified_claims: list[str] = Field(default_factory=list)
    contradicted_claims: list[str] = Field(default_factory=list)
    unverified_claims: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    risks_and_limitations: list[str] = Field(default_factory=list)
    confidence: dict[str, Any]
    sources: list[str] = Field(default_factory=list)
    provider_summary: dict[str, Any]
    usage: UsageSummary


class DecisionBriefItem(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionReason(DecisionBriefItem):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    summary: str = Field(min_length=1, max_length=4000)
    supporting_seat_ids: list[str] = Field(default_factory=list, max_length=20)
    opposing_seat_ids: list[str] = Field(default_factory=list, max_length=20)
    related_claim_ids: list[str] = Field(default_factory=list, max_length=50)


class RejectedAlternative(DecisionBriefItem):
    option: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=4000)


class IssuePosition(DecisionBriefItem):
    seat_id: str = Field(min_length=1, max_length=64)
    position: str = Field(min_length=1, max_length=4000)


class UnresolvedIssue(DecisionBriefItem):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    issue: str = Field(min_length=1, max_length=4000)
    blocking: bool = False
    positions: list[IssuePosition] = Field(default_factory=list, max_length=20)
    resolution_method: str | None = Field(default=None, max_length=2000)


class DecisionAssumption(DecisionBriefItem):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    claim: str = Field(min_length=1, max_length=4000)
    basis: Literal["user_input", "model_inference", "cited_unverified", "outcome_verified"]
    validation_method: str | None = Field(default=None, max_length=2000)
    owner: str | None = Field(default=None, max_length=160)
    due_at: datetime | None = None


class DecisionAction(DecisionBriefItem):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    action: str = Field(min_length=1, max_length=4000)
    owner: str | None = Field(default=None, max_length=160)
    due_at: datetime | None = None
    success_criteria: str | None = Field(default=None, max_length=2000)
    status: Literal["pending", "in_progress", "done", "cancelled"] = "pending"


class ReopenTrigger(DecisionBriefItem):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    condition: str = Field(min_length=1, max_length=4000)
    check_method: str | None = Field(default=None, max_length=2000)
    severity: Literal["informational", "important", "blocking"] = "important"


class MinorityReport(DecisionBriefItem):
    summary: str = Field(min_length=1, max_length=6000)
    seat_ids: list[str] = Field(min_length=1, max_length=20)
    conditions_under_which_it_may_be_correct: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("seat_ids")
    @classmethod
    def unique_seat_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item or len(item) > 64 for item in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("minority seat_ids must be unique, non-empty identifiers")
        return normalized


class GeneralDecisionExtension(DecisionBriefItem):
    contract: Literal["general_decision"] = "general_decision"
    decision_criteria: list[str] = Field(default_factory=list, max_length=30)
    key_tradeoffs: list[str] = Field(default_factory=list, max_length=30)


class ProductValidationExperiment(DecisionBriefItem):
    hypothesis: str = Field(min_length=1, max_length=4000)
    method: str = Field(min_length=1, max_length=4000)
    success_threshold: str = Field(min_length=1, max_length=2000)


class ProductReviewExtension(DecisionBriefItem):
    contract: Literal["product_review"] = "product_review"
    target_users: list[str] = Field(default_factory=list, max_length=30)
    user_problem: str = Field(min_length=1, max_length=12000)
    value_proposition: str = Field(min_length=1, max_length=50000)
    failure_conditions: list[str] = Field(default_factory=list, max_length=30)
    validation_experiments: list[ProductValidationExperiment] = Field(default_factory=list, max_length=20)
    stop_conditions: list[str] = Field(default_factory=list, max_length=30)


class ArchitectureAlternative(DecisionBriefItem):
    option: str = Field(min_length=1, max_length=4000)
    tradeoffs: list[str] = Field(default_factory=list, max_length=20)


class TechnicalArchitectureExtension(DecisionBriefItem):
    contract: Literal["technical_architecture"] = "technical_architecture"
    requirements: list[str] = Field(default_factory=list, max_length=30)
    constraints: list[str] = Field(default_factory=list, max_length=30)
    proposed_architecture: str = Field(min_length=1, max_length=50000)
    alternatives: list[ArchitectureAlternative] = Field(default_factory=list, max_length=20)
    failure_modes: list[str] = Field(default_factory=list, max_length=30)
    migration_plan: list[str] = Field(default_factory=list, max_length=30)
    rollback_plan: list[str] = Field(default_factory=list, max_length=30)
    observability_requirements: list[str] = Field(default_factory=list, max_length=30)


DecisionContractExtension = Annotated[
    GeneralDecisionExtension | ProductReviewExtension | TechnicalArchitectureExtension,
    Field(discriminator="contract"),
]


class DecisionBrief(DecisionBriefItem):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,127}$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    version: int = Field(default=1, ge=1)
    schema_version: Literal[1, 2] = 1
    generated_at: datetime = Field(default_factory=utc_now)
    generation_reason: Literal["run_completed"] = "run_completed"
    status: Literal["proceed", "conditional", "no_decision"]
    recommendation: str = Field(min_length=1, max_length=50000)
    support: Literal["unanimous", "majority", "contested"]
    decisive_reasons: list[DecisionReason] = Field(default_factory=list, max_length=50)
    rejected_alternatives: list[RejectedAlternative] = Field(default_factory=list, max_length=30)
    unresolved: list[UnresolvedIssue] = Field(default_factory=list, max_length=50)
    assumptions: list[DecisionAssumption] = Field(default_factory=list, max_length=50)
    actions: list[DecisionAction] = Field(default_factory=list, max_length=50)
    reopen_triggers: list[ReopenTrigger] = Field(default_factory=list, max_length=50)
    minority_report: MinorityReport | None = None
    limitations: list[str] = Field(min_length=1, max_length=50)
    output_contract: OutputContractId = "general_decision"
    contract_extension: DecisionContractExtension | None = None

    @model_validator(mode="after")
    def validate_semantics(self) -> "DecisionBrief":
        if self.schema_version == 1 and self.contract_extension is not None:
            raise ValueError("DecisionBrief schema v1 cannot contain a contract extension")
        if self.schema_version == 2:
            if self.contract_extension is None:
                raise ValueError("DecisionBrief schema v2 requires a contract extension")
            if self.contract_extension.contract != self.output_contract:
                raise ValueError("DecisionBrief output contract does not match its extension")
        if self.status == "proceed" and any(item.blocking for item in self.unresolved):
            raise ValueError("status=proceed cannot contain a blocking unresolved issue")
        if self.support == "contested" and self.minority_report is None:
            raise ValueError("support=contested requires a minority report")
        if self.minority_report is not None and self.support != "contested":
            raise ValueError("minority report requires support=contested")
        collections = (
            self.decisive_reasons,
            self.unresolved,
            self.assumptions,
            self.actions,
            self.reopen_triggers,
        )
        for items in collections:
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError("DecisionBrief item ids must be unique within each collection")
        return self


class RunEvent(BaseModel):
    event_id: str
    sequence: int = Field(default=0, ge=0)
    run_id: str
    type: str
    stage: str
    message: str
    progress: int = Field(default=0, ge=0, le=100)
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class RunRecord(BaseModel):
    id: str
    question: str
    mode: str
    council_mode: CouncilMode = "general"
    workflow_strategy: Literal["sequential", "independent"] = "sequential"
    provider_id: str
    model: str
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"] = "high"
    workflow_engine: str = "legacy"
    checkpoint_count: int = 0
    context_snapshot: ContextSnapshot = Field(default_factory=ContextSnapshot)
    status: Literal["queued", "running", "awaiting_final_input", "completed", "failed", "stopped", "cancelled"]
    created_at: datetime
    updated_at: datetime
    analysis: QuestionAnalysis | None = None
    readiness: DecisionReadiness | None = None
    candidates: list[CandidateAnswer] = Field(default_factory=list)
    critiques: list[Critique] = Field(default_factory=list)
    verifications: list[VerificationResult] = Field(default_factory=list)
    revisions: list[RevisedAnswer] = Field(default_factory=list)
    scores: list[JudgeScore] = Field(default_factory=list)
    final_decision: FinalDecision | None = None
    usage: UsageSummary = Field(default_factory=UsageSummary)
    provider_attempts: list[ProviderAttempt] = Field(default_factory=list)
    error: str | None = None
    degraded: bool = False
    protocol: str = "mock"
    discussion_turns: list[DiscussionTurn] = Field(default_factory=list)
    participant_roles: list[dict[str, str]] = Field(default_factory=list)
    current_speaker_index: int = 0
    discussion_round: int = 1
    awaiting_user: bool = False
    limits: RunLimits = Field(default_factory=RunLimits)
    assignment_schema_version: int = Field(default=1, ge=1, le=CURRENT_ASSIGNMENT_SCHEMA_VERSION)
    seat_assignments: list[ResolvedAgentAssignment] = Field(default_factory=list)
    finalizer_assignment: ResolvedAgentAssignment | None = None
    auto_summarize: bool = False
    # None marks records written before the high-risk control flag was persisted.
    # The frontend may probe those legacy records once; new records never need a
    # speculative high-risk API request.
    high_risk_control: bool | None = None
    recoverable: bool = False
    limit_reason: str | None = None
    project_id: str | None = None
    project_name: str = ""
    project_context: str = ""
    template_id: str = "open_discussion"
    template_name: str = "开放讨论"
    output_contract: OutputContractId = "general_decision"
    source_snapshots: list[RunSourceSnapshot] = Field(default_factory=list)
    memory_snapshot: list[RunMemorySnapshotItem] = Field(default_factory=list)
    decision_review: DecisionReview | None = None
    traditional_culture_snapshot: TraditionalCultureSnapshot | None = None
    traditional_culture_consent: bool = False
