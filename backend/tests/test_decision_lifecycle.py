from __future__ import annotations

import sqlite3
import importlib

import httpx
import pytest
from pydantic import ValidationError

from app.decision_lifecycle import RunForkCreate, compare_briefs, reusable_seat_count
from app.migrations import SCHEMA_MIGRATIONS, SCHEMA_VERSION
from app.models import ProviderProfile, ProviderType, RunCreate
from app.orchestrator import Orchestrator
from app.risk.schemas import HighRiskCreate
from app.risk.service import HighRiskService
from app.store import Store
from conftest import TEST_INTERNAL_API_TOKEN


def test_fork_request_is_strict_and_checkpoint_must_exist():
    with pytest.raises(ValidationError):
        RunForkCreate.model_validate({"reason": "有效原因", "unknown": True})
    with pytest.raises(ValueError, match="不存在"):
        reusable_seat_count("after_seat_4", 3)
    assert reusable_seat_count("before_synthesis", 3) == 3


async def test_fork_reuses_only_bounded_turns_and_keeps_parent_immutable(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )
    parent = await orchestrator.start(
        RunCreate(
            question="是否应该先灰度发布这个版本？",
            provider_id="mock",
            auto_summarize=True,
        )
    )
    await orchestrator.tasks[parent.id]
    original = await store.get_run(parent.id)
    assert original is not None and original.status == "completed"
    original_json = original.model_dump_json()

    child = await orchestrator.fork(
        original,
        RunForkCreate(
            checkpoint="after_seat_2",
            reason="加入更严格的回滚约束",
            prompt_append="必须在五分钟内完成回滚。",
            auto_summarize=True,
        ),
    )
    await orchestrator.tasks[child.id]
    completed_child = await store.get_run(child.id)
    lineage = await store.get_run_lineage(child.id)

    assert completed_child is not None and completed_child.status == "completed"
    assert completed_child.id != original.id
    assert completed_child.current_speaker_index == len(completed_child.participant_roles)
    assert completed_child.usage.model_calls == len(completed_child.participant_roles) - 2 + 1
    reused = completed_child.discussion_turns[:2]
    assert [turn.id for turn in reused] == [turn.id for turn in original.discussion_turns[:2]]
    assert all(turn.reused_from_run_id == original.id for turn in reused)
    assert lineage.parent is not None
    assert lineage.parent.parent_run_id == original.id
    assert lineage.parent.reused_turn_ids == [turn.id for turn in original.discussion_turns[:2]]
    assert (await store.get_run(original.id)).model_dump_json() == original_json

    left = await store.get_decision_brief(original.id)
    right = await store.get_decision_brief(completed_child.id)
    assert left is not None and right is not None
    comparison = compare_briefs(left, right, related=await store.runs_are_related(original.id, completed_child.id))
    assert comparison.related is True
    assert comparison.left_run_id == original.id
    assert comparison.right_run_id == completed_child.id
    store.close()


async def test_fork_rejects_mode_change_after_reusable_turns(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )
    parent = await orchestrator.start(
        RunCreate(question="比较两套发布计划", provider_id="mock", auto_summarize=True)
    )
    await orchestrator.tasks[parent.id]
    source = await store.get_run(parent.id)
    assert source is not None

    with pytest.raises(ValueError, match="切换审议模式"):
        await orchestrator.fork(
            source,
            RunForkCreate(checkpoint="after_seat_1", reason="切换为快速模式", mode="quick"),
        )
    assert await store.list_run_forks(source.id) == []
    store.close()


async def test_fork_api_is_validated_and_persistently_idempotent(tmp_path, monkeypatch):
    main = importlib.import_module("app.main")
    store = Store(tmp_path / "council.sqlite3")
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )
    parent = await orchestrator.start(
        RunCreate(question="验证分叉接口幂等", provider_id="mock", auto_summarize=True)
    )
    await orchestrator.tasks[parent.id]
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "orchestrator", orchestrator)
    transport = httpx.ASGITransport(app=main.app)
    headers = {
        "X-Council-Internal-Token": TEST_INTERNAL_API_TOKEN,
        "Idempotency-Key": "fork-request-key-123",
        "X-Council-Actor": "local-requester",
    }
    payload = {
        "checkpoint": "before_deliberation",
        "reason": "使用同一幂等键只创建一次",
        "prompt_append": "增加一个新约束。",
        "auto_summarize": True,
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        first = await client.post(f"/api/runs/{parent.id}/fork", headers=headers, json=payload)
        replay = await client.post(f"/api/runs/{parent.id}/fork", headers=headers, json=payload)
        invalid = await client.post(
            f"/api/runs/{parent.id}/fork",
            headers={**headers, "Idempotency-Key": "fork-request-key-456"},
            json={**payload, "unexpected": True},
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["id"] == replay.json()["id"]
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert invalid.status_code == 422
    assert len(await store.list_run_forks(parent.id)) == 1
    await orchestrator.tasks[first.json()["id"]]
    store.close()


async def test_high_risk_fork_persistence_failure_fails_closed(tmp_path, monkeypatch):
    store = Store(tmp_path / "council.sqlite3")
    high_risk_service = HighRiskService(store, {"requester-a": "requester-secret-a"})
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
        high_risk_service=high_risk_service,
    )
    parent = await orchestrator.start(
        RunCreate(question="验证高风险分叉持久化门禁", provider_id="mock", auto_summarize=True)
    )
    await orchestrator.tasks[parent.id]
    source = await store.get_run(parent.id)
    assert source is not None
    source.high_risk_control = True
    await store.save_run(source)
    await high_risk_service.create(
        HighRiskCreate(run_id=source.id, question=source.question),
        "requester-a",
    )

    async def fail_save(*_args, **_kwargs):
        raise sqlite3.OperationalError("simulated fork write failure")

    monkeypatch.setattr(store, "save_forked_run", fail_save)
    with pytest.raises(sqlite3.OperationalError, match="fork write failure"):
        await orchestrator.fork(
            source,
            RunForkCreate(checkpoint="before_deliberation", reason="高风险情景变化"),
            high_risk_actor="requester-a",
        )

    child_row = store.conn.execute(
        "SELECT run_id,status FROM high_risk_runs WHERE run_id<>?",
        (source.id,),
    ).fetchone()
    assert child_row is not None and child_row[1] == "ACTION_BLOCKED"
    assert await store.get_run(child_row[0]) is None
    assert store.conn.execute(
        "SELECT COUNT(*) FROM high_risk_approvals WHERE run_id=?",
        (child_row[0],),
    ).fetchone()[0] == 0
    audit_types = [row[0] for row in store.conn.execute(
        "SELECT event_type FROM high_risk_audit_events WHERE run_id=? ORDER BY sequence",
        (child_row[0],),
    )]
    assert audit_types[-1] == "persistence_failure_blocked"
    store.close()


def test_v6_database_upgrades_to_forks_without_rewriting_history(tmp_path):
    database = tmp_path / "council.sqlite3"
    connection = sqlite3.connect(database)
    for version in range(1, 7):
        for statement in SCHEMA_MIGRATIONS[version]:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version={version}")
    run_payload = '{"id":"historical-run","status":"completed","discussion_turns":[{"id":"turn-1"}]}'
    brief_payload = '{"id":"brief-1","run_id":"historical-run","version":1}'
    connection.execute(
        "INSERT INTO runs(id,payload,created_at) VALUES(?,?,?)",
        ("historical-run", run_payload, "2026-07-31T00:00:00+00:00"),
    )
    connection.execute(
        "INSERT INTO decision_briefs(id,run_id,version,schema_version,payload_json,generation_reason,created_at) VALUES(?,?,?,?,?,?,?)",
        ("brief-1", "historical-run", 1, 1, brief_payload, "run_completed", "2026-07-31T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()

    store = Store(database)
    try:
        assert store.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert store.conn.execute("SELECT payload FROM runs WHERE id='historical-run'").fetchone()[0] == run_payload
        assert store.conn.execute("SELECT payload_json FROM decision_briefs WHERE id='brief-1'").fetchone()[0] == brief_payload
        assert store.conn.execute("SELECT COUNT(*) FROM run_forks").fetchone()[0] == 0
    finally:
        store.close()


def test_failed_v7_migration_restores_v6_database(tmp_path, monkeypatch):
    database = tmp_path / "council.sqlite3"
    connection = sqlite3.connect(database)
    for version in range(1, 7):
        for statement in SCHEMA_MIGRATIONS[version]:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version={version}")
    connection.execute(
        "INSERT INTO runs(id,payload,created_at) VALUES('protected-v6','{}','2026-07-31T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()
    monkeypatch.setitem(SCHEMA_MIGRATIONS, 7, ("THIS IS NOT SQL",))

    with pytest.raises(sqlite3.OperationalError):
        Store(database)

    restored = sqlite3.connect(database)
    try:
        assert restored.execute("PRAGMA user_version").fetchone()[0] == 6
        assert restored.execute("SELECT id FROM runs").fetchone()[0] == "protected-v6"
    finally:
        restored.close()
