from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .credentials import CredentialStoreError, delete_provider_secret, get_provider_secret, save_provider_secret
from .models import AgentAssignmentsConfig, AgentModelAssignment, DiscussionAction, ProviderCreate, ProviderPatch, ProviderProfile, ProviderType, RunCreate, RunLimits
from .orchestrator import Orchestrator
from .paths import database_path
from .provider_catalog import BUILTIN_PROVIDER_IDS, CATALOG_FIELDS, builtin_providers
from .providers import build_backend, discover_ccswitch_models, is_loopback_url, normalize_base_url, validate_base_url
from .store import Store, serialize_public_provider

store = Store(database_path())
providers = builtin_providers()
for saved_provider in store.load_providers():
    if saved_provider.id != "mock":
        catalog_profile = providers.get(saved_provider.id)
        if catalog_profile:
            for field in CATALOG_FIELDS:
                setattr(saved_provider, field, getattr(catalog_profile, field))
            saved_provider.api_key_reference = saved_provider.api_key_reference or catalog_profile.api_key_reference
            saved_provider.requires_api_key = catalog_profile.requires_api_key
            if not saved_provider.available_models:
                saved_provider.available_models = catalog_profile.available_models
        providers[saved_provider.id] = saved_provider
if not any(profile.is_active for profile in providers.values()):
    providers["ccswitch"].is_active = True
orchestrator = Orchestrator(store, providers)
active_profile = next((profile for profile in providers.values() if profile.is_active and profile.default_model), providers["mock"])
assignments = store.load_assignment_config() or orchestrator.default_assignment_config(active_profile.id, active_profile.default_model)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await orchestrator.recover_incomplete_runs()
    try:
        yield
    finally:
        await orchestrator.shutdown()


app = FastAPI(title="Council Lab", version="0.2.2", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def provider_error_message(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in {401, 403}:
        return "API Key 无效或没有访问权限。"
    if status_code == 402:
        return "账户余额不足或计费未开通。"
    if status_code == 404:
        return "接口地址或模型不存在，请重新获取模型列表。"
    if status_code == 429:
        return "请求过于频繁或额度已用完，请稍后重试。"
    if status_code and status_code >= 500:
        return f"供应商服务暂时不可用（HTTP {status_code}）。"
    message = str(exc).strip()
    return message or "连接失败，请检查地址、API Key 和网络。"


def apply_api_key(profile: ProviderProfile, api_key: object | None) -> None:
    if api_key is None:
        return
    secret_value = api_key.get_secret_value() if hasattr(api_key, "get_secret_value") else str(api_key)
    save_provider_secret(profile.id, secret_value)
    profile.credential_saved = True


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "council-lab"}


@app.post("/api/runs")
async def create_run(request: RunCreate):
    if request.use_saved_assignments and request.assignment_config is None:
        request = request.model_copy(update={"assignment_config": assignments})
    elif request.assignment_config is None:
        profile = providers.get(request.provider_id)
        if not profile:
            raise HTTPException(404, "Provider 不存在")
        if not (request.model or profile.default_model):
            raise HTTPException(400, "请先在 Provider 设置中填写默认模型")
    return await orchestrator.start(request)


@app.get("/api/runs")
async def list_runs():
    return await store.list_runs()


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    return run


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    run = await orchestrator.cancel(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    return run


@app.post("/api/runs/{run_id}/advance")
async def advance_run(run_id: str, request: DiscussionAction):
    run = await orchestrator.advance(run_id, request)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    return run


@app.post("/api/runs/{run_id}/interject")
async def interject_run(run_id: str, request: DiscussionAction):
    run = await orchestrator.interject(run_id, request)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    return run


@app.post("/api/runs/{run_id}/retry-turn")
async def retry_run_turn(run_id: str):
    run = await orchestrator.retry_turn(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    return run


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str, limits: RunLimits):
    try:
        run = await orchestrator.resume_with_limits(run_id, limits)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not run:
        raise HTTPException(404, "运行记录不存在")
    return run


@app.post("/api/runs/{run_id}/summarize")
async def summarize_run(run_id: str):
    run = await orchestrator.summarize(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    return run


@app.post("/api/runs/{run_id}/rerun")
async def rerun(run_id: str):
    source = await store.get_run(run_id)
    if not source:
        raise HTTPException(404, "运行记录不存在")
    assignment_config = None
    if source.seat_assignments and source.finalizer_assignment:
        assignment_config = AgentAssignmentsConfig(
            seats=[
                AgentModelAssignment(
                    role=item.role,
                    provider_id=item.provider_id,
                    model=item.model,
                    protocol=item.protocol,
                    reasoning_effort=item.reasoning_effort,
                    max_output_tokens=item.max_output_tokens,
                    temperature=item.temperature,
                    timeout_seconds=item.timeout_seconds,
                )
                for item in source.seat_assignments
            ],
            finalizer=AgentModelAssignment(
                role=source.finalizer_assignment.role,
                provider_id=source.finalizer_assignment.provider_id,
                model=source.finalizer_assignment.model,
                protocol=source.finalizer_assignment.protocol,
                reasoning_effort=source.finalizer_assignment.reasoning_effort,
                max_output_tokens=source.finalizer_assignment.max_output_tokens,
                temperature=source.finalizer_assignment.temperature,
                timeout_seconds=source.finalizer_assignment.timeout_seconds,
            ),
        )
    return await orchestrator.start(
        RunCreate(
            question=source.question,
            mode=source.mode,
            provider_id=source.provider_id,
            model=source.model,
            assignment_config=assignment_config,
            limits=source.limits,
        )
    )


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    if not await orchestrator.delete(run_id):
        raise HTTPException(404, "运行记录不存在")
    return {"deleted": True}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request):
    if not await store.get_run(run_id):
        raise HTTPException(404, "运行记录不存在")
    queue = store.queue(run_id)

    async def stream():
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
                yield f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"
                if event.type in {"final_completed", "run_failed", "run_cancelled", "run_limit_reached"}:
                    break
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/providers")
async def list_providers():
    return [serialize_public_provider(profile) for profile in providers.values()]


@app.post("/api/providers")
async def create_provider(request: ProviderCreate):
    provider_id = str(uuid.uuid4())
    base_url = normalize_base_url(request.base_url, request.provider_type)
    local_only = request.provider_type == ProviderType.CCSWITCH
    if base_url:
        validate_base_url(base_url, local_only=local_only)
    profile = ProviderProfile(id=provider_id, display_name=request.display_name, provider_type=request.provider_type, protocol_mode=request.protocol_mode, base_url=base_url, api_key_reference=request.api_key_env, default_model=request.default_model or "", reasoning_effort=request.reasoning_effort, timeout_seconds=request.timeout_seconds, max_retries=request.max_retries, enabled=request.enabled, local_only=local_only)
    try:
        apply_api_key(profile, request.api_key)
    except CredentialStoreError as exc:
        raise HTTPException(503, str(exc)) from exc
    providers[provider_id] = profile
    await store.save_provider(profile)
    return serialize_public_provider(profile)


@app.patch("/api/providers/{provider_id}")
async def patch_provider(provider_id: str, request: ProviderPatch):
    profile = providers.get(provider_id)
    if not profile:
        raise HTTPException(404, "Provider 不存在")
    values = request.model_dump(exclude_unset=True)
    api_key = values.pop("api_key", None)
    if "base_url" in values:
        values["base_url"] = normalize_base_url(values["base_url"], profile.provider_type)
        validate_base_url(values["base_url"], local_only=profile.local_only)
    if "api_key_env" in values:
        profile.api_key_reference = values.pop("api_key_env")
    try:
        apply_api_key(profile, api_key)
    except CredentialStoreError as exc:
        raise HTTPException(503, str(exc)) from exc
    for key, value in values.items():
        setattr(profile, key, value)
    profile.updated_at = datetime.now(timezone.utc)
    providers[provider_id] = profile
    await store.save_provider(profile)
    return serialize_public_provider(profile)


@app.delete("/api/providers/{provider_id}")
async def delete_provider(provider_id: str):
    if provider_id in BUILTIN_PROVIDER_IDS:
        raise HTTPException(400, "内置 Provider 不可删除")
    if provider_id not in providers:
        raise HTTPException(404, "Provider 不存在")
    try:
        delete_provider_secret(provider_id)
    except CredentialStoreError as exc:
        raise HTTPException(503, str(exc)) from exc
    del providers[provider_id]
    await store.delete_provider(provider_id)
    return {"deleted": True}


@app.delete("/api/providers/{provider_id}/credential")
async def delete_provider_credential(provider_id: str):
    profile = providers.get(provider_id)
    if not profile:
        raise HTTPException(404, "Provider 不存在")
    try:
        delete_provider_secret(provider_id)
    except CredentialStoreError as exc:
        raise HTTPException(503, str(exc)) from exc
    profile.credential_saved = False
    profile.last_health_check = None
    profile.last_error = None
    await store.save_provider(profile)
    return serialize_public_provider(profile)


@app.post("/api/providers/{provider_id}/activate")
async def activate_provider(provider_id: str):
    profile = providers.get(provider_id)
    if not profile:
        raise HTTPException(404, "Provider 不存在")
    for item in providers.values():
        next_value = item.id == provider_id
        if item.is_active != next_value:
            item.is_active = next_value
            await store.save_provider(item)
    return serialize_public_provider(profile)


@app.post("/api/providers/ccswitch/detect")
async def detect_ccswitch():
    profile = providers["ccswitch"]
    backend = build_backend(profile)
    try:
        result = await backend.health_check()
    finally:
        await backend.aclose()
    profile.last_health_check = datetime.now(timezone.utc)
    profile.last_error = None if result.get("status") in {"connected", "route_reachable"} else result.get("error")
    models = result.get("models") or discover_ccswitch_models()
    model_source = "provider" if result.get("models") else "ccswitch_history" if models else "none"
    if models:
        profile.available_models = models
        if profile.default_model not in models:
            profile.default_model = models[0]
        result["models"] = models
    await store.save_provider(profile)
    return {
        "base_url": profile.base_url,
        "loopback": is_loopback_url(profile.base_url),
        "model_source": model_source,
        "default_model": profile.default_model,
        **result,
    }


@app.post("/api/providers/{provider_id}/test")
async def test_provider(provider_id: str):
    profile = providers.get(provider_id)
    if not profile:
        raise HTTPException(404, "Provider 不存在")
    try:
        if profile.requires_api_key and not get_provider_secret(profile):
            raise RuntimeError("尚未配置 API Key。")
        backend = build_backend(profile)
        try:
            if profile.provider_type == ProviderType.MOCK:
                result = await backend.health_check()
            else:
                generation = await backend.generate(
                    "Reply exactly: COUNCIL_CONNECTED",
                    "This is a minimal provider connection test.",
                    profile.default_model,
                )
                if not generation.text.strip():
                    raise RuntimeError("生成接口返回了空内容")
                result = {
                    "status": "connected",
                    "protocol": generation.protocol,
                    "model": profile.default_model,
                    "reasoning_effort_applied": generation.reasoning_effort_applied,
                    "mode_capability": "native_reasoning" if generation.reasoning_effort_applied else "workflow_only",
                    "response": generation.text.strip()[:80],
                }
        finally:
            await backend.aclose()
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if profile.provider_type == ProviderType.CCSWITCH and status_code in {429, 500, 502, 503, 504}:
            result = {
                "status": "route_connected_upstream_busy",
                "protocol": "responses",
                "model": profile.default_model,
                "http_status": status_code,
                "error": "CC Switch 路由已连接；当前上游繁忙或正在故障转移，请稍后重试。",
            }
        else:
            result = {"status": "generation_error", "protocol": "unknown", "model": profile.default_model, "error": provider_error_message(exc)}
    profile.last_health_check = datetime.now(timezone.utc)
    profile.last_error = None if result.get("status") in {"connected", "route_reachable", "route_connected_upstream_busy"} else result.get("error")
    await store.save_provider(profile)
    return result


@app.get("/api/providers/{provider_id}/models")
async def provider_models(provider_id: str):
    profile = providers.get(provider_id)
    if not profile:
        raise HTTPException(404, "Provider 不存在")
    try:
        if profile.requires_api_key and not get_provider_secret(profile):
            raise RuntimeError("先填写 API Key，再获取账号可用模型。")
        backend = build_backend(profile)
        try:
            models = await backend.list_models()
        finally:
            await backend.aclose()
        source = "provider"
        if profile.provider_type == ProviderType.CCSWITCH and not models:
            models = discover_ccswitch_models()
            source = "ccswitch_history" if models else "none"
        models = list(dict.fromkeys(models)) if profile.provider_type == ProviderType.CCSWITCH else sorted(set(models), key=str.casefold)
        if models:
            profile.available_models = models
            if profile.default_model not in models:
                profile.default_model = models[0]
            profile.last_error = None
            profile.last_health_check = datetime.now(timezone.utc)
            await store.save_provider(profile)
        return {"models": profile.available_models, "source": source, "fetched": len(models), "default_model": profile.default_model}
    except Exception as exc:
        profile.last_error = provider_error_message(exc)
        await store.save_provider(profile)
        return {"models": profile.available_models, "source": "saved_or_recommended", "fetched": 0, "error": profile.last_error}


@app.get("/api/providers/{provider_id}/capabilities")
async def provider_capabilities(provider_id: str):
    profile = providers.get(provider_id)
    if not profile:
        raise HTTPException(404, "Provider 不存在")
    return profile.capabilities


@app.get("/api/agent-assignments")
async def get_assignments():
    return assignments


@app.put("/api/agent-assignments")
async def put_assignments(payload: AgentAssignmentsConfig):
    global assignments
    try:
        orchestrator._resolve_config(RunCreate(question="验证席位配置", assignment_config=payload))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    assignments = payload
    await store.save_assignment_config(payload)
    return assignments


@app.get("/api/settings")
async def settings():
    return {
        "default_mode": "standard",
        "fixed_seats": 4,
        "limits": {"max_model_calls": 8, "max_tokens": 40000, "timeout_seconds": 120},
        "privacy": {"store_questions": True, "send_traces": False},
        "appearance": {"theme": "light", "editable": False},
    }
