from __future__ import annotations

from ..domain_rules import match_risk_domains
from .schemas import RequiredFact, RiskAssessment


CLASSIFIER_VERSION = "high-risk-rules-v3"

CRITICAL_MARKERS = (
    "紧急", "立即", "急救", "自杀", "大出血", "删除证据", "数据泄漏",
    "重大事故", "全站故障", "不可逆", "emergency", "suicide", "breach",
)

DOMAIN_FACTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "medical": (
        ("medical_context", "医疗背景", "年龄、症状时间线、关键病史、当前用药和过敏情况。"),
        ("medical_diagnosis_evidence", "诊断与检查依据", "诊断或疑似诊断、检查原文、检查日期和医疗机构。"),
        ("medical_treatment_plan", "当前治疗计划", "当前治疗、剂量、疗程和主治医师已说明的目标与风险。"),
        ("medical_red_flags", "紧急红旗", "是否存在需要立即就医或急救的红旗症状。"),
    ),
    "legal": (
        ("legal_jurisdiction", "司法辖区", "适用国家、地区和具体司法辖区。"),
        ("legal_source_document", "文件与核心条款", "合同、通知或裁判文书的完整原文、签署主体和核心条款。"),
        ("legal_timeline", "事项时间与阶段", "关键日期、程序阶段和适用规则版本。"),
    ),
    "investment": (
        ("investment_decision_type", "财务决策类型", "投资、借贷、保险或其他类型，以及当事方和产品名称。"),
        ("investment_amounts", "金额与计算口径", "金额、币种、期限、年化或月化、税前或税后、费用和现金流。"),
        ("investment_constraints", "投资约束", "目标、期限、流动性、损失承受力、杠杆和集中度。"),
        ("investment_maximum_loss", "最大损失", "可承受的最大损失金额或比例，以及触发停止的条件。"),
        ("investment_data_time", "数据时间戳", "价格和财务数据的来源与时间。"),
    ),
    "compliance": (
        ("compliance_scope", "合规范围", "法域、适用主体、政策版本和控制责任人。"),
        ("compliance_evidence", "控制证据", "控制、证据、缺口和例外批准链。"),
    ),
    "production_incident": (
        ("incident_observations", "已观察事实", "指标、日志、时间线和客户影响，不包含未经验证的根因。"),
        ("incident_rollback", "回滚与证据边界", "回滚条件、证据保留和审批责任人。"),
    ),
    "general_high_risk": (
        ("decision_context", "关键决策背景", "目标、约束、责任主体和不可逆影响。"),
    ),
}


def assess_risk(question: str, run_id: str) -> RiskAssessment:
    lower = question.casefold()
    matched = match_risk_domains(question)
    domains = [domain for domain, markers in matched.items() if markers]
    if not domains:
        domains = ["general_high_risk"]
    critical = any(marker in lower for marker in CRITICAL_MARKERS)
    tier = "critical" if critical else "high"
    reasons = [
        f"检测到高风险领域：{domain}（规则命中 {len(matched.get(domain, []))} 项）"
        for domain in domains
    ]
    if critical:
        reasons.append("检测到紧急、重大或不可逆影响信号")
    return RiskAssessment(
        run_id=run_id,
        risk_tier=tier,
        original_risk_tier=tier,
        detected_domains=domains,
        reasons=reasons,
        classifier_version=CLASSIFIER_VERSION,
        confidence=min(0.95, 0.55 + sum(len(matched.get(domain, [])) for domain in domains) * 0.1),
        requires_user_confirmation=True,
    )


def required_facts_for(assessment: RiskAssessment) -> list[RequiredFact]:
    seen: set[str] = set()
    facts: list[RequiredFact] = []
    for domain in assessment.detected_domains:
        for fact_id, name, description in DOMAIN_FACTS.get(domain, DOMAIN_FACTS["general_high_risk"]):
            if fact_id in seen:
                continue
            seen.add(fact_id)
            facts.append(
                RequiredFact(
                    fact_id=fact_id,
                    name=name,
                    description=description,
                    required=True,
                    materiality="critical",
                )
            )
    return facts


def domain_for_fact_id(fact_id: str) -> str | None:
    for domain, definitions in DOMAIN_FACTS.items():
        if any(candidate_id == fact_id for candidate_id, _name, _description in definitions):
            return domain
    return None
