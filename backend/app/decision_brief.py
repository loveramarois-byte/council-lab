from __future__ import annotations

import uuid

from .models import (
    DecisionAction,
    DecisionAssumption,
    DecisionBrief,
    DecisionReason,
    GeneralDecisionExtension,
    IssuePosition,
    MinorityReport,
    ProductReviewExtension,
    ProductValidationExperiment,
    ReopenTrigger,
    RunRecord,
    TechnicalArchitectureExtension,
    UnresolvedIssue,
)


AGREE_MARKERS = ("表态：认同", "表态:认同")
PARTIAL_MARKERS = ("表态：部分认同", "表态:部分认同")
OPPOSE_MARKERS = ("表态：反驳", "表态:反驳")


def _starts_with(content: str, markers: tuple[str, ...]) -> bool:
    return content.lstrip().startswith(markers)


def _deduplicate(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def build_decision_brief(run: RunRecord) -> DecisionBrief:
    """Build a conservative v1 brief without adding a provider call.

    The recommendation remains the finalizer's public answer. Agreement is derived
    only from the explicit public stance prefixes required by the workflow. Missing
    verification always downgrades actionability and never becomes confidence.
    """
    decision = run.final_decision
    if decision is None or not decision.final_answer.strip():
        raise ValueError("DecisionBrief requires a persisted final decision")

    agent_turns = [turn for turn in run.discussion_turns if turn.speaker_type == "agent"]
    opposing_turns = [turn for turn in agent_turns if _starts_with(turn.content, OPPOSE_MARKERS)]
    partial_turns = [turn for turn in agent_turns if _starts_with(turn.content, PARTIAL_MARKERS)]
    later_turns = agent_turns[1:]
    if opposing_turns:
        support = "contested"
    elif partial_turns or any(not _starts_with(turn.content, AGREE_MARKERS) for turn in later_turns):
        support = "majority"
    else:
        support = "unanimous"

    unresolved: list[UnresolvedIssue] = []
    for index, claim in enumerate(_deduplicate(decision.contradicted_claims), 1):
        unresolved.append(
            UnresolvedIssue(
                id=f"contradiction-{index}",
                issue=claim,
                blocking=True,
                resolution_method="使用第一方资料或可复现测试解决矛盾后重新审议。",
            )
        )
    disagreement_texts = _deduplicate(
        [*decision.disagreements, *(turn.content for turn in opposing_turns), *(turn.content for turn in partial_turns)]
    )
    for index, issue in enumerate(disagreement_texts, 1):
        positions = [
            IssuePosition(seat_id=turn.speaker_id, position=turn.content)
            for turn in [*opposing_turns, *partial_turns]
            if turn.content == issue
        ]
        unresolved.append(
            UnresolvedIssue(
                id=f"disagreement-{index}",
                issue=issue,
                blocking=False,
                positions=positions,
                resolution_method="明确决策门槛并补充能区分各立场的证据。",
            )
        )

    unverified = _deduplicate([*decision.unverified_claims, *decision.partially_verified_claims])
    assumptions = [
        DecisionAssumption(
            id=f"assumption-{index}",
            claim=claim,
            basis="cited_unverified" if run.source_snapshots else "model_inference",
            validation_method="核对第一方资料、原始数据或可复现测试。",
            owner="用户",
        )
        for index, claim in enumerate(unverified, 1)
    ]

    if decision.contradicted_claims:
        status = "no_decision"
    elif unverified or disagreement_texts:
        status = "conditional"
    else:
        status = "proceed"

    seat_ids = [turn.speaker_id for turn in agent_turns if turn not in opposing_turns]
    decisive_reasons = [
        DecisionReason(
            id=f"verified-reason-{index}",
            summary=claim,
            supporting_seat_ids=seat_ids,
        )
        for index, claim in enumerate(_deduplicate(decision.verified_claims), 1)
    ]
    actions = []
    if status != "proceed":
        actions.append(
            DecisionAction(
                id="verify-material-claims",
                action="在执行前核对未验证或存在冲突的关键结论。",
                owner="用户",
                success_criteria="关键结论能对应第一方资料、原始数据或可复现测试。",
            )
        )
    reopen_triggers = [
        ReopenTrigger(
            id="material-facts-change",
            condition="关键事实、约束、成本或风险边界发生实质变化。",
            check_method="对照本简报的假设和未解决问题重新检查。",
            severity="blocking" if status == "no_decision" else "important",
        )
    ]

    limitations = _deduplicate(
        [
            *decision.risks_and_limitations,
            "席位支持度只反映公开讨论中的可观察表态，不代表事实正确概率。",
            "Council 未执行独立联网核验；模型提供或复述的引用仍视为未验证。",
            "推荐内容来自模型综合；用户输入、模型推断与外部事实尚未形成逐条主张映射。",
            *(
                ["这是高风险领域的非约束性决策支持，必须由具备相应责任和资质的人员复核。"]
                if run.high_risk_control
                else []
            ),
        ]
    )
    minority_report = None
    if opposing_turns:
        minority_report = MinorityReport(
            summary="\n\n".join(turn.content for turn in opposing_turns),
            seat_ids=_deduplicate([turn.speaker_id for turn in opposing_turns]),
            conditions_under_which_it_may_be_correct=["其指出的失败条件或关键假设得到第一方证据支持。"],
        )

    if run.output_contract == "product_review":
        contract_extension = ProductReviewExtension(
            target_users=["目标用户需要由用户或真实研究进一步明确"],
            user_problem=run.question,
            value_proposition=decision.final_answer.strip(),
            failure_conditions=_deduplicate([
                *decision.risks_and_limitations,
                *(item.issue for item in unresolved),
            ]),
            validation_experiments=[
                ProductValidationExperiment(
                    hypothesis="当前产品建议能缓解所描述的用户问题。",
                    method="先进行小范围用户研究或灰度实验，并保留原始数据。",
                    success_threshold="执行前由用户明确可量化阈值；未定义阈值时不得宣称验证成功。",
                )
            ],
            stop_conditions=[item.condition for item in reopen_triggers],
        )
    elif run.output_contract == "technical_architecture":
        contract_extension = TechnicalArchitectureExtension(
            requirements=[run.question],
            constraints=[item.claim for item in assumptions],
            proposed_architecture=decision.final_answer.strip(),
            alternatives=[],
            failure_modes=_deduplicate([
                *decision.risks_and_limitations,
                *(item.issue for item in unresolved),
            ]),
            migration_plan=[item.action for item in actions],
            rollback_plan=["关键约束、故障模式或验证结果触发重开条件时，停止推进并恢复到已验证状态。"],
            observability_requirements=["迁移前定义关键健康指标、错误率、延迟、容量和告警阈值，并保留可复盘记录。"],
        )
    else:
        contract_extension = GeneralDecisionExtension(
            decision_criteria=[item.claim for item in assumptions],
            key_tradeoffs=[item.issue for item in unresolved],
        )

    return DecisionBrief(
        id=f"brief-{uuid.uuid4()}",
        run_id=run.id,
        version=1,
        schema_version=2,
        status=status,
        recommendation=decision.final_answer.strip(),
        support=support,
        decisive_reasons=decisive_reasons,
        unresolved=unresolved,
        assumptions=assumptions,
        actions=actions,
        reopen_triggers=reopen_triggers,
        minority_report=minority_report,
        limitations=limitations,
        output_contract=run.output_contract,
        contract_extension=contract_extension,
    )
