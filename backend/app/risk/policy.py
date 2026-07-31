from __future__ import annotations

from datetime import datetime, timezone

from .schemas import EvidenceRecord, HighRiskRun, ProfessionalReviewRecord


DOMAIN_REVIEW_ROLES: dict[str, frozenset[str]] = {
    "medical": frozenset({"physician", "registered_nurse", "pharmacist", "clinical_specialist"}),
    "legal": frozenset({"lawyer", "attorney", "legal_counsel", "compliance_counsel"}),
    "investment": frozenset({"licensed_adviser", "investment_adviser", "portfolio_manager", "risk_officer"}),
    "compliance": frozenset({"compliance_officer", "risk_officer", "internal_auditor", "compliance_counsel"}),
    "production_incident": frozenset({"incident_commander", "site_reliability_engineer", "security_officer"}),
    "general_high_risk": frozenset({"domain_professional", "risk_officer"}),
}


def normalize_role(value: str) -> str:
    return value.strip().casefold().replace(" ", "_").replace("-", "_")


def role_is_allowed(domain: str, reviewer_role: str) -> bool:
    return normalize_role(reviewer_role) in DOMAIN_REVIEW_ROLES.get(
        domain, DOMAIN_REVIEW_ROLES["general_high_risk"]
    )


def evidence_is_current(record: EvidenceRecord, now: datetime | None = None) -> bool:
    current = now or datetime.now(timezone.utc)
    return record.expires_at is None or record.expires_at > current


def medical_red_flag(case: HighRiskRun) -> bool:
    if "medical" not in case.risk_assessment.detected_domains:
        return False
    fact = next((item for item in case.required_facts if item.fact_id == "medical_red_flags"), None)
    if not fact or not fact.value:
        return False
    value = fact.value.casefold().strip()
    explicit_negative = (
        value in {"无", "否", "没有", "none", "no", "no red flags"}
        or value.startswith("无红旗")
        or value.startswith("没有红旗")
        or value.startswith("否认红旗")
    )
    if explicit_negative:
        return False
    markers = (
        "胸痛", "呼吸困难", "意识", "大出血", "抽搐", "中风", "自杀",
        "过量", "休克", "急救", "emergency", "chest pain", "difficulty breathing",
        "unconscious", "bleeding", "seizure", "stroke", "suicide", "overdose",
    )
    negations = ("无", "没有", "否认", "未见", "no ", "not ", "without ")
    for marker in markers:
        start = 0
        while (index := value.find(marker, start)) >= 0:
            prefix = value[max(0, index - 8):index]
            if not any(prefix.endswith(negation) for negation in negations):
                return True
            start = index + len(marker)
    return value == "是" or value.startswith("有红旗") or value.startswith("存在红旗")


def current_approved_professional_reviews(
    case: HighRiskRun, now: datetime | None = None
) -> dict[str, ProfessionalReviewRecord]:
    current = now or datetime.now(timezone.utc)
    latest: dict[str, ProfessionalReviewRecord] = {}
    for review in case.professional_reviews:
        if review.expires_at <= current or review.report_hash != (case.report_hash or ""):
            continue
        latest[review.domain] = review
    return {domain: review for domain, review in latest.items() if review.decision == "approved"}
