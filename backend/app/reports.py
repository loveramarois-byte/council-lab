from __future__ import annotations

from html import escape

from .models import RunRecord


def run_markdown(run: RunRecord) -> str:
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


def run_html(run: RunRecord) -> str:
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
    header,.answer,article,.sources,.review{{background:#fffdf9;border:1px solid #ded7cd;padding:22px 26px;margin:0 0 14px;border-radius:7px}}h1{{font:400 30px/1.25 Georgia,serif}}h2{{font:500 20px Georgia,serif}}h3{{font-size:15px;margin:0 0 9px}}small,header p,.sources span{{color:#756f67}}p{{white-space:normal}}.answer{{border-left:4px solid #c76645}}code{{font-size:11px;color:#756f67}}pre{{white-space:pre-wrap;font:13px/1.6 ui-monospace,monospace;border-top:1px solid #e6dfd5;padding-top:14px}}footer{{color:#756f67;font-size:12px;padding:18px 0}}
</style></head><body><header><h1>{escape(run.question)}</h1><p>{escape(run.template_name)} · {escape(run.project_name or '独立审议')} · {run.created_at.date().isoformat()}</p></header>
    {f"<section class='sources'><h2>资料快照</h2>{sources}</section>" if sources else ""}
    <section><h2>公开讨论</h2>{transcript}</section>{answer}{review}<footer>由 Council Lab 导出。模型共识不等于事实验证；关键结论请核对第一方资料。</footer></body></html>"""
