from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, SecretStr, field_validator


CURRENT_ASSIGNMENT_SCHEMA_VERSION = 2


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


class RunCreate(BaseModel):
    question: str = Field(min_length=3, max_length=12000)
    mode: Literal["quick", "standard", "rigorous"] = "standard"
    provider_id: str = "mock"
    model: str | None = None
    assignment_config: AgentAssignmentsPayload | None = None
    use_saved_assignments: bool = False
    auto_summarize: bool = False
    project_id: str | None = None
    source_ids: list[str] | None = Field(default=None, max_length=20)
    include_project_history: bool = True
    template_id: str = "open_discussion"
    limits: RunLimits = Field(default_factory=RunLimits)


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
    created_at: datetime = Field(default_factory=utc_now)


class QuestionAnalysis(BaseModel):
    question_type: str
    needs_realtime: bool = False
    needs_web: bool = False
    needs_code_execution: bool = False
    needs_math: bool = False
    needs_file: bool = False
    high_risk_domain: bool = False
    faulty_premise: bool = False
    suitable_for_multi_agent: bool = True
    recommended_agents: int = 3
    recommended_mode: str = "standard"
    expected_model_calls: int = 8
    expected_token_limit: int = 40000
    expected_tool_calls: int = 0


class UsageSummary(BaseModel):
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float | None = None
    duration_ms: int = 0


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


class DeliberationTemplate(BaseModel):
    id: str
    name: str
    description: str
    prompt_hint: str
    system_guidance: str


class CandidateAnswer(BaseModel):
    candidate_id: str
    answer: str
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
    candidates: list[CandidateAnswer] = Field(default_factory=list)
    critiques: list[Critique] = Field(default_factory=list)
    verifications: list[VerificationResult] = Field(default_factory=list)
    revisions: list[RevisedAnswer] = Field(default_factory=list)
    scores: list[JudgeScore] = Field(default_factory=list)
    final_decision: FinalDecision | None = None
    usage: UsageSummary = Field(default_factory=UsageSummary)
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
    recoverable: bool = False
    limit_reason: str | None = None
    project_id: str | None = None
    project_name: str = ""
    project_context: str = ""
    template_id: str = "open_discussion"
    template_name: str = "开放讨论"
    source_snapshots: list[RunSourceSnapshot] = Field(default_factory=list)
    decision_review: DecisionReview | None = None
