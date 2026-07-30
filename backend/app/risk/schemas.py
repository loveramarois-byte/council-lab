from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RiskTier = Literal["normal", "elevated", "high", "critical"]
HighRiskRunStatus = Literal[
    "DRAFT",
    "RISK_ASSESSMENT_REQUIRED",
    "MORE_INFORMATION_REQUIRED",
    "EVIDENCE_REQUIRED",
    "INDEPENDENT_ANALYSIS",
    "CROSS_EXAMINATION",
    "PROFESSIONAL_ESCALATION_REQUIRED",
    "READY_FOR_HUMAN_REVIEW",
    "APPROVAL_REQUIRED",
    "APPROVED",
    "REJECTED",
    "ACTION_BLOCKED",
    "COMPLETED",
    "CANCELLED",
]
DecisionStatus = Literal[
    "READY_FOR_HUMAN_REVIEW",
    "MORE_INFORMATION_REQUIRED",
    "PROFESSIONAL_ESCALATION_REQUIRED",
    "CONFLICTING_AUTHORITIES",
    "OUT_OF_SCOPE",
    "ACTION_BLOCKED",
]
ActorType = Literal["user", "reviewer", "system", "model", "tool"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RiskAssessment(BaseModel):
    run_id: str = Field(min_length=1, max_length=128)
    risk_tier: RiskTier
    original_risk_tier: RiskTier
    detected_domains: list[str] = Field(default_factory=list, max_length=10)
    reasons: list[str] = Field(default_factory=list, max_length=20)
    classifier_version: str = Field(min_length=1, max_length=64)
    assessed_at: datetime = Field(default_factory=utc_now)
    manually_overridden: bool = False
    override_actor_id: str | None = Field(default=None, max_length=128)
    override_reason: str | None = Field(default=None, max_length=1000)


class RequiredFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    required: bool = True
    value: str | None = Field(default=None, max_length=4000)
    source: Literal["user", "document", "tool", "system", "unknown"] = "unknown"
    verified: bool = False
    materiality: Literal["low", "medium", "high", "critical"] = "critical"

    @field_validator("value")
    @classmethod
    def normalize_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DecisionQualitySignals(BaseModel):
    evidence_coverage: Literal["none", "partial", "substantial", "complete"] = "none"
    source_quality: Literal["unknown", "low", "mixed", "high"] = "unknown"
    source_freshness: Literal["unknown", "stale", "mixed", "current"] = "unknown"
    agent_disagreement: Literal["none", "minor", "material", "critical"] = "material"
    critical_information_missing: bool = True


class HighRiskDecision(BaseModel):
    status: DecisionStatus
    report: str = Field(min_length=1, max_length=50000)
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_signals: DecisionQualitySignals
    disclaimer: str = "非约束性决策支持；必须由具备相应责任和资质的人员复核。"


class HighRiskRun(BaseModel):
    run_id: str
    status: HighRiskRunStatus
    version: int = Field(ge=1)
    risk_assessment: RiskAssessment
    required_facts: list[RequiredFact]
    decision: HighRiskDecision | None = None
    requested_action_type: str | None = None
    requested_action_payload_hash: str | None = None
    report_hash: str | None = None
    requested_by: str
    created_at: datetime
    updated_at: datetime


class ApprovalRecord(BaseModel):
    approval_id: str
    run_id: str
    requested_action_type: str
    requested_action_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_at: datetime
    requested_by: str
    status: Literal["pending", "approved", "rejected", "expired", "revoked"]
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_reason: str | None = None
    expires_at: datetime
    consumed_at: datetime | None = None


class AuditEvent(BaseModel):
    event_id: str
    sequence: int = 0
    run_id: str
    event_type: str
    occurred_at: datetime
    actor_type: ActorType
    actor_id: str | None = None
    previous_status: str | None = None
    new_status: str | None = None
    policy_version: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    prompt_template_version: str | None = None
    request_hash: str | None = None
    response_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PublicAuditEvent(BaseModel):
    """Minimal audit projection safe to expose to desktop and paired clients."""

    event_id: str
    sequence: int
    run_id: str
    event_type: str
    occurred_at: datetime
    actor_type: ActorType
    previous_status: str | None = None
    new_status: str | None = None


class HighRiskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=3, max_length=12000)


class FactsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facts: list[RequiredFact] = Field(max_length=50)


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_status: HighRiskRunStatus
    reason: str = Field(default="", max_length=1000)


class PrepareReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report: str = Field(min_length=1, max_length=50000)
    requested_action_type: str = Field(min_length=1, max_length=100)
    requested_action_payload: dict[str, Any] = Field(default_factory=dict)
    quality_signals: DecisionQualitySignals = Field(default_factory=DecisionQualitySignals)


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=1000)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expires_in_minutes: int = Field(default=30, ge=1, le=1440)


class RevokeApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)


class RiskOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risk_tier: RiskTier
    reason: str = Field(min_length=8, max_length=1000)
