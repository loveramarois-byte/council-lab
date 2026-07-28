from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Protocol

try:
    import tiktoken
except ImportError:  # Packaged builds include it; source installs degrade explicitly.
    tiktoken = None

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
    token_estimator: str = "conservative_utf8"
    token_estimator_exact: bool = False


class TokenEstimator(Protocol):
    name: str
    exact: bool

    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class ConservativeTokenEstimator:
    name: str = "conservative_utf8"
    exact: bool = False

    def count(self, text: str) -> int:
        if not text:
            return 0
        # Unknown tokenizers vary substantially. Two UTF-8 bytes per token is
        # intentionally biased high for mixed CJK, code, URLs, and emoji.
        return ceil(len(text.encode("utf-8")) / 2)


@dataclass(frozen=True)
class TiktokenEstimator:
    encoding: object
    name: str
    exact: bool
    safety_margin: float = 1.0

    def count(self, text: str) -> int:
        if not text:
            return 0
        raw_count = len(self.encoding.encode(text, disallowed_special=()))
        return ceil(raw_count * self.safety_margin)


DEFAULT_TOKEN_ESTIMATOR: TokenEstimator = ConservativeTokenEstimator()


def token_estimator_for(provider_id: str, model: str) -> TokenEstimator:
    model_name = model.strip()
    compatible = provider_id == "openai" or (
        provider_id == "ccswitch" and model_name.lower().startswith(("gpt-", "chatgpt-", "o1", "o3", "o4", "codex"))
    )
    if not compatible or tiktoken is None:
        return DEFAULT_TOKEN_ESTIMATOR
    try:
        encoding = tiktoken.encoding_for_model(model_name)
        return TiktokenEstimator(encoding=encoding, name=f"tiktoken:{encoding.name}", exact=True)
    except KeyError:
        try:
            encoding = tiktoken.get_encoding("o200k_base")
        except ValueError:
            return DEFAULT_TOKEN_ESTIMATOR
        return TiktokenEstimator(
            encoding=encoding,
            name="tiktoken:o200k_base_compatible",
            exact=False,
            safety_margin=1.2,
        )
    except ValueError:
        return DEFAULT_TOKEN_ESTIMATOR


def context_budget_for_mode(mode: str) -> int:
    return MODE_CONTEXT_BUDGETS.get(mode, MODE_CONTEXT_BUDGETS["standard"])


def estimate_tokens(text: str, estimator: TokenEstimator = DEFAULT_TOKEN_ESTIMATOR) -> int:
    return estimator.count(text)


def _truncate_tokens(text: str, limit: int, estimator: TokenEstimator = DEFAULT_TOKEN_ESTIMATOR) -> str:
    if limit <= 0 or not text:
        return ""
    if estimate_tokens(text, estimator) <= limit:
        return text
    suffix = "…"
    suffix_tokens = estimate_tokens(suffix, estimator)
    if suffix_tokens > limit:
        return ""
    available = limit - suffix_tokens
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle], estimator) <= available:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + suffix


def _truncate_tokens_with_tail(
    text: str,
    limit: int,
    estimator: TokenEstimator = DEFAULT_TOKEN_ESTIMATOR,
) -> str:
    if limit <= 0 or not text:
        return ""
    if estimate_tokens(text, estimator) <= limit:
        return text
    separator = "…"
    separator_tokens = estimate_tokens(separator, estimator)
    if separator_tokens > limit:
        return _truncate_tokens(text, limit, estimator)
    content_budget = limit - separator_tokens
    head_budget = int(content_budget * 0.65)
    tail_budget = content_budget - head_budget
    head = _truncate_tokens(text, head_budget, estimator).removesuffix(separator)
    reversed_tail = _truncate_tokens(text[::-1], tail_budget, estimator).removesuffix(separator)
    tail = reversed_tail[::-1]
    result = f"{head}{separator}{tail}"
    while estimate_tokens(result, estimator) > limit and (head or tail):
        if len(head) >= len(tail) and head:
            head = head[:-1]
        elif tail:
            tail = tail[1:]
        result = f"{head}{separator}{tail}"
    return result if estimate_tokens(result, estimator) <= limit else ""


def _format_turn(
    turn: DiscussionTurn,
    content_limit: int | None = None,
    estimator: TokenEstimator = DEFAULT_TOKEN_ESTIMATOR,
) -> str:
    content = turn.content if content_limit is None else _truncate_tokens(turn.content, content_limit, estimator)
    return f"{turn.speaker_name}（{turn.role_label or '参与者'}）：{content}"


def _build_dialogue_context(
    question: str,
    turns: list[DiscussionTurn],
    token_budget: int,
    estimator: TokenEstimator,
) -> ContextWindow:
    if token_budget < 120:
        raise ValueError("token_budget must be at least 120")

    full_prompt = f"讨论题：{question}\n\n当前公开对话：\n" + ("\n\n".join(_format_turn(turn, estimator=estimator) for turn in turns) or "（尚无发言）")
    if estimate_tokens(full_prompt, estimator) <= token_budget:
        return ContextWindow(
            prompt=full_prompt,
            summary="",
            token_budget=token_budget,
            estimated_tokens=estimate_tokens(full_prompt, estimator),
            included_turns=len(turns),
            total_turns=len(turns),
            compacted=False,
            token_estimator=estimator.name,
            token_estimator_exact=estimator.exact,
        )

    question_text = _truncate_tokens(question, max(32, int(token_budget * 0.18)), estimator)
    latest_user = next((turn for turn in reversed(turns) if turn.speaker_type == "user"), None)
    recent_candidates = [turn for turn in turns[-6:] if latest_user is None or turn.id != latest_user.id]

    older_turns = turns[:-6] or turns[:-2]
    anchor_indexes = [0, len(older_turns) // 2, len(older_turns) - 1] if older_turns else []
    anchors = [older_turns[index] for index in dict.fromkeys(anchor_indexes)]
    summary_ids = {turn.id for turn in anchors}
    summary_lines = [f"- {_format_turn(turn, 28, estimator)}" for turn in anchors]
    summary = _truncate_tokens(
        "\n".join(summary_lines) or "较早发言已按预算裁剪。",
        max(48, int(token_budget * 0.25)),
        estimator,
    )

    recent_budget = max(32, int(token_budget * 0.22))
    recent_lines: list[str] = []
    recent_ids: set[str] = set()
    for turn in reversed(recent_candidates):
        remaining = recent_budget - estimate_tokens("\n".join(recent_lines), estimator)
        if remaining < 16:
            break
        recent_lines.append(_format_turn(turn, min(72, remaining - 4), estimator))
        recent_ids.add(turn.id)
    recent_lines.reverse()

    latest_user_text = ""
    if latest_user is not None:
        user_content = _truncate_tokens_with_tail(
            latest_user.content,
            max(40, int(token_budget * 0.22)),
            estimator,
        )
        latest_user_text = f"{latest_user.speaker_name}（{latest_user.role_label or '参与者'}）：{user_content}"

    sections = [
        f"讨论题：{question_text}",
        f"较早发言摘录（确定性裁剪）：\n{summary}",
        "最近公开发言：\n" + ("\n\n".join(recent_lines) or "（无）"),
    ]
    if latest_user_text:
        sections.append(f"必须优先回应的最新用户插话：\n{latest_user_text}")
    prompt = "\n\n".join(sections)

    if estimate_tokens(prompt, estimator) > token_budget:
        overflow = estimate_tokens(prompt, estimator) - token_budget
        summary = _truncate_tokens(
            summary,
            max(12, estimate_tokens(summary, estimator) - overflow - 2),
            estimator,
        )
        sections[1] = f"较早发言摘录（确定性裁剪）：\n{summary}"
        prompt = "\n\n".join(sections)
    if estimate_tokens(prompt, estimator) > token_budget:
        # Extremely small budgets retain the question and latest user input ahead of recent agent prose.
        sections[2] = "最近公开发言：\n（已按上下文预算折叠）"
        prompt = "\n\n".join(sections)
    if estimate_tokens(prompt, estimator) > token_budget:
        essential_sections = [f"讨论题：{question_text}"]
        if latest_user_text:
            essential_sections.append(f"必须优先回应的最新用户插话：\n{latest_user_text}")
        prompt = "\n\n".join(essential_sections)

    if estimate_tokens(prompt, estimator) > token_budget:
        latest_budget = max(28, int(token_budget * 0.45)) if latest_user else 0
        question_budget = max(28, token_budget - latest_budget - 28)
        question_text = _truncate_tokens_with_tail(question, question_budget, estimator)
        essential_sections = [f"讨论题：{question_text}"]
        if latest_user is not None:
            user_content = _truncate_tokens_with_tail(latest_user.content, latest_budget, estimator)
            essential_sections.append(
                f"必须优先回应的最新用户插话：\n"
                f"{latest_user.speaker_name}（{latest_user.role_label or '参与者'}）：{user_content}"
            )
        prompt = "\n\n".join(essential_sections)

    if estimate_tokens(prompt, estimator) > token_budget:
        # Retain the beginning of the question and the tail of the latest user
        # input even when unusually long speaker labels consume the reserve.
        prompt = _truncate_tokens_with_tail(prompt, token_budget, estimator)

    included_ids = summary_ids | recent_ids | ({latest_user.id} if latest_user else set())
    return ContextWindow(
        prompt=prompt,
        summary=summary,
        token_budget=token_budget,
        estimated_tokens=estimate_tokens(prompt, estimator),
        included_turns=len(included_ids),
        total_turns=len(turns),
        compacted=True,
        token_estimator=estimator.name,
        token_estimator_exact=estimator.exact,
    )


def build_context_window(
    question: str,
    turns: list[DiscussionTurn],
    token_budget: int,
    evidence_context: str = "",
    project_history: str = "",
    estimator: TokenEstimator | None = None,
) -> ContextWindow:
    estimator = estimator or DEFAULT_TOKEN_ESTIMATOR
    if not evidence_context and not project_history:
        return _build_dialogue_context(question, turns, token_budget, estimator)

    extras_budget = max(0, token_budget - 120)
    evidence_limit = min(int(token_budget * 0.38), extras_budget)
    evidence = _truncate_tokens(evidence_context, evidence_limit, estimator) if evidence_context else ""
    remaining = max(0, extras_budget - estimate_tokens(evidence, estimator))
    history_limit = min(int(token_budget * 0.16), remaining)
    history = _truncate_tokens(project_history, history_limit, estimator) if project_history else ""
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
    while estimate_tokens(prefix, estimator) > token_budget - 120:
        overflow = estimate_tokens(prefix, estimator) - (token_budget - 120)
        if history:
            next_limit = max(0, estimate_tokens(history, estimator) - overflow - 8)
            history = _truncate_tokens(history, next_limit, estimator)
            if next_limit == 0:
                history = ""
        elif evidence:
            next_limit = max(0, estimate_tokens(evidence, estimator) - overflow - 8)
            evidence = _truncate_tokens(evidence, next_limit, estimator)
            if next_limit == 0:
                evidence = ""
        else:
            break
        prefix = extras_prefix(history, evidence)

    dialogue_budget = max(120, token_budget - estimate_tokens(prefix, estimator))
    dialogue = _build_dialogue_context(question, turns, dialogue_budget, estimator)
    prompt = prefix + dialogue.prompt
    source_tokens = estimate_tokens(evidence, estimator)
    history_tokens = estimate_tokens(history, estimator)

    return ContextWindow(
        prompt=prompt,
        summary=dialogue.summary,
        token_budget=token_budget,
        estimated_tokens=estimate_tokens(prompt, estimator),
        included_turns=dialogue.included_turns,
        total_turns=dialogue.total_turns,
        compacted=(
            dialogue.compacted
            or source_tokens < estimate_tokens(evidence_context, estimator)
            or history_tokens < estimate_tokens(project_history, estimator)
        ),
        source_tokens=source_tokens,
        history_tokens=history_tokens,
        token_estimator=estimator.name,
        token_estimator_exact=estimator.exact,
    )
