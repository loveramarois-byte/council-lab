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
    )
}


def get_output_contract(contract_id: OutputContractId | str) -> OutputContractDefinition:
    contract = _CONTRACTS.get(contract_id)  # type: ignore[arg-type]
    if contract is None:
        raise ValueError(f"输出契约不存在：{contract_id}")
    return contract


def list_output_contracts() -> list[OutputContractDefinition]:
    return list(_CONTRACTS.values())
