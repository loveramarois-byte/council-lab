from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import ProviderProfile, ProviderType, RunCreate
from app.orchestrator import Orchestrator
from app.output_contracts import get_output_contract, list_output_contracts
from app.providers import Generation
from app.reports import run_html, run_markdown
from app.store import Store
from evals.scoring import aggregate_execution_by_contract


def test_contract_registry_has_six_stable_contracts_and_general_default():
    contracts = list_output_contracts()
    assert [item.id for item in contracts] == [
        "general_decision",
        "product_review",
        "technical_architecture",
        "medical_second_opinion",
        "legal_risk_review",
        "financial_decision_review",
    ]
    assert get_output_contract("general_decision").name == "一般决策"
    with pytest.raises(ValueError, match="输出契约不存在"):
        get_output_contract("unknown")
    with pytest.raises(ValidationError):
        RunCreate(question="验证输入", output_contract="unknown")


async def test_product_contract_changes_guidance_and_creates_typed_brief_extension(tmp_path, monkeypatch):
    class CapturingBackend:
        def __init__(self):
            self.systems: list[str] = []

        async def generate(self, prompt, system, model, temperature=0.2):
            self.systems.append(system)
            return Generation(
                text="目标用户是个人开发者；先做小范围验证，指标不达标就停止。"
                if "记录员" in system
                else "表态：部分认同。需要明确目标用户、失败条件和验证指标。"
            )

    backend = CapturingBackend()
    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: backend)
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})
    run = await orchestrator.start(
        RunCreate(
            question="是否为个人开发者发布这个产品？",
            provider_id="mock",
            auto_summarize=True,
            output_contract="product_review",
        )
    )
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)
    brief = await store.get_decision_brief(run.id)

    assert current is not None and current.output_contract == "product_review"
    assert brief is not None and brief.schema_version == 2
    assert brief.output_contract == "product_review"
    assert brief.contract_extension is not None
    assert brief.contract_extension.contract == "product_review"
    assert brief.contract_extension.user_problem == current.question
    assert any("目标用户" in system and "验证实验" in system for system in backend.systems)
    for exported in (run_markdown(current, decision_brief=brief), run_html(current, decision_brief=brief)):
        assert "产品评审契约" in exported
        assert "用户问题" in exported
    store.close()


async def test_architecture_contract_is_preserved_by_fork_and_rerun_inputs(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    profile = ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)
    orchestrator = Orchestrator(store, {"mock": profile})
    run = await orchestrator.start(
        RunCreate(
            question="是否采用事件驱动架构？",
            provider_id="mock",
            auto_summarize=True,
            output_contract="technical_architecture",
        )
    )
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)
    brief = await store.get_decision_brief(run.id)
    assert current is not None and current.output_contract == "technical_architecture"
    assert brief is not None and brief.contract_extension is not None
    assert brief.contract_extension.contract == "technical_architecture"
    assert brief.contract_extension.requirements == [current.question]
    store.close()


def test_historical_run_and_brief_default_to_general_contract():
    request = RunCreate(question="历史兼容")
    assert request.output_contract == "general_decision"


def test_benchmark_execution_can_be_grouped_by_output_contract():
    cases = [
        {
            "id": "product-1",
            "output_contract": "product_review",
            "variants": [{"strategy": "direct", "status": "completed", "model_calls": 1}],
        },
        {
            "id": "architecture-1",
            "output_contract": "technical_architecture",
            "variants": [{"strategy": "direct", "status": "completed", "model_calls": 1}],
        },
    ]
    grouped = aggregate_execution_by_contract(cases)
    assert grouped["product_review"]["direct"]["cases"] == 1
    assert grouped["technical_architecture"]["direct"]["completed"] == 1
