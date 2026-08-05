from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from app import main
from app.models import ProviderProfile, ProviderType, RunEvent, RunRecord
from app.store import Store
from conftest import TEST_INTERNAL_API_TOKEN


HEADERS = {"X-Council-Internal-Token": TEST_INTERNAL_API_TOKEN}


def make_run(index: int) -> RunRecord:
    created = datetime(2026, 8, 4, tzinfo=timezone.utc) + timedelta(minutes=index)
    return RunRecord(
        id=f"paged-run-{index}",
        question=f"分页记录 {index}",
        mode="standard",
        provider_id="mock",
        model="council-mock",
        status="completed",
        created_at=created,
        updated_at=created,
    )


@pytest.mark.asyncio
async def test_store_run_pagination_returns_newest_slice_and_total(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    try:
        for index in range(5):
            await store.save_run(make_run(index))

        runs, total = await store.list_runs(limit=2, offset=1, include_total=True)

        assert total == 5
        assert [run.id for run in runs] == ["paged-run-3", "paged-run-2"]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_runs_api_returns_paginated_envelope(monkeypatch):
    monkeypatch.setattr(main.store, "list_runs", AsyncMock(return_value=([], 123)))
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        response = await client.get("/api/runs?summary=true&limit=25&offset=50", headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 123, "limit": 25, "offset": 50}
    main.store.list_runs.assert_awaited_once_with(limit=25, offset=50, include_total=True)


@pytest.mark.asyncio
async def test_provider_delete_returns_empty_204(monkeypatch):
    provider_id = "optimization-test-provider"
    monkeypatch.setitem(
        main.providers,
        provider_id,
        ProviderProfile(
            id=provider_id,
            display_name="Optimization Test",
            provider_type=ProviderType.COMPATIBLE,
        ),
    )
    monkeypatch.setattr(main, "delete_provider_secret", lambda _: None)
    monkeypatch.setattr(main.store, "delete_provider", AsyncMock())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        response = await client.delete(f"/api/providers/{provider_id}", headers=HEADERS)

    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_ccswitch_detect_reports_reachable_route_without_models_as_available(monkeypatch):
    class ReachableBackend:
        async def health_check(self):
            return {"status": "route_reachable", "models": []}

        async def aclose(self):
            return None

    monkeypatch.setattr(main, "build_backend", lambda _: ReachableBackend())
    monkeypatch.setattr(main, "offline_model_catalog", lambda _: ([], "none"))
    monkeypatch.setattr(main.store, "save_provider", AsyncMock())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        response = await client.post("/api/providers/ccswitch/detect", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["available"] is True
    assert response.json()["models"] == []


@pytest.mark.asyncio
async def test_readiness_schema_documents_payload_and_rejects_unknown_field():
    schema = main.ReadinessRequest.model_json_schema()
    assert schema["example"] == {
        "question": "是否应该采用微服务架构？",
        "high_risk": False,
    }

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        response = await client.post(
            "/api/readiness",
            headers=HEADERS,
            json={"question": "是否采用微服务？", "provider_id": "mock"},
        )

    assert response.status_code == 422
    assert "provider_id" in response.json()["detail"]


@pytest.mark.asyncio
async def test_run_event_stream_emits_named_ping_before_terminal_event(monkeypatch):
    event = RunEvent(
        event_id="optimization-terminal-event",
        run_id="optimization-run",
        type="run_cancelled",
        stage="cancelled",
        message="cancelled",
        progress=100,
    )
    event.sequence = 1
    calls = 0

    async def wait_for_events(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return [] if calls == 1 else [event]

    monkeypatch.setattr(main.store, "get_run", AsyncMock(return_value=object()))
    monkeypatch.setattr(main.store, "try_open_event_stream", AsyncMock(return_value=True))
    monkeypatch.setattr(main.store, "wait_for_events", wait_for_events)
    monkeypatch.setattr(main.store, "close_event_stream", AsyncMock())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8001") as client:
        response = await client.get("/api/runs/optimization-run/events", headers=HEADERS)

    assert response.status_code == 200
    assert "event: ping\ndata: {}\n\n" in response.text
    assert "event: run_cancelled" in response.text
