from __future__ import annotations

from .schemas import HighRiskRunStatus


ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"RISK_ASSESSMENT_REQUIRED", "CANCELLED"}),
    "RISK_ASSESSMENT_REQUIRED": frozenset(
        {"MORE_INFORMATION_REQUIRED", "EVIDENCE_REQUIRED", "PROFESSIONAL_ESCALATION_REQUIRED", "ACTION_BLOCKED", "CANCELLED"}
    ),
    "MORE_INFORMATION_REQUIRED": frozenset(
        {"EVIDENCE_REQUIRED", "PROFESSIONAL_ESCALATION_REQUIRED", "ACTION_BLOCKED", "CANCELLED"}
    ),
    "EVIDENCE_REQUIRED": frozenset(
        {"READY_FOR_HUMAN_REVIEW", "PROFESSIONAL_ESCALATION_REQUIRED", "ACTION_BLOCKED", "CANCELLED"}
    ),
    "INDEPENDENT_ANALYSIS": frozenset({"CROSS_EXAMINATION", "MORE_INFORMATION_REQUIRED", "ACTION_BLOCKED", "CANCELLED"}),
    "CROSS_EXAMINATION": frozenset({"READY_FOR_HUMAN_REVIEW", "MORE_INFORMATION_REQUIRED", "PROFESSIONAL_ESCALATION_REQUIRED", "ACTION_BLOCKED", "CANCELLED"}),
    "PROFESSIONAL_ESCALATION_REQUIRED": frozenset({"ACTION_BLOCKED", "CANCELLED"}),
    "READY_FOR_HUMAN_REVIEW": frozenset({"APPROVAL_REQUIRED", "EVIDENCE_REQUIRED", "ACTION_BLOCKED", "CANCELLED"}),
    "APPROVAL_REQUIRED": frozenset({"APPROVED", "REJECTED", "EVIDENCE_REQUIRED", "ACTION_BLOCKED", "CANCELLED"}),
    "APPROVED": frozenset({"COMPLETED", "EVIDENCE_REQUIRED", "ACTION_BLOCKED", "CANCELLED"}),
    "REJECTED": frozenset(),
    "ACTION_BLOCKED": frozenset(),
    "COMPLETED": frozenset(),
    "CANCELLED": frozenset(),
}

TERMINAL_STATUSES = frozenset({"REJECTED", "ACTION_BLOCKED", "COMPLETED", "CANCELLED"})


def can_transition(source: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(source, frozenset())


def require_transition(source: str, target: HighRiskRunStatus) -> None:
    if not can_transition(source, target):
        from app.errors import ApiError

        raise ApiError(409, "INVALID_HIGH_RISK_TRANSITION", "当前高风险状态不允许该操作。")
