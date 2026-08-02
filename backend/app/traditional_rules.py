from __future__ import annotations

from typing import Final, Literal, TypedDict


TraditionalInterpretationFramework = Literal[
    "comparative_research",
    "bazi_classical",
    "ziwei_classical",
]


class TraditionalRuleProfile(TypedDict):
    id: TraditionalInterpretationFramework
    label: str
    version: str
    scope: str
    steps: tuple[str, ...]
    instruction: str
    limitations: tuple[str, ...]


TRADITIONAL_RULE_PROFILES: Final[tuple[TraditionalRuleProfile, ...]] = (
    {
        "id": "comparative_research",
        "label": "比较研读（八字 + 紫微）",
        "version": "tc-rules-v1",
        "scope": "以本地四柱和紫微快照做并列研究，不把共享底层计算当作独立验证。",
        "steps": (
            "先复述冻结快照和计算口径，不重新排盘",
            "分别列出八字与紫微的规则解释和证据边界",
            "标出两套体系的一致、冲突和无法比较之处",
            "给出普通替代解释与仍待核对的问题",
        ),
        "instruction": "按四步顺序作答；八字与紫微必须分栏，不能把一套体系的判断偷换成另一套体系的事实。",
        "limitations": (
            "不输出统一的预测正确率",
            "传统解释不进入已验证主张",
        ),
    },
    {
        "id": "bazi_classical",
        "label": "八字规则优先",
        "version": "tc-rules-v1",
        "scope": "以四柱、五行和十神字段为主要解释范围，紫微只作明确标注的旁证对照。",
        "steps": (
            "先复述四柱、时间精度和本地计算口径",
            "按日主、月令、五行和十神的顺序说明规则依据",
            "明确指出没有原文或版本支持的内容只是推断",
            "单列紫微对照、冲突和不能由八字规则解决的问题",
        ),
        "instruction": "八字是主框架；不得用紫微宫位补齐八字缺失，也不得把古籍摘要写成原文引文。",
        "limitations": (
            "当前没有大运、流年和真太阳时校正输入",
            "不代表任何流派的唯一标准答案",
        ),
    },
    {
        "id": "ziwei_classical",
        "label": "紫微规则优先",
        "version": "tc-rules-v1",
        "scope": "以命宫、身宫、十二宫和星曜字段为主要解释范围，四柱只作明确标注的旁证对照。",
        "steps": (
            "先复述紫微盘、时辰和本地计算口径",
            "按命身宫、宫位和星曜字段说明规则依据",
            "明确区分上游精选片段、传统解释和个人推断",
            "单列四柱对照、冲突和不能由紫微规则解决的问题",
        ),
        "instruction": "紫微是主框架；不得把 iztro 的计算字段包装成独立事实验证，也不得补写未载入的星曜或四化。",
        "limitations": (
            "当前快照不包含完整流年、大限和四化派别配置",
            "不代表任何流派的唯一标准答案",
        ),
    },
)

TRADITIONAL_RULE_PROFILES_BY_ID: Final[dict[str, TraditionalRuleProfile]] = {
    item["id"]: item for item in TRADITIONAL_RULE_PROFILES
}
TRADITIONAL_RULE_PROFILE_IDS: Final[frozenset[str]] = frozenset(TRADITIONAL_RULE_PROFILES_BY_ID)


def get_traditional_rule_profile(framework: str) -> TraditionalRuleProfile:
    try:
        return TRADITIONAL_RULE_PROFILES_BY_ID[framework]
    except KeyError as exc:
        raise ValueError("传统文化解释体系 ID 无效") from exc


def render_rule_profile_context(framework: str) -> str:
    profile = get_traditional_rule_profile(framework)
    steps = "；".join(f"{index + 1}. {step}" for index, step in enumerate(profile["steps"]))
    limitations = "；".join(profile["limitations"])
    return (
        f"解释体系：{profile['label']}（{profile['version']}）；适用范围：{profile['scope']}\n"
        f"固定规则顺序：{steps}\n"
        f"体系要求：{profile['instruction']}\n"
        f"固定限制：{limitations}"
    )
