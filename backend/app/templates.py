from __future__ import annotations

from .models import DeliberationTemplate


TEMPLATES = {
    item.id: item
    for item in [
        DeliberationTemplate(
            id="open_discussion",
            name="开放讨论",
            description="适合需要多角度分析的一般问题",
            prompt_hint="写下需要四席共同审议的问题",
            system_guidance="优先澄清目标、约束、分歧和可执行下一步。",
        ),
        DeliberationTemplate(
            id="decision_review",
            name="决策评审",
            description="比较方案、代价、可逆性与退出条件",
            prompt_hint="例如：在这些约束下，我们应该选择哪个方案？",
            system_guidance="明确决策标准，比较至少两个选项，并给出触发退出或复评的条件。",
        ),
        DeliberationTemplate(
            id="risk_audit",
            name="风险审计",
            description="主动寻找失败路径、遗漏与缓解措施",
            prompt_hint="例如：这项计划最可能在哪里失败？",
            system_guidance="优先寻找高影响失败路径、前置预警指标、责任人和缓解措施。",
        ),
        DeliberationTemplate(
            id="research_synthesis",
            name="资料研判",
            description="围绕已添加资料区分事实、推断与未知",
            prompt_hint="例如：根据这些资料，目前能得出什么结论？",
            system_guidance="严格区分资料明确支持的事实、合理推断和未知；引用资料时使用 [S编号]。",
        ),
        DeliberationTemplate(
            id="premortem",
            name="事前验尸",
            description="假设方案已经失败，倒推原因与预警",
            prompt_hint="例如：假设半年后项目失败，最可能是什么原因？",
            system_guidance="假设方案已经失败，倒推具体原因、最早信号、预防动作和止损边界。",
        ),
    ]
}


def get_template(template_id: str) -> DeliberationTemplate:
    return TEMPLATES.get(template_id, TEMPLATES["open_discussion"])


def list_templates() -> list[DeliberationTemplate]:
    return list(TEMPLATES.values())
