from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from statistics import median
from typing import Mapping
from zoneinfo import ZoneInfo

import httpx


TIMEZONE_NAME = "Asia/Shanghai"
TIME_PROVIDER = "https_consensus"
TIME_SOURCES = (
    ("cloudflare", "https://www.cloudflare.com/"),
    ("google", "https://www.google.com/generate_204"),
    ("baidu", "https://www.baidu.com/"),
)
TIME_SOURCE_URL = ",".join(url for _, url in TIME_SOURCES)
_SHANGHAI = ZoneInfo(TIMEZONE_NAME)
_MAX_CONSENSUS_SKEW_SECONDS = 5
_MAX_PROOF_AGE_SECONDS = 10 * 60
_TIME_PROOF_VERSION = "v1"
_MAX_TRACKED_PROOFS = 1024
_TIME_CACHE_TTL_SECONDS = 30.0
_issued_proofs: dict[str, float] = {}
_trusted_time_cache: tuple[float, float, dict[str, object]] | None = None
_trusted_time_cache_lock = asyncio.Lock()
_trusted_time_refresh_task: asyncio.Task[None] | None = None
_time_proof_cache: dict[tuple[str, str, int], tuple[str, float]] = {}


def clear_time_caches() -> None:
    global _trusted_time_cache, _trusted_time_refresh_task
    _trusted_time_cache = None
    if _trusted_time_refresh_task and not _trusted_time_refresh_task.done():
        _trusted_time_refresh_task.cancel()
    _trusted_time_refresh_task = None
    _time_proof_cache.clear()
    _issued_proofs.clear()


def _seconds_iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_http_date(value: str | None) -> datetime:
    if not value:
        raise ValueError("联网时间响应缺少 Date")
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _fallback_time(now: datetime) -> dict[str, object]:
    utc_now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    utc_now = utc_now.astimezone(timezone.utc).replace(microsecond=0)
    local_now = utc_now.astimezone(_SHANGHAI)
    return {
        "utc_datetime": _seconds_iso(utc_now),
        "local_datetime": local_now.isoformat(timespec="seconds"),
        "timezone": TIMEZONE_NAME,
        "source": "local_fallback",
        "provider": "system_clock",
        "source_url": "",
        "synced": False,
    }


def _reference_civil_datetime(utc_datetime: object) -> str:
    if not isinstance(utc_datetime, str):
        raise ValueError("联网校时结果缺少 UTC 时间")
    try:
        parsed = datetime.fromisoformat(utc_datetime.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("联网校时 UTC 时间无效") from exc
    if parsed.tzinfo is None:
        raise ValueError("联网校时 UTC 时间缺少时区")
    return parsed.astimezone(_SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")


def _proof_payload_from_trusted_time(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "reference_civil_datetime": _reference_civil_datetime(payload.get("utc_datetime")),
        "timezone": payload.get("timezone"),
        "time_source": payload.get("source"),
        "time_provider": payload.get("provider"),
        "time_source_url": payload.get("source_url"),
        "synced": payload.get("synced"),
    }


def _proof_payload_from_timing(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "reference_civil_datetime": payload.get("reference_civil_datetime"),
        "timezone": payload.get("timezone"),
        "time_source": payload.get("time_source"),
        "time_provider": payload.get("time_provider"),
        "time_source_url": payload.get("time_source_url"),
        "synced": payload.get("synced"),
    }


def _proof_digest(payload: Mapping[str, object], secret: str) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _snapshot_proof_digest(snapshot_sha256: str, time_proof: str | None, secret: str) -> str:
    payload = f"{snapshot_sha256}\n{time_proof or ''}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def issue_snapshot_proof(snapshot_sha256: str, time_proof: str | None, secret: str) -> str:
    """Attest a locally recomputed snapshot without exposing the process key."""
    return f"{_TIME_PROOF_VERSION}.{_snapshot_proof_digest(snapshot_sha256, time_proof, secret)}"


def verify_snapshot_proof(
    snapshot_sha256: str,
    time_proof: str | None,
    proof: str | None,
    secret: str,
) -> None:
    if not isinstance(proof, str) or not proof.startswith(f"{_TIME_PROOF_VERSION}."):
        raise ValueError("本地排盘证明缺失或格式无效，请重新排盘")
    expected = issue_snapshot_proof(snapshot_sha256, time_proof, secret)
    if not hmac.compare_digest(proof, expected):
        raise ValueError("本地排盘证明无效，请重新排盘")


def issue_time_proof(payload: Mapping[str, object], secret: str) -> str:
    """Bind the browser-visible consensus timestamp to this backend instance."""
    proof_payload = _proof_payload_from_trusted_time(payload)
    if not (
        proof_payload["time_source"] == "network"
        and proof_payload["time_provider"] == TIME_PROVIDER
        and proof_payload["synced"] is True
    ):
        raise ValueError("只有 HTTPS 多源校时结果可以签发证明")
    canonical = json.dumps(proof_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    cache_key = (
        canonical,
        hashlib.sha256(secret.encode("utf-8")).hexdigest(),
        int(time.time() // 60),
    )
    issued_at = time.monotonic()
    cached = _time_proof_cache.get(cache_key)
    if cached and issued_at < cached[1]:
        return cached[0]
    proof = f"{_TIME_PROOF_VERSION}.{_proof_digest(proof_payload, secret)}"
    _time_proof_cache[cache_key] = (proof, issued_at + _TIME_CACHE_TTL_SECONDS)
    if len(_time_proof_cache) > 64:
        oldest_key = min(_time_proof_cache, key=lambda key: _time_proof_cache[key][1])
        _time_proof_cache.pop(oldest_key, None)
    _issued_proofs[proof] = issued_at
    if len(_issued_proofs) > _MAX_TRACKED_PROOFS:
        oldest = min(_issued_proofs, key=_issued_proofs.get)
        _issued_proofs.pop(oldest, None)
    return proof


def verify_time_proof(
    payload: Mapping[str, object],
    secret: str,
    *,
    now: datetime | None = None,
) -> None:
    proof = payload.get("time_proof")
    if not isinstance(proof, str) or not proof.startswith(f"{_TIME_PROOF_VERSION}."):
        raise ValueError("联网校时证明缺失或格式无效，请重新校时")
    proof_payload = _proof_payload_from_timing(payload)
    expected = f"{_TIME_PROOF_VERSION}.{_proof_digest(proof_payload, secret)}"
    if not hmac.compare_digest(proof, expected):
        raise ValueError("联网校时证明无效，请重新校时")
    try:
        reference = datetime.strptime(
            str(proof_payload["reference_civil_datetime"]), "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=_SHANGHAI)
    except ValueError as exc:
        raise ValueError("联网校时时刻格式无效，请重新校时") from exc
    if now is None:
        issued_at = _issued_proofs.get(proof)
        age = time.monotonic() - issued_at if issued_at is not None else _MAX_PROOF_AGE_SECONDS + 1
    else:
        utc_now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        age = abs((utc_now.astimezone(timezone.utc) - reference.astimezone(timezone.utc)).total_seconds())
    if age > _MAX_PROOF_AGE_SECONDS:
        raise ValueError("联网校时证明已过期，请重新校时")


async def _sample_source(client: httpx.AsyncClient, name: str, url: str) -> tuple[str, str, datetime] | None:
    try:
        response = await client.head(url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
        response.raise_for_status()
        return name, url, _parse_http_date(response.headers.get("Date"))
    except (httpx.HTTPError, ValueError, TypeError):
        return None


def _consensus_samples(samples: list[tuple[str, str, datetime]]) -> list[tuple[str, str, datetime]]:
    best: list[tuple[str, str, datetime]] = []
    for sample in samples:
        cluster = [
            candidate
            for candidate in samples
            if abs((candidate[2] - sample[2]).total_seconds()) <= _MAX_CONSENSUS_SKEW_SECONDS
        ]
        if len(cluster) > len(best):
            best = cluster
    return best if len(best) >= 2 else []


async def fetch_trusted_time(
    *,
    client: httpx.AsyncClient | None = None,
    fallback_now: datetime | None = None,
) -> dict[str, object]:
    """Use agreeing HTTPS origin clocks; never call a single source trusted."""
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=5,
        follow_redirects=False,
        headers={"Accept": "*/*", "User-Agent": "Council-Lab/time-sync"},
    )
    try:
        sampled = await asyncio.gather(
            *(_sample_source(active_client, name, url) for name, url in TIME_SOURCES)
        )
        consensus = _consensus_samples([sample for sample in sampled if sample is not None])
        if not consensus:
            return _fallback_time(fallback_now or datetime.now(timezone.utc))
        consensus_timestamp = median(sample[2].timestamp() for sample in consensus)
        utc_now = datetime.fromtimestamp(consensus_timestamp, timezone.utc).replace(microsecond=0)
        local_now = utc_now.astimezone(_SHANGHAI)
        return {
            "utc_datetime": _seconds_iso(utc_now),
            "local_datetime": local_now.isoformat(timespec="seconds"),
            "timezone": TIMEZONE_NAME,
            "source": "network",
            "provider": TIME_PROVIDER,
            "source_url": ",".join(sample[1] for sample in consensus),
            "synced": True,
        }
    finally:
        if owns_client:
            await active_client.aclose()


def _project_trusted_time(
    sampled_at: float,
    payload: Mapping[str, object],
    now: float,
) -> dict[str, object]:
    result = dict(payload)
    try:
        utc_value = datetime.fromisoformat(str(payload["utc_datetime"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return result
    projected_utc = utc_value.astimezone(timezone.utc) + timedelta(seconds=max(0.0, now - sampled_at))
    projected_utc = projected_utc.replace(microsecond=0)
    result["utc_datetime"] = _seconds_iso(projected_utc)
    result["local_datetime"] = projected_utc.astimezone(_SHANGHAI).isoformat(timespec="seconds")
    return result


async def _refresh_trusted_time_cache() -> None:
    global _trusted_time_cache
    async with _trusted_time_cache_lock:
        result = await fetch_trusted_time()
        sampled_at = time.monotonic()
        _trusted_time_cache = (sampled_at + _TIME_CACHE_TTL_SECONDS, sampled_at, dict(result))


async def fetch_cached_trusted_time() -> dict[str, object]:
    """Serve projected trusted time immediately and refresh consensus in the background."""
    global _trusted_time_refresh_task
    now = time.monotonic()
    if _trusted_time_cache:
        expires_at, sampled_at, result = _trusted_time_cache
        if now >= expires_at and (_trusted_time_refresh_task is None or _trusted_time_refresh_task.done()):
            _trusted_time_refresh_task = asyncio.create_task(_refresh_trusted_time_cache())
        return _project_trusted_time(sampled_at, result, now)
    await _refresh_trusted_time_cache()
    assert _trusted_time_cache is not None
    _, sampled_at, result = _trusted_time_cache
    return _project_trusted_time(sampled_at, result, time.monotonic())
