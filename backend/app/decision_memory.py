from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import DecisionBrief, RunMemorySnapshotItem, utc_now


MemoryType = Literal[
    "decision",
    "assumption",
    "risk",
    "unresolved_question",
    "action",
    "outcome",
    "superseded_decision",
]
MemoryActionType = Literal["approved", "rejected", "disabled", "enabled", "deleted"]


class StrictMemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryProposal(StrictMemoryModel):
    id: str = Field(default_factory=lambda: f"proposal-{uuid.uuid4()}")
    workspace_id: str = "local-default"
    source_run_id: str
    type: MemoryType
    content: str = Field(min_length=1, max_length=3000)
    rationale: str = Field(min_length=1, max_length=1000)
    related_entity_ids: list[str] = Field(default_factory=list, max_length=30)
    created_at: datetime = Field(default_factory=utc_now)


class MemoryProposalDecision(StrictMemoryModel):
    content: str | None = Field(default=None, min_length=1, max_length=3000)


class ApprovedMemory(StrictMemoryModel):
    id: str = Field(default_factory=lambda: f"memory-{uuid.uuid4()}")
    workspace_id: str = "local-default"
    source_run_id: str
    proposal_id: str
    type: MemoryType
    content: str = Field(min_length=1, max_length=3000)
    verification_status: Literal[
        "unverified", "supported_by_outcome", "contradicted_by_outcome"
    ] = "unverified"
    valid_from: datetime = Field(default_factory=utc_now)
    valid_until: datetime | None = None
    supersedes_memory_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class MemoryAction(StrictMemoryModel):
    id: str = Field(default_factory=lambda: f"memory-action-{uuid.uuid4()}")
    workspace_id: str = "local-default"
    action: MemoryActionType
    proposal_id: str | None = None
    memory_id: str | None = None
    actor: Literal["user"] = "user"
    created_at: datetime = Field(default_factory=utc_now)


class MemoryProposalView(StrictMemoryModel):
    proposal: MemoryProposal
    status: Literal["pending", "approved", "rejected"]
    memory_id: str | None = None
    reviewed_at: datetime | None = None


class MemoryView(StrictMemoryModel):
    memory: ApprovedMemory
    active: bool
    deleted: bool
    last_action: MemoryActionType
    last_action_at: datetime


class MemoryPreviewRequest(StrictMemoryModel):
    selected_memory_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("selected_memory_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("记忆 ID 不能重复")
        return value


class MemoryPreview(StrictMemoryModel):
    workspace_id: str = "local-default"
    selected_memory_ids: list[str]
    included: list[RunMemorySnapshotItem]
    excluded_memory_ids: list[str]
    rendered_context: str


def build_memory_proposals(brief: DecisionBrief) -> list[MemoryProposal]:
    """Create bounded, deterministic-in-content proposals without a model call."""
    proposals: list[MemoryProposal] = []

    def add(kind: MemoryType, content: str, rationale: str, entity_id: str | None = None) -> None:
        cleaned = " ".join(content.split()).strip()
        if not cleaned or len(proposals) >= 20:
            return
        proposals.append(
            MemoryProposal(
                source_run_id=brief.run_id,
                type=kind,
                content=cleaned[:3000],
                rationale=rationale,
                related_entity_ids=[entity_id] if entity_id else [],
            )
        )

    if brief.status != "no_decision":
        add("decision", brief.recommendation, "结构化简报中的当前建议")
    for item in brief.assumptions[:6]:
        add("assumption", item.claim, "仍需在后续决策中核对的假设", item.id)
    for item in brief.unresolved[:6]:
        add("unresolved_question", item.issue, "结构化简报中尚未解决的问题", item.id)
    for item in brief.actions[:6]:
        add("action", item.action, "结构化简报中的后续行动", item.id)
    for index, limitation in enumerate(brief.limitations[:3]):
        add("risk", limitation, "结构化简报披露的限制或风险", f"limitation-{index + 1}")
    return proposals


def render_memory_context(items: list[RunMemorySnapshotItem]) -> str:
    if not items:
        return ""
    labels = {
        "decision": "已批准的历史决策",
        "superseded_decision": "已被取代的历史决策",
        "assumption": "待验证假设",
        "risk": "已知风险",
        "unresolved_question": "未决问题",
        "action": "后续行动",
        "outcome": "先前结果",
    }
    grouped: dict[str, list[str]] = {}
    for item in items:
        grouped.setdefault(labels[item.type], []).append(item.content)
    sections = [f"[{label}]\n" + "\n".join(f"- {content}" for content in values) for label, values in grouped.items()]
    return "\n\n".join(sections)[:12_000]
