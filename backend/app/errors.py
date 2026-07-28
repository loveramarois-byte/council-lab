from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


logger = logging.getLogger("council.api")
TRUSTED_HOSTS = {"localhost", "127.0.0.1", "::1"}


STATUS_ERROR_CODES = {
    400: "INVALID_REQUEST",
    401: "AUTHENTICATION_REQUIRED",
    403: "ACTION_NOT_ALLOWED",
    404: "RESOURCE_NOT_FOUND",
    409: "STATE_CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


@dataclass(frozen=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", "")
    return value if isinstance(value, str) and value else uuid.uuid4().hex


def _error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": message,
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
            },
        },
        headers={"X-Council-Request-ID": request_id},
    )


def install_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        if request.url.hostname not in TRUSTED_HOSTS:
            return _error_response(request, 400, "INVALID_HOST", "请求主机不受信任。")
        response = await call_next(request)
        response.headers["X-Council-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "请求无法完成。"
        code = STATUS_ERROR_CODES.get(exc.status_code, "REQUEST_FAILED")
        return _error_response(request, exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, _: RequestValidationError) -> JSONResponse:
        return _error_response(request, 422, "VALIDATION_ERROR", "请求参数不完整或格式不正确。")

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        logger.exception(
            "Unhandled API error request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return _error_response(request, 500, "INTERNAL_ERROR", "服务暂时无法完成请求，请使用排错编号查看诊断信息。")
