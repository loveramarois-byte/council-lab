from __future__ import annotations

import asyncio
import importlib
import sqlite3
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.decision_brief import build_decision_brief
from app.models import (
    DecisionBrief,
    DiscussionTurn,
    FinalDecision,
    MinorityReport,
    RunRecord,
    ProviderProfile,
    ProviderType,
    RunCreate,
    UnresolvedIssue,
    UsageSummary,
    utc_now,
)
from app.store import Store
from app.orchestrator import Orchestrator
from app.providers import Generation
from app.reports import run_html, run_markdown
from conftest import TEST_INTERNAL_API_TOKEN


def completed_run(*stances: tuple[str, str], verified: bool = False) -> RunRecord:
    now = utc_now()
    turns = [
        DiscussionTurn(
            id=f"turn-{index}",
            speaker_type="agent",
            speaker_id=seat_id,
            speaker_name=seat_id,
            role_label="测试席",
            content=content,
        )
        for index, (seat_id, content) in enumerate(stances, 1)
    ]
    return RunRecord(
        id="run-brief-1",
        question="是否应该发布这个版本？",
        mode="standard",
        provider_id="mock",
        model="council-mock",
        status="completed",
        created_at=now,
        updated_at=now,
        participant_roles=[
            {"id": seat_id, "name": seat_id, "role": "测试席", "brief": ""}
            for seat_id, _ in stances
        ],
        discussion_turns=turns,
        final_decision=FinalDecision(
            final_answer="先做小范围发布，并保留回滚开关。",
            verified_claims=["回滚流程已演练"] if verified else [],
            unverified_claims=[] if verified else ["用户需求仍未经过外部核验"],
            disagreements=[content for _, content in stances if content.startswith("表态：反驳")],
            risks_and_limitations=["模型共识不等于事实验证。"],
            confidence={"level": "unverified", "explanation": "不提供百分比置信度。"},
            provider_summary={"provider": "Mock", "protocol": "mock", "model": "council-mock"},
            usage=UsageSummary(model_calls=len(stances) + 1),
        ),
    )


def test_decision_brief_rejects_unconditional_proceed_with_blocking_issue():
    with pytest.raises(ValidationError, match="blocking"):
        DecisionBrief(
            id="brief-1",
            run_id="run-1",
            version=1,
            schema_version=1,
            status="proceed",
            recommendation="立即执行",
            support="majority",
            unresolved=[UnresolvedIssue(id="issue-1", issue="预算尚未确认", blocking=True)],
            limitations=["未经过外部事实核验。"],
        )


def test_contested_brief_requires_a_minority_report():
    with pytest.raises(ValidationError, match="minority"):
        DecisionBrief(
            id="brief-1",
            run_id="run-1",
            version=1,
            schema_version=1,
            status="conditional",
            recommendation="满足条件后执行",
            support="contested",
            limitations=["未经过外部事实核验。"],
        )


def test_generator_derives_observable_support_and_preserves_opposition():
    run = completed_run(
        ("analyst", "初步方案"),
        ("challenger", "表态：反驳。预算不足时不应上线。"),
        ("builder", "表态：部分认同。先做灰度。"),
        ("observer", "表态：认同。未解决分歧：预算门槛。"),
    )

    brief = build_decision_brief(run)

    assert brief.status == "conditional"
    assert brief.support == "contested"
    assert brief.minority_report is not None
    assert brief.minority_report.seat_ids == ["challenger"]
    assert "预算不足" in brief.minority_report.summary
    assert any(issue.blocking is False for issue in brief.unresolved)
    assert not hasattr(brief, "confidence")


def test_generator_supports_all_three_statuses_without_percentage_confidence():
    agreeing = (
        ("analyst", "初步方案"),
        ("challenger", "表态：认同。"),
        ("builder", "表态：认同。"),
        ("observer", "表态：认同。"),
    )
    proceed = build_decision_brief(completed_run(*agreeing, verified=True))
    conditional = build_decision_brief(completed_run(*agreeing))
    no_decision_run = completed_run(*agreeing)
    no_decision_run.final_decision = no_decision_run.final_decision.model_copy(
        update={"contradicted_claims": ["关键前提被现有证据否定"]}
    )
    no_decision = build_decision_brief(no_decision_run)

    assert proceed.status == "proceed"
    assert conditional.status == "conditional"
    assert no_decision.status == "no_decision"
    assert proceed.support == "unanimous"
    assert "%" not in proceed.model_dump_json()


async def test_decision_brief_store_is_append_only_and_idempotent(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    run = completed_run(("analyst", "初步方案"), verified=True)
    await store.save_run(run)
    brief = build_decision_brief(run)

    created = await store.create_decision_brief(brief)
    replayed = await store.create_decision_brief(brief)

    assert created == replayed
    assert await store.get_decision_brief(brief.run_id) == brief
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(
            "UPDATE decision_briefs SET generation_reason='tampered' WHERE id=?",
            (brief.id,),
        )
    store.conn.rollback()
    store.close()


def test_minority_report_rejects_duplicate_or_empty_seat_ids():
    with pytest.raises(ValidationError):
        MinorityReport(summary="反对", seat_ids=["challenger", "challenger"])


async def test_brief_persistence_failure_is_retryable_without_repeating_model_calls(tmp_path, monkeypatch):
    class CountingBackend:
        def __init__(self):
            self.calls = 0

        async def generate(self, prompt, system, model, temperature=0.2):
            self.calls += 1
            if "记录员" in system:
                return Generation(text="保留回滚开关后发布。")
            if self.calls == 1:
                return Generation(text="初步方案")
            return Generation(text="表态：认同。继续执行。")

    backend = CountingBackend()
    monkeypatch.setattr("app.orchestrator.build_backend", lambda profile: backend)
    store = Store(tmp_path / "council.sqlite3")
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )
    original_create = store.create_decision_brief
    attempts = 0

    async def fail_once(brief):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("simulated full disk")
        return await original_create(brief)

    monkeypatch.setattr(store, "create_decision_brief", fail_once)
    run = await orchestrator.start(RunCreate(question="验证简报持久化恢复", provider_id="mock"))
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)
    assert current is not None and current.status == "awaiting_final_input"

    await orchestrator.summarize(run.id)
    await orchestrator.tasks[run.id]
    failed = await store.get_run(run.id)
    assert failed is not None
    assert failed.status == "awaiting_final_input"
    assert failed.final_decision is not None
    assert await store.get_decision_brief(run.id) is None
    assert backend.calls == 5

    await orchestrator.summarize(run.id)
    await orchestrator.tasks[run.id]
    completed = await store.get_run(run.id)
    brief = await store.get_decision_brief(run.id)
    assert completed is not None and completed.status == "completed"
    assert brief is not None and brief.version == 1
    assert backend.calls == 5
    events = [event.type for event in await store.list_events(run.id)]
    assert events.count("decision_brief_validation_failed") == 1
    assert events.count("decision_brief_generated") == 1
    assert events[-1] == "final_completed"


def test_exports_render_structured_brief_without_fact_probability():
    run = completed_run(
        ("analyst", "初步方案"),
        ("challenger", "表态：反驳。预算不足时不应上线。"),
        ("builder", "表态：部分认同。先灰度。"),
    )
    brief = build_decision_brief(run)

    markdown = run_markdown(run, decision_brief=brief)
    html = run_html(run, decision_brief=brief)

    for exported in (markdown, html):
        assert "结构化决策简报" in exported
        assert "满足条件后推进" in exported
        assert "存在明确反对" in exported
        assert "少数意见" in exported
        assert "预算不足" in exported
        assert "事实正确概率" in exported
        assert "82%" not in exported


async def test_decision_brief_api_validates_run_id_and_distinguishes_legacy_absence(monkeypatch):
    main = importlib.import_module("app.main")
    run = completed_run(("analyst", "初步方案"), verified=True)
    brief = build_decision_brief(run)
    get_run = AsyncMock(return_value=run)
    get_brief = AsyncMock(return_value=brief)
    monkeypatch.setattr(main.store, "get_run", get_run)
    monkeypatch.setattr(main.store, "get_decision_brief", get_brief)
    monkeypatch.setattr(main.store, "has_high_risk_control", AsyncMock(return_value=False))
    transport = httpx.ASGITransport(app=main.app)
    headers = {"X-Council-Internal-Token": TEST_INTERNAL_API_TOKEN}

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001", headers=headers) as client:
        response = await client.get(f"/api/runs/{run.id}/decision-brief")
        exported = await client.get(f"/api/runs/{run.id}/export?format=markdown")
        invalid = await client.get("/api/runs/%24invalid/decision-brief")
        get_brief.return_value = None
        legacy = await client.get(f"/api/runs/{run.id}/decision-brief")

    assert response.status_code == 200
    assert response.json()["schema_version"] == 2
    assert exported.status_code == 200
    assert "结构化决策简报" in exported.text
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    assert legacy.status_code == 404
    assert legacy.json()["error"]["code"] == "DECISION_BRIEF_NOT_FOUND"
