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
        DeliberationTemplate(
            id="medical_information_review",
            name="医疗信息整理",
            description="整理检查、治疗路径与需要向医生确认的问题",
            prompt_hint="描述诊断或疑似情况、检查结果、当前用药治疗和最想确认的问题",
            system_guidance="这是医疗信息整理，不是诊断或治疗建议；急症红旗优先升级，所有结论保留证据边界。",
            default_output_contract="medical_second_opinion",
            requires_high_risk=True,
            seat_guidance={
                "analyst": "只整理用户提供的病史、检查值、时间线和用药，不自行解释异常或形成诊断。",
                "challenger": "检查诊断依据和证据强度，指出指南版本、适用人群与缺失检查，不质疑患者感受。",
                "builder": "并列整理可与医生讨论的治疗路径及已知利弊，不推荐路径、不调整用药。",
                "observer": "识别红旗、信息缺口、确认偏误和必须由主治医师回答的问题。",
            },
        ),
        DeliberationTemplate(
            id="legal_risk_review",
            name="法律风险梳理",
            description="梳理合同条款、法域、程序与律师确认问题",
            prompt_hint="说明司法辖区、文件类型、关键条款、日期和最关心的风险",
            system_guidance="这是法律风险识别，不是法律意见；法域、规则版本和原文缺失时必须停止确定性结论。",
            default_output_contract="legal_risk_review",
            requires_high_risk=True,
            seat_guidance={
                "analyst": "提取合同或争议的关键原文、当事方、日期和法定形式要件，不补写缺失条款。",
                "challenger": "逐项质疑不利解释、权利空缺和规则适用前提，引用必须带法域、法律全名和条文号。",
                "builder": "并列常见处理路径及各自前提与程序成本，不提供诉讼策略或结果承诺。",
                "observer": "识别司法辖区、时效、证据和文本缺口，形成需要执业律师确认的问题。",
            },
        ),
        DeliberationTemplate(
            id="financial_decision_review",
            name="财务决策分析",
            description="核对金额口径、最坏情景与专业确认问题",
            prompt_hint="说明金额、币种、期限、现金流、费用税务和可承受的最大损失",
            system_guidance="这是财务风险因素分析，不是投资或个性化财务建议；不得承诺收益或发出买卖指令。",
            default_output_contract="financial_decision_review",
            requires_high_risk=True,
            seat_guidance={
                "analyst": "整理金额、币种、期限、年化月化、税前税后和现金流口径，标出无法复算的数字。",
                "challenger": "质疑收益与增长假设，量化最坏情景、杠杆、集中度和流动性风险。",
                "builder": "按同一口径比较方案、费用与退出条件，不推荐具体产品或交易。",
                "observer": "识别信息不对称、遗漏费用、税务与适当性缺口，形成需专业顾问确认的问题。",
            },
        ),
    ]
}


def get_template(template_id: str) -> DeliberationTemplate:
    return TEMPLATES.get(template_id, TEMPLATES["open_discussion"])


def list_templates() -> list[DeliberationTemplate]:
    return list(TEMPLATES.values())
