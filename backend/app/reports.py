from __future__ import annotations

from html import escape

from .models import RunRecord
from .risk.schemas import HighRiskRun


def _high_risk_summary(case: HighRiskRun) -> tuple[int, int, str]:
    completed = sum(1 for fact in case.required_facts if fact.value)
    total = len(case.required_facts)
    domains = "、".join(case.risk_assessment.detected_domains) or "未分类"
    return completed, total, domains


def run_markdown(run: RunRecord, high_risk: HighRiskRun | None = None) -> str:
    lines = [
        f"# {run.question}",
        "",
        f"- 状态：{run.status}",
        f"- 模式：{run.mode}",
        f"- 模板：{run.template_name}",
        f"- 资料空间：{run.project_name or '无'}",
        f"- 创建时间：{run.created_at.isoformat()}",
        f"- 模型调用：{run.usage.model_calls}",
        f"- Token：{run.usage.input_tokens + run.usage.output_tokens}",
        "",
    ]
    if high_risk:
        completed, total, domains = _high_risk_summary(high_risk)
        lines.extend([
            "## 高风险决策支持状态",
            "",
            "> 非约束性决策支持；不代表事实已核验、专业人员已参与或任何监管合规。不得直接用于医疗、法律、投资、合规或生产执行。",
            "",
            f"- 控制状态：{high_risk.status}",
            f"- 风险等级：{high_risk.risk_assessment.risk_tier}",
            f"- 检测领域：{domains}",
            f"- 关键事实：{completed}/{total} 已填写",
            "",
        ])
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
    lines.extend(["## 公开讨论", ""])
    for turn in run.discussion_turns:
        provider = f" · {turn.provider_name} / {turn.model}" if turn.provider_name else ""
        lines.extend([f"### {turn.speaker_name} · {turn.role_label}{provider}", "", turn.content, ""])
    if run.final_decision:
        lines.extend(["## 圆桌最终答案", "", run.final_decision.final_answer, ""])
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


def run_html(run: RunRecord, high_risk: HighRiskRun | None = None) -> str:
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
        f"<section class='answer'><h2>圆桌最终答案</h2><p>{escape(run.final_decision.final_answer).replace(chr(10), '<br>')}</p></section>"
        if run.final_decision
        else ""
    )
    high_risk_section = ""
    if high_risk:
        completed, total, domains = _high_risk_summary(high_risk)
        high_risk_section = (
            "<section class='high-risk'><h2>高风险决策支持状态</h2>"
            "<p><strong>非约束性决策支持；不代表事实已核验、专业人员已参与或任何监管合规。"
            "不得直接用于医疗、法律、投资、合规或生产执行。</strong></p>"
            f"<ul><li>控制状态：{escape(high_risk.status)}</li>"
            f"<li>风险等级：{escape(high_risk.risk_assessment.risk_tier)}</li>"
            f"<li>检测领域：{escape(domains)}</li>"
            f"<li>关键事实：{completed}/{total} 已填写</li></ul></section>"
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
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(run.question)} · Council</title><style>
    body{{max-width:860px;margin:48px auto;padding:0 24px;color:#292724;font:15px/1.7 system-ui,-apple-system,'Segoe UI',sans-serif;background:#f7f3ee}}
    header,.answer,article,.sources,.review,.high-risk{{background:#fffdf9;border:1px solid #ded7cd;padding:22px 26px;margin:0 0 14px;border-radius:7px}}h1{{font:400 30px/1.25 Georgia,serif}}h2{{font:500 20px Georgia,serif}}h3{{font-size:15px;margin:0 0 9px}}small,header p,.sources span{{color:#756f67}}p{{white-space:normal}}.answer{{border-left:4px solid #c76645}}.high-risk{{border-left:4px solid #a8333e}}code{{font-size:11px;color:#756f67}}pre{{white-space:pre-wrap;font:13px/1.6 ui-monospace,monospace;border-top:1px solid #e6dfd5;padding-top:14px}}footer{{color:#756f67;font-size:12px;padding:18px 0}}
</style></head><body><header><h1>{escape(run.question)}</h1><p>{escape(run.template_name)} · {escape(run.project_name or '独立审议')} · {run.created_at.date().isoformat()}</p></header>
    {high_risk_section}{f"<section class='sources'><h2>资料快照</h2>{sources}</section>" if sources else ""}
    <section><h2>公开讨论</h2>{transcript}</section>{answer}{review}<footer>由 Council Lab 导出。模型共识不等于事实验证；关键结论请核对第一方资料。</footer></body></html>"""
