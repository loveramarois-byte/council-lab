from __future__ import annotations

import importlib
import sqlite3

import httpx
import pytest

from app.decision_memory import MemoryPreviewRequest, MemoryProposalDecision, build_memory_proposals
from app.migrations import SCHEMA_MIGRATIONS, SCHEMA_VERSION
from app.models import ProviderProfile, ProviderType, RunCreate
from app.orchestrator import Orchestrator
from app.store import Store
from conftest import TEST_INTERNAL_API_TOKEN


async def completed_run(store: Store):
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )
    run = await orchestrator.start(
        RunCreate(question="是否应该把新功能先灰度两周？", provider_id="mock", auto_summarize=True)
    )
    await orchestrator.tasks[run.id]
    completed = await store.get_run(run.id)
    brief = await store.get_decision_brief(run.id)
    assert completed is not None and completed.status == "completed"
    assert brief is not None
    return orchestrator, completed, brief


async def test_only_explicitly_approved_and_selected_memory_is_injected(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    orchestrator, source, brief = await completed_run(store)
    calls_before_proposals = (await store.get_run(source.id)).usage.model_calls
    proposals = await store.create_memory_proposals(build_memory_proposals(brief))
    assert proposals
    assert (await store.get_run(source.id)).usage.model_calls == calls_before_proposals

    approved = await store.approve_memory_proposal(
        proposals[0].id,
        MemoryProposalDecision(content="只在可于五分钟内回滚时灰度发布。"),
    )
    if len(proposals) > 1:
        await store.reject_memory_proposal(proposals[1].id)
    preview_without_selection = await store.preview_memories([])
    preview = await store.preview_memories([approved.memory.id])
    assert preview_without_selection.included == []
    assert [item.content for item in preview.included] == ["只在可于五分钟内回滚时灰度发布。"]

    child = await orchestrator.start(
        RunCreate(
            question="本周是否应该开始灰度？",
            provider_id="mock",
            selected_memory_ids=[approved.memory.id],
            auto_summarize=True,
        )
    )
    persisted = await store.get_run(child.id)
    immutable_snapshot = await store.get_run_memory_snapshot(child.id)
    assert persisted is not None
    assert [item.memory_id for item in persisted.memory_snapshot] == [approved.memory.id]
    assert [item.memory_id for item in immutable_snapshot] == [approved.memory.id]
    assert "用户为本次 Run 明确选择的已批准记忆" in persisted.project_context
    assert "五分钟内回滚" in persisted.project_context
    await orchestrator.tasks[child.id]
    store.close()


async def test_rejected_disabled_and_deleted_memory_never_enters_preview(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    _, source, brief = await completed_run(store)
    proposals = await store.create_memory_proposals(build_memory_proposals(brief))
    rejected = await store.reject_memory_proposal(proposals[0].id)
    assert rejected.status == "rejected"
    with pytest.raises(ValueError, match="已拒绝"):
        await store.approve_memory_proposal(proposals[0].id, MemoryProposalDecision())

    approved = await store.approve_memory_proposal(proposals[1].id, MemoryProposalDecision())
    replay = await store.approve_memory_proposal(proposals[1].id, MemoryProposalDecision())
    assert replay.memory.id == approved.memory.id
    disabled = await store.set_memory_action(approved.memory.id, "disabled")
    assert disabled.active is False
    assert (await store.preview_memories([approved.memory.id])).excluded_memory_ids == [approved.memory.id]
    enabled = await store.set_memory_action(approved.memory.id, "enabled")
    assert enabled.active is True
    deleted = await store.set_memory_action(approved.memory.id, "deleted")
    assert deleted.deleted is True and deleted.active is False
    with pytest.raises(ValueError, match="不能重新启用"):
        await store.set_memory_action(approved.memory.id, "enabled")
    actions = store.conn.execute(
        "SELECT action FROM memory_actions WHERE memory_id=? ORDER BY sequence", (approved.memory.id,)
    ).fetchall()
    assert [row[0] for row in actions] == ["approved", "disabled", "enabled", "deleted"]
    assert await store.get_run(source.id) is not None
    store.close()


async def test_memory_api_validates_payloads_and_preserves_proposal_history(tmp_path, monkeypatch):
    main = importlib.import_module("app.main")
    store = Store(tmp_path / "council.sqlite3")
    orchestrator, source, _ = await completed_run(store)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "orchestrator", orchestrator)
    transport = httpx.ASGITransport(app=main.app)
    headers = {"X-Council-Internal-Token": TEST_INTERNAL_API_TOKEN}
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        created = await client.post(f"/api/runs/{source.id}/memory-proposals", headers=headers)
        replay = await client.post(f"/api/runs/{source.id}/memory-proposals", headers=headers)
        proposal_id = created.json()[0]["proposal"]["id"]
        approved = await client.post(
            f"/api/memory/proposals/{proposal_id}/approve",
            headers=headers,
            json={"content": "编辑后批准的本地记忆"},
        )
        invalid = await client.post(
            "/api/memory/preview",
            headers=headers,
            json={"selected_memory_ids": [approved.json()["memory"]["id"]] * 2},
        )
        injected = await client.post(
            "/api/memory/preview",
            headers=headers,
            json={"selected_memory_ids": [approved.json()["memory"]["id"]]},
        )
    assert created.status_code == 200 and replay.status_code == 200
    assert [item["proposal"]["id"] for item in created.json()] == [
        item["proposal"]["id"] for item in replay.json()
    ]
    assert approved.status_code == 200
    assert invalid.status_code == 422
    assert injected.json()["included"][0]["content"] == "编辑后批准的本地记忆"
    store.close()


async def test_memory_snapshot_write_failure_rolls_back_new_run(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    orchestrator, _, brief = await completed_run(store)
    proposals = await store.create_memory_proposals(build_memory_proposals(brief))
    approved = await store.approve_memory_proposal(proposals[0].id, MemoryProposalDecision())
    before_ids = {run.id for run in await store.list_runs()}
    store.conn.execute(
        "CREATE TRIGGER fail_memory_snapshot BEFORE INSERT ON run_memory_snapshots "
        "BEGIN SELECT RAISE(ABORT, 'simulated snapshot failure'); END"
    )
    store.conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="snapshot failure"):
        await orchestrator.start(
            RunCreate(
                question="这次写入必须原子失败",
                provider_id="mock",
                selected_memory_ids=[approved.memory.id],
            )
        )
    assert {run.id for run in await store.list_runs()} == before_ids
    assert store.conn.execute("SELECT COUNT(*) FROM run_memory_snapshots").fetchone()[0] == 0
    store.close()


def test_v7_database_upgrades_to_memory_tables_without_rewriting_runs(tmp_path):
    database = tmp_path / "council.sqlite3"
    connection = sqlite3.connect(database)
    for version in range(1, 8):
        for statement in SCHEMA_MIGRATIONS[version]:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version={version}")
    payload = '{"id":"historical-v7","status":"completed"}'
    connection.execute(
        "INSERT INTO runs(id,payload,created_at) VALUES(?,?,?)",
        ("historical-v7", payload, "2026-07-31T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()

    store = Store(database)
    try:
        assert store.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert store.conn.execute("SELECT payload FROM runs").fetchone()[0] == payload
        assert store.conn.execute("SELECT COUNT(*) FROM memory_actions").fetchone()[0] == 0
    finally:
        store.close()


def test_failed_v8_migration_restores_v7_database(tmp_path, monkeypatch):
    database = tmp_path / "council.sqlite3"
    connection = sqlite3.connect(database)
    for version in range(1, 8):
        for statement in SCHEMA_MIGRATIONS[version]:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version={version}")
    connection.execute(
        "INSERT INTO runs(id,payload,created_at) VALUES('protected-v7','{}','2026-07-31T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()
    monkeypatch.setitem(SCHEMA_MIGRATIONS, 8, ("THIS IS NOT SQL",))

    with pytest.raises(sqlite3.OperationalError):
        Store(database)
    restored = sqlite3.connect(database)
    try:
        assert restored.execute("PRAGMA user_version").fetchone()[0] == 7
        assert restored.execute("SELECT id FROM runs").fetchone()[0] == "protected-v7"
    finally:
        restored.close()
