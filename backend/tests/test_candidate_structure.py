from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import CandidateAnswer, DiscussionTurn, RunRecord, UsageSummary
from app.orchestrator import extract_public_key_reasons, make_candidate
from app.reports import run_html, run_markdown


def test_candidate_schema_exposes_structure_source_contract():
    schema = CandidateAnswer.model_json_schema()

    assert set(schema["properties"]["structure_source"]["enum"]) == {
        "agent_output",
        "postprocessed",
        "manual",
        "legacy_default",
        "none",
    }
    assert "structure_source" in schema["required"]


def test_new_unstructured_candidate_does_not_invent_structured_fields():
    candidate = make_candidate(
        "candidate-analyst",
        "是否应该上线？",
        "拆解者",
        "council-mock",
        "Mock",
        "先验证核心假设。",
        UsageSummary(model_calls=1),
    )

    assert candidate.structure_source == "none"
    assert candidate.key_reasons == []
    assert candidate.assumptions == []
    assert candidate.claims_to_verify == []
    assert candidate.uncertainties == []
    assert candidate.risks == []


def test_candidate_without_structure_source_is_marked_as_legacy_default():
    candidate = CandidateAnswer.model_validate(
        {
            "candidate_id": "candidate-legacy",
            "answer": "旧席位正文",
            "key_reasons": ["旧版通用理由"],
            "model": "council-mock",
            "provider": "Mock",
        }
    )

    assert candidate.structure_source == "legacy_default"
    assert candidate.key_reasons == ["旧版通用理由"]


def test_none_structure_source_rejects_attributed_content():
    with pytest.raises(ValueError, match="structure_source=none"):
        CandidateAnswer(
            candidate_id="candidate-invalid",
            answer="席位正文",
            key_reasons=["不能归因给模型的理由"],
            structure_source="none",
            model="council-mock",
            provider="Mock",
        )


def test_final_decision_reasons_are_specific_public_points_not_workflow_metadata():
    turns = [
        DiscussionTurn(
            id="turn-analyst",
            speaker_type="agent",
            speaker_id="analyst",
            speaker_name="析理",
            role_label="拆解者",
            content="首要依据是现有错误率仍高于发布门槛。继续发布会扩大受影响用户范围。",
        )
    ]

    reasons = extract_public_key_reasons(
        """## 建议\n先灰度 10% 用户，并保留一键回滚。\n该结论未经外部事实核验。\n\n## 限制\n不得用于未经负责人确认的生产发布。""",
        turns,
    )

    assert reasons == [
        "先灰度 10% 用户，并保留一键回滚。",
        "首要依据是现有错误率仍高于发布门槛。",
    ]
    assert all("公开上下文" not in reason and "席按顺序" not in reason for reason in reasons)


def test_reports_only_export_actual_discussion_for_legacy_candidate_structure():
    now = datetime.now(timezone.utc)
    run = RunRecord(
        id="run-legacy-candidate",
        question="是否继续？",
        mode="standard",
        provider_id="mock",
        model="council-mock",
        status="completed",
        created_at=now,
        updated_at=now,
        candidates=[
            CandidateAnswer(
                candidate_id="candidate-legacy",
                answer="真实席位正文",
                key_reasons=["旧版通用理由，不是模型明确表达"],
                structure_source="legacy_default",
                model="council-mock",
                provider="Mock",
            )
        ],
        discussion_turns=[
            DiscussionTurn(
                id="turn-1",
                speaker_type="agent",
                speaker_id="analyst",
                speaker_name="析理",
                role_label="拆解者",
                content="真实席位正文",
            )
        ],
    )

    markdown = run_markdown(run)
    html = run_html(run)

    assert "真实席位正文" in markdown
    assert "真实席位正文" in html
    assert "旧版通用理由，不是模型明确表达" not in markdown
    assert "旧版通用理由，不是模型明确表达" not in html
