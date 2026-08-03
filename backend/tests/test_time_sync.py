from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timezone

import httpx
import pytest

from app import time_sync
from app.time_sync import (
    fetch_cached_trusted_time,
    fetch_trusted_time,
    issue_snapshot_proof,
    issue_time_proof,
    verify_snapshot_proof,
    verify_time_proof,
)
from conftest import TEST_INTERNAL_API_TOKEN


@pytest.mark.asyncio
async def test_fetch_trusted_time_uses_network_payload_and_freezes_source():
    def handler(request: httpx.Request) -> httpx.Response:
        dates = {
            "www.cloudflare.com": "Mon, 03 Aug 2026 00:00:00 GMT",
            "www.google.com": "Mon, 03 Aug 2026 00:00:01 GMT",
            # An agreeing majority must win over a badly skewed network source.
            "www.baidu.com": "Mon, 03 Aug 2026 03:00:00 GMT",
        }
        return httpx.Response(200, headers={"Date": dates[request.url.host]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_trusted_time(client=client)

    assert result == {
        "utc_datetime": "2026-08-03T00:00:00Z",
        "local_datetime": "2026-08-03T08:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "source": "network",
        "provider": "https_consensus",
        "source_url": "https://www.cloudflare.com/,https://www.google.com/generate_204",
        "synced": True,
    }


@pytest.mark.asyncio
async def test_fetch_trusted_time_marks_local_clock_fallback_instead_of_claiming_sync():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    fallback = datetime(2026, 8, 3, 0, 5, 6, tzinfo=timezone.utc)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_trusted_time(client=client, fallback_now=fallback)

    assert result["utc_datetime"] == "2026-08-03T00:05:06Z"
    assert result["local_datetime"] == "2026-08-03T08:05:06+08:00"
    assert result["source"] == "local_fallback"
    assert result["provider"] == "system_clock"
    assert result["synced"] is False


@pytest.mark.asyncio
async def test_fetch_trusted_time_does_not_trust_one_surviving_network_source():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.baidu.com":
            return httpx.Response(200, headers={"Date": "Mon, 03 Aug 2026 00:00:00 GMT"})
        return httpx.Response(503)

    fallback = datetime(2026, 8, 3, 0, 5, 6, tzinfo=timezone.utc)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_trusted_time(client=client, fallback_now=fallback)

    assert result["utc_datetime"] == "2026-08-03T00:05:06Z"
    assert result["source"] == "local_fallback"
    assert result["synced"] is False


def test_network_time_proof_is_bound_to_fields_and_freshness():
    trusted = {
        "utc_datetime": "2026-08-03T00:00:00Z",
        "local_datetime": "2026-08-03T08:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "source": "network",
        "provider": "https_consensus",
        "source_url": "https://www.cloudflare.com/,https://www.google.com/generate_204",
        "synced": True,
    }
    proof = issue_time_proof(trusted, "test-secret-at-least-32-characters")
    timing = {
        "reference_civil_datetime": "2026-08-03 08:00:00",
        "timezone": "Asia/Shanghai",
        "time_source": "network",
        "time_provider": "https_consensus",
        "time_source_url": trusted["source_url"],
        "synced": True,
        "time_proof": proof,
    }

    verify_time_proof(
        timing,
        "test-secret-at-least-32-characters",
        now=datetime(2026, 8, 3, 0, 5, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="证明无效"):
        verify_time_proof(
            {**timing, "reference_civil_datetime": "2026-08-03 08:00:01"},
            "test-secret-at-least-32-characters",
            now=datetime(2026, 8, 3, 0, 5, tzinfo=timezone.utc),
        )
    with pytest.raises(ValueError, match="已过期"):
        verify_time_proof(
            timing,
            "test-secret-at-least-32-characters",
            now=datetime(2026, 8, 3, 0, 11, tzinfo=timezone.utc),
        )


def test_network_time_proof_freshness_uses_monotonic_process_time(monkeypatch):
    trusted = {
        "utc_datetime": "2026-08-03T00:00:00Z",
        "timezone": "Asia/Shanghai",
        "source": "network",
        "provider": "https_consensus",
        "source_url": "https://www.cloudflare.com/,https://www.google.com/generate_204",
        "synced": True,
    }
    ticks = iter([100.0, 101.0])
    monkeypatch.setattr(time_sync.time, "monotonic", lambda: next(ticks))
    proof = issue_time_proof(trusted, "test-secret-at-least-32-characters")

    verify_time_proof(
        {
            "reference_civil_datetime": "2026-08-03 08:00:00",
            "timezone": "Asia/Shanghai",
            "time_source": "network",
            "time_provider": "https_consensus",
            "time_source_url": trusted["source_url"],
            "synced": True,
            "time_proof": proof,
        },
        "test-secret-at-least-32-characters",
    )


@pytest.mark.asyncio
async def test_trusted_time_and_proof_are_reused_within_cache_window(monkeypatch):
    trusted = {
        "utc_datetime": "2026-08-03T00:00:00Z",
        "local_datetime": "2026-08-03T08:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "source": "network",
        "provider": "https_consensus",
        "source_url": "https://www.cloudflare.com/,https://www.google.com/generate_204",
        "synced": True,
    }
    calls = 0

    async def fixed_time():
        nonlocal calls
        calls += 1
        return dict(trusted)

    monkeypatch.setattr(time_sync.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(time_sync, "fetch_trusted_time", fixed_time)
    time_sync.clear_time_caches()

    first = await fetch_cached_trusted_time()
    second = await fetch_cached_trusted_time()
    first_proof = issue_time_proof(first, "test-secret-at-least-32-characters")
    second_proof = issue_time_proof(second, "test-secret-at-least-32-characters")

    assert calls == 1
    assert first == second
    assert first_proof == second_proof


@pytest.mark.asyncio
async def test_expired_trusted_time_is_projected_while_consensus_refreshes(monkeypatch):
    trusted = {
        "utc_datetime": "2026-08-03T00:00:00Z",
        "local_datetime": "2026-08-03T08:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "source": "network",
        "provider": "https_consensus",
        "source_url": "https://www.cloudflare.com/,https://www.google.com/generate_204",
        "synced": True,
    }
    now = 100.0
    calls = 0

    async def fixed_time():
        nonlocal calls
        calls += 1
        return dict(trusted)

    monkeypatch.setattr(time_sync, "fetch_trusted_time", fixed_time)
    monkeypatch.setattr(time_sync.time, "monotonic", lambda: now)
    time_sync.clear_time_caches()
    await fetch_cached_trusted_time()

    now = 140.0
    projected = await fetch_cached_trusted_time()
    await asyncio.sleep(0)

    assert projected["utc_datetime"] == "2026-08-03T00:00:40Z"
    assert calls == 2


def test_snapshot_proof_binds_hash_and_time_proof():
    secret = "test-secret-at-least-32-characters"
    snapshot_hash = "a" * 64
    time_proof = f"v1.{('b' * 64)}"
    proof = issue_snapshot_proof(snapshot_hash, time_proof, secret)

    verify_snapshot_proof(snapshot_hash, time_proof, proof, secret)
    with pytest.raises(ValueError, match="本地排盘证明无效"):
        verify_snapshot_proof("c" * 64, time_proof, proof, secret)
    with pytest.raises(ValueError, match="本地排盘证明无效"):
        verify_snapshot_proof(snapshot_hash, None, proof, secret)

@pytest.mark.asyncio
async def test_time_api_signs_consensus_result_and_disables_caching(monkeypatch):
    main = importlib.import_module("app.main")
    trusted = {
        "utc_datetime": "2026-08-03T00:00:00Z",
        "local_datetime": "2026-08-03T08:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "source": "network",
        "provider": "https_consensus",
        "source_url": "https://www.cloudflare.com/,https://www.google.com/generate_204",
        "synced": True,
    }

    async def fixed_time():
        return dict(trusted)

    monkeypatch.setattr(main, "fetch_cached_trusted_time", fixed_time)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8001",
        headers={"X-Council-Internal-Token": TEST_INTERNAL_API_TOKEN},
    ) as client:
        response = await client.get("/api/time")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        **trusted,
        "time_proof": issue_time_proof(trusted, TEST_INTERNAL_API_TOKEN),
    }


@pytest.mark.asyncio
async def test_time_api_never_signs_local_clock_fallback(monkeypatch):
    main = importlib.import_module("app.main")
    fallback = {
        "utc_datetime": "2026-08-03T00:05:06Z",
        "local_datetime": "2026-08-03T08:05:06+08:00",
        "timezone": "Asia/Shanghai",
        "source": "local_fallback",
        "provider": "system_clock",
        "source_url": "",
        "synced": False,
    }

    async def fixed_time():
        return dict(fallback)

    monkeypatch.setattr(main, "fetch_cached_trusted_time", fixed_time)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8001",
        headers={"X-Council-Internal-Token": TEST_INTERNAL_API_TOKEN},
    ) as client:
        response = await client.get("/api/time")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == fallback
