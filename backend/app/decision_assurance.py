from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import DecisionBrief, DecisionReadiness, DecisionReview, ReadinessCheck, utc_now
from .domain_rules import detect_professional_domains, detect_risk_domains


TaskLabel = Literal[
    "simple_answer",
    "decision",
    "analysis",
    "creative",
    "needs_current_data",
    "needs_external_evidence",
    "needs_calculation",
    "high_risk",
]

PROFESSIONAL_CLARIFICATIONS: dict[str, tuple[str, ...]] = {
    "medical": (
        "请补充诊断或疑似诊断、检查结果与日期、当前治疗和全部用药。",
        "是否存在需要立即就医的红旗症状？哪些问题必须由主治医师确认？",
    ),
    "legal": (
        "请补充适用国家、地区和具体司法辖区，以及关键日期和程序阶段。",
        "请提供合同或通知原文，并说明希望由执业律师确认的具体风险。",
    ),
    "investment": (
        "请补充金额、币种、期限、现金流、费用税务和计算口径。",
        "请明确可承受的最大损失、流动性需求和需要专业顾问确认的问题。",
    ),
}

def question_requires_high_risk_control(question: str) -> bool:
    return bool(detect_risk_domains(question))
ClaimBasis = Literal[
    "user_provided",
    "model_inference",
    "cited_unverified",
    "seat_disputed",
    "outcome_supported",
    "outcome_contradicted",
]


class StrictAssuranceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadinessRequest(StrictAssuranceModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "question": "是否应该采用微服务架构？",
                "high_risk": False,
            }
        },
    )

    question: str = Field(min_length=3, max_length=12000)
    high_risk: bool = False


class ReadinessOverride(StrictAssuranceModel):
    id: str = Field(default_factory=lambda: f"readiness-override-{uuid.uuid4()}")
    run_id: str
    reason: str = Field(min_length=3, max_length=1000)
    readiness: DecisionReadiness
    actor: Literal["user"] = "user"
    created_at: datetime = Field(default_factory=utc_now)


class ClaimCitation(StrictAssuranceModel):
    url: str
    provided_by: Literal["user", "model"]
    externally_checked: Literal[False] = False


class DecisionClaim(StrictAssuranceModel):
    id: str = Field(default_factory=lambda: f"claim-{uuid.uuid4()}")
    run_id: str
    text: str = Field(min_length=1, max_length=4000)
    basis: ClaimBasis
    source_seat_ids: list[str] = Field(default_factory=list, max_length=20)
    related_entity_ids: list[str] = Field(default_factory=list, max_length=30)
    citation: ClaimCitation | None = None
    dispute_summary: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)


class ClaimOutcome(StrictAssuranceModel):
    id: str = Field(default_factory=lambda: f"claim-outcome-{uuid.uuid4()}")
    claim_id: str
    run_id: str
    review_id: str
    result: Literal["supported", "contradicted"]
    note: str = Field(default="", max_length=1000)
    created_at: datetime = Field(default_factory=utc_now)


class DecisionClaimView(StrictAssuranceModel):
    claim: DecisionClaim
    current_basis: ClaimBasis
    latest_outcome: ClaimOutcome | None = None


class DecisionOutcomeRecord(StrictAssuranceModel):
    id: str = Field(default_factory=lambda: f"decision-outcome-{uuid.uuid4()}")
    run_id: str
    review: DecisionReview
    created_at: datetime = Field(default_factory=utc_now)


def analyze_readiness(question: str, *, high_risk: bool = False) -> DecisionReadiness:
    text = " ".join(question.split())
    lower = text.lower()
    labels: list[TaskLabel] = []
    decision_terms = ("是否", "应该", "选择", "方案", "取舍", "决定", "还是", "should", "choose", "decision")
    current_terms = ("最新", "现在", "目前", "今天", "今日", "实时", "latest", "current", "today")
    risk_terms = ("合规", "生产事故", "compliance", "production incident")
    calculation_terms = ("计算", "多少", "合计", "概率", "calculate", "how many")
    creative_terms = ("写一", "创作", "故事", "文案", "口号", "creative", "story")
    is_decision = any(term in lower for term in decision_terms)
    risk_domains = detect_risk_domains(text)
    professional_domains = [domain for domain in risk_domains if domain in PROFESSIONAL_CLARIFICATIONS]
    is_high_risk = high_risk or bool(risk_domains) or any(term in lower for term in risk_terms)
    if is_decision:
        labels.append("decision")
    elif len(text) <= 30:
        labels.append("simple_answer")
    else:
        labels.append("analysis")
    if any(term in lower for term in creative_terms):
        labels.append("creative")
    if any(term in lower for term in current_terms):
        labels.extend(["needs_current_data", "needs_external_evidence"])
    if any(term in lower for term in calculation_terms):
        labels.append("needs_calculation")
    if is_high_risk:
        labels.extend(["high_risk", "needs_external_evidence"])
    labels = list(dict.fromkeys(labels))

    checks = [
        ReadinessCheck(
            id="goal_defined",
            status="pass" if len(text) >= 8 else "fail",
            message="目标描述可供席位讨论。" if len(text) >= 8 else "请补充希望解决的具体问题。",
        )
    ]
    constraint_terms = ("预算", "期限", "时间", "成本", "限制", "必须", "不能", "budget", "deadline", "constraint")
    option_terms = ("还是", "或者", "方案", "选项", "A", "B", "option", "versus", " vs ")
    success_terms = ("成功", "验收", "指标", "达到", "success", "metric")
    checks.append(ReadinessCheck(
        id="constraints_defined",
        status="pass" if any(term in text for term in constraint_terms) else ("warning" if is_decision else "pass"),
        message="已看到约束。" if any(term in text for term in constraint_terms) else "若有预算、期限或禁止项，请在开始前补充。",
    ))
    checks.append(ReadinessCheck(
        id="options_defined",
        status="pass" if any(term in text for term in option_terms) else ("warning" if is_decision else "pass"),
        message="已看到候选路径。" if any(term in text for term in option_terms) else "可补充正在比较的方案；Council 也可以帮助提出方案。",
    ))
    checks.append(ReadinessCheck(
        id="success_criteria_defined",
        status="pass" if any(term in lower for term in success_terms) else ("warning" if is_decision else "pass"),
        message="已看到成功标准。" if any(term in lower for term in success_terms) else "可补充怎样才算成功，便于输出可验收行动。",
    ))
    critical_status: Literal["pass", "warning", "fail"] = "fail" if is_high_risk else "pass"
    checks.append(ReadinessCheck(
        id="critical_facts_available",
        status=critical_status,
        message="高风险问题必须进入控制面逐项确认关键事实。" if is_high_risk else "当前未触发高风险关键事实门禁。",
    ))
    questions = [item.message for item in checks if item.status in {"warning", "fail"}]
    for domain in professional_domains:
        questions.extend(PROFESSIONAL_CLARIFICATIONS[domain])
    questions = list(dict.fromkeys(questions))
    ready = all(item.status != "fail" for item in checks)
    recommended = "high_risk_council" if is_high_risk else "full_council" if is_decision else "direct" if "simple_answer" in labels else "quick_council"
    return DecisionReadiness(
        ready=ready,
        task_labels=labels,
        checks=checks,
        clarification_questions=questions,
        recommended_mode=recommended,
    )


def build_decision_claims(brief: DecisionBrief) -> list[DecisionClaim]:
    claims: list[DecisionClaim] = []

    def add(text: str, seats: list[str], related: list[str], disputed: bool = False) -> None:
        cleaned = " ".join(text.split()).strip()
        if not cleaned or len(claims) >= 50:
            return
        url = next(iter(re.findall(r"https?://[^\s)\]}>]+", cleaned)), None)
        basis: ClaimBasis = "seat_disputed" if disputed else "cited_unverified" if url else "model_inference"
        claims.append(DecisionClaim(
            run_id=brief.run_id,
            text=cleaned[:4000],
            basis=basis,
            source_seat_ids=list(dict.fromkeys(seats)),
            related_entity_ids=related,
            citation=ClaimCitation(url=url, provided_by="model") if url else None,
            dispute_summary="至少一个席位明确反对或保留意见。" if disputed else None,
        ))

    for item in brief.decisive_reasons:
        add(item.summary, item.supporting_seat_ids + item.opposing_seat_ids, [item.id, *item.related_claim_ids], bool(item.opposing_seat_ids))
    for item in brief.assumptions:
        add(item.claim, [], [item.id])
    for item in brief.unresolved:
        add(item.issue, [position.seat_id for position in item.positions], [item.id], len(item.positions) > 1)
    return claims
