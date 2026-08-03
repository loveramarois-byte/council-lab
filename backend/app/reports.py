from __future__ import annotations

from html import escape

from .decision_assurance import DecisionClaimView
from .models import DecisionBrief, RunRecord
from .risk.schemas import HighRiskRun
from .traditional_references import TRADITIONAL_REFERENCE_BOOKS_BY_ID
from .traditional_rules import get_traditional_rule_profile


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


def _traditional_snapshot_markdown(run: RunRecord) -> list[str]:
    snapshot = run.traditional_culture_snapshot
    if snapshot is None:
        return []
    profile, facts, chart = snapshot.profile, snapshot.calendar_facts, snapshot.ziwei_chart
    timing = snapshot.timing_facts
    framework = get_traditional_rule_profile(profile.interpretation_framework)
    references = [TRADITIONAL_REFERENCE_BOOKS_BY_ID[item] for item in profile.reference_book_ids]
    reference_lines = []
    for item in references:
        alias = f"（{item['alias']}）" if item["alias"] else ""
        source = item["source"]
        source_link = f" ([来源]({source['url']}))" if source["url"] else ""
        reference_lines.append(
            f"- {item['title']}{alias}：{item['focus']} · {item['tradition']} · "
            f"资料状态：{source['label']}{source_link}"
        )
    if not reference_lines:
        reference_lines = ["- 未选择参考典籍"]
    lines = [
        "## 传统文化本地计算快照",
        "",
        "> 排盘字段来自版本化本地开源引擎，可按相同输入复现；传统解释、预测和流派判断不属于科学验证，不得用于医疗、法律、投资、合规或生产决策。",
        "",
        f"- 输入：{profile.birth_date.isoformat()} {profile.birth_time}；排盘参数：{'男' if profile.gender == 'male' else '女'}；时间精度：{'准确' if profile.time_precision == 'exact' else '约数'}",
        f"- 时区：{profile.timezone} 民用时；出生地：{profile.birth_place_normalized + '（城市级）' if profile.birth_place_normalized else '未识别'}",
        f"- 坐标来源：{profile.birth_place_source}",
        f"- 出生民用时：{facts.civil_solar_datetime or facts.solar_datetime}；真太阳时：{facts.true_solar_datetime or '未应用'}；校正分钟：{facts.true_solar_time_offset_minutes if facts.true_solar_time_offset_minutes is not None else '无'}",
        f"- 固定解释体系：{framework['label']}（{framework['version']}）",
        f"- 公历：{facts.solar_datetime}",
        f"- 农历：{facts.lunar_date}；生肖：{facts.zodiac}；星座：{facts.constellation}",
        f"- 四柱：{facts.eight_char}",
        f"- 出生日柱：{facts.pillars[2]}；出生时辰：{chart.time_label}（{chart.time_range}）；出生时柱：{facts.pillars[3]}",
        f"- 柱五行：{' / '.join(facts.pillar_wuxing)}",
        f"- 天干十神：{' / '.join(facts.heavenly_stem_ten_gods)}",
        f"- 紫微：{chart.five_elements_class}；命主：{chart.soul_star}；身主：{chart.body_star}；命宫地支：{chart.soul_palace_branch}；身宫地支：{chart.body_palace_branch}",
        "",
        "### 参考典籍索引",
        "",
        "> 仅记录研究方向，不代表 Council 已读取或引用典籍原文。",
        *reference_lines,
        "",
        "### 固定解释规则",
        "",
        f"- 适用范围：{framework['scope']}",
        *[f"- {index + 1}. {step}" for index, step in enumerate(framework["steps"])],
        f"- 体系要求：{framework['instruction']}",
        *[f"- 限制：{item}" for item in framework["limitations"]],
        f"- 快照 SHA-256：`{snapshot.snapshot_sha256}`",
        "",
        "### 计算引擎与来源",
        "",
        *[f"- [{engine.id}@{engine.version}]({engine.source_url}) · {engine.license}" for engine in snapshot.engines],
        "",
        "### 紫微十二宫",
        "",
    ]
    if timing is not None:
        time_provider = {"https_consensus": "HTTPS 多源校时", "timeapi.io": "历史单源时间记录"}.get(
            timing.time_provider, timing.time_provider
        )
        lines[14:14] = [
            f"- 咨询时刻：{timing.reference_civil_datetime}；时间来源：{time_provider}（{'联网已同步' if timing.synced else '本机时钟回退'}）",
            f"- 咨询排盘时刻：{timing.reference_true_solar_datetime}；按 Asia/Shanghai 民用时计算（未采集咨询地点，不复用出生地经度）",
            f"- 流年：{timing.year_pillar}；流月：{timing.month_pillar}；流日：{timing.day_pillar}；流时：{timing.hour_pillar}",
            f"- 节气交接：{timing.previous_solar_term.name} {timing.previous_solar_term.datetime} -> {timing.next_solar_term.name} {timing.next_solar_term.datetime}",
        ]
    for palace in chart.palaces:
        markers = [label for enabled, label in ((palace.is_original_palace, "来因宫"), (palace.is_body_palace, "身宫")) if enabled]
        marker = f"（{'、'.join(markers)}）" if markers else ""
        lines.append(f"- {palace.name}{marker} · {palace.heavenly_stem}{palace.earthly_branch} · {('、'.join(palace.major_stars) or '无主星')}")
    return [*lines, ""]


def run_markdown(
    run: RunRecord,
    high_risk: HighRiskRun | None = None,
    decision_brief: DecisionBrief | None = None,
    decision_claims: list[DecisionClaimView] | None = None,
) -> str:
    successful_attempts = sum(1 for item in run.provider_attempts if item.status_code is not None and 200 <= item.status_code < 300)
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
        f"- 实际 API 请求：{len(run.provider_attempts)}（成功 {successful_attempts}）" if run.provider_attempts else "- 实际 API 请求：旧记录未采集",
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
    lines.extend(_traditional_snapshot_markdown(run))
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
        traditional = run.council_mode == "traditional_culture"
        lines.extend([
            "## 传统文化联合研判" if traditional else "## 圆桌最终答案",
            "",
            "> **传统解释不属于科学验证。** 本地计算可复现，但解释、预测和流派判断不能作为高风险决策依据。"
            if traditional
            else "> **未经过外部事实核验。** 模型共识不等于事实；关键结论请使用第一方资料或可复现测试核对。",
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


def _traditional_snapshot_html(run: RunRecord) -> str:
    snapshot = run.traditional_culture_snapshot
    if snapshot is None:
        return ""
    profile, facts, chart = snapshot.profile, snapshot.calendar_facts, snapshot.ziwei_chart
    framework = get_traditional_rule_profile(profile.interpretation_framework)
    references = [TRADITIONAL_REFERENCE_BOOKS_BY_ID[item] for item in profile.reference_book_ids]
    engines = "".join(
        f"<li><a href='{escape(engine.source_url)}'>{escape(engine.id)}@{escape(engine.version)}</a> · {escape(engine.license)}</li>"
        for engine in snapshot.engines
    )
    palaces = "".join(
        "<li>"
        f"<strong>{escape(palace.name)}</strong>"
        f"{'（来因宫）' if palace.is_original_palace else ''}{'（身宫）' if palace.is_body_palace else ''} · "
        f"{escape(palace.heavenly_stem + palace.earthly_branch)} · {escape('、'.join(palace.major_stars) or '无主星')}</li>"
        for palace in chart.palaces
    )
    reference_items = []
    for item in references:
        alias = f"（{escape(item['alias'])}）" if item["alias"] else ""
        source = item["source"]
        source_link = f" · <a href='{escape(source['url'], quote=True)}'>查看来源</a>" if source["url"] else ""
        reference_items.append(
            f"<li>{escape(item['title'])}{alias} · {escape(item['focus'])} · {escape(item['tradition'])} · "
            f"资料状态：{escape(source['label'])}{source_link}</li>"
        )
    reference_html = "".join(reference_items) or "<li>未选择参考典籍</li>"
    framework_steps = "".join(f"<li>{escape(step)}</li>" for step in framework["steps"])
    framework_limits = "".join(f"<li>{escape(item)}</li>" for item in framework["limitations"])
    timing = snapshot.timing_facts
    timing_html = ""
    if timing is not None:
        time_provider = {"https_consensus": "HTTPS 多源校时", "timeapi.io": "历史单源时间记录"}.get(
            timing.time_provider, timing.time_provider
        )
        timing_html = (
            f"<p><strong>咨询时刻：</strong>{escape(timing.reference_civil_datetime)} · "
            f"{escape(time_provider)}（{'联网已同步' if timing.synced else '本机时钟回退'}）<br>"
            f"<strong>咨询排盘时刻：</strong>{escape(timing.reference_true_solar_datetime)} · Asia/Shanghai 民用时（未采集咨询地点）</p>"
            f"<p><strong>流年：</strong>{escape(timing.year_pillar)} · <strong>流月：</strong>{escape(timing.month_pillar)} · "
            f"<strong>流日：</strong>{escape(timing.day_pillar)} · <strong>流时：</strong>{escape(timing.hour_pillar)}<br>"
            f"<strong>节气交接：</strong>{escape(timing.previous_solar_term.name)} {escape(timing.previous_solar_term.datetime)} → "
            f"{escape(timing.next_solar_term.name)} {escape(timing.next_solar_term.datetime)}</p>"
        )
    return (
        "<section class='traditional-snapshot'><h2>传统文化本地计算快照</h2>"
        "<aside class='verification-warning'><strong>计算字段可复现，传统解释不属于科学验证。</strong> "
        "不得用于医疗、法律、投资、合规或生产决策。</aside>"
        f"<p><strong>输入：</strong>{profile.birth_date.isoformat()} {escape(profile.birth_time)} · {'男' if profile.gender == 'male' else '女'} · "
        f"{'准确时间' if profile.time_precision == 'exact' else '约数时间'} · {escape(profile.timezone)} 民用时</p>"
        f"<p><strong>出生地：</strong>{escape(profile.birth_place_normalized + '（城市级）' if profile.birth_place_normalized else '未识别')}<br>"
        f"<strong>出生民用时：</strong>{escape(facts.civil_solar_datetime or facts.solar_datetime)} · "
        f"<strong>真太阳时：</strong>{escape(facts.true_solar_datetime or '未应用')}</p>"
        f"<p><strong>固定解释体系：</strong>{escape(framework['label'])}（{escape(framework['version'])}）</p>"
        f"<p><strong>公历：</strong>{escape(facts.solar_datetime)}<br><strong>农历：</strong>{escape(facts.lunar_date)} · {escape(facts.zodiac)} · {escape(facts.constellation)}</p>"
        f"<p><strong>四柱：</strong>{escape(facts.eight_char)}<br><strong>日柱：</strong>{escape(facts.pillars[2])} · <strong>时辰：</strong>{escape(chart.time_label)}（{escape(chart.time_range)}） · <strong>时柱：</strong>{escape(facts.pillars[3])}<br><strong>柱五行：</strong>{escape(' / '.join(facts.pillar_wuxing))}<br><strong>天干十神：</strong>{escape(' / '.join(facts.heavenly_stem_ten_gods))}</p>"
        f"{timing_html}"
        f"<p><strong>紫微：</strong>{escape(chart.five_elements_class)} · 命主 {escape(chart.soul_star)} · 身主 {escape(chart.body_star)} · 命宫 {escape(chart.soul_palace_branch)} · 身宫 {escape(chart.body_palace_branch)}</p>"
        "<h3>参考典籍索引</h3><p><small>仅记录研究方向，不代表 Council 已读取或引用典籍原文。</small></p>"
        f"<ul>{reference_html}</ul>"
        f"<h3>固定解释规则</h3><p>{escape(framework['scope'])}</p><ol>{framework_steps}</ol>"
        f"<p><strong>体系要求：</strong>{escape(framework['instruction'])}</p><ul>{framework_limits}</ul>"
        f"<p><strong>快照 SHA-256：</strong><code>{escape(snapshot.snapshot_sha256)}</code></p>"
        f"<h3>计算引擎与来源</h3><ul>{engines}</ul><h3>紫微十二宫</h3><ul>{palaces}</ul></section>"
    )


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
    traditional = run.council_mode == "traditional_culture"
    successful_attempts = sum(1 for item in run.provider_attempts if item.status_code is not None and 200 <= item.status_code < 300)
    request_summary = (
        f" · 实际 API 请求 {len(run.provider_attempts)}（成功 {successful_attempts}）"
        if run.provider_attempts
        else " · 实际 API 请求：旧记录未采集"
    )
    answer = (
        f"<section class='answer'><h2>{'传统文化联合研判' if traditional else '圆桌最终答案'}</h2>"
        + (
            "<aside class='verification-warning'><strong>传统解释不属于科学验证。</strong> "
            "本地计算可复现，但解释、预测和流派判断不能作为高风险决策依据。</aside>"
            if traditional
            else "<aside class='verification-warning'><strong>未经过外部事实核验。</strong> "
            "模型共识不等于事实；关键结论请使用第一方资料或可复现测试核对。</aside>"
        )
        + f"<p>{escape(run.final_decision.final_answer).replace(chr(10), '<br>')}</p></section>"
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
    traditional_section = _traditional_snapshot_html(run)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(run.question)} · Council</title><style>
    body{{max-width:860px;margin:48px auto;padding:0 24px;color:#292724;font:15px/1.7 system-ui,-apple-system,'Segoe UI',sans-serif;background:#f7f3ee}}
    header,.answer,article,.sources,.review,.high-risk,.decision-brief,.decision-claims,.traditional-snapshot{{background:#fffdf9;border:1px solid #ded7cd;padding:22px 26px;margin:0 0 14px;border-radius:7px}}h1{{font:400 30px/1.25 Georgia,serif}}h2{{font:500 20px Georgia,serif}}h3{{font-size:15px;margin:18px 0 9px}}small,header p,.sources span,.support-note,.decision-claims small{{display:block;color:#756f67}}p{{white-space:normal}}.answer{{border-left:4px solid #c76645}}.traditional-snapshot{{border-left:4px solid #8b7247}}.decision-brief{{border-left:4px solid #456d64}}.decision-claims{{border-left:4px solid #987137}}.decision-claims li{{margin:10px 0}}.verification-warning{{background:#fff4df;border:1px solid #d9a54b;color:#61420d;padding:12px 14px;margin:0 0 16px;border-radius:5px}}.high-risk{{border-left:4px solid #a8333e}}code{{font-size:11px;color:#756f67;overflow-wrap:anywhere}}pre{{white-space:pre-wrap;font:13px/1.6 ui-monospace,monospace;border-top:1px solid #e6dfd5;padding-top:14px}}footer{{color:#756f67;font-size:12px;padding:18px 0}}
</style></head><body><header><h1>{escape(run.question)}</h1><p>{escape(run.template_name)} · {escape('先独立初答' if run.workflow_strategy == 'independent' else '连续审议')} · {escape(run.project_name or '独立审议')} · {run.created_at.date().isoformat()}{escape(request_summary)}</p></header>
    {high_risk_section}{traditional_section}{f"<section class='sources'><h2>资料快照</h2>{sources}</section>" if sources else ""}
    {brief_section}{claims_section}<section><h2>公开讨论</h2>{transcript}</section>{answer}{review}<footer>由 Council Lab 导出。模型共识不等于事实验证；关键结论请核对第一方资料。</footer></body></html>"""
