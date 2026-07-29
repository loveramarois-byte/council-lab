import importlib
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx

from app.models import RunCreate, RunRecord
from app.updater import Release, UpdateError


async def test_lifespan_persists_migrated_assignment_config(monkeypatch):
    main = importlib.import_module("app.main")
    save = AsyncMock()
    recover = AsyncMock(return_value=[])
    shutdown = AsyncMock()
    monkeypatch.setattr(main, "assignments_need_persist", True)
    monkeypatch.setattr(main.store, "save_assignment_config", save)
    monkeypatch.setattr(main.orchestrator, "recover_incomplete_runs", recover)
    monkeypatch.setattr(main.orchestrator, "shutdown", shutdown)

    async with main.lifespan(main.app):
        pass

    save.assert_awaited_once_with(main.assignments)
    recover.assert_awaited_once()
    shutdown.assert_awaited_once()


async def test_assignment_api_migrates_payload_without_schema_version(monkeypatch):
    main = importlib.import_module("app.main")
    transport = httpx.ASGITransport(app=main.app)
    profile = main.providers["ccswitch"].model_copy(
        deep=True,
        update={
            "default_model": "gpt-5.6-sol",
            "available_models": ["gpt-5.6-sol"],
            "model_source": "ccswitch_history",
            "timeout_seconds": 120,
        },
    )
    monkeypatch.setitem(main.providers, "ccswitch", profile)
    monkeypatch.setattr(main, "assignments", main.assignments.model_copy(deep=True))
    save = AsyncMock()
    monkeypatch.setattr(main.store, "save_assignment_config", save)
    assignment = {
        "provider_id": "ccswitch",
        "model": "gpt-5.6-sol",
        "protocol": "auto",
        "reasoning_effort": "ultra",
        "timeout_seconds": 30,
    }
    payload = {
        "seats": [{"role": role, **assignment} for role in ["analyst", "challenger", "builder", "observer"]],
        "finalizer": {"role": "finalizer", **assignment},
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        response = await client.put("/api/agent-assignments", json=payload)

    assert response.status_code == 200
    saved = response.json()
    assert saved["schema_version"] == 2
    assert [item["timeout_seconds"] for item in [*saved["seats"], saved["finalizer"]]] == [120] * 5
    save.assert_awaited_once()


async def test_update_routes_enforce_local_header_and_report_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("COUNCIL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("COUNCIL_VERSION", "0.4.0")
    main = importlib.import_module("app.main")
    transport = httpx.ASGITransport(app=main.app)

    start = AsyncMock(return_value={"phase": "checking", "current_version": "0.4.0"})
    monkeypatch.setattr(main.update_manager, "start", start)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        hostile_host = await client.get("/api/health", headers={"Host": "attacker.example"})
        assert hostile_host.status_code == 400
        assert hostile_host.json()["error"]["code"] == "INVALID_HOST"
        assert hostile_host.headers["X-Council-Request-ID"] == hostile_host.json()["error"]["request_id"]

        blocked = await client.post("/api/update/install")
        assert blocked.status_code == 403
        assert "Council 软件内" in blocked.json()["detail"]
        assert blocked.json()["error"]["code"] == "ACTION_NOT_ALLOWED"
        assert len(blocked.json()["error"]["request_id"]) == 32
        assert blocked.headers["X-Council-Request-ID"] == blocked.json()["error"]["request_id"]
        start.assert_not_awaited()

        accepted = await client.post("/api/update/install", headers={"X-Council-Request": "app"})
        assert accepted.status_code == 200
        assert accepted.json()["phase"] == "checking"
        start.assert_awaited_once()

        monkeypatch.setattr(main, "fetch_release", AsyncMock(side_effect=UpdateError("offline")))
        blocked_refresh = await client.get("/api/update/check?refresh=true")
        assert blocked_refresh.status_code == 403

        unavailable = await client.get("/api/update/check?refresh=true", headers={"X-Council-Request": "app"})
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"] == "offline"

        release = Release(
            version="0.5.0",
            tag="v0.5.0",
            page_url="https://github.com/loveramarois-byte/council-lab/releases/tag/v0.5.0",
            notes="API route test",
            published_at=None,
            package_name=None,
            package_url=None,
            checksum_url=None,
        )
        monkeypatch.setattr(main, "fetch_release", AsyncMock(return_value=release))
        available = await client.get("/api/update/check")
        assert available.status_code == 200
        assert available.json()["update_available"] is True

        monkeypatch.setattr(main.update_manager, "status", lambda: {"phase": "idle", "current_version": "0.4.0"})
        status = await client.get("/api/update/status")
        assert status.status_code == 200
        assert status.json() == {"phase": "idle", "current_version": "0.4.0"}
        assert len(status.headers["X-Council-Request-ID"]) == 32

        invalid = await client.post("/api/runs", json={})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
        assert invalid.json()["detail"] == "请求参数不完整或格式不正确。"


async def test_legacy_workspace_is_read_only_unless_explicitly_enabled(monkeypatch):
    main = importlib.import_module("app.main")
    transport = httpx.ASGITransport(app=main.app)
    monkeypatch.delenv("COUNCIL_ENABLE_LEGACY_WORKSPACE", raising=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        readable = await client.get("/api/projects")
        assert readable.status_code == 200
        assert readable.headers["Deprecation"] == "true"
        assert "Sunset" in readable.headers

        blocked = await client.post("/api/projects", json={"name": "不应创建"})
        assert blocked.status_code == 410
        assert blocked.json()["error"]["code"] == "FEATURE_RETIRED"
        assert blocked.headers["Deprecation"] == "true"

        blocked_run = await client.post(
            "/api/runs",
            json={"question": "不应重新启用资料空间", "provider_id": "mock", "project_id": "legacy-project"},
        )
        assert blocked_run.status_code == 410

        monkeypatch.setenv("COUNCIL_ENABLE_LEGACY_WORKSPACE", "1")
        created = await client.post("/api/projects", json={"name": "迁移读取"})
        assert created.status_code == 200
        assert created.json()["name"] == "迁移读取"
        assert created.headers["Deprecation"] == "true"


async def test_run_creation_idempotency_replays_without_duplicate_start(monkeypatch):
    main = importlib.import_module("app.main")
    transport = httpx.ASGITransport(app=main.app)
    now = datetime.now(timezone.utc)
    fixture = RunRecord(
        id="idempotent-run",
        question="只创建一次",
        mode="standard",
        provider_id="mock",
        model="council-mock",
        status="queued",
        created_at=now,
        updated_at=now,
    )
    start = AsyncMock(return_value=fixture)
    monkeypatch.setattr(main.orchestrator, "start", start)
    headers = {"Idempotency-Key": f"create-request-{uuid.uuid4().hex}"}
    payload = {"question": "只创建一次", "provider_id": "mock"}

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        first = await client.post("/api/runs", json=payload, headers=headers)
        replayed = await client.post("/api/runs", json=payload, headers=headers)
        conflict = await client.post(
            "/api/runs",
            json={"question": "不同请求", "provider_id": "mock"},
            headers=headers,
        )
        invalid = await client.post(
            "/api/runs",
            json=payload,
            headers={"Idempotency-Key": "short"},
        )

    assert first.status_code == 200
    assert first.headers["Idempotency-Replayed"] == "false"
    assert replayed.status_code == 200
    assert replayed.headers["Idempotency-Replayed"] == "true"
    assert replayed.json() == first.json()
    start.assert_awaited_once()
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "IDEMPOTENCY_KEY_INVALID"


async def test_rerun_idempotency_does_not_create_a_second_run(monkeypatch):
    main = importlib.import_module("app.main")
    transport = httpx.ASGITransport(app=main.app)
    now = datetime.now(timezone.utc)
    seats, finalizer = main.orchestrator._resolve_config(
        RunCreate(question="构造旧版本重跑快照", provider_id="mock")
    )
    source = RunRecord(
        id="rerun-source",
        question="重跑也只能创建一次",
        mode="standard",
        provider_id="mock",
        model="council-mock",
        status="completed",
        created_at=now,
        updated_at=now,
        assignment_schema_version=1,
        seat_assignments=seats,
        finalizer_assignment=finalizer,
    )
    created = source.model_copy(update={"id": "rerun-result", "status": "queued"})
    await main.store.save_run(source)
    start = AsyncMock(return_value=created)
    monkeypatch.setattr(main.orchestrator, "start", start)
    headers = {"Idempotency-Key": f"rerun-request-{uuid.uuid4().hex}"}

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        first = await client.post("/api/runs/rerun-source/rerun", headers=headers)
        replayed = await client.post("/api/runs/rerun-source/rerun", headers=headers)

    assert first.status_code == 200
    assert replayed.status_code == 200
    assert replayed.headers["Idempotency-Replayed"] == "true"
    assert replayed.json() == first.json()
    start.assert_awaited_once()
    rerun_request = start.await_args.args[0]
    assert rerun_request.assignment_config is not None
    assert rerun_request.assignment_config.schema_version == 1
