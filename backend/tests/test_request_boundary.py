from __future__ import annotations

import importlib
from pathlib import Path

import httpx
import pytest

from conftest import TEST_INTERNAL_API_TOKEN
from app.request_boundary import (
    browser_origin_is_trusted,
    load_internal_api_token,
    load_trusted_frontend_ports,
    token_identifier,
)


INTERNAL_HEADER = {"X-Council-Internal-Token": TEST_INTERNAL_API_TOKEN}


@pytest.mark.security_boundary
async def test_health_is_public_but_application_api_requires_internal_token():
    main = importlib.import_module("app.main")
    transport = httpx.ASGITransport(app=main.app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8001",
    ) as client:
        health = await client.get("/api/health")
        missing = await client.get("/api/providers")
        wrong = await client.get(
            "/api/providers",
            headers={"X-Council-Internal-Token": "wrong-token"},
        )
        allowed = await client.get("/api/providers", headers=INTERNAL_HEADER)

    assert health.status_code == 200
    assert health.json()["internal_api_id"] == token_identifier(TEST_INTERNAL_API_TOKEN)
    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert missing.json()["error"]["code"] == "INTERNAL_API_AUTH_REQUIRED"
    assert allowed.status_code == 200


@pytest.mark.security_boundary
@pytest.mark.parametrize(
    ("headers", "content"),
    [
        (
            {
                "Origin": "https://evil.example",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            "activate=1",
        ),
        (
            {"Origin": "null", "Content-Type": "text/plain"},
            "activate",
        ),
        (
            {"Content-Type": "application/x-www-form-urlencoded"},
            "activate=1",
        ),
    ],
)
async def test_untrusted_simple_browser_mutation_is_rejected_without_state_change(
    monkeypatch,
    headers: dict[str, str],
    content: str,
):
    main = importlib.import_module("app.main")
    transport = httpx.ASGITransport(app=main.app)
    original = {provider_id: profile.is_active for provider_id, profile in main.providers.items()}
    target = next(provider_id for provider_id, active in original.items() if not active)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8001",
    ) as client:
        response = await client.post(
            f"/api/providers/{target}/activate",
            headers=headers,
            content=content,
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INTERNAL_API_AUTH_REQUIRED"
    assert {provider_id: profile.is_active for provider_id, profile in main.providers.items()} == original


@pytest.mark.security_boundary
@pytest.mark.parametrize(
    "headers",
    [
        {**INTERNAL_HEADER, "Origin": "https://evil.example"},
        {**INTERNAL_HEADER, "Origin": "null"},
        {**INTERNAL_HEADER, "Origin": "http://0.0.0.0:3000"},
        {**INTERNAL_HEADER, "Origin": "http://192.0.2.1:3000"},
        {
            **INTERNAL_HEADER,
            "Origin": "http://127.0.0.1:3000",
            "Sec-Fetch-Site": "cross-site",
        },
        {
            **INTERNAL_HEADER,
            "Origin": "http://127.0.0.1:3000",
            "Sec-Fetch-Site": "same-site",
        },
        {**INTERNAL_HEADER, "Origin": "http://127.0.0.1:9999"},
        {**INTERNAL_HEADER, "Origin": "http://127.0.0.1"},
    ],
)
async def test_internal_token_does_not_override_browser_origin_controls(headers: dict[str, str]):
    main = importlib.import_module("app.main")
    transport = httpx.ASGITransport(app=main.app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8001",
    ) as client:
        response = await client.get("/api/providers", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "UNTRUSTED_BROWSER_ORIGIN"


@pytest.mark.security_boundary
@pytest.mark.parametrize(
    "origin",
    ["http://localhost:3000", "http://127.0.0.1:3000", "http://192.168.1.20:3000"],
)
async def test_internal_proxy_allows_loopback_and_private_lan_origins(origin: str):
    main = importlib.import_module("app.main")
    transport = httpx.ASGITransport(app=main.app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8001",
    ) as client:
        response = await client.get(
            "/api/providers",
            headers={**INTERNAL_HEADER, "Origin": origin, "Sec-Fetch-Site": "same-origin"},
        )

    assert response.status_code == 200


@pytest.mark.security_boundary
async def test_rebinding_style_host_is_rejected_before_api_dispatch():
    main = importlib.import_module("app.main")
    transport = httpx.ASGITransport(app=main.app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8001",
    ) as client:
        response = await client.get(
            "/api/providers",
            headers={**INTERNAL_HEADER, "Host": "127.0.0.1.attacker.example"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_HOST"


@pytest.mark.security_boundary
def test_short_configured_internal_token_fails_closed(monkeypatch):
    monkeypatch.setenv("COUNCIL_INTERNAL_API_TOKEN", "short")
    with pytest.raises(RuntimeError, match="at least 32"):
        load_internal_api_token()


@pytest.mark.security_boundary
def test_missing_internal_token_generates_an_unpredictable_ephemeral_value(monkeypatch):
    monkeypatch.delenv("COUNCIL_INTERNAL_API_TOKEN", raising=False)
    first = load_internal_api_token()
    second = load_internal_api_token()
    assert len(first) >= 32
    assert first != second


@pytest.mark.security_boundary
@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_invalid_explicit_frontend_port_fails_closed(monkeypatch, port: str):
    monkeypatch.setenv("COUNCIL_FRONTEND_PORT", port)
    with pytest.raises(RuntimeError, match="COUNCIL_FRONTEND_PORT"):
        load_trusted_frontend_ports()


@pytest.mark.security_boundary
def test_explicit_frontend_port_is_narrowly_configurable(monkeypatch):
    monkeypatch.setenv("COUNCIL_FRONTEND_PORT", "13000")
    assert load_trusted_frontend_ports() == frozenset({13000})


@pytest.mark.security_boundary
def test_empty_frontend_port_uses_the_product_default(monkeypatch):
    monkeypatch.setenv("COUNCIL_FRONTEND_PORT", "")
    assert load_trusted_frontend_ports() == frozenset({3000})


@pytest.mark.security_boundary
@pytest.mark.parametrize(
    "origin",
    [
        "ftp://127.0.0.1:3000",
        "http://:3000",
        "http://127.0.0.1:4000",
        "http://user@127.0.0.1:3000",
        "http://127.0.0.1:3000/path",
        "http://127.0.0.1:3000?query=1",
        "http://127.0.0.1:invalid",
    ],
)
def test_origin_parser_rejects_malformed_or_overbroad_frontend_origins(origin: str):
    assert browser_origin_is_trusted(origin, "same-origin") is False


@pytest.mark.security_boundary
@pytest.mark.parametrize(
    "origin",
    ["http://[::1]:3000", "http://[fd00::20]:3000"],
)
def test_origin_parser_accepts_loopback_and_private_ipv6_frontends(origin: str):
    assert browser_origin_is_trusted(origin, "same-origin") is True


@pytest.mark.security_boundary
def test_internal_token_identifier_is_stable_and_does_not_expose_token():
    identifier = token_identifier(TEST_INTERNAL_API_TOKEN)
    assert identifier == "d600895cb89eface"
    assert TEST_INTERNAL_API_TOKEN not in identifier


@pytest.mark.security_boundary
def test_all_desktop_launchers_share_and_remove_the_internal_token():
    root = Path(__file__).resolve().parents[2]
    start_scripts = [
        root / "desktop/start-council.sh",
        root / "desktop/start-bundled.sh",
        root / "desktop/start-council.ps1",
        root / "desktop/start-bundled.ps1",
    ]
    stop_scripts = [
        root / "desktop/stop-council.sh",
        root / "desktop/stop-bundled.sh",
        root / "desktop/stop-council.ps1",
        root / "desktop/stop-bundled.ps1",
    ]

    for script in start_scripts:
        content = script.read_text(encoding="utf-8")
        assert "backend-access.token" in content
        assert "internal_api_id" in content
        assert content.count("COUNCIL_INTERNAL_API_TOKEN") >= 2
        assert content.find("COUNCIL_INTERNAL_API_TOKEN") < content.rfind("COUNCIL_INTERNAL_API_TOKEN")
        if script.suffix == ".sh":
            assert "chmod 600" in content
    for script in stop_scripts:
        content = script.read_text(encoding="utf-8")
        assert "backend-access.token" in content
        assert "Remove-Item" in content or "rm -f" in content


@pytest.mark.security_boundary
def test_release_smoke_uses_internal_token_for_protected_backend_api():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert workflow.count("backend-access.token") >= 2
    assert 'X-Council-Internal-Token: $internal_token' in workflow
    assert '"X-Council-Internal-Token" = $internalToken' in workflow
