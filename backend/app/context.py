from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from .models import DiscussionTurn


MODE_CONTEXT_BUDGETS = {
    "quick": 1800,
    "standard": 4000,
    "rigorous": 7000,
}


@dataclass(frozen=True)
class ContextWindow:
    prompt: str
    summary: str
    token_budget: int
    estimated_tokens: int
    included_turns: int
    total_turns: int
    compacted: bool
    source_tokens: int = 0
    history_tokens: int = 0


def context_budget_for_mode(mode: str) -> int:
    return MODE_CONTEXT_BUDGETS.get(mode, MODE_CONTEXT_BUDGETS["standard"])


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for char in text if "\u3400" <= char <= "\u9fff")
    non_cjk = len(text) - cjk
    return cjk + ceil(non_cjk / 4)


def _truncate_tokens(text: str, limit: int) -> str:
    if limit <= 0 or not text:
        return ""
    if estimate_tokens(text) <= limit:
        return text
    output: list[str] = []
    used = 0.0
    for char in text:
        cost = 1.0 if "\u3400" <= char <= "\u9fff" else 0.25
        if used + cost > max(1, limit - 1):
            break
        output.append(char)
        used += cost
    return "".join(output).rstrip() + "…"


def _truncate_tokens_with_tail(text: str, limit: int) -> str:
    if estimate_tokens(text) <= limit:
        return text
    head = _truncate_tokens(text, max(1, int(limit * 0.65))).removesuffix("…")
    reversed_tail = _truncate_tokens(text[::-1], max(1, int(limit * 0.35))).removesuffix("…")
    return f"{head}…{reversed_tail[::-1]}"


def _format_turn(turn: DiscussionTurn, content_limit: int | None = None) -> str:
    content = turn.content if content_limit is None else _truncate_tokens(turn.content, content_limit)
    return f"{turn.speaker_name}（{turn.role_label or '参与者'}）：{content}"


def _build_dialogue_context(question: str, turns: list[DiscussionTurn], token_budget: int) -> ContextWindow:
    if token_budget < 120:
        raise ValueError("token_budget must be at least 120")

    full_prompt = f"讨论题：{question}\n\n当前公开对话：\n" + ("\n\n".join(_format_turn(turn) for turn in turns) or "（尚无发言）")
    if estimate_tokens(full_prompt) <= token_budget:
        return ContextWindow(
            prompt=full_prompt,
            summary="",
            token_budget=token_budget,
            estimated_tokens=estimate_tokens(full_prompt),
            included_turns=len(turns),
            total_turns=len(turns),
            compacted=False,
        )

    question_text = _truncate_tokens(question, max(32, int(token_budget * 0.18)))
    latest_user = next((turn for turn in reversed(turns) if turn.speaker_type == "user"), None)
    recent_candidates = [turn for turn in turns[-6:] if latest_user is None or turn.id != latest_user.id]

    older_turns = turns[:-6] or turns[:-2]
    anchor_indexes = [0, len(older_turns) // 2, len(older_turns) - 1] if older_turns else []
    anchors = [older_turns[index] for index in dict.fromkeys(anchor_indexes)]
    summary_ids = {turn.id for turn in anchors}
    summary_lines = [f"- {_format_turn(turn, 28)}" for turn in anchors]
    summary = _truncate_tokens("\n".join(summary_lines) or "较早发言已按预算裁剪。", max(48, int(token_budget * 0.25)))

    recent_budget = max(32, int(token_budget * 0.22))
    recent_lines: list[str] = []
    recent_ids: set[str] = set()
    for turn in reversed(recent_candidates):
        remaining = recent_budget - estimate_tokens("\n".join(recent_lines))
        if remaining < 16:
            break
        recent_lines.append(_format_turn(turn, min(72, remaining - 4)))
        recent_ids.add(turn.id)
    recent_lines.reverse()

    latest_user_text = ""
    if latest_user is not None:
        user_content = _truncate_tokens_with_tail(latest_user.content, max(40, int(token_budget * 0.22)))
        latest_user_text = f"{latest_user.speaker_name}（{latest_user.role_label or '参与者'}）：{user_content}"

    sections = [
        f"讨论题：{question_text}",
        f"较早发言摘录（确定性裁剪）：\n{summary}",
        "最近公开发言：\n" + ("\n\n".join(recent_lines) or "（无）"),
    ]
    if latest_user_text:
        sections.append(f"必须优先回应的最新用户插话：\n{latest_user_text}")
    prompt = "\n\n".join(sections)

    if estimate_tokens(prompt) > token_budget:
        overflow = estimate_tokens(prompt) - token_budget
        summary = _truncate_tokens(summary, max(12, estimate_tokens(summary) - overflow - 2))
        sections[1] = f"较早发言摘录（确定性裁剪）：\n{summary}"
        prompt = "\n\n".join(sections)
    if estimate_tokens(prompt) > token_budget:
        # Extremely small budgets retain the question and latest user input ahead of recent agent prose.
        sections[2] = "最近公开发言：\n（已按上下文预算折叠）"
        prompt = "\n\n".join(sections)
    if estimate_tokens(prompt) > token_budget:
        essential_sections = [f"讨论题：{question_text}"]
        if latest_user_text:
            essential_sections.append(f"必须优先回应的最新用户插话：\n{latest_user_text}")
        prompt = "\n\n".join(essential_sections)
    if estimate_tokens(prompt) > token_budget:
        latest_budget = max(28, int(token_budget * 0.45)) if latest_user else 0
        question_budget = max(28, token_budget - latest_budget - 28)
        question_text = _truncate_tokens_with_tail(question, question_budget)
        essential_sections = [f"讨论题：{question_text}"]
        if latest_user is not None:
            user_content = _truncate_tokens_with_tail(latest_user.content, latest_budget)
            essential_sections.append(
                f"必须优先回应的最新用户插话：\n"
                f"{latest_user.speaker_name}（{latest_user.role_label or '参与者'}）：{user_content}"
            )
        prompt = "\n\n".join(essential_sections)

    included_ids = summary_ids | recent_ids | ({latest_user.id} if latest_user else set())
    return ContextWindow(
        prompt=prompt,
        summary=summary,
        token_budget=token_budget,
        estimated_tokens=estimate_tokens(prompt),
        included_turns=len(included_ids),
        total_turns=len(turns),
        compacted=True,
    )


def build_context_window(
    question: str,
    turns: list[DiscussionTurn],
    token_budget: int,
    evidence_context: str = "",
    project_history: str = "",
) -> ContextWindow:
    if not evidence_context and not project_history:
        return _build_dialogue_context(question, turns, token_budget)

    extras_budget = max(0, token_budget - 120)
    evidence_limit = min(int(token_budget * 0.38), extras_budget)
    evidence = _truncate_tokens(evidence_context, evidence_limit) if evidence_context else ""
    remaining = max(0, extras_budget - estimate_tokens(evidence))
    history_limit = min(int(token_budget * 0.16), remaining)
    history = _truncate_tokens(project_history, history_limit) if project_history else ""
    def extras_prefix(current_history: str, current_evidence: str) -> str:
        sections: list[str] = []
        if current_history:
            sections.append(f"同一资料空间的历史结论（仅作上下文，不替代当前证据）：\n{current_history}")
        if current_evidence:
            sections.append(
                "本次资料证据（引用时只能使用现有 [S编号]，资料本身尚未经过 Council 独立核验）：\n"
                + current_evidence
            )
        return ("\n\n".join(sections) + "\n\n") if sections else ""

    prefix = extras_prefix(history, evidence)
    while estimate_tokens(prefix) > token_budget - 120:
        overflow = estimate_tokens(prefix) - (token_budget - 120)
        if history:
            next_limit = max(0, estimate_tokens(history) - overflow - 8)
            history = _truncate_tokens(history, next_limit)
            if next_limit == 0:
                history = ""
        elif evidence:
            next_limit = max(0, estimate_tokens(evidence) - overflow - 8)
            evidence = _truncate_tokens(evidence, next_limit)
            if next_limit == 0:
                evidence = ""
        else:
            break
        prefix = extras_prefix(history, evidence)

    dialogue_budget = max(120, token_budget - estimate_tokens(prefix))
    dialogue = _build_dialogue_context(question, turns, dialogue_budget)
    prompt = prefix + dialogue.prompt
    source_tokens = estimate_tokens(evidence)
    history_tokens = estimate_tokens(history)

    return ContextWindow(
        prompt=prompt,
        summary=dialogue.summary,
        token_budget=token_budget,
        estimated_tokens=estimate_tokens(prompt),
        included_turns=dialogue.included_turns,
        total_turns=dialogue.total_turns,
        compacted=dialogue.compacted or source_tokens < estimate_tokens(evidence_context) or history_tokens < estimate_tokens(project_history),
        source_tokens=source_tokens,
        history_tokens=history_tokens,
    )
