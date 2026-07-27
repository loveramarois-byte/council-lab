from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .credentials import get_provider_secret
from .models import (
    ProviderCapabilities,
    ProviderProfile,
    ProviderType,
    ProtocolMode,
    UsageSummary,
)

DEFAULT_CCSWITCH_URL = "http://127.0.0.1:15721/v1"
BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal", "100.100.100.200"}


def normalize_base_url(base_url: str, provider_type: ProviderType) -> str:
    value = (base_url or "").strip().rstrip("/")
    if provider_type == ProviderType.CCSWITCH and not value:
        return DEFAULT_CCSWITCH_URL
    if provider_type == ProviderType.CCSWITCH and value and not value.endswith("/v1"):
        return f"{value}/v1"
    return value


def is_loopback_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return bool(hostname and ipaddress.ip_address(hostname).is_loopback)
    except ValueError:
        return False


def validate_base_url(base_url: str, local_only: bool = False) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("地址必须使用 http 或 https，并包含主机名")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in BLOCKED_HOSTS:
        raise ValueError("出于 SSRF 防护，云元数据地址不可用")
    if local_only and not is_loopback_url(base_url):
        raise ValueError("CC Switch 默认只允许本机 loopback 地址")

    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            records = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError(f"无法解析 Provider 主机名：{hostname}") from exc
        addresses = list({ipaddress.ip_address(record[4][0]) for record in records})

    if not addresses:
        raise ValueError(f"无法解析 Provider 主机名：{hostname}")
    for address in addresses:
        if str(address) in BLOCKED_HOSTS or address.is_link_local:
            raise ValueError("出于 SSRF 防护，云元数据或 link-local 地址不可用")
        if address.is_unspecified or address.is_multicast or address.is_reserved:
            raise ValueError("地址属于危险保留网段")
        if local_only and not address.is_loopback:
            raise ValueError("CC Switch 主机名必须全部解析到 loopback 地址")


@dataclass
class Generation:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    protocol: str = "mock"
    reasoning_effort_applied: str | None = None


class ModelBackend:
    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError

    async def list_models(self) -> list[str]:
        raise NotImplementedError

    async def generate(self, prompt: str, system: str, model: str, temperature: float = 0.2) -> Generation:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


def extract_model_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw_models = payload.get("data") or payload.get("models") or []
    model_ids: list[str] = []
    for item in raw_models:
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("slug") or item.get("model")
        else:
            model_id = None
        if isinstance(model_id, str) and model_id.strip():
            model_ids.append(model_id.strip())
    return list(dict.fromkeys(model_ids))


def resolve_model_catalog(live_models: list[str], fallback_models: list[str], fallback_source: str) -> tuple[list[str], str, int]:
    clean_live = list(dict.fromkeys(model.strip() for model in live_models if model.strip()))
    if clean_live:
        return clean_live, "provider", len(clean_live)
    clean_fallback = list(dict.fromkeys(model.strip() for model in fallback_models if model.strip()))
    return clean_fallback, fallback_source if clean_fallback else "none", 0


def replace_model_catalog(profile: ProviderProfile, models: list[str], source: str) -> None:
    clean_models = list(dict.fromkeys(model.strip() for model in models if model.strip()))
    profile.available_models = clean_models
    profile.model_source = source
    if clean_models and (not profile.default_model or source == "provider" and profile.default_model not in clean_models):
        profile.default_model = clean_models[0]


def discover_ccswitch_models(db_path: Path | None = None, limit: int = 30) -> list[str]:
    """Read only successful model names when CC Switch exposes no catalog."""
    configured_path = os.getenv("CCSWITCH_DB_PATH")
    path = db_path or (Path(configured_path).expanduser() if configured_path else Path.home() / ".cc-switch" / "cc-switch.db")
    if not path.is_file():
        return []

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.25)
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'proxy_request_logs'"
        ).fetchone()
        if not table:
            return []
        rows = connection.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(request_model), ''), NULLIF(TRIM(model), '')) AS model_name,
                   MAX(created_at) AS latest
            FROM proxy_request_logs
            WHERE app_type = 'codex' AND status_code BETWEEN 200 AND 299
            GROUP BY model_name
            HAVING model_name IS NOT NULL
            ORDER BY latest DESC
            LIMIT ?
            """,
            (max(1, min(limit, 100)),),
        ).fetchall()
    except (OSError, sqlite3.Error):
        return []
    finally:
        if connection is not None:
            connection.close()

    models = []
    for row in rows:
        model = row[0]
        if isinstance(model, str) and 0 < len(model) <= 200 and not any(ord(char) < 32 for char in model):
            models.append(model)
    return list(dict.fromkeys(models))


def build_responses_payload(prompt: str, system: str, model: str, reasoning_effort: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    return payload


def extract_responses_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    output = payload.get("output") or []
    if isinstance(output, str):
        return output
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or []
        if isinstance(content, str) and content.strip():
            return content
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str) and part["text"].strip():
                return part["text"]
    return ""


class MockProvider(ModelBackend):
    async def health_check(self) -> dict[str, Any]:
        return {"status": "connected", "protocol": "mock", "models": ["council-mock"]}

    async def list_models(self) -> list[str]:
        return ["council-mock"]

    async def generate(self, prompt: str, system: str, model: str, temperature: float = 0.2) -> Generation:
        await asyncio.sleep(0.18)
        if "记录员" in system:
            text = "最终答案：先确认目标与约束，再根据四席已经公开的认同、反驳和用户补充选择可执行方案；对仍有分歧的部分保留验证步骤和回退条件。"
        elif "第一位发言者" in system:
            text = "初步观点：先明确问题的目标、已知条件和决策标准，再比较方案；这能让后续反驳落到具体依据上。"
        else:
            text = "表态：部分认同。前文对目标和条件的拆分是必要起点，但还应补充反例、成本与失败后的回退方案，再决定优先级。"
        return Generation(text=text, input_tokens=max(20, len(prompt) // 4), output_tokens=max(35, len(text) // 4))


class OpenAICompatibleProvider(ModelBackend):
    def __init__(self, profile: ProviderProfile):
        self.profile = profile
        self.base_url = normalize_base_url(profile.base_url, profile.provider_type)
        validate_base_url(self.base_url, local_only=profile.local_only)
        headers = {}
        key = get_provider_secret(profile)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self.client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=profile.timeout_seconds)

    async def _post_with_retry(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        retryable = {429, 500, 502, 503, 504}
        response: httpx.Response | None = None
        for attempt in range(self.profile.max_retries + 1):
            response = await self.client.post(path, json=payload)
            if response.status_code not in retryable or attempt >= self.profile.max_retries:
                return response
            await asyncio.sleep(min(1.5 * (attempt + 1), 4.0))
        assert response is not None
        return response

    async def health_check(self) -> dict[str, Any]:
        try:
            response = await self.client.get("/models")
            if response.status_code == 401:
                return {"status": "authentication_error", "protocol": "unknown", "models": []}
            if response.is_success:
                return {"status": "connected", "protocol": "unknown", "models": extract_model_ids(response.json())}
            return {"status": "route_reachable", "protocol": "unknown", "models": [], "error": f"HTTP {response.status_code}"}
        except httpx.ConnectError:
            return {"status": "connection_refused", "protocol": "unknown", "models": []}
        except httpx.TimeoutException:
            return {"status": "timeout", "protocol": "unknown", "models": []}
        except Exception as exc:
            return {"status": "unknown", "protocol": "unknown", "models": [], "error": str(exc)}

    async def list_models(self) -> list[str]:
        response = await self.client.get("/models")
        response.raise_for_status()
        return extract_model_ids(response.json())

    async def generate(self, prompt: str, system: str, model: str, temperature: float = 0.2) -> Generation:
        protocol = self.profile.protocol_mode
        if protocol in (ProtocolMode.AUTO, ProtocolMode.RESPONSES):
            effort = self.profile.reasoning_effort if self.profile.capabilities.supports_reasoning_effort else None
            response = await self._post_with_retry(
                "/responses",
                build_responses_payload(prompt, system, model, effort),
            )
            if response.status_code in (404, 405, 501) and protocol == ProtocolMode.AUTO:
                protocol = ProtocolMode.CHAT_COMPLETIONS
            elif response.status_code >= 400:
                response.raise_for_status()
            else:
                data = response.json()
                output = extract_responses_text(data)
                if not output:
                    raise RuntimeError("Responses 接口成功但没有返回可用文本")
                usage = data.get("usage") or {}
                return Generation(output, usage.get("input_tokens", 0), usage.get("output_tokens", 0), "responses", effort)
        response = await self._post_with_retry("/chat/completions", {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "temperature": temperature})
        response.raise_for_status()
        data = response.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage") or {}
        return Generation(text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), "chat_completions")

    async def aclose(self) -> None:
        await self.client.aclose()


def build_backend(profile: ProviderProfile) -> ModelBackend:
    if profile.provider_type == ProviderType.MOCK:
        return MockProvider()
    return OpenAICompatibleProvider(profile)
