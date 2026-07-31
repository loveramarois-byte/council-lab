from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx

from fastapi import FastAPI, File, Header, HTTPException, Path as ApiPath, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .credentials import CredentialStoreError, delete_provider_secret, get_provider_secret, save_provider_secret
from .diagnostics import DIAGNOSTICS_SCHEMA_VERSION, build_diagnostic_bundle
from .evidence import MAX_UPLOAD_BYTES, content_hash, extract_file_text, fetch_webpage
from .errors import install_error_handling
from .idempotency import execute_idempotent_model_action, execute_idempotent_run_action
from .legacy import legacy_workspace_enabled, mark_legacy_response, require_legacy_workspace_write
from .decision_lifecycle import DecisionBriefComparison, RunForkCreate, RunForkLineage, compare_briefs
from .decision_memory import MemoryPreview, MemoryPreviewRequest, MemoryProposalDecision, MemoryProposalView, MemoryView, build_memory_proposals
from .decision_assurance import DecisionClaimView, DecisionOutcomeRecord, ReadinessRequest, analyze_readiness
from .models import AgentAssignmentsConfig, AgentAssignmentsPayload, AgentModelAssignment, DecisionBrief, DecisionReview, DecisionReviewUpdate, DiscussionAction, ProjectCreate, ProjectPatch, ProjectRecord, ProjectSource, ProviderCreate, ProviderPatch, ProviderProfile, ProviderType, RunCreate, RunLimits, SourceTextCreate, SourceURLCreate, utc_now
from .orchestrator import Orchestrator
from .paths import database_path
from .provider_catalog import BUILTIN_PROVIDER_IDS, builtin_providers
from .providers import build_backend, discover_ccswitch_models, is_loopback_url, normalize_base_url, replace_model_catalog, resolve_model_catalog, validate_base_url
from .risk.schemas import ApprovalDecisionRequest, ApprovalRecord, ApprovalRequest, FactsUpdateRequest, HighRiskCreate, HighRiskRun, PrepareReviewRequest, PublicAuditEvent, RevokeApprovalRequest, RiskOverrideRequest, TransitionRequest
from .risk.service import HighRiskService
from .reports import run_html, run_markdown
from .request_boundary import load_internal_api_token, token_identifier
from .runtime_config import assignment_config_is_valid, restore_provider_profiles
from .store import Store, serialize_public_provider
from .templates import list_templates
from .output_contracts import list_output_contracts
from .updater import UpdateError, current_version, fetch_release, install_request_is_allowed, public_update_info, runtime_identity, update_manager

store = Store(database_path())
providers = restore_provider_profiles(store.load_providers())
if not any(profile.is_active for profile in providers.values()):
    providers["ccswitch"].is_active = True
high_risk_service = HighRiskService(store)
orchestrator = Orchestrator(store, providers, high_risk_service)
active_profile = next((profile for profile in providers.values() if profile.is_active and profile.default_model), None)
if active_profile is None:
    for profile in providers.values():
        profile.is_active = profile.id == "mock"
    active_profile = providers["mock"]
saved_assignments = store.load_assignment_config()
saved_assignments_valid = assignment_config_is_valid(saved_assignments, providers)
assignments = saved_assignments if saved_assignments_valid else orchestrator.default_assignment_config(active_profile.id, active_profile.default_model)
assignments = orchestrator.normalize_assignment_config(assignments)
assignments_need_persist = bool(
    saved_assignments_valid and saved_assignments and saved_assignments.schema_version < assignments.schema_version
)

RunIdPath = Annotated[str, ApiPath(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
RunIdQuery = Annotated[str, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
MemoryIdPath = Annotated[str, ApiPath(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{2,127}$")]


@asynccontextmanager
async def lifespan(_: FastAPI):
    if assignments_need_persist:
        await store.save_assignment_config(assignments)
    await high_risk_service.recover()
    await orchestrator.recover_incomplete_runs()
    try:
        yield
    finally:
        await orchestrator.shutdown()


app = FastAPI(title="Council Lab", version=current_version(), lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
internal_api_token = load_internal_api_token()
install_error_handling(app, internal_api_token)


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


def offline_model_catalog(profile: ProviderProfile) -> tuple[list[str], str]:
    if profile.provider_type == ProviderType.CCSWITCH:
        models = discover_ccswitch_models()
        return models, "ccswitch_history" if models else "none"
    catalog = builtin_providers().get(profile.id)
    if catalog and catalog.model_source == "recommended":
        return list(catalog.available_models), "recommended"
    return [], "none"


def require_actor(actor_id: str | None) -> str:
    normalized = (actor_id or "").strip()
    if not normalized or len(normalized) > 128:
        from .errors import ApiError

        raise ApiError(401, "HIGH_RISK_ACTOR_REQUIRED", "高风险操作需要明确的本地操作主体。")
    return normalized


def require_reviewer_secret(value: str | None) -> str:
    if not value:
        from .errors import ApiError

        raise ApiError(401, "REVIEWER_CREDENTIAL_REQUIRED", "高风险审批需要服务端配置的复核凭据。")
    return value


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "council-lab",
        "runtime_id": runtime_identity(),
        "internal_api_id": token_identifier(internal_api_token),
    }


@app.get("/api/update/check")
async def check_for_update(refresh: bool = False, x_council_request: str | None = Header(default=None)):
    if refresh and not install_request_is_allowed(x_council_request):
        raise HTTPException(403, "只能从 Council 软件内强制刷新版本信息。")
    try:
        return public_update_info(await fetch_release(refresh=refresh))
    except UpdateError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/update/status")
async def update_status():
    return update_manager.status()


@app.get("/api/diagnostics/export")
async def export_diagnostics(x_council_request: str | None = Header(default=None)):
    if not install_request_is_allowed(x_council_request):
        raise HTTPException(403, "只能从 Council 软件内生成诊断包。")
    bundle = await build_diagnostic_bundle(store, providers, assignments)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Response(
        bundle,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="council-diagnostics-{stamp}.zip"',
            "X-Council-Diagnostics-Schema": str(DIAGNOSTICS_SCHEMA_VERSION),
        },
    )


@app.post("/api/update/install")
async def install_update(x_council_request: str | None = Header(default=None)):
    if not install_request_is_allowed(x_council_request):
        raise HTTPException(403, "只能从 Council 软件内启动更新。")
    return await update_manager.start()


@app.post("/api/runs")
async def create_run(
    request: RunCreate,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not legacy_workspace_enabled() and (request.project_id or request.source_ids):
        raise HTTPException(410, "新建审议已不再接受资料空间字段；历史 Run 和不可变快照仍可读取。")
    if request.use_saved_assignments and request.assignment_config is None:
        request = request.model_copy(update={"assignment_config": assignments})
    elif request.assignment_config is None:
        profile = providers.get(request.provider_id)
        if not profile:
            raise HTTPException(404, "Provider 不存在")
        if not (request.model or profile.default_model):
            raise HTTPException(400, "请先在 Provider 设置中填写默认模型")
    high_risk_actor = require_actor(actor_header) if request.high_risk else None
    if request.high_risk and request.auto_summarize:
        from .errors import ApiError

        raise ApiError(400, "HIGH_RISK_AUTO_SUMMARY_FORBIDDEN", "高风险模式不能开启自动总结。")

    async def start_run():
        return await orchestrator.start(request, high_risk_actor=high_risk_actor)

    try:
        return await execute_idempotent_run_action(
            store,
            "runs:create",
            idempotency_key,
            {**request.model_dump(mode="json"), "actor_id": high_risk_actor},
            start_run,
            response,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/readiness")
async def check_decision_readiness(payload: ReadinessRequest):
    return analyze_readiness(payload.question, high_risk=payload.high_risk)


@app.post("/api/high-risk/runs", response_model=HighRiskRun)
async def create_high_risk_run(
    payload: HighRiskCreate,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    actor_id = require_actor(actor_header)
    run = await store.get_run(payload.run_id)
    if not run:
        from .errors import ApiError

        raise ApiError(404, "RESOURCE_NOT_FOUND", "必须先创建对应的 Council 运行。")
    if (
        run.status != "queued"
        or run.usage.model_calls > 0
        or run.discussion_turns
        or run.auto_summarize
        or payload.run_id in orchestrator.live_runs
        or payload.run_id in orchestrator.tasks
    ):
        from .errors import ApiError

        raise ApiError(409, "HIGH_RISK_LINK_TOO_LATE", "高风险控制必须在任何模型调用开始前启用，且不能开启自动总结。")
    return await execute_idempotent_model_action(
        store,
        f"high-risk:{payload.run_id}:create",
        idempotency_key,
        {"actor_id": actor_id, **payload.model_dump(mode="json")},
        lambda: high_risk_service.create(payload, actor_id),
        response,
        HighRiskRun,
        lambda _cached: high_risk_service.get(payload.run_id),
    )


@app.get("/api/high-risk/runs/{run_id}", response_model=HighRiskRun)
async def get_high_risk_run(run_id: str):
    return await high_risk_service.get(run_id)


@app.get("/api/high-risk/runs/{run_id}/audit", response_model=list[PublicAuditEvent])
async def get_high_risk_audit(run_id: str):
    return await high_risk_service.audit(run_id)


@app.put("/api/high-risk/runs/{run_id}/facts", response_model=HighRiskRun)
async def update_high_risk_facts(
    run_id: str,
    payload: FactsUpdateRequest,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    actor_id = require_actor(actor_header)
    return await execute_idempotent_model_action(
        store,
        f"high-risk:{run_id}:facts",
        idempotency_key,
        {"actor_id": actor_id, **payload.model_dump(mode="json")},
        lambda: high_risk_service.replace_facts(run_id, payload.facts, actor_id),
        response,
        HighRiskRun,
        lambda _cached: high_risk_service.get(run_id),
    )


@app.post("/api/high-risk/runs/{run_id}/transition", response_model=HighRiskRun)
async def transition_high_risk_run(
    run_id: str,
    payload: TransitionRequest,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    actor_id = require_actor(actor_header)
    return await execute_idempotent_model_action(
        store,
        f"high-risk:{run_id}:transition",
        idempotency_key,
        {"actor_id": actor_id, **payload.model_dump(mode="json")},
        lambda: transition_and_stop_model_work(run_id, payload, actor_id),
        response,
        HighRiskRun,
        lambda _cached: high_risk_service.get(run_id),
    )


async def transition_and_stop_model_work(
    run_id: str,
    payload: TransitionRequest,
    actor_id: str,
) -> HighRiskRun:
    case = await high_risk_service.transition(run_id, payload, actor_id)
    if case.status in {"PROFESSIONAL_ESCALATION_REQUIRED", "ACTION_BLOCKED"}:
        await orchestrator.cancel(run_id)
    return case


@app.post("/api/high-risk/runs/{run_id}/prepare-review", response_model=HighRiskRun)
async def prepare_high_risk_review(
    run_id: str,
    payload: PrepareReviewRequest,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    actor_id = require_actor(actor_header)
    return await execute_idempotent_model_action(
        store,
        f"high-risk:{run_id}:prepare-review",
        idempotency_key,
        {"actor_id": actor_id, **payload.model_dump(mode="json")},
        lambda: high_risk_service.prepare_review(run_id, payload, actor_id),
        response,
        HighRiskRun,
        lambda _cached: high_risk_service.get(run_id),
    )


@app.post("/api/high-risk/runs/{run_id}/approval-requests", response_model=ApprovalRecord)
async def request_high_risk_approval(
    run_id: str,
    payload: ApprovalRequest,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    actor_id = require_actor(actor_header)
    return await execute_idempotent_model_action(
        store,
        f"high-risk:{run_id}:approval-request",
        idempotency_key,
        {"actor_id": actor_id, **payload.model_dump(mode="json")},
        lambda: high_risk_service.request_approval(
            run_id, actor_id, expires_in=timedelta(minutes=payload.expires_in_minutes)
        ),
        response,
        ApprovalRecord,
        lambda cached: high_risk_service.get_approval(run_id, cached.approval_id),
    )


@app.get("/api/high-risk/runs/{run_id}/approvals/{approval_id}", response_model=ApprovalRecord)
async def get_high_risk_approval(run_id: str, approval_id: str):
    return await high_risk_service.get_approval(run_id, approval_id)


@app.get("/api/high-risk/runs/{run_id}/approval", response_model=ApprovalRecord)
async def get_latest_high_risk_approval(run_id: str):
    return await high_risk_service.latest_approval(run_id)


@app.post("/api/high-risk/runs/{run_id}/approvals/{approval_id}/decision", response_model=ApprovalRecord)
async def decide_high_risk_approval(
    run_id: str,
    approval_id: str,
    payload: ApprovalDecisionRequest,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    reviewer_header: str | None = Header(default=None, alias="X-Council-Reviewer-Key"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    actor_id = require_actor(actor_header)
    reviewer_secret = require_reviewer_secret(reviewer_header)
    await high_risk_service.authorize_reviewer_access(
        run_id, actor_id, reviewer_secret, "approval_decision"
    )
    return await execute_idempotent_model_action(
        store,
        f"high-risk:{run_id}:approval:{approval_id}:decision",
        idempotency_key,
        {"actor_id": actor_id, "approval_id": approval_id, **payload.model_dump(mode="json")},
        lambda: high_risk_service.decide_approval(
            run_id, approval_id, payload, actor_id, reviewer_secret
        ),
        response,
        ApprovalRecord,
        lambda cached: high_risk_service.resolve_cached_approval_decision(
            run_id, approval_id, payload, actor_id, reviewer_secret, cached
        ),
    )


@app.post("/api/high-risk/runs/{run_id}/approvals/{approval_id}/revoke", response_model=ApprovalRecord)
async def revoke_high_risk_approval(
    run_id: str,
    approval_id: str,
    payload: RevokeApprovalRequest,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    actor_id = require_actor(actor_header)
    return await execute_idempotent_model_action(
        store,
        f"high-risk:{run_id}:approval:{approval_id}:revoke",
        idempotency_key,
        {"actor_id": actor_id, "approval_id": approval_id, **payload.model_dump(mode="json")},
        lambda: high_risk_service.revoke_approval(run_id, approval_id, actor_id, payload.reason),
        response,
        ApprovalRecord,
        lambda _cached: high_risk_service.get_approval(run_id, approval_id),
    )


@app.post("/api/high-risk/runs/{run_id}/complete", response_model=HighRiskRun)
async def complete_high_risk_run(
    run_id: str,
    approval_id: str,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    actor_id = require_actor(actor_header)
    return await execute_idempotent_model_action(
        store,
        f"high-risk:{run_id}:complete",
        idempotency_key,
        {"actor_id": actor_id, "approval_id": approval_id},
        lambda: high_risk_service.complete(run_id, approval_id, actor_id),
        response,
        HighRiskRun,
        lambda _cached: high_risk_service.get(run_id),
    )


@app.post("/api/high-risk/runs/{run_id}/risk-override", response_model=HighRiskRun)
async def override_high_risk_tier(
    run_id: str,
    payload: RiskOverrideRequest,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    reviewer_header: str | None = Header(default=None, alias="X-Council-Reviewer-Key"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    actor_id = require_actor(actor_header)
    reviewer_secret = require_reviewer_secret(reviewer_header)
    await high_risk_service.authorize_reviewer_access(
        run_id, actor_id, reviewer_secret, "risk_override"
    )
    return await execute_idempotent_model_action(
        store,
        f"high-risk:{run_id}:risk-override",
        idempotency_key,
        {"actor_id": actor_id, **payload.model_dump(mode="json")},
        lambda: high_risk_service.override_risk(run_id, payload, actor_id, reviewer_secret),
        response,
        HighRiskRun,
        lambda cached: high_risk_service.resolve_cached_risk_override(
            run_id, payload, actor_id, reviewer_secret, cached
        ),
    )


@app.post("/api/high-risk/runs/{run_id}/cancel", response_model=HighRiskRun)
async def cancel_high_risk_run(
    run_id: str,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    actor_id = require_actor(actor_header)

    async def cancel_both():
        case = await high_risk_service.cancel(run_id, actor_id)
        await orchestrator.cancel(run_id)
        return case

    return await execute_idempotent_model_action(
        store,
        f"high-risk:{run_id}:cancel",
        idempotency_key,
        {"actor_id": actor_id},
        cancel_both,
        response,
        HighRiskRun,
        lambda _cached: high_risk_service.get(run_id),
    )


@app.get("/api/templates")
async def deliberation_templates():
    return list_templates()


@app.get("/api/output-contracts")
async def output_contracts():
    return list_output_contracts()


@app.get("/api/projects")
async def list_projects(response: Response):
    mark_legacy_response(response)
    return await store.list_projects()


@app.post("/api/projects")
async def create_project(payload: ProjectCreate, response: Response):
    require_legacy_workspace_write(response)
    project = ProjectRecord(id=str(uuid.uuid4()), **payload.model_dump())
    await store.save_project(project)
    return project


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str, response: Response):
    mark_legacy_response(response)
    project = await store.get_project(project_id)
    if not project:
        raise HTTPException(404, "资料空间不存在")
    project.source_count = len(await store.list_sources(project_id))
    project.run_count = sum(1 for run in await store.list_runs() if run.project_id == project_id)
    return project


@app.patch("/api/projects/{project_id}")
async def patch_project(project_id: str, payload: ProjectPatch, response: Response):
    require_legacy_workspace_write(response)
    project = await store.get_project(project_id)
    if not project:
        raise HTTPException(404, "资料空间不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    project.updated_at = utc_now()
    await store.save_project(project)
    return project


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, response: Response):
    require_legacy_workspace_write(response)
    if not await store.delete_project(project_id):
        raise HTTPException(404, "资料空间不存在")
    return {"deleted": True}


@app.get("/api/projects/{project_id}/sources")
async def list_project_sources(project_id: str, response: Response):
    mark_legacy_response(response)
    if not await store.get_project(project_id):
        raise HTTPException(404, "资料空间不存在")
    return await store.list_sources(project_id)


@app.post("/api/projects/{project_id}/sources/text")
async def add_text_source(project_id: str, payload: SourceTextCreate, response: Response):
    require_legacy_workspace_write(response)
    if not await store.get_project(project_id):
        raise HTTPException(404, "资料空间不存在")
    raw = payload.content.encode("utf-8")
    source = ProjectSource(
        id=str(uuid.uuid4()),
        project_id=project_id,
        kind="text",
        title=payload.title.strip(),
        content=payload.content.strip(),
        size_bytes=len(raw),
        sha256=content_hash(raw),
    )
    await store.save_source(source)
    return source


@app.post("/api/projects/{project_id}/sources/url")
async def add_url_source(project_id: str, payload: SourceURLCreate, response: Response):
    require_legacy_workspace_write(response)
    if not await store.get_project(project_id):
        raise HTTPException(404, "资料空间不存在")
    try:
        final_url, fetched_title, text = await fetch_webpage(payload.url)
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(400, f"网页导入失败：{exc}") from exc
    raw = text.encode("utf-8")
    source = ProjectSource(
        id=str(uuid.uuid4()),
        project_id=project_id,
        kind="url",
        title=payload.title.strip() or fetched_title,
        content=text,
        url=final_url,
        media_type="text/html",
        size_bytes=len(raw),
        sha256=content_hash(raw),
    )
    await store.save_source(source)
    return source


@app.post("/api/projects/{project_id}/sources/file")
async def add_file_source(project_id: str, response: Response, file: UploadFile = File(...)):
    require_legacy_workspace_write(response)
    if not await store.get_project(project_id):
        raise HTTPException(404, "资料空间不存在")
    filename = (file.filename or "资料").split("/")[-1].split("\\")[-1]
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    try:
        text, media_type = extract_file_text(filename, raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    source = ProjectSource(
        id=str(uuid.uuid4()),
        project_id=project_id,
        kind="file",
        title=filename.rsplit(".", 1)[0][:160],
        content=text,
        filename=filename,
        media_type=media_type,
        size_bytes=len(raw),
        sha256=content_hash(raw),
    )
    await store.save_source(source)
    return source


@app.delete("/api/projects/{project_id}/sources/{source_id}")
async def delete_project_source(project_id: str, source_id: str, response: Response):
    require_legacy_workspace_write(response)
    if not await store.delete_source(project_id, source_id):
        raise HTTPException(404, "资料不存在")
    return {"deleted": True}


@app.get("/api/runs")
async def list_runs():
    return await store.list_runs()


@app.get("/api/runs/compare", response_model=DecisionBriefComparison)
async def compare_runs(left: RunIdQuery, right: RunIdQuery):
    if left == right:
        raise HTTPException(400, "请选择两个不同的 Run")
    left_run, right_run = await store.get_run(left), await store.get_run(right)
    if not left_run or not right_run:
        raise HTTPException(404, "比较的运行记录不存在")
    left_brief, right_brief = await store.get_decision_brief(left), await store.get_decision_brief(right)
    if left_brief is None or right_brief is None:
        raise HTTPException(409, "两个 Run 都完成并生成结构化简报后才能比较")
    return compare_briefs(
        left_brief,
        right_brief,
        related=await store.runs_are_related(left, right),
    )


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    return run


@app.get("/api/runs/{run_id}/decision-brief", response_model=DecisionBrief)
async def get_decision_brief(run_id: RunIdPath):
    if not await store.get_run(run_id):
        raise HTTPException(404, "运行记录不存在")
    brief = await store.get_decision_brief(run_id)
    if brief is None:
        from .errors import ApiError

        raise ApiError(404, "DECISION_BRIEF_NOT_FOUND", "该历史运行尚无结构化决策简报。")
    return brief


@app.get("/api/runs/{run_id}/claims", response_model=list[DecisionClaimView])
async def list_run_claims(run_id: RunIdPath):
    if not await store.get_run(run_id):
        raise HTTPException(404, "运行记录不存在")
    return await store.list_decision_claims(run_id)


@app.get("/api/runs/{run_id}/outcomes", response_model=list[DecisionOutcomeRecord])
async def list_run_outcomes(run_id: RunIdPath):
    if not await store.get_run(run_id):
        raise HTTPException(404, "运行记录不存在")
    return await store.list_decision_outcomes(run_id)


@app.get("/api/runs/{run_id}/lineage", response_model=RunForkLineage)
async def get_run_lineage(run_id: RunIdPath):
    if not await store.get_run(run_id):
        raise HTTPException(404, "运行记录不存在")
    return await store.get_run_lineage(run_id)


@app.post("/api/runs/{run_id}/memory-proposals", response_model=list[MemoryProposalView])
async def create_run_memory_proposals(run_id: RunIdPath):
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    if run.status != "completed":
        raise HTTPException(409, "Run 完成并生成结构化简报后才能提出长期记忆")
    brief = await store.get_decision_brief(run_id)
    if not brief:
        raise HTTPException(409, "当前 Run 没有结构化简报")
    await store.create_memory_proposals(build_memory_proposals(brief))
    return await store.list_memory_proposals(run_id)


@app.get("/api/runs/{run_id}/memory-proposals", response_model=list[MemoryProposalView])
async def list_run_memory_proposals(run_id: RunIdPath):
    if not await store.get_run(run_id):
        raise HTTPException(404, "运行记录不存在")
    return await store.list_memory_proposals(run_id)


@app.get("/api/runs/{run_id}/memory-snapshot")
async def get_run_memory_snapshot(run_id: RunIdPath):
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    return {"run_id": run_id, "items": await store.get_run_memory_snapshot(run_id)}


@app.get("/api/memory", response_model=list[MemoryView])
async def list_approved_memory():
    return await store.list_memories()


@app.post("/api/memory/preview", response_model=MemoryPreview)
async def preview_approved_memory(payload: MemoryPreviewRequest):
    return await store.preview_memories(payload.selected_memory_ids)


@app.post("/api/memory/proposals/{proposal_id}/approve", response_model=MemoryView)
async def approve_memory_proposal(proposal_id: MemoryIdPath, payload: MemoryProposalDecision):
    try:
        return await store.approve_memory_proposal(proposal_id, payload)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/memory/proposals/{proposal_id}/reject", response_model=MemoryProposalView)
async def reject_memory_proposal(proposal_id: MemoryIdPath):
    try:
        return await store.reject_memory_proposal(proposal_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/memory/{memory_id}/{action}", response_model=MemoryView)
async def change_memory_state(
    memory_id: MemoryIdPath,
    action: Annotated[str, ApiPath(pattern=r"^(disable|enable|delete)$")],
):
    action_name = {"disable": "disabled", "enable": "enabled", "delete": "deleted"}[action]
    try:
        return await store.set_memory_action(memory_id, action_name)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/runs/{run_id}/fork")
async def fork_run(
    run_id: RunIdPath,
    request: RunForkCreate,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    source = await store.get_run(run_id)
    if not source:
        raise HTTPException(404, "运行记录不存在")

    async def create_fork():
        try:
            return await orchestrator.fork(source, request, high_risk_actor=actor_header)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    return await execute_idempotent_run_action(
        store,
        f"runs:{run_id}:fork",
        idempotency_key,
        request.model_dump(mode="json"),
        create_fork,
        response,
    )


@app.get("/api/runs/{run_id}/export")
async def export_run(run_id: str, format: str = "markdown"):
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    high_risk = await high_risk_service.get(run_id) if await store.has_high_risk_control(run_id) else None
    decision_brief = await store.get_decision_brief(run_id)
    decision_claims = await store.list_decision_claims(run_id)
    if format == "markdown":
        return Response(
            run_markdown(run, high_risk, decision_brief, decision_claims),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="council-{run.id[:8]}.md"'},
        )
    if format == "html":
        return Response(
            run_html(run, high_risk, decision_brief, decision_claims),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="council-{run.id[:8]}.html"'},
        )
    raise HTTPException(400, "导出格式只支持 markdown 或 html")


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    await high_risk_service.assert_normal_action_allowed(run_id, "cancel", actor_header)
    return await execute_idempotent_run_action(
        store, f"runs:{run_id}:cancel", idempotency_key, {}, lambda: orchestrator.cancel(run_id), response
    )


@app.post("/api/runs/{run_id}/advance")
async def advance_run(
    run_id: str,
    request: DiscussionAction,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    await high_risk_service.assert_normal_action_allowed(run_id, "advance", actor_header)
    return await execute_idempotent_run_action(
        store,
        f"runs:{run_id}:advance",
        idempotency_key,
        request.model_dump(mode="json"),
        lambda: orchestrator.advance(run_id, request),
        response,
    )


@app.post("/api/runs/{run_id}/interject")
async def interject_run(
    run_id: str,
    request: DiscussionAction,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    await high_risk_service.assert_normal_action_allowed(run_id, "interject", actor_header)
    return await execute_idempotent_run_action(
        store,
        f"runs:{run_id}:interject",
        idempotency_key,
        request.model_dump(mode="json"),
        lambda: orchestrator.interject(run_id, request),
        response,
    )


@app.post("/api/runs/{run_id}/retry-turn")
async def retry_run_turn(
    run_id: str,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    await high_risk_service.assert_normal_action_allowed(run_id, "retry-turn", actor_header)
    return await execute_idempotent_run_action(
        store, f"runs:{run_id}:retry-turn", idempotency_key, {}, lambda: orchestrator.retry_turn(run_id), response
    )


@app.post("/api/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    limits: RunLimits,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    await high_risk_service.assert_normal_action_allowed(run_id, "resume", actor_header)
    try:
        return await execute_idempotent_run_action(
            store,
            f"runs:{run_id}:resume",
            idempotency_key,
            limits.model_dump(mode="json"),
            lambda: orchestrator.resume_with_limits(run_id, limits),
            response,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/runs/{run_id}/summarize")
async def summarize_run(
    run_id: str,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    await high_risk_service.assert_normal_action_allowed(run_id, "summarize", actor_header)
    return await execute_idempotent_run_action(
        store, f"runs:{run_id}:summarize", idempotency_key, {}, lambda: orchestrator.summarize(run_id), response
    )


@app.post("/api/runs/{run_id}/rerun")
async def rerun(
    run_id: str,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    await high_risk_service.assert_normal_action_allowed(run_id, "rerun", actor_header)
    source = await store.get_run(run_id)
    if not source:
        raise HTTPException(404, "运行记录不存在")
    assignment_config = None
    if source.seat_assignments and source.finalizer_assignment:
        assignment_config = AgentAssignmentsConfig(
            schema_version=source.assignment_schema_version,
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
    async def start_rerun():
        return await orchestrator.start(
            RunCreate(
                question=source.question,
                mode=source.mode,
                workflow_strategy=source.workflow_strategy,
                provider_id=source.provider_id,
                model=source.model,
                assignment_config=assignment_config,
                limits=source.limits,
                project_id=source.project_id,
                source_ids=[item.id for item in source.source_snapshots],
                include_project_history=True,
                template_id=source.template_id,
                output_contract=source.output_contract,
            ),
            frozen_sources=source.source_snapshots,
            frozen_project_name=source.project_name,
            frozen_project_context=source.project_context,
        )

    return await execute_idempotent_run_action(
        store,
        f"runs:{run_id}:rerun",
        idempotency_key,
        {"source_run_id": run_id},
        start_rerun,
        response,
    )


@app.put("/api/runs/{run_id}/decision-review")
async def save_decision_review(
    run_id: str,
    payload: DecisionReviewUpdate,
    response: Response,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    await high_risk_service.assert_normal_action_allowed(run_id, "decision-review", actor_header)
    run = await store.get_run(run_id)
    if not run:
        raise HTTPException(404, "运行记录不存在")
    if run.status != "completed" or not run.final_decision:
        raise HTTPException(409, "圆桌完成后才能记录结果回访")
    async def append_review():
        await store.append_decision_outcome(
            DecisionOutcomeRecord(run_id=run_id, review=DecisionReview(**payload.model_dump()))
        )
        return await store.get_run(run_id)

    return await execute_idempotent_run_action(
        store,
        f"runs:{run_id}:decision-review",
        idempotency_key,
        payload.model_dump(mode="json"),
        append_review,
        response,
    )


@app.delete("/api/runs/{run_id}")
async def delete_run(
    run_id: str,
    actor_header: str | None = Header(default=None, alias="X-Council-Actor"),
):
    await high_risk_service.assert_normal_action_allowed(run_id, "delete", actor_header)
    if not await orchestrator.delete(run_id):
        raise HTTPException(404, "运行记录不存在")
    return {"deleted": True}


@app.get("/api/runs/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    last_event_id: int = 0,
    replay_header: str | None = Header(default=None, alias="Last-Event-ID"),
):
    if not await store.get_run(run_id):
        raise HTTPException(404, "运行记录不存在")
    try:
        cursor = max(0, last_event_id, int(replay_header or 0))
    except ValueError as exc:
        raise HTTPException(400, "Last-Event-ID 必须是非负整数") from exc
    if not await store.try_open_event_stream(run_id):
        raise HTTPException(429, "当前审议的实时连接过多，请关闭多余页面后重试")

    async def stream():
        nonlocal cursor
        try:
            yield "retry: 1000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                events = await store.wait_for_events(run_id, cursor, timeout=15)
                if not events:
                    yield ": keep-alive\n\n"
                    continue
                for event in events:
                    cursor = event.sequence
                    yield f"id: {event.sequence}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
                    if event.type in {"final_completed", "run_cancelled"}:
                        return
        finally:
            await store.close_event_stream(run_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    fallback_models, fallback_source = offline_model_catalog(profile)
    models, model_source, _ = resolve_model_catalog(result.get("models") or [], fallback_models, fallback_source)
    replace_model_catalog(profile, models, model_source)
    result["models"] = profile.available_models
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
        if profile.provider_type != ProviderType.MOCK and not profile.default_model.strip():
            raise RuntimeError("尚未选择模型。请先获取模型列表，或手动填写模型 ID。")
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
        fallback_models, fallback_source = offline_model_catalog(profile)
        models, source, fetched = resolve_model_catalog(models, fallback_models, fallback_source)
        if source == "provider" and profile.provider_type != ProviderType.CCSWITCH:
            models = sorted(models, key=str.casefold)
        replace_model_catalog(profile, models, source)
        profile.last_error = None
        profile.last_health_check = datetime.now(timezone.utc)
        await store.save_provider(profile)
        return {"models": profile.available_models, "source": source, "fetched": fetched, "default_model": profile.default_model}
    except Exception as exc:
        profile.last_error = provider_error_message(exc)
        models, source = offline_model_catalog(profile)
        replace_model_catalog(profile, models, source)
        await store.save_provider(profile)
        return {"models": profile.available_models, "source": source, "fetched": 0, "default_model": profile.default_model, "error": profile.last_error}


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
async def put_assignments(payload: AgentAssignmentsPayload):
    global assignments
    try:
        orchestrator._resolve_config(RunCreate(question="验证席位配置", assignment_config=payload))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    assignments = orchestrator.normalize_assignment_config(payload)
    await store.save_assignment_config(assignments)
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
