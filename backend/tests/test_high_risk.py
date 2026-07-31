from __future__ import annotations

import asyncio
import importlib
import json
from datetime import timedelta
from pathlib import Path

import pytest
import httpx
from pydantic import ValidationError

from conftest import TEST_INTERNAL_API_TOKEN
from app.errors import ApiError
from app.idempotency import execute_idempotent_model_action
from app.risk.classifier import assess_risk
from app.risk.schemas import (
    ApprovalDecisionRequest,
    ApprovalRecord,
    EvidenceCreateRequest,
    EvidenceVerificationRequest,
    HighRiskCreate,
    PrepareReviewRequest,
    ProfessionalReviewRequest,
    RequiredFact,
    RiskOverrideRequest,
    TransitionRequest,
    utc_now,
)
from app.risk.service import HighRiskService
from app.risk.state_machine import can_transition
from app.models import RunCreate, RunRecord
from app.orchestrator import Orchestrator
from app.provider_catalog import builtin_providers
from app.reports import run_html, run_markdown
from app.store import Store


INTERNAL_HEADERS = {"X-Council-Internal-Token": TEST_INTERNAL_API_TOKEN}


def reviewer_config() -> dict[str, str]:
    return {
        "requester-a": "requester-secret-a",
        "reviewer-b": "reviewer-secret-b",
        "reviewer-c": "reviewer-secret-c",
    }


def complete_facts(case) -> list[RequiredFact]:
    return [
        fact.model_copy(update={"value": f"confirmed-{fact.fact_id}", "source": "user"})
        for fact in case.required_facts
    ]


REVIEW_ROLE_BY_DOMAIN = {
    "medical": "physician",
    "legal": "lawyer",
    "investment": "licensed_adviser",
    "compliance": "compliance_officer",
    "production_incident": "incident_commander",
    "general_high_risk": "domain_professional",
}


async def verify_all_required_evidence(service: HighRiskService, case):
    current = await service.get(case.run_id)
    for fact in current.required_facts:
        domain = next(
            domain
            for domain in current.risk_assessment.detected_domains
            if fact.fact_id.startswith(domain.split("_")[0])
            or (domain == "production_incident" and fact.fact_id.startswith("incident_"))
            or (domain == "general_high_risk" and fact.fact_id == "decision_context")
        )
        evidence = await service.add_evidence(
            current.run_id,
            EvidenceCreateRequest(
                fact_id=fact.fact_id,
                source_type="manual",
                source_title=f"Test source for {fact.fact_id}",
                source_ref=f"test://{current.run_id}/{fact.fact_id}",
                source_timestamp=utc_now(),
                expires_at=utc_now() + timedelta(hours=2),
            ),
            "requester-a",
        )
        await service.verify_evidence(
            current.run_id,
            evidence.evidence_id,
            EvidenceVerificationRequest(
                status="verified",
                method="independent test review",
                reviewer_role=REVIEW_ROLE_BY_DOMAIN[domain],
                domain=domain,
                note="verified fixture evidence",
            ),
            "reviewer-b",
            "reviewer-secret-b",
        )
    return await service.get(current.run_id)


async def approve_all_professional_domains(service: HighRiskService, case):
    current = await service.get(case.run_id)
    for domain in current.risk_assessment.detected_domains:
        await service.submit_professional_review(
            current.run_id,
            ProfessionalReviewRequest(
                reviewer_role=REVIEW_ROLE_BY_DOMAIN[domain],
                domain=domain,
                scope=f"review {domain} evidence and report",
                attestation="I accept responsibility for this independent professional review.",
                decision="approved",
                expires_in_minutes=60,
            ),
            "reviewer-c",
            "reviewer-secret-c",
        )
    return await service.get(current.run_id)


def test_classifier_is_server_side_multidomain_and_monotonic():
    assessment = assess_risk("请判断上海法律下这项投资合规吗", "run-1")
    assert assessment.risk_tier == "high"
    assert assessment.detected_domains == ["legal", "investment", "compliance"]
    assert assessment.classifier_version
    assert assessment.manually_overridden is False

    critical = assess_risk("生产数据库泄漏，需要立刻删除证据吗", "run-2")
    assert critical.risk_tier == "critical"
    assert "production_incident" in critical.detected_domains


def test_assurance_request_schema_rejects_extra_fields_and_invalid_hash():
    with pytest.raises(ValidationError):
        EvidenceCreateRequest(
            fact_id="legal_jurisdiction",
            source_type="document",
            source_title="statute",
            source_ref="https://example.test/statute",
            source_timestamp=utc_now(),
            content_sha256="not-a-sha256",
            hidden_override=True,
        )


def test_high_risk_metric_catalog_is_complete_and_contains_no_results():
    root = Path(__file__).resolve().parents[2]
    catalog = json.loads((root / "evals/high_risk/metric-catalog-v1.json").read_text(encoding="utf-8"))
    expected = {
        "critical_harmful_recommendation_rate",
        "unsafe_action_block_rate",
        "missing_fact_detection_recall",
        "professional_escalation_recall",
        "appropriate_abstention_rate",
        "unsupported_material_claim_rate",
        "citation_entailment_rate",
        "fabricated_citation_rate",
        "false_reassurance_rate",
        "jurisdiction_error_rate",
        "stale_source_usage_rate",
        "audit_completeness_rate",
        "prompt_injection_resistance_rate",
    }
    metric_ids = [metric["id"] for metric in catalog["metrics"]]
    assert set(metric_ids) == expected
    assert len(metric_ids) == len(set(metric_ids))
    assert catalog["status"] == "definitions_only"
    assert catalog["quality_claims_allowed"] is False
    assert all(set(metric) == {"id", "direction", "unit"} for metric in catalog["metrics"])


async def test_high_risk_exports_include_only_public_control_summary(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-export", question="法律意见"), "requester-a")
    run = RunRecord(
        id=case.run_id,
        question="法律意见",
        mode="standard",
        provider_id="mock",
        model="council-mock",
        status="awaiting_final_input",
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    markdown = run_markdown(run, case)
    html = run_html(run, case)

    for exported in (markdown, html):
        assert "高风险决策支持状态" in exported
        assert "非约束性决策支持" in exported
        assert "MORE_INFORMATION_REQUIRED" in exported
        assert "legal" in exported
        assert "requester-a" not in exported
        assert "reviewer-secret-b" not in exported
        assert "report_hash" not in exported
        assert "approval_id" not in exported


@pytest.mark.parametrize(
    ("source", "target", "allowed"),
    [
        ("DRAFT", "RISK_ASSESSMENT_REQUIRED", True),
        ("MORE_INFORMATION_REQUIRED", "EVIDENCE_REQUIRED", True),
        ("EVIDENCE_REQUIRED", "READY_FOR_HUMAN_REVIEW", True),
        ("READY_FOR_HUMAN_REVIEW", "APPROVAL_REQUIRED", True),
        ("APPROVAL_REQUIRED", "APPROVED", True),
        ("APPROVED", "COMPLETED", True),
        ("MORE_INFORMATION_REQUIRED", "APPROVED", False),
        ("ACTION_BLOCKED", "APPROVED", False),
        ("COMPLETED", "DRAFT", False),
    ],
)
def test_state_machine_has_explicit_edges(source: str, target: str, allowed: bool):
    assert can_transition(source, target) is allowed


async def test_schema_v5_migration_and_append_only_audit(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] >= 5
    for table in ("high_risk_runs", "high_risk_approvals", "high_risk_audit_events"):
        assert store.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()

    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-a", question="医疗建议"), "requester-a")
    row = store.conn.execute(
        "SELECT event_id FROM high_risk_audit_events WHERE run_id=? ORDER BY sequence LIMIT 1",
        (case.run_id,),
    ).fetchone()
    assert row
    with pytest.raises(Exception):
        store.conn.execute("DELETE FROM high_risk_audit_events WHERE event_id=?", (row[0],))
    store.conn.rollback()


async def test_missing_critical_fact_blocks_review_and_illegal_transition_is_audited(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-b", question="请给出医疗诊断"), "requester-a")
    assert case.status == "MORE_INFORMATION_REQUIRED"
    assert any(f.required and f.materiality == "critical" and not f.value for f in case.required_facts)

    with pytest.raises(ApiError) as blocked:
        await service.transition(case.run_id, TransitionRequest(target_status="EVIDENCE_REQUIRED"), "requester-a")
    assert blocked.value.code == "CRITICAL_FACTS_MISSING"
    assert (await service.get(case.run_id)).status == "MORE_INFORMATION_REQUIRED"
    events = await service.audit(case.run_id)
    assert events[-1].event_type == "transition_denied"


async def test_filled_facts_without_verified_evidence_cannot_prepare_review(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-evidence-gate", question="法律意见"), "requester-a")
    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")

    with pytest.raises(ApiError) as blocked:
        await service.prepare_review(
            case.run_id,
            PrepareReviewRequest(
                report="report",
                requested_action_type="decision_support_report",
                requested_action_payload={"effect": "read_only"},
            ),
            "requester-a",
        )
    assert blocked.value.code == "HIGH_RISK_EVIDENCE_NOT_READY"


async def test_expired_or_conflicting_evidence_fails_closed(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-stale-evidence", question="投资建议"), "requester-a")
    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    current = await service.get(case.run_id)
    first = current.required_facts[0]
    evidence = await service.add_evidence(
        case.run_id,
        EvidenceCreateRequest(
            fact_id=first.fact_id,
            source_type="manual",
            source_title="time-limited source",
            source_ref="test://stale",
            source_timestamp=utc_now(),
            expires_at=utc_now() + timedelta(milliseconds=20),
        ),
        "requester-a",
    )
    await service.verify_evidence(
        case.run_id,
        evidence.evidence_id,
        EvidenceVerificationRequest(
            status="verified",
            method="independent review",
            reviewer_role="licensed_adviser",
            domain="investment",
        ),
        "reviewer-b",
        "reviewer-secret-b",
    )
    await asyncio.sleep(0.03)
    assert (await service.get(case.run_id)).required_facts[0].verification_status == "expired"

    second = (await service.get(case.run_id)).required_facts[1]
    conflicting = await service.add_evidence(
        case.run_id,
        EvidenceCreateRequest(
            fact_id=second.fact_id,
            source_type="manual",
            source_title="conflicting source",
            source_ref="test://conflict",
            source_timestamp=utc_now(),
        ),
        "requester-a",
    )
    await service.verify_evidence(
        case.run_id,
        conflicting.evidence_id,
        EvidenceVerificationRequest(
            status="conflicting",
            method="cross-source comparison",
            reviewer_role="licensed_adviser",
            domain="investment",
        ),
        "reviewer-b",
        "reviewer-secret-b",
    )
    assert (await service.get(case.run_id)).assurance.evidence_conflict is True


async def test_role_domain_mismatch_and_medical_red_flag_are_blocked(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    legal = await service.create(HighRiskCreate(run_id="run-role-mismatch", question="法律建议"), "requester-a")
    await service.replace_facts(legal.run_id, complete_facts(legal), "requester-a")
    fact = (await service.get(legal.run_id)).required_facts[0]
    evidence = await service.add_evidence(
        legal.run_id,
        EvidenceCreateRequest(
            fact_id=fact.fact_id,
            source_type="manual",
            source_title="legal source",
            source_ref="test://legal",
            source_timestamp=utc_now(),
        ),
        "requester-a",
    )
    with pytest.raises(ApiError) as wrong_role:
        await service.verify_evidence(
            legal.run_id,
            evidence.evidence_id,
            EvidenceVerificationRequest(
                status="verified",
                method="independent review",
                reviewer_role="physician",
                domain="legal",
            ),
            "reviewer-b",
            "reviewer-secret-b",
        )
    assert wrong_role.value.code == "REVIEWER_ROLE_MISMATCH"

    medical = await service.create(HighRiskCreate(run_id="run-medical-red-flag", question="医疗建议"), "requester-a")
    red_flag_facts = [
        item.model_copy(update={"value": "有胸痛和呼吸困难" if item.fact_id == "medical_red_flags" else "confirmed context"})
        for item in medical.required_facts
    ]
    await service.replace_facts(medical.run_id, red_flag_facts, "requester-a")
    red_flag = next(item for item in (await service.get(medical.run_id)).required_facts if item.fact_id == "medical_red_flags")
    await service.add_evidence(
        medical.run_id,
        EvidenceCreateRequest(
            fact_id=red_flag.fact_id,
            source_type="manual",
            source_title="reported symptoms",
            source_ref="manual://patient-report",
            source_timestamp=utc_now(),
        ),
        "requester-a",
    )
    escalated = await service.get(medical.run_id)
    assert escalated.status == "PROFESSIONAL_ESCALATION_REQUIRED"
    assert escalated.assurance.medical_red_flag is True


async def test_professional_review_is_required_and_separated_from_final_approval(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-professional-gate", question="合规建议"), "requester-a")
    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    await verify_all_required_evidence(service, case)
    await service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="compliance report",
            requested_action_type="decision_support_report",
            requested_action_payload={"effect": "read_only"},
        ),
        "requester-a",
    )
    with pytest.raises(ApiError) as missing_professional:
        await service.request_approval(case.run_id, "requester-a")
    assert missing_professional.value.code == "PROFESSIONAL_REVIEW_REQUIRED"

    await approve_all_professional_domains(service, case)
    approval = await service.request_approval(case.run_id, "requester-a")
    with pytest.raises(ApiError) as same_reviewer:
        await service.decide_approval(
            case.run_id,
            approval.approval_id,
            ApprovalDecisionRequest(decision="approved", reason="same actor"),
            "reviewer-c",
            "reviewer-secret-c",
        )
    assert same_reviewer.value.code == "SEPARATION_OF_DUTIES_REQUIRED"
    approved = await service.decide_approval(
        case.run_id,
        approval.approval_id,
        ApprovalDecisionRequest(decision="approved", reason="independent final approval"),
        "reviewer-b",
        "reviewer-secret-b",
    )
    assert approved.status == "approved"


async def test_evidence_and_professional_review_tables_are_append_only(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-assurance-append-only", question="法律建议"), "requester-a")
    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    await verify_all_required_evidence(service, case)
    await service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="immutable assurance report",
            requested_action_type="decision_support_report",
            requested_action_payload={"effect": "read_only"},
        ),
        "requester-a",
    )
    await approve_all_professional_domains(service, case)
    hydrated = await service.get(case.run_id)
    evidence_id = hydrated.evidence_records[0].evidence_id
    review_id = hydrated.professional_reviews[0].review_id
    with pytest.raises(Exception):
        store.conn.execute("DELETE FROM high_risk_evidence_records WHERE evidence_id=?", (evidence_id,))
    store.conn.rollback()
    with pytest.raises(Exception):
        store.conn.execute("UPDATE high_risk_professional_reviews SET scope='changed' WHERE review_id=?", (review_id,))
    store.conn.rollback()


async def test_approval_is_persisted_bound_and_not_replayable(tmp_path):
    database = tmp_path / "council.sqlite3"
    store = Store(database)
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-c", question="投资建议"), "requester-a")
    case = await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    assert case.status == "EVIDENCE_REQUIRED"
    case = await verify_all_required_evidence(service, case)
    case = await service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="非约束性报告；需要持牌专业人员复核。",
            requested_action_type="decision_support_report",
            requested_action_payload={"recommendation": "pause-and-review"},
        ),
        "requester-a",
    )
    await approve_all_professional_domains(service, case)
    approval = await service.request_approval(case.run_id, "requester-a", expires_in=timedelta(minutes=10))

    with pytest.raises(ApiError) as approval_bypass:
        await service.transition(
            case.run_id,
            TransitionRequest(target_status="APPROVED", reason="skip reviewer"),
            "requester-a",
        )
    assert approval_bypass.value.code == "HIGH_RISK_TRANSITION_REQUIRES_DEDICATED_ENDPOINT"
    assert (await service.get(case.run_id)).status == "APPROVAL_REQUIRED"

    with pytest.raises(ApiError) as self_approval:
        await service.decide_approval(
            case.run_id,
            approval.approval_id,
            ApprovalDecisionRequest(decision="approved", reason="self"),
            "requester-a",
            "requester-secret-a",
        )
    assert self_approval.value.code == "SELF_APPROVAL_FORBIDDEN"

    with pytest.raises(ApiError) as unauthorized:
        await service.decide_approval(
            case.run_id,
            approval.approval_id,
            ApprovalDecisionRequest(decision="approved", reason="unknown"),
            "reviewer-x",
            "wrong",
        )
    assert unauthorized.value.code == "REVIEWER_NOT_AUTHORIZED"
    denied_events = [event for event in await service.audit(case.run_id) if event.event_type == "approval_decision_denied"]
    assert {event.metadata["reason_code"] for event in denied_events} == {
        "REVIEWER_NOT_AUTHORIZED",
        "SELF_APPROVAL_FORBIDDEN",
    }

    approved = await service.decide_approval(
        case.run_id,
        approval.approval_id,
        ApprovalDecisionRequest(decision="approved", reason="facts reviewed"),
        "reviewer-b",
        "reviewer-secret-b",
    )
    assert approved.status == "approved"
    with pytest.raises(ApiError) as completion_bypass:
        await service.transition(
            case.run_id,
            TransitionRequest(target_status="COMPLETED", reason="skip approval consumption"),
            "requester-a",
        )
    assert completion_bypass.value.code == "HIGH_RISK_TRANSITION_REQUIRES_DEDICATED_ENDPOINT"
    assert (await service.get(case.run_id)).status == "APPROVED"
    store.close()

    reopened = Store(database)
    restarted = HighRiskService(reopened, reviewer_config())
    persisted = await restarted.get_approval(case.run_id, approval.approval_id)
    assert persisted.status == "approved"
    completed = await restarted.complete(case.run_id, approval.approval_id, "requester-a")
    assert completed.status == "COMPLETED"
    with pytest.raises(ApiError) as replay:
        await restarted.complete(case.run_id, approval.approval_id, "requester-a")
    assert replay.value.code in {"APPROVAL_ALREADY_CONSUMED", "INVALID_HIGH_RISK_TRANSITION"}


async def test_cross_run_hash_mutation_expiry_revoke_and_concurrent_decision_are_blocked(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())

    async def ready(run_id: str):
        case = await service.create(HighRiskCreate(run_id=run_id, question="法律意见"), "requester-a")
        await service.replace_facts(run_id, complete_facts(case), "requester-a")
        await verify_all_required_evidence(service, case)
        await service.prepare_review(
            run_id,
            PrepareReviewRequest(
                report=f"report-{run_id}",
                requested_action_type="decision_support_report",
                requested_action_payload={"run": run_id},
            ),
            "requester-a",
        )
        await approve_all_professional_domains(service, case)
        return await service.request_approval(run_id, "requester-a", expires_in=timedelta(minutes=5))

    first = await ready("run-d")
    await ready("run-e")
    with pytest.raises(ApiError) as cross_run:
        await service.decide_approval(
            "run-e", first.approval_id,
            ApprovalDecisionRequest(decision="approved", reason="replay"),
            "reviewer-b", "reviewer-secret-b",
        )
    assert cross_run.value.code == "APPROVAL_NOT_FOUND"

    results = await asyncio.gather(
        service.decide_approval(
            "run-d", first.approval_id,
            ApprovalDecisionRequest(decision="approved", reason="b"),
            "reviewer-b", "reviewer-secret-b",
        ),
        service.decide_approval(
            "run-d", first.approval_id,
            ApprovalDecisionRequest(decision="rejected", reason="c"),
            "reviewer-c", "reviewer-secret-c",
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(item, Exception) for item in results) == 1

    expired = await ready("run-f")
    store.conn.execute(
        "UPDATE high_risk_approvals SET expires_at=? WHERE approval_id=?",
        ((utc_now() - timedelta(seconds=1)).isoformat(), expired.approval_id),
    )
    store.conn.commit()
    with pytest.raises(ApiError) as expiry:
        await service.decide_approval(
            "run-f", expired.approval_id,
            ApprovalDecisionRequest(decision="approved", reason="late"),
            "reviewer-b", "reviewer-secret-b",
        )
    assert expiry.value.code == "APPROVAL_EXPIRED"

    revoked = await ready("run-g")
    revoked = await service.revoke_approval("run-g", revoked.approval_id, "requester-a", "changed")
    assert revoked.status == "revoked"
    with pytest.raises(ApiError):
        await service.decide_approval(
            "run-g", revoked.approval_id,
            ApprovalDecisionRequest(decision="approved", reason="after revoke"),
            "reviewer-b", "reviewer-secret-b",
        )


async def test_only_authorized_override_can_lower_tier_and_original_is_preserved(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-h", question="生产事故紧急回滚"), "requester-a")
    assert case.risk_assessment.risk_tier in {"high", "critical"}

    with pytest.raises(ApiError):
        await service.override_risk(
            case.run_id,
            RiskOverrideRequest(risk_tier="normal", reason="trust me"),
            "requester-a",
            "bad-key",
        )
    lowered = await service.override_risk(
        case.run_id,
        RiskOverrideRequest(risk_tier="normal", reason="case was synthetic training data"),
        "reviewer-b",
        "reviewer-secret-b",
    )
    assert lowered.risk_assessment.risk_tier == "normal"
    assert lowered.risk_assessment.original_risk_tier in {"high", "critical"}
    assert lowered.risk_assessment.manually_overridden is True


async def test_audit_failure_rolls_back_security_state(tmp_path, monkeypatch):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-i", question="医疗建议"), "requester-a")

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("simulated audit write failure")

    monkeypatch.setattr(service, "_insert_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit write failure"):
        await service.replace_facts(case.run_id, complete_facts(case), "requester-a")

    persisted = await service.get(case.run_id)
    assert persisted.status == "MORE_INFORMATION_REQUIRED"
    assert all(fact.value is None for fact in persisted.required_facts)


async def test_professional_escalation_and_action_block_are_server_states(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-j", question="紧急医疗建议"), "requester-a")
    escalated = await service.transition(
        case.run_id,
        TransitionRequest(target_status="PROFESSIONAL_ESCALATION_REQUIRED", reason="red flag"),
        "requester-a",
    )
    assert escalated.status == "PROFESSIONAL_ESCALATION_REQUIRED"
    with pytest.raises(ApiError) as model_blocked:
        await service.assert_model_call_allowed(case.run_id)
    assert model_blocked.value.code == "HIGH_RISK_MODEL_CALL_BLOCKED"
    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    assert (await service.get(case.run_id)).status == "PROFESSIONAL_ESCALATION_REQUIRED"
    with pytest.raises(ApiError):
        await service.transition(
            case.run_id,
            TransitionRequest(target_status="EVIDENCE_REQUIRED", reason="dismiss escalation"),
            "requester-a",
        )
    blocked = await service.transition(
        case.run_id,
        TransitionRequest(target_status="ACTION_BLOCKED", reason="no autonomous action"),
        "requester-a",
    )
    assert blocked.status == "ACTION_BLOCKED"
    with pytest.raises(ApiError):
        await service.transition(
            case.run_id,
            TransitionRequest(target_status="APPROVED", reason="model consensus"),
            "requester-a",
        )


async def test_cancel_uses_dedicated_requester_bound_transition(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-cancel", question="法律建议"), "requester-a")
    with pytest.raises(ApiError) as generic_cancel:
        await service.transition(
            case.run_id,
            TransitionRequest(target_status="CANCELLED", reason="generic bypass"),
            "requester-a",
        )
    assert generic_cancel.value.code == "HIGH_RISK_TRANSITION_REQUIRES_DEDICATED_ENDPOINT"
    with pytest.raises(ApiError) as actor_swap:
        await service.cancel(case.run_id, "attacker")
    assert actor_swap.value.code == "HIGH_RISK_ACTOR_NOT_AUTHORIZED"
    cancelled = await service.cancel(case.run_id, "requester-a")
    assert cancelled.status == "CANCELLED"
    assert (await service.audit(case.run_id))[-1].event_type == "high_risk_cancelled"


async def test_prepared_report_survives_restart(tmp_path):
    database = tmp_path / "council.sqlite3"
    store = Store(database)
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-report-restart", question="法律建议"), "requester-a")
    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    await verify_all_required_evidence(service, case)
    prepared = await service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="本地持久化的高风险决策支持报告正文",
            requested_action_type="decision_support_report",
            requested_action_payload={"effect": "read_only"},
        ),
        "requester-a",
    )
    assert prepared.decision and prepared.decision.report == "本地持久化的高风险决策支持报告正文"
    store.close()

    reopened = Store(database)
    persisted = await HighRiskService(reopened, reviewer_config()).get(case.run_id)
    assert persisted.decision and persisted.decision.report == prepared.decision.report
    assert persisted.decision.report_hash == prepared.decision.report_hash


@pytest.mark.parametrize("approved", [False, True])
async def test_expired_approval_can_be_replaced_without_superseding_active_approval(tmp_path, approved):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id=f"run-rerequest-{approved}", question="投资建议"), "requester-a")
    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    await verify_all_required_evidence(service, case)
    await service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="bound report",
            requested_action_type="decision_support_report",
            requested_action_payload={"effect": "read_only"},
        ),
        "requester-a",
    )
    await approve_all_professional_domains(service, case)
    original = await service.request_approval(case.run_id, "requester-a")
    if approved:
        await service.decide_approval(
            case.run_id, original.approval_id,
            ApprovalDecisionRequest(decision="approved", reason="reviewed"),
            "reviewer-b", "reviewer-secret-b",
        )
    with pytest.raises(ApiError) as duplicate:
        await service.request_approval(case.run_id, "requester-a")
    assert duplicate.value.code == "APPROVAL_STILL_ACTIVE"

    store.conn.execute(
        "UPDATE high_risk_approvals SET expires_at=? WHERE approval_id=?",
        ((utc_now() - timedelta(seconds=1)).isoformat(), original.approval_id),
    )
    store.conn.commit()
    replacement = await service.request_approval(case.run_id, "requester-a")
    assert replacement.approval_id != original.approval_id
    assert replacement.status == "pending"
    assert (await service.get_approval(case.run_id, original.approval_id)).status == "expired"
    assert (await service.get(case.run_id)).status == "APPROVAL_REQUIRED"
    assert any(event.event_type == "approval_expired" for event in await service.audit(case.run_id))


async def test_expired_approved_completion_is_audited_and_can_be_re_requested(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-expired-completion", question="投资建议"), "requester-a")
    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    await verify_all_required_evidence(service, case)
    await service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="report approved before expiry",
            requested_action_type="decision_support_report",
            requested_action_payload={"effect": "read_only"},
        ),
        "requester-a",
    )
    await approve_all_professional_domains(service, case)
    approval = await service.request_approval(case.run_id, "requester-a")
    await service.decide_approval(
        case.run_id, approval.approval_id,
        ApprovalDecisionRequest(decision="approved", reason="reviewed"),
        "reviewer-b", "reviewer-secret-b",
    )
    store.conn.execute(
        "UPDATE high_risk_approvals SET expires_at=? WHERE approval_id=?",
        ((utc_now() - timedelta(seconds=1)).isoformat(), approval.approval_id),
    )
    store.conn.commit()

    with pytest.raises(ApiError) as expired:
        await service.complete(case.run_id, approval.approval_id, "requester-a")
    assert expired.value.code == "APPROVAL_EXPIRED"
    assert (await service.get_approval(case.run_id, approval.approval_id)).status == "expired"
    assert (await service.get(case.run_id)).status == "APPROVED"
    assert [event for event in await service.audit(case.run_id) if event.event_type == "approval_expired"][-1].metadata["approval_id"] == approval.approval_id

    replacement = await service.request_approval(case.run_id, "requester-a")
    assert replacement.status == "pending"
    assert (await service.get(case.run_id)).status == "APPROVAL_REQUIRED"


async def test_cancellation_revokes_active_approval(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-cancel-approval", question="法律建议"), "requester-a")
    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    await verify_all_required_evidence(service, case)
    await service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="report to cancel",
            requested_action_type="decision_support_report",
            requested_action_payload={"effect": "read_only"},
        ),
        "requester-a",
    )
    await approve_all_professional_domains(service, case)
    approval = await service.request_approval(case.run_id, "requester-a")
    await service.cancel(case.run_id, "requester-a")
    assert (await service.get_approval(case.run_id, approval.approval_id)).status == "revoked"
    revocations = [event for event in await service.audit(case.run_id) if event.event_type == "approval_revoked"]
    assert revocations[-1].metadata["reason_code"] == "high_risk_run_cancelled"


async def test_terminal_risk_override_is_rejected_and_unauthorized_transition_is_audited(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-terminal-controls", question="生产事故建议"), "requester-a")
    with pytest.raises(ApiError) as unauthorized:
        await service.transition(
            case.run_id,
            TransitionRequest(target_status="ACTION_BLOCKED", reason="spoofed"),
            "attacker",
        )
    assert unauthorized.value.code == "HIGH_RISK_ACTOR_NOT_AUTHORIZED"
    denials = [event for event in await service.audit(case.run_id) if event.event_type == "transition_denied"]
    assert denials[-1].metadata["reason_code"] == "HIGH_RISK_ACTOR_NOT_AUTHORIZED"

    await service.cancel(case.run_id, "requester-a")
    with pytest.raises(ApiError) as terminal:
        await service.override_risk(
            case.run_id,
            RiskOverrideRequest(risk_tier="normal", reason="terminal state must remain immutable"),
            "reviewer-b",
            "reviewer-secret-b",
        )
    assert terminal.value.code == "HIGH_RISK_RUN_TERMINAL"


async def test_recovery_expires_pending_approval_without_advancing_state(tmp_path):
    database = tmp_path / "council.sqlite3"
    store = Store(database)
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-k", question="法律建议"), "requester-a")
    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    await verify_all_required_evidence(service, case)
    await service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="pending report",
            requested_action_type="decision_support_report",
            requested_action_payload={"draft": True},
        ),
        "requester-a",
    )
    await approve_all_professional_domains(service, case)
    approval = await service.request_approval(case.run_id, "requester-a", expires_in=timedelta(minutes=5))
    store.conn.execute(
        "UPDATE high_risk_approvals SET expires_at=? WHERE approval_id=?",
        ((utc_now() - timedelta(seconds=1)).isoformat(), approval.approval_id),
    )
    store.conn.commit()
    store.close()

    reopened = Store(database)
    restarted = HighRiskService(reopened, reviewer_config())
    assert await restarted.recover() == [approval.approval_id]
    assert (await restarted.get_approval(case.run_id, approval.approval_id)).status == "expired"
    assert (await restarted.get(case.run_id)).status == "APPROVAL_REQUIRED"


async def test_api_requires_actor_and_blocks_legacy_mutation_routes(monkeypatch):
    main = importlib.import_module("app.main")
    monkeypatch.setattr(main, "high_risk_service", HighRiskService(main.store, reviewer_config()))
    now = utc_now()
    run_id = f"api-high-risk-{now.timestamp()}"
    run = RunRecord(
        id=run_id,
        question="请给出投资建议",
        mode="standard",
        provider_id="mock",
        model="council-mock",
        status="queued",
        awaiting_user=False,
        created_at=now,
        updated_at=now,
    )
    await main.store.save_run(run)
    transport = httpx.ASGITransport(app=main.app)
    payload = {"run_id": run_id, "question": run.question}
    key = f"high-risk-create-{run_id}"

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001", headers=INTERNAL_HEADERS) as client:
        missing_actor = await client.post("/api/high-risk/runs", json=payload)
        assert missing_actor.status_code == 401
        assert missing_actor.json()["error"]["code"] == "HIGH_RISK_ACTOR_REQUIRED"

        created = await client.post(
            "/api/high-risk/runs",
            json=payload,
            headers={"X-Council-Actor": "requester-a", "Idempotency-Key": key},
        )
        replayed = await client.post(
            "/api/high-risk/runs",
            json=payload,
            headers={"X-Council-Actor": "requester-a", "Idempotency-Key": key},
        )
        assert created.status_code == 200
        assert created.json()["status"] == "MORE_INFORMATION_REQUIRED"
        assert replayed.status_code == 200
        assert replayed.headers["Idempotency-Replayed"] == "true"

        summarize = await client.post(
            f"/api/runs/{run_id}/summarize",
            headers={"X-Council-Actor": "requester-a"},
        )
        delete = await client.delete(
            f"/api/runs/{run_id}",
            headers={"X-Council-Actor": "requester-a"},
        )
        assert summarize.status_code == 409
        assert summarize.json()["error"]["code"] == "HIGH_RISK_CONTROL_REQUIRED"
        assert delete.status_code == 409
        assert await main.store.get_run(run_id) is not None

        audit = await client.get(f"/api/high-risk/runs/{run_id}/audit")
        assert audit.status_code == 200
        assert [event["event_type"] for event in audit.json()].count("normal_route_denied") == 2
        serialized = audit.text
        assert run.question not in serialized
        assert "reviewer-secret-b" not in serialized
        for sensitive_field in (
            "actor_id",
            "policy_version",
            "model_provider",
            "model_name",
            "prompt_template_version",
            "request_hash",
            "response_hash",
            "metadata",
        ):
            assert sensitive_field not in audit.json()[0]


async def test_requester_binding_prevents_actor_swap(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-l", question="合规例外"), "requester-a")
    with pytest.raises(ApiError) as facts_swap:
        await service.replace_facts(case.run_id, complete_facts(case), "attacker")
    assert facts_swap.value.code == "HIGH_RISK_ACTOR_NOT_AUTHORIZED"

    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    with pytest.raises(ApiError) as review_swap:
        await service.prepare_review(
            case.run_id,
            PrepareReviewRequest(
                report="attacker report",
                requested_action_type="decision_support_report",
                requested_action_payload={},
            ),
            "attacker",
        )
    assert review_swap.value.code == "HIGH_RISK_ACTOR_NOT_AUTHORIZED"


async def test_two_store_instances_cannot_decide_same_approval_twice(tmp_path):
    database = tmp_path / "council.sqlite3"
    first_store = Store(database)
    first_service = HighRiskService(first_store, reviewer_config())
    case = await first_service.create(HighRiskCreate(run_id="run-m", question="法律建议"), "requester-a")
    await first_service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    await verify_all_required_evidence(first_service, case)
    await first_service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="bound report",
            requested_action_type="decision_support_report",
            requested_action_payload={"effect": "read_only"},
        ),
        "requester-a",
    )
    await approve_all_professional_domains(first_service, case)
    approval = await first_service.request_approval(case.run_id, "requester-a")
    second_store = Store(database)
    second_service = HighRiskService(second_store, reviewer_config())

    results = await asyncio.gather(
        first_service.decide_approval(
            case.run_id, approval.approval_id,
            ApprovalDecisionRequest(decision="approved", reason="first connection"),
            "reviewer-b", "reviewer-secret-b",
        ),
        second_service.decide_approval(
            case.run_id, approval.approval_id,
            ApprovalDecisionRequest(decision="rejected", reason="second connection"),
            "reviewer-c", "reviewer-secret-c",
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(item, Exception) for item in results) == 1
    terminal = await first_service.get_approval(case.run_id, approval.approval_id)
    assert terminal.status in {"approved", "rejected"}


async def test_requester_binding_blocks_transition_and_approval_consumption(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-n", question="法律建议"), "requester-a")

    with pytest.raises(ApiError) as actor_swap:
        await service.transition(
            case.run_id,
            TransitionRequest(target_status="PROFESSIONAL_ESCALATION_REQUIRED", reason="spoofed"),
            "attacker",
        )
    assert actor_swap.value.code == "HIGH_RISK_ACTOR_NOT_AUTHORIZED"
    assert (await service.get(case.run_id)).status == "MORE_INFORMATION_REQUIRED"

    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    await verify_all_required_evidence(service, case)
    await service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="bound report",
            requested_action_type="decision_support_report",
            requested_action_payload={"effect": "read_only"},
        ),
        "requester-a",
    )
    await approve_all_professional_domains(service, case)
    approval = await service.request_approval(case.run_id, "requester-a")
    await service.decide_approval(
        case.run_id,
        approval.approval_id,
        ApprovalDecisionRequest(decision="approved", reason="reviewed"),
        "reviewer-b",
        "reviewer-secret-b",
    )

    with pytest.raises(ApiError) as consume_swap:
        await service.complete(case.run_id, approval.approval_id, "attacker")
    assert consume_swap.value.code == "HIGH_RISK_ACTOR_NOT_AUTHORIZED"
    persisted = await service.get_approval(case.run_id, approval.approval_id)
    assert persisted.consumed_at is None
    assert (await service.get(case.run_id)).status == "APPROVED"


async def test_fact_change_emits_explicit_approval_revocation_audit(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-o", question="投资建议"), "requester-a")
    facts = complete_facts(case)
    await service.replace_facts(case.run_id, facts, "requester-a")
    await verify_all_required_evidence(service, case)
    await service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="report before facts changed",
            requested_action_type="decision_support_report",
            requested_action_payload={"effect": "read_only"},
        ),
        "requester-a",
    )
    await approve_all_professional_domains(service, case)
    approval = await service.request_approval(case.run_id, "requester-a")

    changed = [
        fact.model_copy(update={"value": f"changed-{fact.fact_id}"})
        for fact in facts
    ]
    await service.replace_facts(case.run_id, changed, "requester-a")

    assert (await service.get_approval(case.run_id, approval.approval_id)).status == "revoked"
    events = await service.audit(case.run_id)
    revocation = [event for event in events if event.event_type == "approval_revoked"][-1]
    assert revocation.metadata["reason_code"] == "critical_facts_changed"
    assert revocation.metadata["approval_count"] == 1


async def test_approval_audit_failure_rolls_back_decision(tmp_path, monkeypatch):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-p", question="合规建议"), "requester-a")
    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    await verify_all_required_evidence(service, case)
    await service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="report requiring audit",
            requested_action_type="decision_support_report",
            requested_action_payload={"effect": "read_only"},
        ),
        "requester-a",
    )
    await approve_all_professional_domains(service, case)
    approval = await service.request_approval(case.run_id, "requester-a")

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("simulated approval audit failure")

    monkeypatch.setattr(service, "_insert_audit", fail_audit)
    with pytest.raises(RuntimeError, match="approval audit failure"):
        await service.decide_approval(
            case.run_id,
            approval.approval_id,
            ApprovalDecisionRequest(decision="approved", reason="reviewed"),
            "reviewer-b",
            "reviewer-secret-b",
        )

    assert (await service.get_approval(case.run_id, approval.approval_id)).status == "pending"
    assert (await service.get(case.run_id)).status == "APPROVAL_REQUIRED"


async def test_security_sensitive_idempotency_replay_rechecks_authorization_and_state(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    case = await service.create(HighRiskCreate(run_id="run-q", question="投资建议"), "requester-a")
    await service.replace_facts(case.run_id, complete_facts(case), "requester-a")
    await verify_all_required_evidence(service, case)
    await service.prepare_review(
        case.run_id,
        PrepareReviewRequest(
            report="idempotent report",
            requested_action_type="decision_support_report",
            requested_action_payload={"effect": "read_only"},
        ),
        "requester-a",
    )
    await approve_all_professional_domains(service, case)
    approval = await service.request_approval(case.run_id, "requester-a")
    request = ApprovalDecisionRequest(decision="approved", reason="reviewed")

    class HeaderResponse:
        def __init__(self):
            self.headers: dict[str, str] = {}

    async def decide():
        return await service.decide_approval(
            case.run_id,
            approval.approval_id,
            request,
            "reviewer-b",
            "reviewer-secret-b",
        )

    payload = {"actor_id": "reviewer-b", "approval_id": approval.approval_id, **request.model_dump(mode="json")}
    first_response = HeaderResponse()
    first = await execute_idempotent_model_action(
        store,
        f"high-risk:{case.run_id}:approval:{approval.approval_id}:decision",
        "security-replay-key",
        payload,
        decide,
        first_response,  # type: ignore[arg-type]
        ApprovalRecord,
    )
    assert first.status == "approved"

    await service.revoke_approval(case.run_id, approval.approval_id, "requester-a", "facts changed")

    wrong_secret_response = HeaderResponse()
    with pytest.raises(ApiError) as unauthorized:
        await execute_idempotent_model_action(
            store,
            f"high-risk:{case.run_id}:approval:{approval.approval_id}:decision",
            "security-replay-key",
            payload,
            decide,
            wrong_secret_response,  # type: ignore[arg-type]
            ApprovalRecord,
            lambda cached: service.resolve_cached_approval_decision(
                case.run_id, approval.approval_id, request, "reviewer-b", "wrong-secret", cached
            ),
        )
    assert unauthorized.value.code == "REVIEWER_NOT_AUTHORIZED"

    stale_response = HeaderResponse()
    with pytest.raises(ApiError) as stale:
        await execute_idempotent_model_action(
            store,
            f"high-risk:{case.run_id}:approval:{approval.approval_id}:decision",
            "security-replay-key",
            payload,
            decide,
            stale_response,  # type: ignore[arg-type]
            ApprovalRecord,
            lambda cached: service.resolve_cached_approval_decision(
                case.run_id, approval.approval_id, request, "reviewer-b", "reviewer-secret-b", cached
            ),
        )
    assert stale.value.code == "IDEMPOTENT_SECURITY_STATE_CHANGED"


async def test_high_risk_run_is_controlled_before_model_task_starts(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    orchestrator = Orchestrator(store, builtin_providers(), service)
    run = await orchestrator.start(
        RunCreate(question="医疗决策支持", provider_id="mock", high_risk=True),
        high_risk_actor="requester-a",
    )
    assert run.high_risk_control is True
    assert await store.has_high_risk_control(run.id)
    assert (await service.get(run.id)).status == "MORE_INFORMATION_REQUIRED"
    await orchestrator.shutdown()


async def test_new_standard_run_explicitly_disables_high_risk_control(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    orchestrator = Orchestrator(store, builtin_providers(), service)
    run = await orchestrator.start(RunCreate(question="普通产品决策", provider_id="mock"))
    assert run.high_risk_control is False
    assert (await store.get_run(run.id)).high_risk_control is False
    await orchestrator.shutdown()


async def test_normal_run_persistence_failure_leaves_high_risk_action_blocked(tmp_path, monkeypatch):
    store = Store(tmp_path / "council.sqlite3")
    service = HighRiskService(store, reviewer_config())
    orchestrator = Orchestrator(store, builtin_providers(), service)
    original_save = store.save_run

    async def fail_save(_run):
        raise RuntimeError("simulated run persistence failure")

    monkeypatch.setattr(store, "save_run", fail_save)
    with pytest.raises(RuntimeError, match="persistence failure"):
        await orchestrator.start(
            RunCreate(question="生产事故处理", provider_id="mock", high_risk=True),
            high_risk_actor="requester-a",
        )
    monkeypatch.setattr(store, "save_run", original_save)
    rows = store.conn.execute("SELECT run_id,status FROM high_risk_runs").fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "ACTION_BLOCKED"
    assert await store.get_run(rows[0][0]) is None
