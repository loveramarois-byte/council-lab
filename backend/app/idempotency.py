from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Response

from .errors import ApiError
from .models import RunRecord
from .store import Store


IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def request_fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def execute_idempotent_run_action(
    store: Store,
    scope: str,
    operation_key: str | None,
    payload: Any,
    action: Callable[[], Awaitable[RunRecord | None]],
    response: Response,
) -> RunRecord:
    if not operation_key:
        result = await action()
        if result is None:
            raise ApiError(404, "RESOURCE_NOT_FOUND", "运行记录不存在")
        return result
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(operation_key):
        raise ApiError(
            400,
            "IDEMPOTENCY_KEY_INVALID",
            "Idempotency-Key 需为 8-128 位字母、数字、点、下划线、冒号或连字符。",
        )

    claim = await store.claim_idempotent_operation(scope, operation_key, request_fingerprint(payload))
    if claim.state == "conflict":
        raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "同一 Idempotency-Key 不能用于不同请求。")
    if claim.state == "in_progress":
        raise ApiError(409, "IDEMPOTENT_OPERATION_IN_PROGRESS", "相同请求正在处理中，请稍后使用同一 Idempotency-Key 重试。")
    if claim.state == "cached" and claim.response_json:
        response.headers["Idempotency-Replayed"] = "true"
        return RunRecord.model_validate_json(claim.response_json)

    try:
        result = await action()
        if result is None:
            raise ApiError(404, "RESOURCE_NOT_FOUND", "运行记录不存在")
        await store.complete_idempotent_operation(scope, operation_key, result.model_dump_json())
        response.headers["Idempotency-Replayed"] = "false"
        return result
    except Exception:
        await store.abandon_idempotent_operation(scope, operation_key)
        raise
