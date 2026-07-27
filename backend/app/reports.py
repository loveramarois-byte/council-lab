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
            lines.append(f"- [S{index}] **{source.title}** — {origin} — SHA-256 `{source.sha256}`")
        lines.append("")
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
        f"<li><strong>[S{index}] {escape(source.title)}</strong><br><span>{escape(source.url or source.filename or '本地文字资料')}</span>"
        f"<br><code>{escape(source.sha256)}</code></li>"
        for index, source in enumerate(run.source_snapshots, 1)
    )
    answer = (
        f"<section class='answer'><h2>圆桌最终答案</h2><p>{escape(run.final_decision.final_answer).replace(chr(10), '<br>')}</p></section>"
        if run.final_decision
        else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(run.question)} · Council</title><style>
body{{max-width:860px;margin:48px auto;padding:0 24px;color:#202938;font:15px/1.7 system-ui,-apple-system,'Segoe UI',sans-serif;background:#f6f7f9}}
header,.answer,article,.sources{{background:white;border:1px solid #dce1e8;padding:22px 26px;margin:0 0 14px}}h1{{font-size:30px;line-height:1.25}}h2{{font-size:20px}}h3{{font-size:15px;margin:0 0 9px}}small,header p,.sources span{{color:#6b7689}}p{{white-space:normal}}.answer{{border-top:4px solid #245fc7}}code{{font-size:11px;color:#607086}}footer{{color:#6b7689;font-size:12px;padding:18px 0}}
</style></head><body><header><h1>{escape(run.question)}</h1><p>{escape(run.template_name)} · {escape(run.project_name or '独立审议')} · {run.created_at.date().isoformat()}</p></header>
{f"<section class='sources'><h2>资料快照</h2><ol>{sources}</ol></section>" if sources else ""}
<section><h2>公开讨论</h2>{transcript}</section>{answer}<footer>由 Council Lab 导出。模型共识不等于事实验证；关键结论请核对第一方资料。</footer></body></html>"""
