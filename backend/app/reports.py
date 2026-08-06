from __future__ import annotations

from html import escape

from .decision_assurance import DecisionClaimView
from .models import DecisionBrief, RunRecord
from .risk.schemas import HighRiskRun


def _high_risk_summary(case: HighRiskRun) -> tuple[int, int, str]:
    completed = sum(1 for fact in case.required_facts if fact.value)
    total = len(case.required_facts)
    domains = "、".join(case.risk_assessment.detected_domains) or "未分类"
    return completed, total, domains


def _decision_brief_markdown(brief: DecisionBrief) -> list[str]:
    status_labels = {"proceed": "可以推进", "conditional": "满足条件后推进", "no_decision": "暂不形成决定"}
    support_labels = {"unanimous": "一致支持", "majority": "多数支持", "contested": "存在明确反对"}
    lines = [
        "## 结构化决策简报",
        "",
        f"- 简报版本：v{brief.version} / schema v{brief.schema_version}",
        f"- 决策状态：{status_labels[brief.status]}",
        f"- 席位支持：{support_labels[brief.support]}（只表示公开表态，不代表事实正确概率）",
        "",
        "### 当前建议",
        "",
        brief.recommendation,
        "",
    ]
    sections = (
        ("决定性理由", [item.summary for item in brief.decisive_reasons]),
        ("被否决的备选项", [f"{item.option} — {item.reason}" for item in brief.rejected_alternatives]),
        ("尚未解决的问题", [f"{'[阻塞] ' if item.blocking else ''}{item.issue}" for item in brief.unresolved]),
        ("假设与依据", [f"{item.claim}（依据：{item.basis}）" for item in brief.assumptions]),
        ("下一步行动", [item.action for item in brief.actions]),
        ("重新审议条件", [f"{item.condition}（{item.severity}）" for item in brief.reopen_triggers]),
    )
    for heading, items in sections:
        if items:
            lines.extend([f"### {heading}", "", *[f"- {item}" for item in items], ""])
    if brief.minority_report:
        lines.extend([
            "### 少数意见",
            "",
            f"- 反对席位：{', '.join(brief.minority_report.seat_ids)}",
            f"- 意见：{brief.minority_report.summary}",
            "",
        ])
    lines.extend(_contract_extension_markdown(brief))
    lines.extend(["### 限制", "", *[f"- {item}" for item in brief.limitations], ""])
    return lines


def _contract_extension_markdown(brief: DecisionBrief) -> list[str]:
    extension = brief.contract_extension
    if extension is None:
        return []
    if extension.contract == "product_review":
        lines = ["### 产品评审契约", "", f"- 用户问题：{extension.user_problem}", f"- 价值主张：{extension.value_proposition}"]
        sections = (
            ("目标用户", extension.target_users),
            ("失败条件", extension.failure_conditions),
            ("停止条件", extension.stop_conditions),
        )
        for label, items in sections:
            lines.extend(f"- {label}：{item}" for item in items)
        for item in extension.validation_experiments:
            lines.append(
                f"- 验证实验：{item.hypothesis}；方法：{item.method}；成功阈值：{item.success_threshold}"
            )
        return [*lines, ""]
    if extension.contract == "technical_architecture":
        lines = ["### 技术架构评审契约", "", f"- 建议架构：{extension.proposed_architecture}"]
        sections = (
            ("需求", extension.requirements),
            ("约束", extension.constraints),
            ("故障模式", extension.failure_modes),
            ("迁移计划", extension.migration_plan),
            ("回滚计划", extension.rollback_plan),
            ("可观测性", extension.observability_requirements),
        )
        for label, items in sections:
            lines.extend(f"- {label}：{item}" for item in items)
        for item in extension.alternatives:
            lines.append(f"- 备选架构：{item.option}；取舍：{'；'.join(item.tradeoffs)}")
        return [*lines, ""]
    if extension.contract in {"medical_second_opinion", "legal_risk_review", "financial_decision_review"}:
        labels = {
            "medical_second_opinion": "医疗信息整理契约",
            "legal_risk_review": "法律风险梳理契约",
            "financial_decision_review": "财务决策分析契约",
        }
        lines = [f"### {labels[extension.contract]}", "", f"- 范围：{extension.scope}"]
        sections = (
            ("已核验信息", extension.verified_information),
            ("未核验信息", extension.unverified_information),
            ("风险因素", extension.risk_factors),
            ("专业确认问题", extension.professional_questions),
        )
        for label, values in sections:
            lines.extend(f"- {label}：{item}" for item in values)
        lines.extend([f"- 免责声明：{extension.required_disclaimer}", ""])
        return lines
    return [
        "### 一般决策契约",
        "",
        *[f"- 决策标准：{item}" for item in extension.decision_criteria],
        *[f"- 关键取舍：{item}" for item in extension.key_tradeoffs],
        "",
    ]


_CLAIM_BASIS_LABELS = {
    "user_provided": "用户提供",
    "model_inference": "模型推断",
    "cited_unverified": "有引用，未核验",
    "seat_disputed": "席位间有争议",
    "outcome_supported": "后续结果支持",
    "outcome_contradicted": "后续结果反驳",
}


def _decision_claims_markdown(claims: list[DecisionClaimView]) -> list[str]:
    if not claims:
        return []
    lines = ["## 关键主张与依据", ""]
    for item in claims:
        label = _CLAIM_BASIS_LABELS[item.current_basis]
        lines.append(f"- **{label}**：{item.claim.text}")
        if item.claim.citation:
            lines.append(
                f"  - 引用：{item.claim.citation.url}（{item.claim.citation.provided_by} 提供，未外部核验）"
            )
        if item.claim.dispute_summary:
            lines.append(f"  - 争议：{item.claim.dispute_summary}")
        if item.latest_outcome and item.latest_outcome.note:
            lines.append(f"  - 回访依据：{item.latest_outcome.note}")
    lines.append("")
    return lines


def run_markdown(
    run: RunRecord,
    high_risk: HighRiskRun | None = None,
    decision_brief: DecisionBrief | None = None,
    decision_claims: list[DecisionClaimView] | None = None,
) -> str:
    lines = [
        f"# {run.question}",
        "",
        f"- 状态：{run.status}",
        f"- 模式：{run.mode}",
        f"- 模板：{run.template_name}",
        f"- 资料空间：{run.project_name or '无'}",
        f"- 创建时间：{run.created_at.isoformat()}",
        f"- 发言策略：{'先独立初答' if run.workflow_strategy == 'independent' else '连续审议'}",
        f"- 模型调用：{run.usage.model_calls}",
        f"- Token：{run.usage.input_tokens + run.usage.output_tokens}",
        "",
    ]
    if high_risk:
        completed, total, domains = _high_risk_summary(high_risk)
        assurance = high_risk.assurance
        lines.extend([
            "## 高风险决策支持状态",
            "",
            "> 非约束性决策支持；证据核验和专业角色均以本地记录为准，专业角色为复核人声明而非系统执照验证。不得直接用于开药、交易、法律提交、合规放行或生产变更。",
            "",
            f"- 控制状态：{high_risk.status}",
            f"- 风险等级：{high_risk.risk_assessment.risk_tier}",
            f"- 检测领域：{domains}",
            f"- 关键事实：{completed}/{total} 已填写",
            f"- 证据门禁：{'完整且当前有效' if assurance.evidence_complete and assurance.evidence_current else '未满足'}",
            f"- 证据冲突：{'有' if assurance.evidence_conflict else '无'}",
            f"- 专业复核：{'已覆盖全部领域' if assurance.professional_review_complete else '未完成或已过期'}",
            f"- 医疗紧急红旗：{'有，必须升级' if assurance.medical_red_flag else '未触发'}",
            "",
        ])
        for fact in high_risk.required_facts:
            source = fact.source_title or "未记录来源"
            timestamp = fact.source_timestamp.isoformat() if fact.source_timestamp else "无时间戳"
            lines.append(f"- {fact.name}：{fact.verification_status}；来源：{source}；时间：{timestamp}")
        if high_risk.required_facts:
            lines.append("")
    if run.source_snapshots:
        lines.extend(["## 资料快照", ""])
        for index, source in enumerate(run.source_snapshots, 1):
            origin = source.url or source.filename or "本地文字资料"
            lines.extend([
                f"### [S{index}] {source.title}",
                "",
                f"来源：{origin}  ",
                f"SHA-256：`{source.sha256}`",
                "",
                source.content,
                "",
            ])
    if decision_brief:
        lines.extend(_decision_brief_markdown(decision_brief))
    lines.extend(_decision_claims_markdown(decision_claims or []))
    lines.extend(["## 公开讨论", ""])
    for turn in run.discussion_turns:
        provider = f" · {turn.provider_name} / {turn.model}" if turn.provider_name else ""
        lines.extend([f"### {turn.speaker_name} · {turn.role_label}{provider}", "", turn.content, ""])
    if run.final_decision:
        lines.extend([
            "## 圆桌最终答案",
            "",
            "> **未经过外部事实核验。** 模型共识不等于事实；关键结论请使用第一方资料或可复现测试核对。",
            "",
            run.final_decision.final_answer,
            "",
        ])
        if run.final_decision.disagreements:
            lines.extend(["### 保留分歧", ""] + [f"- {item}" for item in run.final_decision.disagreements] + [""])
        if run.final_decision.risks_and_limitations:
            lines.extend(["### 风险与限制", ""] + [f"- {item}" for item in run.final_decision.risks_and_limitations] + [""])
    if run.decision_review:
        review = run.decision_review
        lines.extend([
            "## 决策回访",
            "",
            f"- 最终选择：{review.selected_decision}",
            f"- 预期结果：{review.expected_result}",
            f"- 复盘日期：{review.review_date.isoformat() if review.review_date else '未设置'}",
            f"- 结果状态：{review.outcome_status}",
            f"- 实际结果：{review.actual_result or '尚未填写'}",
            "",
        ])
        if review.seat_outcomes:
            lines.extend(["### 席位观点验证", ""])
            lines.extend(f"- {item.role}: {item.status}" + (f" — {item.note}" if item.note else "") for item in review.seat_outcomes)
            lines.append("")
    lines.extend([
        "---",
        "由 Council Lab 导出。模型共识不等于事实验证；关键结论请核对第一方资料。",
        "",
    ])
    return "\n".join(lines)


def _decision_brief_html(brief: DecisionBrief) -> str:
    status_labels = {"proceed": "可以推进", "conditional": "满足条件后推进", "no_decision": "暂不形成决定"}
    support_labels = {"unanimous": "一致支持", "majority": "多数支持", "contested": "存在明确反对"}

    def list_items(items: list[str]) -> str:
        return f"<ul>{''.join(f'<li>{escape(item)}</li>' for item in items)}</ul>" if items else ""

    sections = "".join(
        f"<h3>{escape(heading)}</h3>{list_items(items)}"
        for heading, items in (
            ("决定性理由", [item.summary for item in brief.decisive_reasons]),
            ("尚未解决的问题", [f"{'[阻塞] ' if item.blocking else ''}{item.issue}" for item in brief.unresolved]),
            ("假设与依据", [f"{item.claim}（依据：{item.basis}）" for item in brief.assumptions]),
            ("下一步行动", [item.action for item in brief.actions]),
            ("重新审议条件", [f"{item.condition}（{item.severity}）" for item in brief.reopen_triggers]),
        )
        if items
    )
    minority = ""
    if brief.minority_report:
        minority = (
            "<h3>少数意见</h3>"
            f"<p><strong>反对席位：</strong>{escape(', '.join(brief.minority_report.seat_ids))}</p>"
            f"<p>{escape(brief.minority_report.summary).replace(chr(10), '<br>')}</p>"
        )
    contract_extension = _contract_extension_html(brief)
    return (
        "<section class='decision-brief'><h2>结构化决策简报</h2>"
        f"<p><strong>决策状态：</strong>{escape(status_labels[brief.status])} · "
        f"<strong>席位支持：</strong>{escape(support_labels[brief.support])}</p>"
        "<p class='support-note'>支持度只表示公开表态，不代表事实正确概率。</p>"
        f"<h3>当前建议</h3><p>{escape(brief.recommendation).replace(chr(10), '<br>')}</p>"
        f"{sections}{minority}{contract_extension}<h3>限制</h3>{list_items(brief.limitations)}</section>"
    )


def _contract_extension_html(brief: DecisionBrief) -> str:
    extension = brief.contract_extension
    if extension is None:
        return ""

    def items(values: list[str]) -> str:
        return f"<ul>{''.join(f'<li>{escape(item)}</li>' for item in values)}</ul>" if values else ""

    if extension.contract == "product_review":
        experiments = [
            f"{item.hypothesis}；方法：{item.method}；成功阈值：{item.success_threshold}"
            for item in extension.validation_experiments
        ]
        return (
            "<section class='contract-extension'><h3>产品评审契约</h3>"
            f"<p><strong>用户问题：</strong>{escape(extension.user_problem)}</p>"
            f"<p><strong>价值主张：</strong>{escape(extension.value_proposition)}</p>"
            f"<h4>目标用户</h4>{items(extension.target_users)}"
            f"<h4>失败条件</h4>{items(extension.failure_conditions)}"
            f"<h4>验证实验</h4>{items(experiments)}"
            f"<h4>停止条件</h4>{items(extension.stop_conditions)}</section>"
        )
    if extension.contract == "technical_architecture":
        alternatives = [f"{item.option}：{'；'.join(item.tradeoffs)}" for item in extension.alternatives]
        return (
            "<section class='contract-extension'><h3>技术架构评审契约</h3>"
            f"<p><strong>建议架构：</strong>{escape(extension.proposed_architecture)}</p>"
            f"<h4>需求</h4>{items(extension.requirements)}"
            f"<h4>约束</h4>{items(extension.constraints)}"
            f"<h4>备选架构</h4>{items(alternatives)}"
            f"<h4>故障模式</h4>{items(extension.failure_modes)}"
            f"<h4>迁移计划</h4>{items(extension.migration_plan)}"
            f"<h4>回滚计划</h4>{items(extension.rollback_plan)}"
            f"<h4>可观测性</h4>{items(extension.observability_requirements)}</section>"
        )
    if extension.contract in {"medical_second_opinion", "legal_risk_review", "financial_decision_review"}:
        labels = {
            "medical_second_opinion": "医疗信息整理契约",
            "legal_risk_review": "法律风险梳理契约",
            "financial_decision_review": "财务决策分析契约",
        }
        return (
            f"<section class='contract-extension'><h3>{escape(labels[extension.contract])}</h3>"
            f"<p><strong>范围：</strong>{escape(extension.scope)}</p>"
            f"<h4>已核验信息</h4>{items(extension.verified_information)}"
            f"<h4>未核验信息</h4>{items(extension.unverified_information)}"
            f"<h4>风险因素</h4>{items(extension.risk_factors)}"
            f"<h4>专业确认问题</h4>{items(extension.professional_questions)}"
            f"<p><strong>免责声明：</strong>{escape(extension.required_disclaimer)}</p></section>"
        )
    return (
        "<section class='contract-extension'><h3>一般决策契约</h3>"
        f"<h4>决策标准</h4>{items(extension.decision_criteria)}"
        f"<h4>关键取舍</h4>{items(extension.key_tradeoffs)}</section>"
    )


def _decision_claims_html(claims: list[DecisionClaimView]) -> str:
    if not claims:
        return ""
    items: list[str] = []
    for item in claims:
        details = []
        if item.claim.citation:
            details.append(
                f"<small>引用：{escape(item.claim.citation.url)}（{escape(item.claim.citation.provided_by)} 提供，未外部核验）</small>"
            )
        if item.claim.dispute_summary:
            details.append(f"<small>争议：{escape(item.claim.dispute_summary)}</small>")
        if item.latest_outcome and item.latest_outcome.note:
            details.append(f"<small>回访依据：{escape(item.latest_outcome.note)}</small>")
        items.append(
            "<li>"
            f"<strong>{escape(_CLAIM_BASIS_LABELS[item.current_basis])}</strong>：{escape(item.claim.text)}"
            f"{''.join(details)}</li>"
        )
    return f"<section class='decision-claims'><h2>关键主张与依据</h2><ul>{''.join(items)}</ul></section>"


def run_html(
    run: RunRecord,
    high_risk: HighRiskRun | None = None,
    decision_brief: DecisionBrief | None = None,
    decision_claims: list[DecisionClaimView] | None = None,
) -> str:
    transcript = "".join(
        f"<article><h3>{escape(turn.speaker_name)} <small>{escape(turn.role_label)}</small></h3>"
        f"<p>{escape(turn.content).replace(chr(10), '<br>')}</p></article>"
        for turn in run.discussion_turns
    )
    sources = "".join(
        f"<article class='source'><h3>[S{index}] {escape(source.title)}</h3><span>{escape(source.url or source.filename or '本地文字资料')}</span>"
        f"<br><code>{escape(source.sha256)}</code><pre>{escape(source.content)}</pre></article>"
        for index, source in enumerate(run.source_snapshots, 1)
    )
    answer = (
        "<section class='answer'><h2>圆桌最终答案</h2>"
        "<aside class='verification-warning'><strong>未经过外部事实核验。</strong> "
        "模型共识不等于事实；关键结论请使用第一方资料或可复现测试核对。</aside>"
        f"<p>{escape(run.final_decision.final_answer).replace(chr(10), '<br>')}</p></section>"
        if run.final_decision
        else ""
    )
    high_risk_section = ""
    if high_risk:
        completed, total, domains = _high_risk_summary(high_risk)
        assurance = high_risk.assurance
        fact_rows = "".join(
            f"<li>{escape(fact.name)}：{escape(fact.verification_status)}；来源：{escape(fact.source_title or '未记录来源')}；时间：{escape(fact.source_timestamp.isoformat() if fact.source_timestamp else '无时间戳')}</li>"
            for fact in high_risk.required_facts
        )
        high_risk_section = (
            "<section class='high-risk'><h2>高风险决策支持状态</h2>"
            "<p><strong>非约束性决策支持；证据核验和专业角色均以本地记录为准，专业角色为复核人声明而非系统执照验证。"
            "不得直接用于开药、交易、法律提交、合规放行或生产变更。</strong></p>"
            f"<ul><li>控制状态：{escape(high_risk.status)}</li>"
            f"<li>风险等级：{escape(high_risk.risk_assessment.risk_tier)}</li>"
            f"<li>检测领域：{escape(domains)}</li>"
            f"<li>关键事实：{completed}/{total} 已填写</li>"
            f"<li>证据门禁：{'完整且当前有效' if assurance.evidence_complete and assurance.evidence_current else '未满足'}</li>"
            f"<li>证据冲突：{'有' if assurance.evidence_conflict else '无'}</li>"
            f"<li>专业复核：{'已覆盖全部领域' if assurance.professional_review_complete else '未完成或已过期'}</li>"
            f"<li>医疗紧急红旗：{'有，必须升级' if assurance.medical_red_flag else '未触发'}</li>"
            f"</ul><h3>关键事实证据状态</h3><ul>{fact_rows}</ul></section>"
        )
    review = ""
    if run.decision_review:
        item = run.decision_review
        seats = "".join(
            f"<li>{escape(seat.role)}: {escape(seat.status)}{f' — {escape(seat.note)}' if seat.note else ''}</li>"
            for seat in item.seat_outcomes
        )
        review = (
            "<section class='review'><h2>决策回访</h2>"
            f"<p><strong>最终选择：</strong>{escape(item.selected_decision)}</p>"
            f"<p><strong>预期结果：</strong>{escape(item.expected_result)}</p>"
            f"<p><strong>复盘日期：</strong>{item.review_date.isoformat() if item.review_date else '未设置'}</p>"
            f"<p><strong>实际结果：</strong>{escape(item.actual_result or '尚未填写')}</p>"
            f"<p><strong>结果状态：</strong>{escape(item.outcome_status)}</p>"
            f"{f'<ul>{seats}</ul>' if seats else ''}</section>"
        )
    brief_section = _decision_brief_html(decision_brief) if decision_brief else ""
    claims_section = _decision_claims_html(decision_claims or [])
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(run.question)} · Council</title><style>
    body{{max-width:860px;margin:48px auto;padding:0 24px;color:#292724;font:15px/1.7 system-ui,-apple-system,'Segoe UI',sans-serif;background:#f7f3ee}}
    header,.answer,article,.sources,.review,.high-risk,.decision-brief,.decision-claims{{background:#fffdf9;border:1px solid #ded7cd;padding:22px 26px;margin:0 0 14px;border-radius:7px}}h1{{font:400 30px/1.25 Georgia,serif}}h2{{font:500 20px Georgia,serif}}h3{{font-size:15px;margin:18px 0 9px}}small,header p,.sources span,.support-note,.decision-claims small{{display:block;color:#756f67}}p{{white-space:normal}}.answer{{border-left:4px solid #c76645}}.decision-brief{{border-left:4px solid #456d64}}.decision-claims{{border-left:4px solid #987137}}.decision-claims li{{margin:10px 0}}.verification-warning{{background:#fff4df;border:1px solid #d9a54b;color:#61420d;padding:12px 14px;margin:0 0 16px;border-radius:5px}}.high-risk{{border-left:4px solid #a8333e}}code{{font-size:11px;color:#756f67}}pre{{white-space:pre-wrap;font:13px/1.6 ui-monospace,monospace;border-top:1px solid #e6dfd5;padding-top:14px}}footer{{color:#756f67;font-size:12px;padding:18px 0}}
</style></head><body><header><h1>{escape(run.question)}</h1><p>{escape(run.template_name)} · {escape('先独立初答' if run.workflow_strategy == 'independent' else '连续审议')} · {escape(run.project_name or '独立审议')} · {run.created_at.date().isoformat()}</p></header>
    {high_risk_section}{f"<section class='sources'><h2>资料快照</h2>{sources}</section>" if sources else ""}
    {brief_section}{claims_section}<section><h2>公开讨论</h2>{transcript}</section>{answer}{review}<footer>由 Council Lab 导出。模型共识不等于事实验证；关键结论请核对第一方资料。</footer></body></html>"""
