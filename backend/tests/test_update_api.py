import importlib
from unittest.mock import AsyncMock

import httpx

from app.updater import Release, UpdateError


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
