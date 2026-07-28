from __future__ import annotations

import os

from fastapi import HTTPException, Response


LEGACY_SUNSET = "Thu, 31 Dec 2026 00:00:00 GMT"


def legacy_workspace_enabled() -> bool:
    return os.getenv("COUNCIL_ENABLE_LEGACY_WORKSPACE", "").strip().lower() in {"1", "true", "yes", "on"}


def legacy_headers() -> dict[str, str]:
    return {
        "Deprecation": "true",
        "Sunset": LEGACY_SUNSET,
        "Warning": '299 Council "Legacy workspace writes are disabled by default"',
    }


def mark_legacy_response(response: Response) -> None:
    for key, value in legacy_headers().items():
        response.headers[key] = value


def require_legacy_workspace_write(response: Response | None = None) -> None:
    if not legacy_workspace_enabled():
        raise HTTPException(
            410,
            "资料空间写入已退出当前产品。历史资料仍可读取；如需临时迁移，请显式启用兼容开关。",
            headers=legacy_headers(),
        )
    if response is not None:
        mark_legacy_response(response)
