from __future__ import annotations

from .models import OutputContractDefinition, OutputContractId


_CONTRACTS = {
    item.id: item
    for item in (
        OutputContractDefinition(
            id="general_decision",
            name="一般决策",
            description="比较目标、约束、选项、取舍和退出条件。",
            input_checks=["决策目标", "关键约束", "候选方案", "成功标准"],
            prompt_hint="说明要做的决定、约束、候选方案和怎样算成功。",
            system_guidance=(
                "按一般决策契约工作：明确决策标准、关键取舍、可逆性、主要风险、执行动作和重新审议条件。"
            ),
        ),
        OutputContractDefinition(
            id="product_review",
            name="产品评审",
            description="围绕目标用户、用户问题、价值、验证实验和停止条件审议。",
            input_checks=["目标用户", "用户问题", "价值主张", "验证指标", "停止条件"],
            prompt_hint="说明目标用户、用户问题、产品方案以及希望用什么指标验证。",
            system_guidance=(
                "按产品评审契约工作：必须检查目标用户、用户问题、价值主张、失败条件、验证实验、成功阈值和停止条件。"
                "缺少真实用户证据时要明确标为待验证，不得把席位共识写成市场验证。"
            ),
        ),
        OutputContractDefinition(
            id="technical_architecture",
            name="技术架构评审",
            description="围绕需求、约束、备选架构、故障模式、迁移、回滚和可观测性审议。",
            input_checks=["功能与非功能需求", "现有约束", "备选架构", "迁移与回滚", "可观测性"],
            prompt_hint="说明需求、规模、现状约束、候选架构，以及迁移和回滚要求。",
            system_guidance=(
                "按技术架构评审契约工作：必须覆盖需求、约束、架构方案、备选方案取舍、故障模式、迁移计划、回滚计划和可观测性。"
                "代码或性能未经运行验证时必须明确保留为未验证。"
            ),
        ),
        OutputContractDefinition(
            id="medical_second_opinion",
            name="医疗信息整理",
            description="整理诊断与检查信息、比较可讨论的治疗路径，并形成向医生确认的问题。",
            input_checks=["诊断或疑似诊断", "检查结果与时间", "当前用药或治疗", "症状与红旗", "最想确认的问题"],
            prompt_hint="描述诊断或疑似情况、检查结果、当前治疗与用药，以及最希望向医生确认的问题。",
            system_guidance=(
                "按医疗信息整理契约工作。不得诊断、开药、建议停换药、调整剂量或替代临床处置。"
                "严格区分用户提供、资料支持、模型推断和未知；提到研究或指南时注明来源类型与版本不确定性。"
                "出现急症红旗时只提示立即联系当地急救或执业医师，不继续比较方案。"
                "输出以需要向主治医师确认的具体问题收束。"
            ),
            required_disclaimer="本次审议仅用于医疗信息整理和问题梳理，不构成诊断或治疗建议；所有结论须由执业医师结合完整病历确认。",
            requires_high_risk=True,
        ),
        OutputContractDefinition(
            id="legal_risk_review",
            name="法律风险梳理",
            description="识别合同或争议中的风险、适用规则缺口，以及需向律师确认的问题。",
            input_checks=["司法辖区", "文件或争议类型", "核心条款与完整原文", "关键日期与程序阶段", "当事方与目标"],
            prompt_hint="说明司法辖区、合同或争议类型、核心条款、关键日期，以及最关心的风险。",
            system_guidance=(
                "按法律风险梳理契约工作。只识别风险和信息缺口，不给出法律意见、诉讼策略或胜诉承诺。"
                "引用法律时必须注明法域、法律全名、条文号和版本或生效时间；无法核验时标为未核验。"
                "每项风险标注高、中、低和明确规定、通常认定、存在争议之一，并列出需向执业律师确认的问题。"
            ),
            required_disclaimer="本次审议仅用于法律风险识别，不构成法律意见；重要权利义务和程序选择请由适用司法辖区的执业律师确认。",
            requires_high_risk=True,
        ),
        OutputContractDefinition(
            id="financial_decision_review",
            name="财务决策分析",
            description="核对金额与口径、比较风险因素、量化最坏情景并形成专业确认问题。",
            input_checks=["决策类型", "关键金额与计算口径", "时间周期", "现金流与流动性", "可承受的最大损失"],
            prompt_hint="说明决策类型、金额、期限、现金流约束、费用税务，以及可承受的最大损失。",
            system_guidance=(
                "按财务决策分析契约工作。不得给出投资建议、具体买卖指令、收益承诺或个性化适当性结论。"
                "所有数字注明口径、时间、币种、税费和假设；必须包含最坏情景、流动性风险和假设失效条件。"
                "历史表现不得写成未来保证，最终列出需向持牌财务专业人士确认的问题。"
            ),
            required_disclaimer="本次审议仅用于财务风险因素分析，不构成投资、借贷、保险或税务建议；重要决定请由具备相应资质的专业人士确认。",
            requires_high_risk=True,
        ),
    )
}


def get_output_contract(contract_id: OutputContractId | str) -> OutputContractDefinition:
    contract = _CONTRACTS.get(contract_id)  # type: ignore[arg-type]
    if contract is None:
        raise ValueError(f"输出契约不存在：{contract_id}")
    return contract


def list_output_contracts() -> list[OutputContractDefinition]:
    return list(_CONTRACTS.values())
