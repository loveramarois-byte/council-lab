from __future__ import annotations

import re


PROFESSIONAL_DOMAINS = frozenset({"medical", "legal", "investment"})

DOMAIN_RULES: dict[str, tuple[str, ...]] = {
    "medical": (
        "医疗", "诊断", "症状", "病症", "用药", "药物", "手术", "化疗", "放疗", "停药", "换药", "剂量",
        "处方", "药片", "服药", "癌症", "肿瘤", "急救", "急诊", "重症", "icu", "插管", "medical",
        "diagnosis", "medication", "prescription", "prescribe", "dosage", "dose", "tablet", "tablets",
        "pill", "pills", "metformin", "insulin", "antibiotic", "surgery",
    ),
    "legal": (
        "法律", "诉讼", "合同", "律师", "法域", "仲裁", "起诉", "判决", "违约", "赔偿", "劳动争议",
        "房东", "租客", "驱逐", "legal", "lawsuit", "jurisdiction", "arbitration", "contract dispute",
        "landlord", "tenant", "evict", "eviction",
    ),
    "investment": (
        "投资", "金融", "股票", "基金", "证券", "加密资产", "杠杆", "理财", "贷款", "借贷", "保险", "债务",
        "利率", "收益", "收益率", "亏损", "最大损失", "退休金", "期权", "investment", "financial", "trading",
        "portfolio", "loan", "insurance", "retirement savings", "stock options", "options trading", "call option",
        "call options", "put option", "put options", "nvda",
    ),
    "compliance": (
        "合规", "监管", "审计例外", "政策豁免", "compliance", "regulatory",
    ),
    "production_incident": (
        "生产事故", "线上事故", "生产环境", "生产故障", "数据库泄漏", "incident", "outage", "production",
    ),
}

NON_DOMAIN_COMPOUNDS: dict[str, tuple[str, ...]] = {
    "保险": ("保险箱", "保险柜"),
    "基金": ("基金会",),
}


def _normalized_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def _contains_term(text: str, term: str) -> bool:
    if term.isascii():
        return bool(re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", text))
    compounds = NON_DOMAIN_COMPOUNDS.get(term, ())
    if compounds:
        for compound in compounds:
            text = text.replace(compound, "")
    return term in text


def match_risk_domains(text: str) -> dict[str, list[str]]:
    normalized = _normalized_text(text)
    return {
        domain: [term for term in terms if _contains_term(normalized, term)]
        for domain, terms in DOMAIN_RULES.items()
    }


def detect_risk_domains(text: str) -> list[str]:
    return [domain for domain, matches in match_risk_domains(text).items() if matches]


def detect_professional_domains(text: str) -> list[str]:
    return [domain for domain in detect_risk_domains(text) if domain in PROFESSIONAL_DOMAINS]
