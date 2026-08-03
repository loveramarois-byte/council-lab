from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.time_sync import fetch_trusted_time, issue_time_proof, verify_time_proof


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
