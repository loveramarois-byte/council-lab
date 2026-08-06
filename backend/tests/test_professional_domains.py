from __future__ import annotations

import importlib
from datetime import datetime, timezone

import httpx
import pytest

from conftest import TEST_INTERNAL_API_TOKEN
from app.decision_assurance import analyze_readiness, detect_professional_domains
from app.decision_memory import MemoryProposal, MemoryProposalDecision
from app.models import ProviderProfile, ProviderType, RunCreate, RunRecord
from app.orchestrator import Orchestrator, analyze_question
from app.output_contracts import get_output_contract, list_output_contracts
from app.risk.classifier import assess_risk, required_facts_for
from app.store import Store
from app.templates import get_template


DOMAIN_CONTRACTS = {
    "medical_second_opinion": "医疗信息整理",
    "legal_risk_review": "法律风险梳理",
    "financial_decision_review": "财务决策分析",
}

TEMPLATE_CONTRACTS = {
    "medical_information_review": "medical_second_opinion",
    "legal_risk_review": "legal_risk_review",
    "financial_decision_review": "financial_decision_review",
}


def test_professional_contracts_have_stable_disclaimers_and_high_risk_boundary():
    contracts = {item.id: item for item in list_output_contracts()}

    for contract_id, name in DOMAIN_CONTRACTS.items():
        contract = contracts[contract_id]
        assert contract.name == name
        assert contract.required_disclaimer
        assert "不构成" in contract.required_disclaimer
        assert contract.requires_high_risk is True
        assert get_output_contract(contract_id) == contract


def test_professional_templates_give_each_seat_a_distinct_bounded_job():
    for template_id, contract_id in TEMPLATE_CONTRACTS.items():
        template = get_template(template_id)
        assert template.default_output_contract == contract_id
        assert template.requires_high_risk is True
        assert set(template.seat_guidance) == {"analyst", "challenger", "builder", "observer"}
        assert len(set(template.seat_guidance.values())) == 4
        assert all(len(value) >= 12 for value in template.seat_guidance.values())


@pytest.mark.parametrize(
    ("question", "expected_prompt"),
    [
        ("癌症患者是否应该停药并改做手术？", "主治医师"),
        ("劳动合同解除争议已经收到仲裁通知，下一步怎么办？", "司法辖区"),
        ("是否应该贷款购买这份保险，最多能承受损失十万元？", "最大损失"),
    ],
)
def test_professional_questions_force_high_risk_and_domain_specific_facts(question: str, expected_prompt: str):
    readiness = analyze_readiness(question)

    assert "high_risk" in readiness.task_labels
    assert readiness.recommended_mode == "high_risk_council"
    assert readiness.ready is False
    assert any(expected_prompt in item for item in readiness.clarification_questions)


@pytest.mark.parametrize(
    ("question", "domain"),
    [
        ("Should I take two metformin tablets instead of one tonight?", "medical"),
        ("Can my landlord throw me out tomorrow without notice?", "legal"),
        ("Should I put my retirement savings into NVDA calls?", "investment"),
    ],
)
def test_adversarial_english_professional_questions_cannot_use_normal_flow(question: str, domain: str):
    assert detect_professional_domains(question) == [domain]
    readiness = analyze_readiness(question)
    assert "high_risk" in readiness.task_labels
    assert readiness.ready is False
    analysis = analyze_question(question, "quick")
    assert analysis.high_risk_domains == [domain]
    assert analysis.short_task_route is False
    assessment = assess_risk(question, f"risk-{domain}")
    assert assessment.detected_domains == [domain]
    assert any(fact.fact_id.startswith(f"{domain}_") for fact in required_facts_for(assessment))


@pytest.mark.parametrize(
    "question",
    [
        "保险箱应该放在哪里？",
        "基金会的官网如何改版？",
        "数据库迁移需要保留回滚方案。",
        "只在可于五分钟内回滚时灰度发布。",
    ],
)
def test_non_professional_chinese_compounds_do_not_trigger_high_risk(question: str):
    assert detect_professional_domains(question) == []
    assert analyze_question(question, "standard").high_risk_domain is False


async def test_orchestrator_rejects_professional_question_without_high_risk_control(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )

    with pytest.raises(ValueError, match="高风险控制"):
        await orchestrator.start(RunCreate(question="是否应该调整化疗剂量？", provider_id="mock"))

    store.close()


async def test_orchestrator_rejects_professional_contract_without_high_risk_control(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )

    with pytest.raises(ValueError, match="高风险控制"):
        await orchestrator.start(
            RunCreate(
                question="请整理这份材料。",
                provider_id="mock",
                output_contract="legal_risk_review",
            )
        )

    store.close()


async def test_orchestrator_rejects_professional_template_without_high_risk_control(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )

    with pytest.raises(ValueError, match="高风险控制"):
        await orchestrator.start(
            RunCreate(
                question="请整理这份材料。",
                provider_id="mock",
                template_id="medical_information_review",
            )
        )

    store.close()


async def test_orchestrator_rejects_professional_template_with_wrong_contract(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )

    with pytest.raises(ValueError, match="对应的输出契约"):
        await orchestrator.start(
            RunCreate(
                question="请整理这份材料。",
                provider_id="mock",
                template_id="medical_information_review",
                high_risk=True,
            )
        )

    store.close()


async def test_orchestrator_rejects_professional_risk_hidden_in_selected_memory(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )
    proposal = MemoryProposal(
        source_run_id="source-run",
        type="risk",
        content="The patient takes metformin tablets and is considering changing the dose.",
        rationale="Carry this medical constraint into the next decision.",
    )
    now = datetime.now(timezone.utc)
    await store.save_run(
        RunRecord(
            id="source-run",
            question="What should we remember?",
            mode="standard",
            provider_id="mock",
            model="council-mock",
            status="completed",
            created_at=now,
            updated_at=now,
        )
    )
    await store.create_memory_proposals([proposal])
    approved = await store.approve_memory_proposal(proposal.id, MemoryProposalDecision())

    with pytest.raises(ValueError, match="记忆、资料或项目上下文"):
        await orchestrator.start(
            RunCreate(
                question="Should we continue with the current plan?",
                provider_id="mock",
                selected_memory_ids=[approved.memory.id],
            )
        )

    store.close()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "question": "是否应该调整化疗剂量？",
            "provider_id": "mock",
            "high_risk": False,
            "readiness_override": True,
            "readiness_override_reason": "用户选择继续",
        },
        {
            "question": "请整理这份材料。",
            "provider_id": "mock",
            "output_contract": "legal_risk_review",
            "high_risk": False,
        },
        {
            "question": "请整理这份材料。",
            "provider_id": "mock",
            "template_id": "medical_information_review",
            "high_risk": False,
        },
        {
            "question": "这次合规审计是否可以直接批准？",
            "provider_id": "mock",
            "high_risk": False,
        },
        {
            "question": "生产事故后是否应该立即回滚？",
            "provider_id": "mock",
            "high_risk": False,
        },
    ],
)
async def test_run_api_rejects_professional_normal_route_bypass(payload):
    main = importlib.import_module("app.main")
    transport = httpx.ASGITransport(app=main.app)
    headers = {"X-Council-Internal-Token": TEST_INTERNAL_API_TOKEN}

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        response = await client.post("/api/runs", headers=headers, json=payload)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "HIGH_RISK_CONTROL_REQUIRED"


async def test_run_api_rejects_professional_template_contract_mismatch():
    main = importlib.import_module("app.main")
    transport = httpx.ASGITransport(app=main.app)
    headers = {
        "X-Council-Internal-Token": TEST_INTERNAL_API_TOKEN,
        "X-Council-Actor": "user-a",
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        response = await client.post(
            "/api/runs",
            headers=headers,
            json={
                "question": "请整理这份材料。",
                "provider_id": "mock",
                "template_id": "medical_information_review",
                "output_contract": "general_decision",
                "high_risk": True,
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TEMPLATE_OUTPUT_CONTRACT_REQUIRED"
