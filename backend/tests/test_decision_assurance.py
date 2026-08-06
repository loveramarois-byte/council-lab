from __future__ import annotations

import importlib
import sqlite3

import httpx
import pytest

from app.decision_assurance import (
    DecisionClaim,
    DecisionOutcomeRecord,
    analyze_readiness,
    build_decision_claims,
)
from app.migrations import SCHEMA_MIGRATIONS, SCHEMA_VERSION
from app.models import (
    DecisionBrief,
    DecisionReason,
    DecisionReview,
    ProviderProfile,
    ProviderType,
    RunCreate,
    SeatOutcomeReview,
)
from app.orchestrator import Orchestrator
from app.reports import run_html, run_markdown
from app.store import Store
from conftest import TEST_INTERNAL_API_TOKEN


def test_readiness_is_multilabel_and_never_promises_tool_availability():
    result = analyze_readiness("是否应该今天投资这个产品？预算未知。", high_risk=False)
    assert {"decision", "needs_current_data", "needs_external_evidence", "high_risk"}.issubset(result.task_labels)
    assert result.recommended_mode == "high_risk_council"
    assert result.ready is False
    assert all("可用" not in check.message for check in result.checks)

    simple = analyze_readiness("解释 API")
    assert "simple_answer" in simple.task_labels
    assert simple.recommended_mode == "direct"


def test_claims_keep_model_urls_unverified_and_seat_opposition_disputed():
    brief = DecisionBrief(
        id="brief-claim-run",
        run_id="claim-run",
        status="conditional",
        recommendation="先验证",
        support="majority",
        decisive_reasons=[
            DecisionReason(
                id="reason-1",
                summary="参考 https://example.com/report 的数字后再推进",
                supporting_seat_ids=["analyst"],
                opposing_seat_ids=["challenger"],
            )
        ],
        limitations=["未联网核验"],
    )
    claims = build_decision_claims(brief)
    assert claims[0].basis == "seat_disputed"
    assert claims[0].citation is not None
    assert claims[0].citation.externally_checked is False
    assert claims[0].citation.provided_by == "model"


async def test_outcomes_are_append_only_and_update_claim_view_without_rewriting_run(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )
    run = await orchestrator.start(RunCreate(question="是否先灰度发布？", provider_id="mock", auto_summarize=True))
    await orchestrator.tasks[run.id]
    raw_before = store.conn.execute("SELECT payload FROM runs WHERE id=?", (run.id,)).fetchone()[0]
    claim = DecisionClaim(
        run_id=run.id,
        text="灰度可以降低一次性发布风险",
        basis="model_inference",
        source_seat_ids=["analyst"],
    )
    store.conn.execute("DELETE FROM decision_claims WHERE run_id=?", (run.id,))
    store.conn.commit()
    await store.create_decision_claims([claim])

    first = DecisionOutcomeRecord(
        run_id=run.id,
        review=DecisionReview(
            selected_decision="先灰度",
            expected_result="降低风险",
            actual_result="回滚成功",
            outcome_status="successful",
            seat_outcomes=[SeatOutcomeReview(role="analyst", status="supported", note="实测支持")],
        ),
    )
    second = DecisionOutcomeRecord(
        run_id=run.id,
        review=DecisionReview(
            selected_decision="继续灰度",
            expected_result="保持稳定",
            actual_result="出现新故障",
            outcome_status="unsuccessful",
            seat_outcomes=[SeatOutcomeReview(role="analyst", status="contradicted", note="结果反驳")],
        ),
    )
    await store.append_decision_outcome(first)
    supported = await store.list_decision_claims(run.id)
    await store.append_decision_outcome(second)
    contradicted = await store.list_decision_claims(run.id)

    assert supported[0].current_basis == "outcome_supported"
    assert contradicted[0].current_basis == "outcome_contradicted"
    assert len(await store.list_decision_outcomes(run.id)) == 2
    assert store.conn.execute("SELECT payload FROM runs WHERE id=?", (run.id,)).fetchone()[0] == raw_before
    assert (await store.get_run(run.id)).decision_review.actual_result == "出现新故障"
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute("UPDATE decision_outcomes SET payload_json='{}'")
    store.close()


async def test_claim_provenance_is_included_in_exports_and_removed_with_explicit_run_deletion(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )
    run = await orchestrator.start(
        RunCreate(question="是否先灰度发布？", provider_id="mock", auto_summarize=True)
    )
    await orchestrator.tasks[run.id]
    current = await store.get_run(run.id)
    assert current is not None
    claims = await store.list_decision_claims(run.id)
    assert claims

    markdown = run_markdown(current, decision_claims=claims)
    html = run_html(current, decision_claims=claims)
    for exported in (markdown, html):
        assert "关键主张与依据" in exported
        assert claims[0].claim.text in exported
        assert "模型推断" in exported or "席位间有争议" in exported

    await store.append_decision_outcome(
        DecisionOutcomeRecord(
            run_id=run.id,
            review=DecisionReview(
                selected_decision="先灰度",
                expected_result="降低风险",
                actual_result="验证完成",
                outcome_status="successful",
                seat_outcomes=[
                    SeatOutcomeReview(role="analyst", status="supported", note="实测支持")
                ],
            ),
        )
    )
    assert await store.delete_run(run.id) is True
    for table in (
        "readiness_overrides",
        "decision_claims",
        "decision_outcomes",
        "claim_outcomes",
    ):
        assert store.conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run.id,)
        ).fetchone()[0] == 0
    store.close()


async def test_readiness_override_and_review_api_are_validated_and_idempotent(tmp_path, monkeypatch):
    main = importlib.import_module("app.main")
    store = Store(tmp_path / "council.sqlite3")
    orchestrator = Orchestrator(
        store,
        {"mock": ProviderProfile(id="mock", display_name="Mock", provider_type=ProviderType.MOCK)},
    )
    run = await orchestrator.start(
        RunCreate(
            question="是否调整产品发布时间？",
            provider_id="mock",
            auto_summarize=True,
            readiness_override=True,
            readiness_override_reason="用户确认信息仍不足但继续",
        )
    )
    await orchestrator.tasks[run.id]
    assert store.conn.execute("SELECT COUNT(*) FROM readiness_overrides WHERE run_id=?", (run.id,)).fetchone()[0] == 1
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "orchestrator", orchestrator)
    headers = {
        "X-Council-Internal-Token": TEST_INTERNAL_API_TOKEN,
        "Idempotency-Key": "decision-review-idempotent-1",
    }
    payload = {
        "selected_decision": "暂缓",
        "expected_result": "补齐信息",
        "actual_result": "已补齐",
        "outcome_status": "successful",
        "seat_outcomes": [],
    }
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        readiness = await client.post("/api/readiness", headers=headers, json={"question": "是否调整产品发布时间？"})
        invalid = await client.post("/api/readiness", headers=headers, json={"question": "x", "unknown": True})
        first = await client.put(f"/api/runs/{run.id}/decision-review", headers=headers, json=payload)
        replay = await client.put(f"/api/runs/{run.id}/decision-review", headers=headers, json=payload)
    assert readiness.status_code == 200
    assert invalid.status_code == 422
    assert first.status_code == 200 and replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert len(await store.list_decision_outcomes(run.id)) == 1
    store.close()


def test_v8_database_upgrades_to_assurance_tables_without_rewriting_runs(tmp_path):
    database = tmp_path / "council.sqlite3"
    connection = sqlite3.connect(database)
    for version in range(1, 9):
        for statement in SCHEMA_MIGRATIONS[version]:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version={version}")
    payload = '{"id":"historical-v8","status":"completed"}'
    connection.execute(
        "INSERT INTO runs(id,payload,created_at) VALUES(?,?,?)",
        ("historical-v8", payload, "2026-07-31T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()
    store = Store(database)
    try:
        assert store.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert store.conn.execute("SELECT payload FROM runs").fetchone()[0] == payload
        assert store.conn.execute("SELECT COUNT(*) FROM decision_claims").fetchone()[0] == 0
    finally:
        store.close()


def test_failed_v9_migration_restores_v8_database(tmp_path, monkeypatch):
    database = tmp_path / "council.sqlite3"
    connection = sqlite3.connect(database)
    for version in range(1, 9):
        for statement in SCHEMA_MIGRATIONS[version]:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version={version}")
    connection.execute(
        "INSERT INTO runs(id,payload,created_at) VALUES('protected-v8','{}','2026-07-31T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()
    monkeypatch.setitem(SCHEMA_MIGRATIONS, 9, ("THIS IS NOT SQL",))
    with pytest.raises(sqlite3.OperationalError):
        Store(database)
    restored = sqlite3.connect(database)
    try:
        assert restored.execute("PRAGMA user_version").fetchone()[0] == 8
        assert restored.execute("SELECT id FROM runs").fetchone()[0] == "protected-v8"
    finally:
        restored.close()


def test_failed_v10_migration_restores_v9_database(tmp_path, monkeypatch):
    database = tmp_path / "council.sqlite3"
    connection = sqlite3.connect(database)
    for version in range(1, 10):
        for statement in SCHEMA_MIGRATIONS[version]:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version={version}")
    connection.execute(
        "INSERT INTO runs(id,payload,created_at) VALUES('protected-v9','{}','2026-07-31T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()
    monkeypatch.setitem(SCHEMA_MIGRATIONS, 10, ("THIS IS NOT SQL",))
    with pytest.raises(sqlite3.OperationalError):
        Store(database)
    restored = sqlite3.connect(database)
    try:
        assert restored.execute("PRAGMA user_version").fetchone()[0] == 9
        assert restored.execute("SELECT id FROM runs").fetchone()[0] == "protected-v9"
        trigger_names = {
            row[0]
            for row in restored.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        assert "decision_outcomes_no_delete" in trigger_names
        assert "claim_outcomes_no_delete" in trigger_names
    finally:
        restored.close()
