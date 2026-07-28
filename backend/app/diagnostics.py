from __future__ import annotations

import io
import json
import os
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .models import AgentAssignmentsConfig, ProviderProfile
from .store import Store
from .updater import current_version


DIAGNOSTICS_SCHEMA_VERSION = 1
COUNCIL_LOG_NAMES = {
    "backend.log",
    "backend.stderr.log",
    "backend.stdout.log",
    "frontend.log",
    "frontend.stderr.log",
    "frontend.stdout.log",
    "update.log",
}


def _log_dir() -> Path:
    override = os.getenv("COUNCIL_LOG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "Council"
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "Council" / "logs"
    root = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / "council" / "logs"


def _log_manifest() -> list[dict[str, object]]:
    root = _log_dir()
    if not root.is_dir():
        return []
    files: list[dict[str, object]] = []
    for path in sorted(root.glob("*.log")):
        if path.name not in COUNCIL_LOG_NAMES:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "content_included": False,
            }
        )
    return files


def _provider_summary(
    providers: Mapping[str, ProviderProfile],
    provider_refs: Mapping[str, str],
) -> list[dict[str, object]]:
    return [
        {
            "provider_ref": provider_refs[profile.id],
            "type": getattr(profile.provider_type, "value", profile.provider_type),
            "enabled": profile.enabled,
            "active": profile.is_active,
            "local_only": profile.local_only,
            "credential_configured": profile.credential_saved
            or bool(profile.api_key_reference and os.getenv(profile.api_key_reference)),
            "default_model_configured": bool(profile.default_model.strip()),
            "model_source": profile.model_source,
            "model_count": len(profile.available_models),
            "last_health_check": profile.last_health_check.isoformat() if profile.last_health_check else None,
            "has_error": bool(profile.last_error),
        }
        for profile in sorted(providers.values(), key=lambda item: item.id)
    ]


def _assignment_summary(
    assignments: AgentAssignmentsConfig,
    provider_refs: Mapping[str, str],
) -> list[dict[str, object]]:
    seats = [*assignments.seats, assignments.finalizer]
    return [
        {
            "role": seat.role,
            "provider_ref": provider_refs.get(seat.provider_id, "unavailable"),
            "model_configured": bool(seat.model.strip()),
            "protocol": seat.protocol,
            "reasoning_effort": seat.reasoning_effort,
            "max_output_tokens": seat.max_output_tokens,
            "timeout_seconds": seat.timeout_seconds,
        }
        for seat in seats
    ]


async def build_diagnostic_bundle(
    store: Store,
    providers: Mapping[str, ProviderProfile],
    assignments: AgentAssignmentsConfig,
) -> bytes:
    generated_at = datetime.now(timezone.utc).isoformat()
    provider_refs = {
        provider_id: f"P{index}"
        for index, provider_id in enumerate(sorted(providers), 1)
    }
    report = {
        "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
        "generated_at": generated_at,
        "application": {
            "name": "Council Lab",
            "version": current_version(),
            "python": platform.python_version(),
            "platform": sys.platform,
            "architecture": platform.machine(),
        },
        "storage": await store.diagnostic_snapshot(),
        "providers": _provider_summary(providers, provider_refs),
        "assignments": _assignment_summary(assignments, provider_refs),
        "logs": _log_manifest(),
        "privacy": {
            "conversation_content_included": False,
            "log_content_included": False,
            "credentials_included": False,
            "cookies_or_pairing_tokens_included": False,
            "filesystem_paths_included": False,
        },
    }
    readme = (
        "Council Lab diagnostic bundle\n"
        f"Generated: {generated_at}\n\n"
        "This bundle contains runtime, storage-integrity, provider-readiness, and log-file metadata.\n"
        "It intentionally excludes prompts, model responses, source documents, API keys, cookies, pairing tokens,\n"
        "log contents, hostnames, usernames, IP addresses, and filesystem paths.\n"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", readme)
        archive.writestr("diagnostics.json", json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return output.getvalue()
