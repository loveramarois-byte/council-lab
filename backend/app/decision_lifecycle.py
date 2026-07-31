from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import DecisionBrief, RunLimits, utc_now


ForkCheckpoint = Literal[
    "before_deliberation",
    "after_seat_1",
    "after_seat_2",
    "after_seat_3",
    "after_seat_4",
    "before_synthesis",
]


class StrictLifecycleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunForkCreate(StrictLifecycleModel):
    checkpoint: ForkCheckpoint = "before_deliberation"
    reason: str = Field(min_length=3, max_length=1000)
    prompt_append: str = Field(default="", max_length=6000)
    mode: Literal["quick", "standard", "rigorous"] | None = None
    limits: RunLimits | None = None
    auto_summarize: bool = False


class RunFork(StrictLifecycleModel):
    id: str = Field(default_factory=lambda: f"fork-{uuid.uuid4()}", pattern=r"^[a-z0-9][a-z0-9_-]{1,127}$")
    parent_run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    child_run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    checkpoint: ForkCheckpoint
    reason: str = Field(min_length=3, max_length=1000)
    changed_inputs: dict[str, str | int | bool | dict[str, int]] = Field(default_factory=dict)
    reused_turn_ids: list[str] = Field(default_factory=list, max_length=100)
    regenerated_seat_ids: list[str] = Field(default_factory=list, max_length=20)
    approval_inherited: Literal[False] = False
    created_at: datetime = Field(default_factory=utc_now)


class RunForkLineage(StrictLifecycleModel):
    parent: RunFork | None = None
    children: list[RunFork] = Field(default_factory=list)


class DecisionBriefComparison(StrictLifecycleModel):
    left_run_id: str
    right_run_id: str
    related: bool
    left: DecisionBrief
    right: DecisionBrief
    changed_fields: list[str] = Field(default_factory=list)
    status_changed: bool
    recommendation_changed: bool
    support_changed: bool
    unresolved_added: list[str] = Field(default_factory=list)
    unresolved_removed: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_distinct_runs(self) -> "DecisionBriefComparison":
        if self.left_run_id == self.right_run_id:
            raise ValueError("comparison requires two distinct Runs")
        return self


def compare_briefs(
    left: DecisionBrief,
    right: DecisionBrief,
    *,
    related: bool,
) -> DecisionBriefComparison:
    changed: list[str] = []
    if left.status != right.status:
        changed.append("status")
    if left.recommendation != right.recommendation:
        changed.append("recommendation")
    if left.support != right.support:
        changed.append("support")
    left_issues = {item.issue for item in left.unresolved}
    right_issues = {item.issue for item in right.unresolved}
    if left_issues != right_issues:
        changed.append("unresolved")
    if left.actions != right.actions:
        changed.append("actions")
    if left.assumptions != right.assumptions:
        changed.append("assumptions")
    return DecisionBriefComparison(
        left_run_id=left.run_id,
        right_run_id=right.run_id,
        related=related,
        left=left,
        right=right,
        changed_fields=changed,
        status_changed=left.status != right.status,
        recommendation_changed=left.recommendation != right.recommendation,
        support_changed=left.support != right.support,
        unresolved_added=sorted(right_issues - left_issues),
        unresolved_removed=sorted(left_issues - right_issues),
    )


def reusable_seat_count(checkpoint: ForkCheckpoint, participant_count: int) -> int:
    if participant_count < 1 or participant_count > 4:
        raise ValueError("父 Run 的席位数量无效")
    mapping = {
        "before_deliberation": 0,
        "after_seat_1": 1,
        "after_seat_2": 2,
        "after_seat_3": 3,
        "after_seat_4": 4,
        "before_synthesis": participant_count,
    }
    reusable = mapping[checkpoint]
    if reusable > participant_count:
        raise ValueError("所选分叉点在父 Run 中不存在")
    return reusable
